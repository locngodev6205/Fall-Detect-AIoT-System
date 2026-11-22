"""Freeze and evaluate a subject-balanced external GMDCSA24 pilot."""
import argparse
from collections import defaultdict
import csv
from functools import partial
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import quote

import numpy as np
import torch

from accuracy_ctr_gcn import graph_input, UPSTREAM_REVISION
from accuracy_pose import extractor, measure
from accuracy_stability import SEEDS
from ml.integrity import decoded_video_digest, digest
from pr04_experiment import MANIFEST, load_pinned
from pr08_replay import replay, summarize
from research.streaming import load_model

SOURCE = "https://raw.githubusercontent.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos/5abac76/"
VERSION = "zenodo-13354453-v2.1"
SOURCE_CATALOG_SHA = "f933879456cb414d5704f41810f840e97885dc6e6d2b2b758e61e436a1b957d1"
LABELS_SHA = "d4682729276a08be783a2c189c1617f6202f92c87c0b1b74ad88a2e1f634337a"


def temporal_interval(segments, duration, positive):
    times = sorted((float(r["start"]), float(r["end"]), int(r["label"])) for r in segments)
    if (not times or abs(times[0][0]) > .05 or abs(times[-1][1]-duration) > .08
            or any(not np.isfinite([a, b]).all() or a < 0 or a >= b for a, b, _ in times)
            or any(abs(a-prev) > .05 for (_, prev, _), (a, _, _) in zip(times, times[1:]))):
        raise ValueError("Annotation does not cover the verified recording clock")
    falls = [(a, b) for a, b, label in times if label == 1]
    if len(falls) != int(positive):
        raise ValueError("Temporal Fall count disagrees with source class")
    return falls[0] if falls else None


def freeze(labels, upstream_manifest):
    if digest(labels) != LABELS_SHA:
        raise ValueError("Expected pinned OmniFall label bytes")
    if digest(upstream_manifest) != SOURCE_CATALOG_SHA:
        raise ValueError("Expected pinned v2.1 catalog bytes")
    by_path = defaultdict(list)
    with labels.open() as stream:
        for label in csv.DictReader(stream):
            by_path[label["path"]].append(label)
    by_group = defaultdict(list)
    rejected = []
    with upstream_manifest.open() as stream:
        for src in csv.DictReader(stream):
            if src["dataset"] != "gmdcsa24" or src["source_version"] != VERSION:
                continue
            relative = Path(*Path(src["source_path"]).parts[-3:])
            subject = src["subject_id"]
            if relative.parts[0] != subject or subject not in {f"Subject {i}" for i in range(1, 5)}:
                raise ValueError("Unexpected upstream subject lineage")
            label_path = relative.with_suffix("").as_posix().replace("Subject ", "Subject_", 1)
            segments = by_path[label_path]
            positive = int(src["label"])
            if any(r["subject"] != subject.split()[-1] for r in segments):
                raise ValueError("OmniFall subject mismatch")
            try:
                event = temporal_interval(segments, float(src["duration_s"]), positive)
            except ValueError as exc:
                rejected.append(dict(recording=label_path, reason=str(exc)))
                continue
            row = dict(video_id=label_path, scene_id=relative.parts[1], subject=subject,
                       group=src["recording_group_id"], event=event, file=label_path.replace("/", "-")+".mp4",
                       source_sha256=src["source_sha256"], url=SOURCE+quote(relative.as_posix()),
                       duration=float(src["duration_s"]), fps=float(src["original_fps"]),
                       frame_count=int(src["frame_count"]))
            by_group[subject, positive].append(row)
    if len(by_group) != 8 or any(len(items) < 3 for items in by_group.values()):
        raise ValueError("Not enough eligible recordings by subject and class")
    # Fixed three per subject/class by deterministic hash, before inference.
    selected = [row for _, rows in sorted(by_group.items()) for row in sorted(
        rows, key=lambda r: hashlib.sha256(("annha-gmd-v1:"+r["video_id"]).encode()).digest())[:3]]
    return dict(protocol="gmdcsa24-v1-independent-pilot", recordings=selected, rejected=rejected,
                labels_sha256=digest(labels), source_manifest_sha256=digest(upstream_manifest),
                source_version=VERSION)


def training_fingerprints(pinned):
    train = [r for r in pinned["sources"] if r["split"] == "train"]
    subjects = {r["subject_id"] for r in train if r["source_dataset"] == "caucafall"}
    train.extend(r for r in pinned["group_context"]
                 if r["source_dataset"] == "caucafall" and r["subject_id"] in subjects)
    if any(r["source_dataset"] not in {"caucafall", "urfd", "mcfd"} for r in train):
        raise ValueError("Unexpected training source")
    return {r["video_sha256"] for r in train}, {r["decoded_sha256"] for r in train}


def evaluate(args):
    import cv2
    import subprocess
    cv2.setNumThreads(1)
    torch.set_num_threads(2)
    if subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"],
                               text=True).strip() != UPSTREAM_REVISION:
        raise ValueError("Unexpected CTR-GCN implementation")
    sys.path.insert(0, str(args.upstream.resolve()))
    from src.model import CTRGCN

    pinned = load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST)
    byte_hashes, decoded = training_fingerprints(pinned)
    bundle = json.loads(args.cohort.read_text())
    rows = bundle["recordings"]
    if len(rows) != 24 or len({r["group"] for r in rows}) != len(rows):
        raise ValueError("Unexpected cohort or repeated recording group")
    seen = set()
    for row in rows:
        path = args.media/Path(row["file"]).name
        media_sha = digest(path)
        if media_sha != row["source_sha256"] or media_sha in byte_hashes:
            raise ValueError(f"Media checksum mismatch or train overlap: {path.name}")
        frame_sha = decoded_video_digest(path)
        if frame_sha in seen or frame_sha in decoded:
            raise ValueError(f"Decoded frames overlap: {path.name}")
        seen.add(frame_sha)
        row["decoded_sha256"] = frame_sha
    models = {"gru": load_model(args.gru)}
    hashes = {"gru": digest(args.gru)}
    cache_hash = digest(args.full_cache/"manifest.json")
    for seed in SEEDS:
        path = args.artifacts/f"full-{seed}.pt"
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        if any(checkpoint[k] != v for k, v in dict(seed=seed, manifest=MANIFEST,
               pose_cache_sha256=cache_hash, width=8, architecture=UPSTREAM_REVISION).items()):
            raise ValueError("Unexpected Full checkpoint")
        model = CTRGCN(base_channels=8)
        model.load_state_dict(checkpoint["state_dict"])
        models[str(seed)] = model.eval()
        hashes[str(seed)] = digest(path)

    @torch.inference_mode()
    def score(model, inputs):
        return model(graph_input(torch.from_numpy(inputs))).sigmoid().item()

    results = {key: [] for key in models}
    with tempfile.TemporaryDirectory() as workspace:
        for row in rows:
            entry = dict(row)
            entry["event"] = tuple(row["event"]) if row["event"] else None
            path = args.media/Path(row["file"]).name
            for mode in ("lite", "full"):
                pose_file = Path(workspace)/f"{mode}.npz"
                with extractor(mode) as process:
                    quality = measure(entry, path, process, cache=pose_file)
                if quality["all"]["frames"] != row["frame_count"] or abs(quality["source_fps"]-row["fps"]) > .1:
                    raise ValueError(f"Measured clip clock does not match label provenance: {path.name}")
                with np.load(pose_file, allow_pickle=False) as poses:
                    if abs(poses["stamps"][-1]+1/quality["source_fps"]-row["duration"]) > .08:
                        raise ValueError(f"Decoded timestamp duration mismatch: {path.name}")
                    for key in ("gru",) if mode == "lite" else tuple(str(s) for s in SEEDS):
                        fn = models[key] if key == "gru" else partial(score, models[key])
                        result = replay(entry, fn, poses=(poses["stamps"], poses["points"]))
                        results[key].append(dict(result, subject=row["subject"], pose=quality))
                pose_file.unlink()
            print(row["video_id"], flush=True)
    with args.output.open("x") as target:
        json.dump(dict(protocol=bundle["protocol"], cohort_sha256=digest(args.cohort), checkpoints=hashes,
            cohort=rows, results={key: dict(metrics=summarize(values, "baseline"), recordings=values)
                                  for key, values in results.items()}), target, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("freeze")
    for name in ("labels", "upstream_manifest", "output"):
        prep.add_argument(name, type=Path)
    run = commands.add_parser("evaluate")
    for name in ("upstream", "data", "cohort", "media", "gru", "full_cache", "artifacts", "output"):
        run.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output")
    if args.command == "freeze":
        with args.output.open("x") as target:
            json.dump(freeze(args.labels, args.upstream_manifest), target, indent=2, allow_nan=False)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
