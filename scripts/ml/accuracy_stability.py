"""Summarize fixed-seed event replays and inspect Full seed-42 false alerts."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean, stdev

import numpy as np

from pr04_experiment import MANIFEST, development, load_pinned

from accuracy_compare import paired
from accuracy_pose_cache import PoseCache
from ml.features import normalize_sequence
from ml.integrity import digest

SEEDS = (42, 123, 2026)
KEYS = ("tp", "fp", "fn")


def metric_fields(result):
    metrics = result["metrics"]
    return [metrics[key] for key in ("tp", "fp", "fn", "recall", "precision", "f2", "delay_p50_s")]


def interval_flags(event, alerts):
    if event is None:
        return ["ADL"] * len(alerts)
    start, end = event
    deadline = min(start+3., end+1.)
    matched = False
    result = []
    for stamp in alerts:
        if stamp < start:
            result.append("early")
        elif stamp > deadline:
            result.append("late")
        elif matched:
            result.append("duplicate")
        else:
            result.append("TP")
            matched = True
    return result


def describe(value):
    return "—" if value is None else f"{value:.3f}"


def spread(values):
    sample = [v for v in values if v is not None]
    if len(sample) != len(values):
        return f"— ({len(sample)}/{len(values)} đo được)"
    return f"{mean(sample):.3f} ± {stdev(sample):.3f}"


def score_context(scores, t):
    window = [(stamp, p) for stamp, p in scores if p is not None and t-2. <= stamp <= t+1.e-8]
    return " ".join(f"{stamp:.2f}@{p:.2f}" for stamp, p in window) or "—"


def table(runs, source):
    columns = ("TP", "FP", "FN", "Recall", "Precision", "F2", "Trễ p50 (s)")
    print("| Model | Seed | " + " | ".join(columns) + " |")
    print("| --- | ---: |" + " ---: |"*len(columns))
    grouped = {}
    for model, results in runs.items():
        by_group = defaultdict(list)
        for seed, data in zip(SEEDS, results, strict=True):
            result = data["results"]["ctr_gcn"]
            values = metric_fields(result)
            print(f"| {model} | {seed} | " + " | ".join(map(describe, values)) + " |")
            counts = defaultdict(lambda: [0, 0, 0])
            for row in result["recordings"]:
                metadata = source[row["id"]]
                for group in ("Subject " + metadata["subject_id"], metadata["scene_id"]):
                    for i, key in enumerate(KEYS):
                        counts[group][i] += row["evaluation"]["baseline"][key]
            for group, fields in counts.items():
                by_group[group].append(fields)
        print(f"| {model} | Mean ± SD | " + " | ".join(map(spread, zip(
            *(metric_fields(data["results"]["ctr_gcn"]) for data in results), strict=True))) + " |")
        grouped[model] = by_group
    print("\n| Hành động / subject | Lite TP/FP/FN theo seed 42, 123, 2026 | Full TP/FP/FN theo seed 42, 123, 2026 |")
    print("| --- | --- | --- |")
    for group in sorted(grouped["lite"]):
        format_runs = lambda model: " · ".join("/".join(map(str, v)) for v in grouped[model][group])
        print(f"| {group} | {format_runs('lite')} | {format_runs('full')} |")


def fp_table(rows, cache, source, train):
    print("| Recording | Loại | Alert (s) | Pose trong 2 s trước báo | Score 2 s trước báo (s@p) | Train cùng hoạt động |")
    print("| --- | --- | ---: | ---: | --- | ---: |")
    for row in rows:
        alerts = row["events"]["baseline"]
        flags = interval_flags(row["event"], alerts)
        if not any(flag != "TP" for flag in flags):
            continue
        stamps, points = cache.load(source[row["id"]])
        valid = normalize_sequence(points)[:, 2::3].any(axis=1)
        for t, flag in zip(alerts, flags, strict=True):
            if flag == "TP":
                continue
            we = (stamps >= t-2.) & (stamps <= t+1.e-8)
            count = sum(r["scene_id"] == row["action"] for r in train)
            print(f"| {row['id'].split(':')[-1]} | {flag} | {t:.2f} | "
                  f"{valid[we].sum()}/{we.sum()} | {score_context(row['scores'], t)} | {count} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "artifacts", "full_cache"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    pinned = load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST)
    _, rows = development(args.data, pinned)
    rows = [r for r in rows if r["source_dataset"] == "caucafall"]
    source = {r["video_id"]: r for r in rows}
    runs = {mode: [json.loads((args.artifacts/f"{mode}-{seed}.json").read_text()) for seed in SEEDS]
            for mode in ("lite", "full")}
    reference = runs["full"][0]["results"]["ctr_gcn"]["recordings"]
    for mode, group in runs.items():
        for seed, run in zip(SEEDS, group, strict=True):
            if run["seed"] != seed or run["pose_extractor"] != mode or run["manifest"] != MANIFEST:
                raise ValueError("Unexpected run provenance")
            list(paired(reference, run["results"]["ctr_gcn"]["recordings"]))
    full = PoseCache(args.full_cache, rows, pinned)
    if any(r["pose_cache_sha256"] != digest(args.full_cache/"manifest.json") for r in runs["full"]):
        raise ValueError("Full cache differs from the evaluated runs")
    table(runs, source)
    print()
    fp_table(reference, full, source, [r for r in rows if r["split"] == "train"])


if __name__ == "__main__":
    main()
