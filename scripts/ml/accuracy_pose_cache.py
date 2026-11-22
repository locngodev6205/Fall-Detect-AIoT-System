"""Validate pose cache provenance before loading any training or evaluation data."""
import json
from pathlib import Path

import numpy as np

from ml.features import SPEC, SHAPE, normalize_sequence, resample_keypoints
from ml.integrity import digest
from pr04_experiment import MANIFEST


class PoseCache:
    def __init__(self, root, recordings, pinned):
        self.root = Path(root)
        self.meta = json.loads((self.root/"manifest.json").read_text())
        expected = dict(cache_version="accuracy-pose-v1", manifest=MANIFEST,
                        joint_order=list(SPEC.keypoints), schema_version=SPEC.schema_version,
                        coordinate_space=SPEC.coordinate_space)
        if any(self.meta.get(key) != value for key, value in expected.items()):
            raise ValueError("Unexpected pose cache schema or provenance")
        rows = self.meta["recordings"]
        self.entries = {row["id"]: row for row in rows}
        if len(rows) != len(self.entries) or self.entries.keys() != {r["video_id"] for r in recordings}:
            raise ValueError("Unexpected or duplicate cache recordings")
        artifacts = {row["video_id"]: row for row in pinned["sources"] + pinned["group_context"]}
        for row in recordings:
            key = row["video_id"]
            entry = self.entries[key]
            event = list(row["event"]) if row["event"] else None
            if (row["split"] not in ("train", "val") or entry["split"] != row["split"]
                    or entry["action"] != row["scene_id"] or entry["event"] != event
                    or entry["video_sha256"] != artifacts[key]["video_sha256"]):
                raise ValueError(f"Pose cache source or split mismatch: {key}")

    def load(self, row):
        entry = self.entries[row["video_id"]]
        path = self.root/Path(entry["feature_file"]).name
        if digest(path) != entry["feature_sha256"]:
            raise ValueError("Feature SHA-256 mismatch")
        with np.load(path, allow_pickle=False) as data:
            stamps, points = data["stamps"], data["points"]
        if (stamps.ndim != 1 or points.shape != (len(stamps), *SHAPE) or not len(stamps)
                or points.dtype != np.float32 or not np.isfinite(points).all()
                or not np.isfinite(stamps).all() or np.any(np.diff(stamps) <= 0)
                or np.any((points[..., 2] < 0) | (points[..., 2] > 1))
                or np.any(np.abs(points[..., :2]) > 4)):
            raise ValueError(f"Invalid temporal pose tensor: {row['video_id']}")
        return stamps, points

    def grid(self, row):
        stamps, points = self.load(row)
        features = normalize_sequence(resample_keypoints(stamps, points))
        return (stamps[0] + np.arange(len(features))/SPEC.sample_rate_hz,
                features, features[:, 2::3].any(axis=1))
