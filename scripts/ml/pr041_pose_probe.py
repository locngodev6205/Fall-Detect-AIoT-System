"""Compare pose complexity on development clips, with the same frames and timestamps."""
import argparse
import json
from pathlib import Path
import time

import cv2
import mediapipe as mp
import numpy as np
import torch

from pr04_experiment import MANIFEST, development, load_pinned, make_model, starts
from pr041_ablation import evaluate
from ml.features import extract_keypoints, normalize_sequence, resample_keypoints, video_frame_timestamp


def probe(video, complexity):
    capture = cv2.VideoCapture(str(video))
    stamps, poses, durations = [], [], []
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        with mp.solutions.pose.Pose(model_complexity=complexity) as detector:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                stamp = video_frame_timestamp(capture.get(cv2.CAP_PROP_POS_MSEC), fps,
                                              stamps[-1] if stamps else None)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                start = time.perf_counter()
                pose = detector.process(rgb).pose_landmarks
                durations.append((time.perf_counter()-start)*1000)
                poses.append(extract_keypoints(pose))
                stamps.append(stamp)
    finally:
        capture.release()
    features = normalize_sequence(resample_keypoints(stamps, poses))
    return (stamps[0] + np.arange(len(features))/10, features, features[:,2::3].any(axis=1),
            dict(frames=len(stamps), p50_ms=float(np.median(durations[1:])),
                 p95_ms=float(np.percentile(durations[1:],95))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    cv2.setNumThreads(1)
    manifest = load_pinned(args.root/'annha-v2.1'/'manifest.json', MANIFEST)
    _, rows = development(args.root,manifest)
    model = make_model(torch,'gru',20)
    model.load_state_dict(torch.load(args.checkpoint,weights_only=True,map_location='cpu'))
    model.eval()
    clips = [r for r in rows if r['split']=='val' and r['subject_id']=='6' and
             r['scene_id'] in ('Fall forward','Fall left','Fall right')]
    results = {}
    for complexity in (0,1):
        details = {}
        for row in clips:
            stamps, features, valid, timing = probe(row['source_file'],complexity)
            _, windows30 = starts(stamps, valid, 30, row['event'])
            _, windows20 = starts(stamps, valid, 20, row['event'],3)
            # Per-clip analysis uses the same event scorer as the aggregate comparison.
            details[row['scene_id']] = (row, stamps, features, valid, timing, len(windows30), len(windows20))
        result = evaluate(model,[v[:4] for v in details.values()],20,3)
        results[complexity] = [dict(**r, timing=details[r['action']][4],
                                    windows30=details[r['action']][5], windows20=details[r['action']][6])
                               for r in result['recordings']]
    with args.output.open('x') as stream:
        json.dump(results,stream,indent=2)


if __name__ == '__main__':
    main()
