"""Compare native Fall pipelines on pinned CAUCAFall Validation recordings."""

import argparse
from functools import partial
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

from pr04_experiment import MANIFEST, development, load_pinned, metrics
from ml.integrity import digest

BI_SHA = "cbf699648240d2a2c0db1b580b98d70003d0f830bbdd008da7292af4a6b7e6c8"
TCN_SHA = "2d3c3b7c1a87abddc565c0c6386c151935f6719ca73274e4b2e0de946f3127d8"


def summarize(rows):
    scored = [row for row in rows if row["prediction"] is not None]
    if not scored:
        return dict(scored=0, no_prediction=len(rows), status="NOT_ENOUGH_EVALUATION_DATA")
    status = ("DEVELOPMENT_ONLY" if len({row["label"] for row in scored}) == 2
              else "NOT_ENOUGH_EVALUATION_DATA")
    return dict(
        metrics([row["label"] for row in scored], [row["prediction"] for row in scored]),
        scored=len(scored), no_prediction=len(rows)-len(scored), status=status,
        wall_ms_per_clip_median=statistics.median(row["wall_ms"] for row in scored),
        no_prediction_fall=sum(row["label"] for row in rows if row["prediction"] is None),
        no_prediction_no_fall=sum(1-row["label"] for row in rows if row["prediction"] is None),
    )


def score_result(score, predicted, windows, **details):
    if not windows:
        return dict(score=None, prediction=None, windows=0, **details)
    if score is None or not math.isfinite(score):
        raise ValueError("Non-finite score")
    return dict(score=score, prediction=int(predicted), windows=windows, **details)


def gru_video(path, model):
    from research.benchmark import benchmark
    result = benchmark(str(path), model, complexity=0)
    return score_result(
        result["max_fall_probability"], bool(result["alerts"]), result["scored"],
        pose_coverage=result["valid_pose_frames"]/max(1, result["frames"]),
        forward_ms=result["inference_ms"], fps=result["throughput_fps"],
        errors=result["model_errors"],
    )


def tcn_video(path, detector):
    started = 0.0
    durations = []

    def before(*_):
        nonlocal started
        started = time.perf_counter()

    def after(*_):
        durations.append((time.perf_counter()-started)*1000)

    pre = detector.model.register_forward_pre_hook(before)
    post = detector.model.register_forward_hook(after)
    try:
        result = detector.analyze_video(path)
    finally:
        pre.remove()
        post.remove()
    return score_result(
        result.score, result.is_fall, len(result.windows),
        pose_coverage=result.pose_coverage, fps=result.frames*1000/result.latency_ms,
        forward_batch_ms=durations[0],
    )


def bilstm_video(path, config, classifier, *, observe=None):
    import cv2
    import numpy as np
    from src.alarm.detector import AlarmDetector, FallState
    from src.features.extractor import FeatureExtractor
    from src.features.window import SlidingWindow
    from src.pose.estimator import PoseEstimator
    from research.benchmark import quantiles
    from ml.features import video_frame_timestamp

    pose_cfg, alarm_cfg = config["pose"], config["alarm"]
    target_fps = config["video"]["target_fps"]
    estimator = PoseEstimator(
        backend=pose_cfg["backend"], model_complexity=pose_cfg["model_complexity"],
        min_detection_confidence=pose_cfg["min_detection_confidence"],
        min_tracking_confidence=pose_cfg["min_tracking_confidence"],
    )
    extractor = FeatureExtractor(keypoint_format="mediapipe")
    window = SlidingWindow(config["features"]["window_size"], extractor.NUM_FEATURES)
    alarm = AlarmDetector(
        confidence_threshold=alarm_cfg["confidence_threshold"],
        persistence_frames=alarm_cfg["persistence_frames"],
        cooldown_seconds=alarm_cfg["cooldown_seconds"],
        stillness_duration=alarm_cfg["stillness_duration_seconds"],
        ema_alpha=alarm_cfg["ema_alpha"], fps=target_fps,
        warning_threshold=alarm_cfg["warning_threshold"],
    )
    cap = cv2.VideoCapture(str(path))
    scores, durations = [], []
    frames = pose_frames = 0
    previous = None
    velocity = float("nan")
    detected = False
    stamp = None
    started = time.perf_counter()
    try:
        if not cap.isOpened():
            raise ValueError("Cannot open video")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames += 1
            if observe is not None:
                stamp = video_frame_timestamp(cap.get(cv2.CAP_PROP_POS_MSEC),
                                              cap.get(cv2.CAP_PROP_FPS), stamp)
            keypoints = estimator.estimate(frame)
            if keypoints is None:
                continue
            pose_frames += 1
            features = np.nan_to_num(extractor.extract(
                keypoints, prev_keypoints=previous, dt=1/target_fps, prev_velocity=velocity,
            ), nan=0.0)
            previous, velocity = keypoints, features[3]
            window.push(features)
            if window.is_ready:
                before = time.perf_counter()
                _, score = classifier.predict(window.get_array())
                durations.append((time.perf_counter()-before)*1000)
                if not math.isfinite(score):
                    raise ValueError("Non-finite BiLSTM score")
                scores.append(score)
                state = alarm.process_frame(score, features[0] < 45.0)
                if observe is not None:
                    observe(stamp, score, state == FallState.FALL_CONFIRMED)
                detected |= state == FallState.FALL_CONFIRMED
    finally:
        cap.release()
        estimator.release()
    if not frames:
        raise ValueError("Empty video")
    return score_result(
        max(scores, default=None), detected, len(scores), pose_coverage=pose_frames/frames,
        fps=frames/(time.perf_counter()-started), forward_ms=quantiles(durations), frames=frames,
    )


def load_runner(model, upstream, checkpoint):
    if model == "gru":
        from research.streaming import load_model
        return partial(gru_video, model=load_model(checkpoint)), lambda: None
    sys.path.insert(0, str(upstream.resolve()))
    if model == "falltcn":
        from src.inference.pipeline import FallDetector
        if digest(checkpoint) != TCN_SHA:
            raise ValueError("Unexpected FallTCN checkpoint")
        detector = FallDetector(checkpoint)
        return partial(tcn_video, detector=detector), detector.close
    if digest(checkpoint) != BI_SHA:
        raise ValueError("Unexpected BiLSTM checkpoint")
    import yaml
    from src.models.classifier import FallClassifier
    from src.features.extractor import FeatureExtractor

    config = yaml.safe_load((upstream/"config/config.yaml").read_text())
    if (config["pose"]["backend"] != "mediapipe"
            or config["pose"]["smoothing"]["enabled"]
            or config["features"]["calibration"]["enabled"]):
        raise ValueError("Expected the pinned BiLSTM demo defaults")
    cfg = config["model"]
    classifier = FallClassifier(
        model_path=checkpoint, input_size=FeatureExtractor.NUM_FEATURES,
        hidden_size=cfg["hidden_size"], num_layers=cfg["num_layers"],
        bidirectional=cfg["bidirectional"], device="cpu",
    )
    return partial(bilstm_video, config=config, classifier=classifier), lambda: None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("gru", "falltcn", "bilstm"))
    parser.add_argument("root", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    if args.model != "gru" and args.upstream is None:
        parser.error("--upstream is required for external models")
    if args.output.exists():
        parser.error("output already exists")

    import cv2
    import mediapipe
    import torch
    cv2.setNumThreads(1)
    torch.set_num_threads(2)
    manifest = load_pinned(args.root/"annha-v2.1/manifest.json", MANIFEST)
    _, rows = development(args.root, manifest)
    artifacts = {artifact["video_id"]: artifact
                 for artifact in manifest["sources"] + manifest["group_context"]}
    selection = sorted((row for row in rows if row["split"] == "val"
                        and row["source_dataset"] == "caucafall"), key=lambda row: row["video_id"])
    if not selection:
        raise ValueError("No eligible Validation recordings")
    runner, close = load_runner(args.model, args.upstream, args.checkpoint)
    predictions = []
    try:
        for row in selection:
            path = Path(row["source_file"])
            artifact = artifacts[row["video_id"]]
            started = time.perf_counter()
            try:
                if digest(path) != artifact["video_sha256"]:
                    raise ValueError("Source video SHA-256 mismatch")
                started = time.perf_counter()
                result = runner(path)
            except (OSError, ValueError, RuntimeError) as exc:
                result = score_result(None, None, 0, error=f"{type(exc).__name__}: {exc}")
            predictions.append(dict(
                result, id=row["video_id"], action=row["scene_id"], label=row["y"],
                subject=row["subject_id"], wall_ms=(time.perf_counter()-started)*1000,
            ))
            print(row["video_id"], result, flush=True)
    finally:
        close()
    with args.output.open("x") as output:
        json.dump(dict(model=args.model, manifest=MANIFEST, checkpoint_sha256=digest(args.checkpoint),
                       machine=platform.machine(), torch=torch.__version__, opencv=cv2.__version__,
                       mediapipe=mediapipe.__version__, summary=summarize(predictions),
                       predictions=predictions), output, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
