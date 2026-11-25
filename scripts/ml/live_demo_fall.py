"""Observe the candidate on a local webcam without any alert or backend clients."""
import argparse
import json
import time

import cv2
import mediapipe as mp

from modules.temporal_fall import TemporalFall
from modules.temporal_features import extract_keypoints, normalize_sequence


def emit(**fields):
    print(json.dumps(fields), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("camera")
    parser.add_argument("onnx")
    parser.add_argument("--seconds", type=int, default=240)
    args = parser.parse_args()
    candidate = TemporalFall("ctr_gcn_40_2026_lite", args.onnx)
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            raise RuntimeError("Camera could not be opened")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        start = time.monotonic()
        last = None
        frames = failures = 0
        with mp.solutions.pose.Pose(model_complexity=candidate.pose_complexity) as pose:
            while time.monotonic() - start < args.seconds:
                ok, frame = cap.read()
                stamp = time.monotonic()
                if not ok:
                    candidate.reset()
                    failures += 1
                    if failures >= 5:
                        raise RuntimeError("Camera failed to deliver frames")
                    continue
                failures = 0
                frames += 1
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                points = extract_keypoints(pose.process(rgb).pose_landmarks)
                windows = candidate.stream.push(stamp, points)
                if frames == 1:
                    emit(status="CAMERA_READY", width=frame.shape[1], height=frame.shape[0])
                emit(
                    elapsed=round(stamp - start, 3),
                    fps=round(frames / max(time.monotonic() - start, 1e-6), 2),
                    frame_gap_ms=None if last is None else round((stamp - last) * 1000, 1),
                    pose_valid=bool(normalize_sequence([points]).any()),
                    state=candidate.stream.engine.state,
                    windows=[
                        dict(score=w.score, valid_samples=int(w.mask.sum()),
                             alert=any(event == "simulated_alert" for event, _ in w.events),
                             error=w.error)
                        for w in windows
                    ],
                )
                last = stamp
    finally:
        cap.release()


if __name__ == "__main__":
    main()
