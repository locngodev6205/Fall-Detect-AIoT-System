"""Evaluate a fixed hybrid policy without using annotations during scoring."""
import argparse
import json
from pathlib import Path

from modules.hybrid_fall import HybridFall, MotionEvidence


def score_record(record, threshold, with_motion, raw_pose):
    engine = HybridFall(threshold=threshold, use_motion=with_motion)
    motion = MotionEvidence()
    next_pose = 0
    alerts = []
    for window in record["windows"]:
        stamp = window["arrival"]
        while next_pose < len(raw_pose) and raw_pose[next_pose][0] <= stamp + 1e-9:
            instant, points = raw_pose[next_pose]
            motion.observe(instant, points, aspect=1.5)
            next_pose += 1
        features = motion.features(stamp)
        if engine.update(stamp, window["score"], features):
            alerts.append(stamp)
    return alerts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", type=Path)
    args = parser.parse_args()
    for name in ("legacy", "ctr", "ctr_lite", "gru"):
        source = args.traces / f"{name}.json"
        if not source.exists():
            continue
        report = json.loads(source.read_text())
        scores = {}
        for record in report["records"]:
            raw = record.get("raw_pose", [])
            threshold = 0.85 if name == "legacy" else 0.5
            scores[record["clip"]] = {
                "baseline": [w["arrival"] for w in record["windows"] if w["baseline"]],
                "hybrid_fsm_smoothing": score_record(record, threshold, False, []),
            }
            if raw:
                scores[record["clip"]]["hybrid_soft_motion"] = score_record(record, threshold, True, raw)
        (args.traces / f"{name}.decisions.json").write_text(json.dumps(scores))


if __name__ == "__main__":
    main()
