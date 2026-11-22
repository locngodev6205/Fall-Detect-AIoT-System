"""Train one supervised CTR-GCN pilot on pinned Train; compare event replay on Validation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

from pr04_experiment import MANIFEST, development, grids, load_pinned
from pr041_ablation import training_examples
from pr08_replay import replay, summarize
from pr05_replay import evaluate_alerts
from ml.integrity import digest
from research.streaming import SIZE, load_model

UPSTREAM_REVISION = "dada2669566897ac0432d681c0898bb6208938a2"


HARD_NEGATIVE_ACTIONS = frozenset({"Sit down", "Kneel"})


def recording_weights(ids, labels, hard_negative_ids):
    """Increase exposure to verified difficult ADLs while preserving total class mass."""
    counts = Counter(ids)
    classes = Counter(dict(zip(ids, labels, strict=True)).values())
    weights = np.array([len(ids)/(2*counts[key]*classes[y])
                        for key, y in zip(ids, labels, strict=True)])
    negative = np.asarray(labels) == 0
    mass = weights[negative].sum()
    for index, key in enumerate(ids):
        if negative[index] and key in hard_negative_ids:
            weights[index] *= 2
    if mass:
        weights[negative] *= mass/weights[negative].sum()
    return weights


def graph_input(inputs):
    return inputs.reshape(-1, SIZE, 17, 3).permute(0, 3, 1, 2).unsqueeze(-1).contiguous()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("upstream", "data", "baseline", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--hard-negatives", action="store_true")
    parser.add_argument("--pose-cache", type=Path)
    parser.add_argument("--checkpoint-out", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.checkpoint_out and args.checkpoint_out.exists():
        parser.error("Use a fresh checkpoint output")
    if args.output.exists():
        parser.error("Use a fresh output")
    import subprocess
    revision = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"],
                                       text=True).strip()
    if revision != UPSTREAM_REVISION:
        raise ValueError("Unexpected CTR-GCN upstream revision")
    sys.path.insert(0, str(args.upstream.resolve()))
    from src.model import CTRGCN

    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    baseline = load_model(args.baseline)
    manifest = load_pinned(args.data/"annha-v2.1/manifest.json", MANIFEST)
    _, rows = development(args.data, manifest)
    cache = None
    if args.pose_cache:
        from accuracy_pose_cache import PoseCache
        rows = [row for row in rows if row["source_dataset"] == "caucafall"]
        cache = PoseCache(args.pose_cache, rows, manifest)
    train = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "val"]
    samples, ids, labels = training_examples([(row, *(cache.grid(row) if cache else grids(row))) for row in train], SIZE, 3)
    hard_ids = {r["video_id"] for r in train
                if not r["y"] and r["scene_id"] in HARD_NEGATIVE_ACTIONS} if args.hard_negatives else set()
    hard_ids.intersection_update(ids)
    if args.hard_negatives and not hard_ids:
        raise ValueError("No eligible Train hard negatives")
    weights = recording_weights(ids, labels, hard_ids)
    device = torch.device(args.device)
    x = graph_input(torch.from_numpy(samples)).to(device)
    y = torch.tensor(labels, dtype=torch.float32, device=device)
    w = torch.tensor(weights, dtype=torch.float32, device=device)
    model = CTRGCN(base_channels=8).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001)
    started = time.perf_counter()
    losses = []
    for epoch in range(12):
        total_loss = 0.
        for idx in torch.randperm(len(x)).split(32):
            idx = idx.to(device)
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                model(x[idx]), y[idx], weight=w[idx])
            loss.backward()
            optimizer.step()
            total_loss += loss.item()*len(idx)
        losses.append(total_loss/len(x))
        print(f"epoch {epoch+1}: {losses[-1]:.4f}", flush=True)
    train_seconds = time.perf_counter()-started
    model.eval()

    @torch.inference_mode()
    def candidate(inputs):
        return model(graph_input(torch.from_numpy(inputs)).to(device)).sigmoid().item()

    result = {}
    for name, score in (("gru", baseline), ("ctr_gcn", candidate)):
        start = time.perf_counter()
        # E4-42 is always evaluated on the original MediaPipe pose, never on RTMPose.
        loader = cache.load if cache and name == "ctr_gcn" else lambda _: None
        details = [replay(row, score, poses=loader(row)) for row in validation]
        cold = [replay(row, score, max(0., row["event"][0]-.5), poses=loader(row))
                for row in validation if row["event"]]
        for row in details:
            above = False
            crossings = []
            for stamp, probability in row["scores"]:
                high = probability is not None and probability >= .5
                if high and not above:
                    crossings.append(stamp)
                above = high
            row["evaluation"]["raw"] = evaluate_alerts(
                row["event"], crossings, row["evaluation"]["baseline"]["covered"])
            row["events"]["raw"] = crossings
        result[name] = dict(metrics=summarize(details, "baseline"),
                            raw=summarize(details, "raw"), cold=summarize(cold, "baseline"),
                            replay_wall_s=time.perf_counter()-start, recordings=details,
                            cold_recordings=cold)
    cache_hash = digest(args.pose_cache/"manifest.json") if cache else None
    if args.checkpoint_out:
        with args.checkpoint_out.open("xb") as target:
            torch.save(dict(state_dict=model.cpu().state_dict(), pose_cache_sha256=cache_hash,
                            seed=args.seed, manifest=MANIFEST, width=8, architecture=revision), target)
    with args.output.open("x") as target:
        json.dump(dict(results=result, revision=revision, manifest=MANIFEST, seed=args.seed,
                       train_recordings=len(set(ids)), hard_negative_recordings=sorted(hard_ids), train_windows=len(ids), device=str(device), pose_cache_sha256=cache_hash,
                       pose_extractor=cache.meta["model"] if cache else "legacy_lite_csv",
                       train_seconds=train_seconds, losses=losses,
                       parameters=sum(p.numel() for p in model.parameters())),
                  target, allow_nan=False, indent=2)


if __name__ == "__main__":
    main()
