"""Render recording-level event and pose results from paired benchmark JSON."""
import argparse
from collections import defaultdict
import json
import re
from pathlib import Path


def paired(left, right):
    indexed = {row["id"]: row for row in right}
    if (len(indexed) != len(right) or len({row["id"] for row in left}) != len(left)
            or {row["id"] for row in left} != indexed.keys()):
        raise ValueError("Benchmark cohorts differ or contain duplicate recordings")
    for row in left:
        other = indexed[row["id"]]
        if row["event"] != other["event"] or row["action"] != other["action"]:
            raise ValueError(f"Annotation mismatch for {row['id']}")
        yield row, other


def score_trace(row):
    """Format peak score/time and contiguous high-score ranges; None breaks a run."""
    scores = [(t, p) for t, p in row["scores"] if p is not None]
    if not scores:
        return "—"
    peak_t, peak_score = max(scores, key=lambda item: item[1])
    ranges = []
    high = []
    for t, score in row["scores"] + [(None, None)]:
        if score is not None and score >= .5:
            high.append(t)
        elif high:
            ranges.append(f"{high[0]:.2f}–{high[-1]:.2f}")
            high = []
    return f"{peak_score:.3f}@{peak_t:.2f}; " + (", ".join(ranges) or "—")


def event_table(data, title, adl_coverage):
    print(f"\n### {title}\n")
    print("| Recording | Hành động | Fall interval (s) | Pose trước / trong / sau hoặc cả clip ADL | Match GRU → CTR | Alert GRU → CTR (s) | Score GRU | Score CTR |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    totals = defaultdict(lambda: [0]*6)
    for gru, ctr in paired(*(data["results"][key]["recordings"] for key in ("gru", "ctr_gcn"))):
        a, b = (row["evaluation"]["baseline"] for row in (gru, ctr))
        subject = re.search(r"S(\d+)$", gru["id"])
        for group in (gru["action"], "Subject " + (subject[1] if subject else "unknown")):
            for i, value in enumerate([a["tp"], a["fp"], a["fn"], b["tp"], b["fp"], b["fn"]]):
                totals[group][i] += value
        coverage = " / ".join("/".join(map(str, gru["coverage"][k]))
                              for k in ("before", "during", "after")) if gru["event"] else adl_coverage.get(gru["id"], "—")
        stamps = ["; ".join(f"{t:.2f}" for t in row["events"]["baseline"]) or "—"
                  for row in (gru, ctr)]
        interval = "–".join(f"{t:.2f}" for t in gru["event"]) if gru["event"] else "—"
        print(f"| {gru['id'].split(':')[-1]} | {gru['action']} | {interval} | {coverage} | "
              f"{a['tp']}/{a['fp']}/{a['fn']} → {b['tp']}/{b['fp']}/{b['fn']} | "
              f"{stamps[0]} → {stamps[1]} | {score_trace(gru)} | {score_trace(ctr)} |")
    print("\n| Hành động / Subject | GRU TP/FP/FN | CTR TP/FP/FN |")
    print("| --- | --- | --- |")
    for name, counts in sorted(totals.items()):
        print(f"| {name} | {'/'.join(map(str, counts[:3]))} | {'/'.join(map(str, counts[3:]))} |")


def pose_table(lite, rtm):
    if lite["manifest"] != rtm["manifest"]:
        raise ValueError("Different source manifest")
    print("| Recording | Pose toàn clip | Pose trong Fall | Pose sau Fall | Missing joints toàn clip | Dropout dài nhất trong Fall | FPS | p50 ms | Peak RSS MiB |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for a, b in paired(lite["recordings"], rtm["recordings"]):
        if a["source_fps"] != b["source_fps"] or a.get("source_size") != b.get("source_size"):
            raise ValueError(f"Source cadence or size mismatch for {a['id']}")
        fields = []
        for phase in ("all", "fall", "after"):
            left, right = a.get(phase), b.get(phase)
            if bool(left) != bool(right) or (left and left["frames"] != right["frames"]):
                raise ValueError(f"Frame count mismatch for {a['id']} ({phase})")
            fields.append(f"{left['usable']}/{left['frames']} → {right['usable']}/{right['frames']}"
                          if left else "—")
        fields.append(f"{a['all']['missing_joints']} → {b['all']['missing_joints']}")
        fields.append(f"{a['fall']['longest_unusable_frames']} → {b['fall']['longest_unusable_frames']}"
                      if a.get("fall") else "—")
        for key in ("fps", "pose_ms_p50", "process_peak_rss_mib"):
            fields.append(f"{a[key]:.2f} → {b[key]:.2f}")
        print("| " + " | ".join([a["id"].split(":")[-1], *fields]) + " |")


def read_adl_coverage(root):
    from pr04_experiment import MANIFEST, development, load_pinned
    from ml.dataset import read_keypoints_csv
    from ml.features import normalize_sequence

    _, rows = development(root, load_pinned(root/"annha-v2.1/manifest.json", MANIFEST))
    result = {}
    for row in rows:
        if row["split"] == "val" and row["event"] is None:
            _, raw = read_keypoints_csv(Path(row["keypoint_csv"]))
            valid = normalize_sequence(raw)[:, 2::3].any(axis=1)
            result[row["video_id"]] = f"{valid.sum()}/{len(valid)}"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot", type=Path)
    parser.add_argument("--weighted", type=Path)
    parser.add_argument("--pose", type=Path, nargs=2, metavar=("LITE", "RTM"))
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    coverage = read_adl_coverage(args.data) if args.data else {}
    event_table(json.loads(args.pilot.read_text()), "CTR-GCN pilot và GRU", coverage)
    if args.weighted:
        event_table(json.loads(args.weighted.read_text()), "CTR-GCN hard-negative và GRU", coverage)
    if args.pose:
        print("\n### Pose Lite → RTMPose\n")
        pose_table(*(json.loads(path.read_text()) for path in args.pose))


if __name__ == "__main__":
    main()
