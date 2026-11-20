"""Standalone benchmark from video or camera. No network or alert integrations."""
import argparse
import json
import logging
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import time

import numpy as np

from ml.features import extract_keypoints, normalize_sequence, video_frame_timestamp
from .streaming import Stream


def quantiles(values):
    return dict(zip(('p50','p95','p99'), map(float,np.percentile(values,[50,95,99])))) if values else None


def device_sample(start, cpu, frames):
    try:
        rss = next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines()
                   if line.startswith('VmRSS:'))
    except (OSError, StopIteration):
        rss = None
    try:
        temp = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
    except (OSError, ValueError):
        temp = None
    return dict(elapsed_s=time.monotonic()-start, cpu_s=time.process_time()-cpu,
                frames=frames, rss_kib=int(rss) if rss else None, temperature_c=temp)


def benchmark(source, model, complexity, *, live=False, limit=None, confirmations=1, preview=None):
    import cv2
    import mediapipe as mp
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        cap.release()
        raise ValueError(f'Cannot open {source}')
    capture, pose, pipeline, inference, stamps, delivery, preprocessing = ([] for _ in range(7))
    height = width = 0
    valid = windows = scored = frames = interruptions = no_landmarks = 0
    alerts, score_grid, transitions = [], [], []
    max_score = None
    presence, presence_transitions = None, []
    stream = Stream(model, confirmations=confirmations)
    recovery = []
    outage_started = None
    begin, cpu = time.monotonic(), time.process_time()
    resources = [device_sample(begin, cpu, 0)]
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not live and fps <= 0:
        cap.release()
        raise ValueError('Invalid video FPS')
    try:
        with mp.solutions.pose.Pose(model_complexity=complexity) as detector:
            while limit is None or time.monotonic()-begin < limit:
                start = time.monotonic()
                ok, frame = cap.read()
                arrived = time.monotonic()
                if arrived-begin-resources[-1]['elapsed_s'] >= 5:
                    resources.append(device_sample(begin, cpu, frames))
                if not ok:
                    if not live:
                        break
                    if outage_started is None:
                        interruptions += 1
                        outage_started = arrived
                        stream.reset('camera_disconnect')
                        detector.reset()
                    cap.release()
                    time.sleep(.5)
                    cap = cv2.VideoCapture(source)
                    continue
                if outage_started is not None:
                    recovery.append((arrived-outage_started)*1000)
                    outage_started = None
                stamp = arrived-begin if live else video_frame_timestamp(
                    cap.get(cv2.CAP_PROP_POS_MSEC),fps,stamps[-1] if stamps else None)
                height, width = frame.shape[:2]
                stamps.append(stamp)
                capture.append((arrived-start)*1000)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                t = time.monotonic()
                landmarks = detector.process(rgb).pose_landmarks
                points = extract_keypoints(landmarks)
                no_landmarks += int(landmarks is None)
                pose.append((time.monotonic()-t)*1000)
                present = bool(normalize_sequence([points])[0,2::3].any())
                valid += int(present)
                if present != presence:
                    presence_transitions.append(dict(source_time=stamp, pose_valid=present))
                    presence = present
                results = stream.push(stamp,points)
                preprocessing.append(stream.preprocess_ms)
                windows += len(results)
                for row in results:
                    if row.score is not None:
                        scored += 1
                        max_score = row.score if max_score is None else max(max_score, row.score)
                        score_grid.append(row.end)
                        inference.append(row.inference_ms)
                    for event, when in row.events:
                        transitions.append(dict(event=event, grid=when, source_time=row.arrival,
                                                capture_elapsed_s=arrived-begin,
                                                inference_completed_elapsed_s=row.completed_monotonic-begin,
                                                dispatch_elapsed_s=time.monotonic()-begin))
                        if event == 'simulated_alert':
                            alerts.append([when,row.arrival])
                            delivery.append((time.monotonic()-arrived)*1000)
                if preview is not None:
                    preview(frame, present)
                frames += 1
                pipeline.append((time.monotonic()-start)*1000)
    finally:
        cap.release()
    elapsed = time.monotonic()-begin
    resources.append(device_sample(begin, cpu, frames))
    diffs = np.diff(stamps)
    throttled = None
    if shutil.which('vcgencmd'):
        result = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True, timeout=3)
        throttled = result.stdout.strip() if result.returncode == 0 else None
    temp = Path('/sys/class/thermal/thermal_zone0/temp')
    return dict(source_kind='camera' if live else 'video_replay', complexity=complexity,
                machine=platform.machine(), python=platform.python_version(),
                opencv=cv2.__version__, mediapipe=mp.__version__,
                frames=frames, width=width, height=height, elapsed_seconds=elapsed, throughput_fps=frames/elapsed,
                input_fps=(frames-1)/(stamps[-1]-stamps[0]) if frames>1 else None,
                capture_ms=quantiles(capture), inter_frame_ms=quantiles(list(diffs*1000)),
                pose_ms=quantiles(pose), pipeline_ms=quantiles(pipeline),
                preprocessing_ms=quantiles(preprocessing), inference_ms=quantiles(inference), simulated_alert_delivery_ms=quantiles(delivery),
                valid_pose_frames=valid, no_landmark_frames=no_landmarks, windows=windows, scored=scored, alerts=alerts, score_grid=score_grid,
                transitions=transitions, pose_validity_transitions=presence_transitions,
                max_fall_probability=max_score, interruptions=interruptions,
                recovery_ms=quantiles(recovery), model_errors=stream.model_errors,
                invalid_poses=stream.invalid_poses,
                timestamp_resets=sum(reason == 'timestamp_gap' for reason, _ in stream.resets),
                cpu_seconds=time.process_time()-cpu, peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                temperature_c=int(temp.read_text())/1000 if temp.is_file() else None,
                throttled=throttled, resource_samples=resources, dropped_frames=None)


def main():
    from .streaming import load_model
    import torch
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--video')
    sources.add_argument('--camera',type=int)
    parser.add_argument('--checkpoint',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--complexity',choices=(0,1),type=int,default=0)
    parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--confirmations',choices=(1,2),type=int,default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    torch.set_num_threads(2)
    live = args.camera is not None
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    result = benchmark(args.camera if live else args.video,load_model(args.checkpoint),
                       args.complexity,live=live,limit=args.seconds if live else None,
                       confirmations=args.confirmations)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2)


if __name__ == '__main__':
    main()
