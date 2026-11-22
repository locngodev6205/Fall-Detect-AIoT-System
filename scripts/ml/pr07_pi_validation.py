"""Export a pinned development cohort and replay GRU/BiLSTM one model per process."""
import argparse
import json
from pathlib import Path
import platform
import resource
import statistics
import time

from pr04_experiment import MANIFEST, development, load_pinned
from pr05_replay import evaluate_alerts
from pr06_benchmark import load_runner
from ml.integrity import digest

CLIPS = (
    "FallForwardS6", "FallBackwardsS7", "FallLeftS7", "FallRightS9",
    "FallSittingS9", "PickupobjectS6", "PickupobjectS7", "PickupobjectS9",
    "SitDownS7", "WalkS7",
)


def cohort(root):
    manifest = load_pinned(root/"annha-v2.1/manifest.json", MANIFEST)
    hashes = {x["video_id"]: x["video_sha256"]
              for x in manifest["sources"] + manifest["group_context"]}
    _, rows = development(root, manifest)
    selected = {x["video_id"]: x for x in rows if x["split"] == "val"
                and x["source_dataset"] == "caucafall"}
    for clip in CLIPS:
        row = selected[f"caucafall:{clip}"]
        path = Path(row["source_file"])
        yield dict(file=path.name, action=row["scene_id"], event=row["event"],
                   sha256=hashes[row["video_id"]]), path


class Trace:
    """Record threshold crossings and confirmed entries without dispatch."""
    def __init__(self, threshold):
        self.threshold = threshold
        self.raw = []
        self.alerts = []
        self.scored = []
        self.high = self.confirmed = False

    def observe(self, stamp, score, confirmed):
        high = score >= self.threshold
        if high and not self.high:
            self.raw.append(stamp)
        if confirmed and not self.confirmed:
            self.alerts.append(stamp)
        self.scored.append(stamp)
        self.high, self.confirmed = high, confirmed

    def frame(self, stream, stamp, points, present, arrived, windows):
        for window in windows:
            if window.score is None:
                self.high = False
                continue
            self.observe(window.end, window.score, False)
            self.alerts.extend(t for name, t in window.events if name == "simulated_alert")

    def evaluate(self, event):
        coverage = any(event[0] <= t <= min(event[0]+3, event[1]+1)
                       for t in self.scored) if event else None
        return {key: evaluate_alerts(event, stamps, coverage)
                for key, stamps in (("raw", self.raw), ("engine", self.alerts))}


def temperature():
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (ValueError, OSError):
        return None


def summarize(rows, key):
    result = {field: sum(row["events"][key][field] for row in rows)
              for field in ("tp", "fp", "fn")}
    total = result["tp"] + result["fn"]
    delays = [row["events"][key]["delay"] for row in rows
              if row["events"][key]["delay"] is not None]
    return dict(result, recall=result["tp"]/total if total else None,
                delay_p50_s=statistics.median(delays) if delays else None)


def run(args):
    import cv2
    import mediapipe
    import torch
    from research.benchmark import benchmark

    cv2.setNumThreads(1)
    torch.set_num_threads(2)
    rows = json.loads(args.manifest.read_text())
    if [Path(x["file"]).stem for x in rows] != list(CLIPS):
        raise ValueError("Unexpected replay cohort")
    for row in rows:
        path = args.media / Path(row["file"]).name
        if digest(path) != row["sha256"]:
            raise ValueError(f"Incorrect checksum for {path.name}")
    runner, close = load_runner(args.model, args.upstream, args.checkpoint)
    results = []
    try:
        for row in rows:
            path = args.media / Path(row["file"]).name
            trace = Trace(.5 if args.model == "gru" else
                          runner.keywords["config"]["alarm"]["confidence_threshold"])
            temp_start = temperature()
            start, cpu = time.monotonic(), time.process_time()
            if args.model == "gru":
                result = benchmark(str(path), runner.keywords["model"], 0, trace=trace)
                result = {key: result[key] for key in ("frames", "inference_ms", "model_errors")}
                if result["model_errors"]:
                    raise RuntimeError(f"GRU inference failed for {path.name}")
            else:
                result = runner(path, observe=trace.observe)
                result["inference_ms"] = result.pop("forward_ms")
            elapsed = time.monotonic()-start
            results.append(dict(
                row, **result, events=trace.evaluate(row["event"]),
                raw_times=trace.raw, engine_times=trace.alerts, elapsed_s=elapsed,
                cpu_percent=100*(time.process_time()-cpu)/elapsed,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                temperature_start_c=temp_start, temperature_end_c=temperature(),
            ))
            print(path.name, round(result["frames"]/elapsed, 2), flush=True)
    finally:
        close()
    with args.output.open("x") as target:
        json.dump(dict(machine=platform.machine(), model=args.model, torch=torch.__version__,
                       opencv=cv2.__version__, mediapipe=mediapipe.__version__,
                       fps=sum(x["frames"] for x in results)/sum(x["elapsed_s"] for x in results),
                       metrics={k: summarize(results, k) for k in ("raw", "engine")},
                       recordings=results), target, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("root", type=Path)
    export.add_argument("manifest", type=Path)
    replay = commands.add_parser("run")
    replay.add_argument("model", choices=("gru", "bilstm"))
    for field in ("manifest", "media", "checkpoint", "output"):
        replay.add_argument(field, type=Path)
    replay.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        selected = list(cohort(args.root))
        with args.manifest.open("x") as target:
            json.dump([row for row, _ in selected], target, indent=2)
        for _, path in selected:
            print(path)
    else:
        if args.output.exists() or (args.model == "bilstm" and args.upstream is None):
            parser.error("Use a fresh output and supply --upstream for BiLSTM")
        run(args)


if __name__ == "__main__":
    main()
