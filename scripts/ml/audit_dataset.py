"""Audit verified source identities across splits; never infer IDs from filenames."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path


def audit(manifest):
    groups = {name: defaultdict(set) for name in ("video_id", "subject_id", "sha256", "parent_id")}
    missing = Counter()
    counts = defaultdict(Counter)
    pose_frames = missing_pose_frames = 0
    videos = defaultdict(set)
    with manifest.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        if not {"split", "label", "video_id"} <= set(rows.fieldnames or []):
            raise ValueError("Manifest requires split, label and verified video_id columns")
        for row in rows:
            split = row["split"].strip().lower()
            label = row["label"].strip()
            if split == "validation":
                split = "val"
            if split not in {"train", "val", "test"} or not label:
                raise ValueError(f"Invalid split or label on row {rows.line_num}")
            counts[split][label] += 1
            if row["video_id"]:
                videos[split].add(row["video_id"].strip())
            if row.get("feature_path"):
                with (manifest.parent / row["feature_path"]).open("rb") as features:
                    digest = hashlib.file_digest(features, "sha256").hexdigest()
                if row.get("sha256") and row["sha256"].lower() != digest:
                    raise ValueError(f"SHA-256 mismatch on row {rows.line_num}")
                row["sha256"] = digest
            for field, index in groups.items():
                value = (row.get(field) or "").strip()
                if value:
                    index[value.lower() if field == "sha256" else value].add(split)
                else:
                    missing[field] += 1
            if row.get("total_frames") and row.get("missing_pose_frames"):
                total, absent = int(row["total_frames"]), int(row["missing_pose_frames"])
                if not 0 <= absent <= total:
                    raise ValueError(f"Invalid pose counts on row {rows.line_num}")
                pose_frames += total
                missing_pose_frames += absent
            else:
                missing["pose_counts"] += 1
    if not counts:
        raise ValueError("Manifest is empty")
    overlaps = {field: sum(len(splits) > 1 for splits in index.values()) for field, index in groups.items()}
    return {"counts": counts, "videos_per_split": {split: len(ids) for split, ids in videos.items()},
            "video_overlap": overlaps["video_id"], "subject_overlap": overlaps["subject_id"],
            "duplicate_hash_overlap": overlaps["sha256"], "parent_overlap": overlaps["parent_id"],
            "missing_metadata": missing, "pose_frames_audited": pose_frames,
            "missing_pose_rate": missing_pose_frames / pose_frames if pose_frames else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--fail-on-overlap", action="store_true")
    args = parser.parse_args()
    result = audit(args.manifest)
    print(json.dumps(result, indent=2))
    if args.fail_on_overlap and (
        any(result[key] for key in ("video_overlap", "subject_overlap", "duplicate_hash_overlap", "parent_overlap"))
        or result["missing_metadata"]["video_id"] or set(result["counts"]) != {"train", "val", "test"}
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
