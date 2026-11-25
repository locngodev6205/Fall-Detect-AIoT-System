"""Dry-run the demo models against labelled S8 video files, without alerts.

Run with PYTHONPATH pointing at fall_detect and an environment with ONNX Runtime.
Media timestamps drive scoring. Measured wall time separately gives throughput.
"""
import argparse, json, resource, time
from contextlib import ExitStack
from pathlib import Path
import cv2
import mediapipe as mp
import numpy as np
from modules.temporal_fall import TemporalFall
from modules.temporal_features import SPEC, extract_keypoints, video_frame_timestamp
from modules.temporal_stream import EventEngine, Stream

POSE_VARIANTS = {
    "baseline": (0.5, 0.5, False),
    "detect35": (0.35, 0.5, False),
    "track65": (0.5, 0.65, False),
    "full_on_loss": (0.5, 0.5, True),
}


def replay(root, model, complexity, result_name, pose_variant="baseline"):
    detection, tracking, fallback_on_loss = POSE_VARIANTS[pose_variant]
    cv2.setNumThreads(1)
    selector = {"ctr": "ctr_gcn_40_2026", "gru": "gru_e4_42"}[model]
    if model == "ctr" and complexity == 0:
        selector = "ctr_gcn_40_2026_lite"
    runtime = TemporalFall(selector, root / (model + ".onnx"))
    poses, inference, records, capture, count, gaps=[],[],[],[],0,0
    cpu0=time.process_time()
    elapsed=0.
    pose_frames = 0
    for clip in sorted(root.glob('*S8.avi')):
        cap=cv2.VideoCapture(str(clip))
        stream=Stream(runtime.score)
        delayed=EventEngine(confirmations=2)
        last=None
        trace=[]
        raw_pose=[]
        with ExitStack() as stack:
            estimator = stack.enter_context(mp.solutions.pose.Pose(
                model_complexity=complexity, min_detection_confidence=detection,
                min_tracking_confidence=tracking,
            ))
            fallback = stack.enter_context(mp.solutions.pose.Pose(
                model_complexity=1, static_image_mode=True,
            )) if fallback_on_loss else None
            start=time.monotonic()
            while True:
                begin=time.monotonic()
                ok,frame=cap.read()
                if not ok: break
                count+=1
                stamp=video_frame_timestamp(cap.get(cv2.CAP_PROP_POS_MSEC),cap.get(cv2.CAP_PROP_FPS),last)
                if last is not None and stamp-last>SPEC.max_gap_s: gaps+=1
                last=stamp
                rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                capture.append((time.monotonic()-begin)*1000)
                begin=time.monotonic()
                pose=estimator.process(rgb)
                if pose.pose_landmarks is None and fallback is not None:
                    pose = fallback.process(rgb)
                poses.append((time.monotonic()-begin)*1000)
                keypoints = extract_keypoints(pose.pose_landmarks)
                pose_frames += pose.pose_landmarks is not None
                raw_pose.append([stamp, keypoints.tolist() if pose.pose_landmarks is not None else None])
                for w in stream.push(stamp, keypoints):
                    if w.error: raise RuntimeError(w.error)
                    extra=()
                    if w.score is None: delayed.unavailable()
                    else:
                        inference.append(w.inference_ms)
                        extra=delayed.update(w.end,w.score)
                    trace.append(dict(arrival=w.arrival, end=w.end, score=w.score, baseline=bool(w.events and w.events[-1][0]=='simulated_alert'), confirm2=bool(extra and extra[-1][0]=='simulated_alert')))
            elapsed+=time.monotonic()-start
        cap.release()
        if last is None: raise RuntimeError(f'No frames in {clip.name}')
        records.append(dict(clip=clip.name,windows=trace,raw_pose=raw_pose))
        print(clip.name,'valid',sum(w['score'] is not None for w in trace),'/',len(trace),flush=True)
    all_windows=[w for item in records for w in item['windows']]
    result=dict(model=model, fps=count/elapsed, cpu_percent=(time.process_time()-cpu0)/elapsed*100, rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, pose_ms=np.percentile(poses,[50,95]).tolist(), model_ms=np.percentile(inference,[50,95]).tolist(),decode_ms=np.percentile(capture,[50,95]).tolist(), frames=count,valid_windows=sum(w['score'] is not None for w in all_windows),windows=len(all_windows),source_gaps=gaps,pose_frames=pose_frames,records=records)
    (root/(result_name+'.json')).write_text(json.dumps(result))
    print({k:v for k,v in result.items() if k!='records'},flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('model',choices=['ctr','gru'])
    parser.add_argument('--ctr-lite', action='store_true')
    parser.add_argument('--pose-variant', choices=POSE_VARIANTS, default='baseline')
    args=parser.parse_args()
    if args.ctr_lite and args.model != 'ctr':
        parser.error('--ctr-lite requires the CTR-GCN model')
    if args.pose_variant != "baseline" and not args.ctr_lite:
        parser.error("--pose-variant requires --ctr-lite")
    name = "ctr_lite" if args.ctr_lite else args.model
    if args.pose_variant != "baseline":
        name = args.pose_variant
    replay(args.root, args.model, int(args.model == 'ctr' and not args.ctr_lite),
           name, args.pose_variant)
