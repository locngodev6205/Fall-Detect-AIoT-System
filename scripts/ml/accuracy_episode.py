"""Evaluate a causal rearm policy around the existing EventEngine (research only)."""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from pr04_experiment import MANIFEST, development, load_pinned
from accuracy_pose_cache import PoseCache
from accuracy_stability import SEEDS
from ml.features import SPEC
from ml.integrity import digest
from pr05_replay import evaluate_alerts
from pr08_replay import summarize
from research.streaming import SIZE, STRIDE

ANCHORS = [SPEC.keypoints.index(name) for name in
           ("Left Shoulder", "Right Shoulder", "Left Hip", "Right Hip")]
RECOVERY_SECONDS = (SIZE-1)/SPEC.sample_rate_hz
MAX_SCORE_GAP = (STRIDE+1)/SPEC.sample_rate_hz


def torso_angle(pose):
    joints = pose[ANCHORS]
    if not np.isfinite(joints).all() or (joints[:, 2] < SPEC.minimum_visibility).any():
        return None
    dx, up = joints[2:, :2].mean(axis=0) - joints[:2, :2].mean(axis=0)
    if up <= 0 or math.hypot(dx, up) < 1e-4:
        return None
    return math.degrees(math.atan2(abs(dx), up))


class Episode:
    def __init__(self, upright_limit):
        self.upright_limit = upright_limit
        self.latched = False
        self.recovery_start = self.previous = None

    def step(self, stamp, score, angle, alert):
        if self.latched:
            interrupted = self.previous is None or stamp-self.previous > MAX_SCORE_GAP+1e-8
            upright = angle is not None and angle <= self.upright_limit
            if interrupted or score is None or score >= .5 or not upright:
                self.recovery_start = None
            elif self.recovery_start is None:
                self.recovery_start = stamp
            elif stamp-self.recovery_start >= RECOVERY_SECONDS-1e-8:
                self.latched = False
        self.previous = stamp
        if alert and not self.latched:
            self.latched = True
            self.recovery_start = None
            return True
        return False


def filter_alerts(row, stamps, points, upright_limit):
    signals = {}
    for stamp, score in row["scores"]:
        signals[stamp] = [score, False]
    for stamp in row["events"]["baseline"]:
        if stamp not in signals:
            raise ValueError("Alert timestamp has no corresponding score")
        signals[stamp][1] = True
    episode = Episode(upright_limit)
    accepted = []
    for stamp, (score, alert) in sorted(signals.items()):
        index = np.searchsorted(stamps, stamp+1e-8, side="right")-1
        angle = torso_angle(points[index]) if index >= 0 and stamp-stamps[index] <= SPEC.max_gap_s else None
        if episode.step(stamp, score, angle, alert):
            accepted.append(stamp)
    return accepted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "full_cache", "artifacts", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    pinned = load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST)
    _, rows = development(args.data, pinned)
    rows = [r for r in rows if r["source_dataset"] == "caucafall"]
    source = {r["video_id"]: r for r in rows}
    cache = PoseCache(args.full_cache, rows, pinned)
    walks = [r for r in rows if r["split"] == "train" and not r["y"] and r["scene_id"] == "Walk"]
    recording_limits = [np.percentile([angle for p in cache.load(r)[1]
                                      if (angle := torso_angle(p)) is not None], 90) for r in walks]
    limit = float(np.median(recording_limits))
    output = {}
    for seed in SEEDS:
        run = json.loads((args.artifacts/f"full-{seed}.json").read_text())
        if run["seed"] != seed or run["pose_cache_sha256"] != digest(args.full_cache/"manifest.json"):
            raise ValueError("Full run provenance mismatch")
        results = run["results"]["ctr_gcn"]["recordings"]
        for row in results:
            stamps, points = cache.load(source[row["id"]])
            alerts = filter_alerts(row, stamps, points, limit)
            row["evaluation"]["episode"] = evaluate_alerts(
                row["event"], alerts, row["evaluation"]["baseline"]["covered"])
            row["events"]["episode"] = alerts
        output[str(seed)] = dict(
            metrics={mode: summarize(results, mode) for mode in ("baseline", "episode")},
            adl_alerts={mode: sum(len(r["events"][mode]) for r in results if not r["event"])
                        for mode in ("baseline", "episode")}, recordings=results,
        )
    with args.output.open("x") as target:
        json.dump(dict(results=output, upright_limit=limit, recovery_seconds=RECOVERY_SECONDS,
                       calibration_recordings=[r["video_id"] for r in walks]), target,
                  indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
