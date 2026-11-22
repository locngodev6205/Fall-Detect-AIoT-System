"""Compare pose extractors on pinned CAUCAFall development videos."""
import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np

from pr04_experiment import MANIFEST, development, load_pinned
from ml.features import EMPTY, SPEC, extract_keypoints, normalize_sequence, video_frame_timestamp
from ml.integrity import digest

CLIPS = ("FallForwardS6", "FallLeftS6", "FallRightS6", "FallBackwardsS6",
         "FallBackwardsS7", "FallLeftS7", "PickupobjectS9")
TORSO = [5, 6, 11, 12]


def phase_summary(points):
    if not len(points):
        return None
    usable = [bool(normalize_sequence([p])[0, 2::3].any()) for p in points]
    visible = points[..., 2] >= SPEC.minimum_visibility
    run = longest = 0
    for ok in usable:
        run = 0 if ok else run+1
        longest = max(longest, run)
    torso = points[:, TORSO]
    shoulder = torso[:, :2, :2].mean(axis=1)
    hip = torso[:, 2:, :2].mean(axis=1)
    delta = np.abs(shoulder-hip)
    horizontal = (delta[:, 0] >= delta[:, 1]) & visible[:, TORSO].all(axis=1)
    return dict(frames=len(points), usable=sum(usable), missing_joints=int((~visible).sum()),
                longest_unusable_frames=longest, torso_high_confidence=int(visible[:, TORSO].all(axis=1).sum()),
                horizontal_proxy_frames=int(horizontal.sum()),
                median_joint_score=float(np.median(points[..., 2])))


def rtm_points(model, frame):

    boxes = model.det_model(frame)
    if not len(boxes):
        return EMPTY
    # Single-subject videos. Select the largest person box before running pose.
    largest = max(boxes, key=lambda box: (box[2]-box[0])*(box[3]-box[1]))
    points, scores = model.pose_model(frame, bboxes=[largest])
    if points.shape != (1, 17, 2) or scores.shape != (1, 17):
        raise ValueError("Expected COCO-17 RTMPose outputs")
    xy = points[0] / [frame.shape[1], frame.shape[0]]
    return np.column_stack((xy, scores[0])).astype(np.float32)


def measure(row, path, process):
    import cv2

    cap = cv2.VideoCapture(str(path))
    stamps, poses, times = [], [], []
    fps = cap.get(cv2.CAP_PROP_FPS)
    size = [int(cap.get(key)) for key in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT)]
    started, cpu = time.perf_counter(), time.process_time()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            stamps.append(video_frame_timestamp(cap.get(cv2.CAP_PROP_POS_MSEC), fps,
                                                stamps[-1] if stamps else None))
            t = time.perf_counter()
            poses.append(process(frame))
            times.append(time.perf_counter()-t)
    finally:
        cap.release()
    if not stamps:
        raise ValueError(f"No decoded frames: {path}")
    wall = time.perf_counter()-started
    points, stamps = np.asarray(poses), np.asarray(stamps)
    if not np.isfinite(points).all():
        raise ValueError("Invalid pose output")
    result = dict(id=row["video_id"], action=row["scene_id"], event=row["event"],
                  all=phase_summary(points), fps=len(stamps)/wall,
                  source_fps=fps, source_size=size, inference_errors=0, pose_ms_p50=float(np.median(times)*1000),
                  cpu_percent=100*(time.process_time()-cpu)/wall,
                  process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
    if row["event"]:
        a, b = row["event"]
        for key, start, end in (("before", a-2, a), ("fall", a, b), ("after", b, b+2)):
            result[key] = phase_summary(points[(stamps >= start) & (stamps < end)])
    return result


def main():
    import cv2
    import mediapipe as mp
    import platform
    from functools import partial

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("lite", "rtmpose"))
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--detector", type=Path)
    parser.add_argument("--pose", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output")
    cv2.setNumThreads(1)
    manifest = load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST)
    _, rows = development(args.data, manifest)
    rows = {row["video_id"]: row for row in rows if row["split"] == "val"}
    artifacts = {row["video_id"]: row for row in manifest["sources"] + manifest["group_context"]}
    output = dict(model=args.model, manifest=MANIFEST, machine=platform.machine(), recordings=[])
    if args.model == "rtmpose":
        import onnxruntime as ort
        from rtmlib import Body

        if args.detector is None or args.pose is None:
            parser.error("RTMPose requires local --detector and --pose ONNX files")
        output["weights"] = {p.name + str(i): digest(p)
                             for i, p in enumerate((args.detector, args.pose))}
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        # RTMLib constructs its own sessions. Inject this session configuration
        # only during model creation, leaving subsequent callers untouched.
        from unittest.mock import patch
        session = partial(ort.InferenceSession, sess_options=options)
        with patch.object(ort, "InferenceSession", session):
            model = Body(det=str(args.detector), pose=str(args.pose),
                         pose_input_size=(192, 256))
    for clip in CLIPS:
        row = rows[f"caucafall:{clip}"]
        path = Path(row["source_file"])
        if digest(path) != artifacts[row["video_id"]]["video_sha256"]:
            raise ValueError(f"Unexpected media checksum: {clip}")
        if args.model == "lite":
            with mp.solutions.pose.Pose(model_complexity=0) as model:
                result = measure(row, path, lambda frame: extract_keypoints(
                    model.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).pose_landmarks))
        else:
            result = measure(row, path, partial(rtm_points, model))
        output["recordings"].append(result)
        print(clip, result["all"], round(result["fps"], 2), flush=True)
    with args.output.open("x") as target:
        json.dump(output, target, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
