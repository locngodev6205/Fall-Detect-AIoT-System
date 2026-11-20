"""Foreground camera readiness and one explicitly labeled ADL trial at a time."""
import argparse
import json
import subprocess
from contextlib import contextmanager, nullcontext
import time
from pathlib import Path

import numpy as np

from .benchmark import benchmark
from .diagnostics import Trace
from .streaming import load_model

SCENARIOS = ('standing', 'walking', 'sit-stand', 'pick-up', 'leave-reenter')


def image_quality(frames):
    """Check signal and temporal variation on grayscale sampled frames."""
    black = sum(float(frame.mean()) < 8 and float(frame.std()) < 4 for frame in frames)
    changed = sum(not np.array_equal(a, b) for a, b in zip(frames, frames[1:]))
    return dict(black_frames=black, changed_pairs=changed,
                ready=len(frames) >= 20 and black == 0 and changed > 0)


def prepare(camera):
    import cv2
    import mediapipe as mp

    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(camera)
    try:
        if not cap.isOpened():
            raise ValueError('Camera could not be opened')
        sampled = []
        size = None
        failures = 0
        pose_frames = 0
        start = time.monotonic()
        with mp.solutions.pose.Pose(model_complexity=0) as detector:
            for _ in range(28):
                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    continue
                size = tuple(frame.shape[1::-1])
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sampled.append(cv2.resize(gray, (64, 48)))
                pose_frames += int(detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                                   .pose_landmarks is not None)
        quality = image_quality(sampled)
        quality['ready'] &= failures == 0
        return dict(quality, frames_read=len(sampled), read_failures=failures,
                    resolution=size, fps=len(sampled)/(time.monotonic()-start),
                    frames_with_landmarks=pose_frames, mediapipe_processed=len(sampled))
    finally:
        cap.release()



@contextmanager
def vnc_preview(enabled):
    if not enabled:
        yield None
        return
    import cv2

    player = subprocess.Popen([
        'ffplay', '-loglevel', 'error', '-f', 'rawvideo', '-pixel_format', 'bgr24',
        '-video_size', '320x240', '-framerate', '10', '-window_title',
        'AnNha PR-05.2 - Camera research', '-x', '640', '-y', '480',
        '-fflags', 'nobuffer', '-autoexit', '-i', 'pipe:0'],
        stdin=subprocess.PIPE)
    try:
        def show(frame, present):
            display = cv2.resize(frame, (320, 240))
            cv2.putText(display, 'POSE OK' if present else 'POSE UNAVAILABLE',
                        (8, 22), cv2.FONT_HERSHEY_SIMPLEX, .55,
                        (0, 255, 0) if present else (0, 200, 255), 1)
            try:
                player.stdin.write(display.tobytes())
            except BrokenPipeError:
                raise RuntimeError('VNC preview player closed') from None
        yield show
    finally:
        try:
            player.stdin.close()
        except BrokenPipeError:
            pass
        player.terminate()
        player.wait(timeout=5)


def main():
    import torch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--checkpoint', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare')
    trial = commands.add_parser('start')
    trial.add_argument('--scenario', choices=SCENARIOS, required=True)
    trial.add_argument('--seconds', type=int, choices=range(30, 61), default=30, metavar='30–60')
    trial.add_argument('--trace', type=Path)
    trial.add_argument('--consent-pose-trace', action='store_true')
    trial.add_argument('--preview', action='store_true')
    trial.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    model = load_model(args.checkpoint)
    if args.command == 'prepare':
        outcome = prepare(args.camera)
        print(json.dumps(outcome))
        if not outcome['ready']:
            raise SystemExit(2)
        return
    if args.consent_pose_trace and not args.trace:
        parser.error('--consent-pose-trace requires --trace')
    context = Trace(args.trace, scenario=args.scenario, include_pose=args.consent_pose_trace) if args.trace else nullcontext()
    with args.output.open('x') as target, vnc_preview(args.preview) as preview, context as trace:
        result = benchmark(args.camera, model, 0, live=True, limit=args.seconds, preview=preview, trace=trace)
        json.dump(dict(scenario=args.scenario, ground_truth='awaiting_operator_confirmation',
                       **result), target, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
