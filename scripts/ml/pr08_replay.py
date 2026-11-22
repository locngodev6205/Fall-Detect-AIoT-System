"""Evaluate one causal motion policy on V2.1 development or on a video."""
import argparse
import json
from pathlib import Path
import statistics

from pr04_experiment import MANIFEST, development, grids, load_pinned
from pr05_replay import evaluate_alerts
from ml.dataset import read_keypoints_csv
from ml.features import SPEC, normalize_sequence
from research.benchmark import benchmark
from research.motion_verification import MotionVerification
from research.streaming import Stream, load_model


class Comparison:
    def __init__(self):
        self.policy = MotionVerification()
        self.events = {"baseline": [], "motion": []}
        self.poses = []
        self.scores = []
        self.valid_times = []

    def reset(self, reason):
        self.policy.history.clear()
        self.policy.upright_since = None

    def frame(self, stream, stamp, points, present, arrived, windows):
        self.poses.append((stamp, present))
        self.policy.observe(stamp, points)
        for window in windows:
            self.events["baseline"].extend(window.arrival for name, _ in window.events
                                           if name == "simulated_alert")
        if windows:
            # Multiple grid samples can arrive in a batch. One decision per input
            # frame uses the last score and only the pose available at arrival.
            score = windows[-1].score
            self.scores.append((stamp, score))
            if score is not None:
                self.valid_times.append(stamp)
            if self.policy.update(stamp, score):
                self.events["motion"].append(stamp)


def summarize(rows, mode):
    evaluations = [r["evaluation"][mode] for r in rows]
    counts = {k: sum(v[k] for v in evaluations) for k in ("tp", "fp", "fn", "duplicate")}
    tp, fp, fn = (counts[k] for k in ("tp", "fp", "fn"))
    delays = [v["delay"] for v in evaluations if v["delay"] is not None]
    return dict(counts, recall=tp/(tp+fn), precision=tp/(tp+fp) if tp+fp else None,
                f2=5*tp/(5*tp+4*fn+fp),
                delay_p50_s=statistics.median(delays) if delays else None)


def replay(row, model, start=None):
    event = row["event"]
    trace, stream = Comparison(), Stream(model)
    stamps, points = read_keypoints_csv(Path(row["keypoint_csv"]))
    for stamp, pose in zip(stamps, points, strict=True):
        if start is not None and stamp < start:
            continue
        present = bool(normalize_sequence([pose])[0, 2::3].any())
        trace.frame(stream, stamp, pose, present, None, stream.push(stamp, pose))
    covered = bool(event and any(event[0] <= t <= min(event[0]+3, event[1]+1)
                                 for t in trace.valid_times))
    phases = {}
    if event:
        a, b = event
        for name, low, high in (("before", a-2, a), ("during", a, b), ("after", b, b+2)):
            valid = [p for t, p in trace.poses if low <= t < high]
            phases[name] = [sum(valid), len(valid)]
    return dict(id=row["video_id"], action=row["scene_id"], event=event, coverage=phases,
                first_pose=next((t for t, p in trace.poses if p), None),
                first_score=next(iter(trace.valid_times), None),
                scores=trace.scores, events=trace.events,
                evaluation={k: evaluate_alerts(event, v, covered) for k, v in trace.events.items()})


def main():
    import torch
    torch.set_num_threads(2)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--data", type=Path)
    sources.add_argument("--video", help="Replay a file through MediaPipe Lite and the research stream")
    sources.add_argument("--camera", type=int, help="Research camera index, no recording or alerts")
    parser.add_argument("--seconds", type=float, default=45.)
    parser.add_argument("--retrain", action="store_true",
                        help="Run one fixed pickup-weighted training experiment on Train only")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    if args.retrain and args.data is None:
        parser.error("--retrain requires --data")
    if args.output.exists():
        parser.error("Output already exists")
    model = load_model(args.checkpoint)
    if args.data is None:
        trace = Comparison()
        live = args.camera is not None
        source = args.camera if live else args.video
        perf = benchmark(source, model, 0, live=live, limit=args.seconds if live else None,
                         trace=trace, resolution=(640, 480) if live else None)
        result = dict(perf=perf, scores=trace.scores, events=trace.events)
    else:
        _, rows = development(args.data, load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST))
        val = [r for r in rows if r["split"] == "val"]
        full = [replay(r, model) for r in val]
        cold = [replay(r, model, max(0., r["event"][0]-.5)) for r in val if r["event"]]
        result = dict(full=full, cold=cold, metrics={
            name: {mode: summarize(results, mode) for mode in ("baseline", "motion")}
            for name, results in (("full", full), ("cold", cold))})
        if args.retrain:
            from pr041_ablation import fit, training_examples
            train = [r for r in rows if r["split"] == "train"]
            weights = {r["video_id"]: 2. for r in train
                       if not r["y"] and r["scene_id"] == "Pick up object"}
            if not weights:
                raise ValueError("No verified Train pickup recordings")
            examples = training_examples([(r, *grids(r)) for r in train], 20, 3)
            trained, info = fit(examples, 20, 42, recording_weights=weights)

            @torch.inference_mode()
            def candidate(inputs):
                return trained(torch.from_numpy(inputs[None])).sigmoid().item()

            candidate_rows = [replay(r, candidate) for r in val]
            result["retrain"] = dict(info, weighted_recordings=sorted(weights),
                                      metrics=summarize(candidate_rows, "baseline"),
                                      recordings=candidate_rows)
    with args.output.open("x") as target:
        json.dump(result, target, allow_nan=False, indent=2)


if __name__ == "__main__":
    main()
