"""Compare pose extractors on pinned CAUCAFall development videos."""
import argparse
from contextlib import contextmanager
from functools import partial
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


def rtm_points(model, frame, timing=None):
    start = time.perf_counter()
    boxes = model.det_model(frame)
    if timing is not None:
        timing["detector"].append((time.perf_counter()-start)*1000)
    if not len(boxes):
        return EMPTY
    largest = max(boxes, key=lambda box: (box[2]-box[0])*(box[3]-box[1]))
    start = time.perf_counter()
    points, scores = model.pose_model(frame, bboxes=[largest])
    if timing is not None:
        timing["landmarks"].append((time.perf_counter()-start)*1000)
    if points.shape != (1, 17, 2) or scores.shape != (1, 17):
        raise ValueError("Expected COCO-17 RTMPose outputs")
    xy = points[0] / [frame.shape[1], frame.shape[0]]
    return np.column_stack((xy, scores[0])).astype(np.float32)


@contextmanager
def extractor(kind, detector=None, pose=None, timing=None):
    import cv2

    if kind in ("lite", "full"):
        import mediapipe as mp
        with mp.solutions.pose.Pose(model_complexity=int(kind == "full")) as model:
            yield lambda frame: extract_keypoints(
                model.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).pose_landmarks)
        return

    import onnxruntime as ort
    from rtmlib import Body
    from unittest.mock import patch

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = partial(ort.InferenceSession, sess_options=options)
    size = (416, 416) if kind == "rtmpose_s" else (640, 640)
    with patch.object(ort, "InferenceSession", session):
        model = Body(det=str(detector), det_input_size=size, pose=str(pose),
                     pose_input_size=(192, 256))
    yield partial(rtm_points, model, timing=timing)


def measure(row, path, process, *, cache=None, step=1):
    import cv2

    cap = cv2.VideoCapture(str(path))
    stamps, poses, times = [], [], []
    fps = cap.get(cv2.CAP_PROP_FPS)
    size = [int(cap.get(key)) for key in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT)]
    started, cpu = time.perf_counter(), time.process_time()
    index, previous = 0, None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            previous = video_frame_timestamp(cap.get(cv2.CAP_PROP_POS_MSEC), fps, previous)
            index += 1
            if (index-1) % step:
                continue
            stamps.append(previous)
            t = time.perf_counter()
            poses.append(process(frame))
            times.append(time.perf_counter()-t)
    finally:
        cap.release()
    if not stamps:
        raise ValueError(f"No decoded frames: {path}")
    wall = time.perf_counter()-started
    points, stamps = np.asarray(poses), np.asarray(stamps)
    if points.shape != (len(stamps), 17, 3) or not np.isfinite(points).all():
        raise ValueError("Invalid pose output")
    # SimCC can exceed one. Store canonical confidence range for model input.
    points[..., 2] = np.clip(points[..., 2], 0, 1)
    if cache is not None:
        with cache.open("xb") as target:
            np.savez_compressed(target, stamps=stamps, points=points)
    result = dict(id=row["video_id"], action=row["scene_id"], event=row["event"],
                  all=phase_summary(points), fps=len(stamps)/wall,
                  source_fps=fps, source_size=size, inference_errors=0, pose_ms_p50=float(np.median(times)*1000), pose_ms_p95=float(np.percentile(times, 95)*1000),
                  cpu_percent=100*(time.process_time()-cpu)/wall,
                  process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
    if row["event"]:
        a, b = row["event"]
        for key, start, end in (("before", a-2, a), ("fall", a, b), ("after", b, b+2)):
            result[key] = phase_summary(points[(stamps >= start) & (stamps < end)])
    return result


def main():
    import cv2
    import platform

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("lite", "full", "rtmpose", "rtmpose_s"))
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--detector", type=Path)
    parser.add_argument("--pose", type=Path)
    parser.add_argument("--cache", type=Path, help="New cache directory for all CAUCAFall Train/Validation")
    parser.add_argument("--profile-step", type=int, default=1,
                        help="Process every Nth frame for diagnostic stage timing only")
    args = parser.parse_args()
    if args.profile_step < 1 or (args.cache and args.profile_step != 1):
        parser.error("Pose cache requires every input frame")
    if args.output.exists():
        parser.error("Use a fresh output")
    cv2.setNumThreads(1)
    manifest = load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST)
    _, rows = development(args.data, manifest)
    rows = {row["video_id"]: row for row in rows if row["source_dataset"] == "caucafall"}
    artifacts = {row["video_id"]: row for row in manifest["sources"] + manifest["group_context"]}
    output = dict(model=args.model, manifest=MANIFEST, machine=platform.machine(), frame_step=args.profile_step, recordings=[])
    if args.model.startswith("rtmpose"):
        if args.detector is None or args.pose is None:
            parser.error("RTMPose requires local --detector and --pose ONNX files")
        output["weights"] = {"detector": digest(args.detector), "pose": digest(args.pose)}
    if args.cache:
        selected = list(rows.values())
        args.cache.mkdir(mode=0o700)
    else:
        selected = [rows[f"caucafall:{clip}"] for clip in CLIPS]
    for row in selected:
        clip = row["video_id"]
        path = Path(row["source_file"])
        media_hash = digest(path)
        if media_hash != artifacts[clip]["video_sha256"]:
            raise ValueError(f"Unexpected media checksum: {clip}")
        cache = args.cache / (path.stem+".npz") if args.cache else None
        timing = {"detector": [], "landmarks": []}
        with extractor(args.model, args.detector, args.pose, timing) as process:
            result = measure(row, path, process, cache=cache, step=args.profile_step)
        result["video_sha256"] = media_hash
        result["split"] = row["split"]
        result["stages_ms_p50"] = {key: float(np.median(v)) for key, v in timing.items() if v}
        if cache:
            result["feature_file"] = cache.name
            result["feature_sha256"] = digest(cache)
        output["recordings"].append(result)
        print(clip, result["all"], round(result["fps"], 2), flush=True)
    if args.cache:
        output.update(cache_version="accuracy-pose-v1", joint_order=SPEC.keypoints,
                      schema_version=SPEC.schema_version, coordinate_space=SPEC.coordinate_space)
        with (args.cache/"manifest.json").open("x") as target:
            json.dump(output, target, indent=2, allow_nan=False)
    with args.output.open("x") as target:
        json.dump(output, target, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
