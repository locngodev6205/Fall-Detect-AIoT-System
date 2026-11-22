"""Build a portable Full-pose bundle and train matched CTR-GCN experiments."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import torch

from pr04_experiment import MANIFEST, development, load_pinned
from accuracy_episode import filter_alerts, torso_angle
from pr05_replay import evaluate_alerts
from accuracy_ctr_gcn import UPSTREAM_REVISION, graph_input, recording_weights
from accuracy_pose import extractor, measure
from accuracy_pose_cache import PoseCache
from ml.features import SPEC, normalize_sequence, resample_keypoints
from ml.integrity import digest
from pr041_ablation import training_examples
from pr08_replay import replay, summarize
from research.streaming import SIZE

VERSION = "annha-multisource-full-v1"
LICENSES = {"caucafall": ("v5", "CC BY 4.0"),
            "urfd": ("official cam0 RGB / PR-03 clock", "CC BY-NC-SA 4.0")}


def write_json(path, data):
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")
    temp.replace(path)


def validate_partition(rows):
    for field in ("group_id", "video_sha256", "decoded_sha256", "subject"):
        splits = {}
        for row in rows:
            data = row[field]
            if not data:
                if field != "subject":
                    raise ValueError(f"Missing {field}")
                continue
            key = (row["dataset"], data) if field == "subject" else data
            if splits.setdefault(key, row["split"]) != row["split"]:
                raise ValueError(f"Split overlap by {field}")


def prepare(data, full_cache, target):
    import cv2
    import mediapipe
    cv2.setNumThreads(1)
    pinned = load_pinned(data/"annha-v2.1/manifest.json", MANIFEST)
    _, all_rows = development(data, pinned)
    artifacts = {a["video_id"]: a for a in pinned["sources"]+pinned["group_context"]}
    caucafall = [r for r in all_rows if r["source_dataset"] == "caucafall"]
    cache = PoseCache(full_cache, caucafall, pinned)
    if cache.meta["model"] != "full" or mediapipe.__version__ != "0.10.14":
        raise ValueError("Expected MediaPipe Full 0.10.14")
    asset = Path(mediapipe.__file__).parent/"modules/pose_landmark/pose_landmark_full.tflite"
    asset_hash = "e9a5c5cb17f736fafd4c2ec1da3b3d331d6edbe8a0d32395855aeb2cdfd64b9f"
    if digest(asset) != asset_hash:
        raise ValueError("Unexpected Full landmark weights")
    target.mkdir(mode=0o700)
    exported = []
    for row in all_rows:
        name = row["source_dataset"]
        if name not in LICENSES or row["split"] != "train":
            continue
        key = row["video_id"]
        a = artifacts[key]
        if a["provenance_status"] != "VERIFIED" or a["group_status"] != "VERIFIED":
            raise ValueError(f"Unverified provenance: {key}")
        outfile = target/f"{len(exported):03d}.npz"
        if name == "caucafall":
            cache.load(row)
            shutil.copyfile(full_cache/cache.entries[key]["feature_file"], outfile)
        else:
            video = Path(row["source_file"])
            if digest(video) != a["video_sha256"]:
                raise ValueError(f"Video SHA-256 mismatch: {key}")
            with extractor("full") as process:
                measured = measure(row, video, process, cache=outfile)
            if measured["all"]["frames"] != a["frame_count"]:
                raise ValueError(f"URFD decoded frame count changed: {key}")
            # The RGB reconstruction has a nominal playback FPS. Keep the
            # original synchronized timestamps already verified against cam0.
            from ml.dataset import read_keypoints_csv
            original, _ = read_keypoints_csv(Path(row["keypoint_csv"]))
            with np.load(outfile, allow_pickle=False) as values:
                points = values["points"]
            if len(original) != len(points) or np.any(np.diff(original) <= 0):
                raise ValueError(f"URFD source-frame clocks disagree: {key}")
            np.savez_compressed(outfile, stamps=original, points=points)
        release, license_id = LICENSES[name]
        exported.append(dict(video_id=key, dataset=name, release=release, license=license_id,
            split="val" if name == "caucafall" and a["subject_id"] == "8" else "train",
            subject=a["subject_id"], group_id=a["group_id"], camera=a["camera_id"],
            event=row["event"], y=row["y"], scene_id=row["scene_id"],
            annotation_source=a["annotation_source"], annotation_version=a["annotation_version"],
            video_sha256=a["video_sha256"], decoded_sha256=a["decoded_sha256"],
            source_ref=a["source_ref"], feature_file=outfile.name, feature_sha256=digest(outfile)))
        print(key, flush=True)
    validate_partition(exported)
    write_json(target/"manifest.json", dict(version=VERSION, upstream_manifest=MANIFEST, model="full",
        mediapipe=mediapipe.__version__, opencv=cv2.__version__, pose_asset_sha256=asset_hash,
        joint_order=SPEC.keypoints, schema_version=SPEC.schema_version,
        pose_config=dict(model_complexity=1, smooth_landmarks=True, coordinate_space=SPEC.coordinate_space,
                         sample_rate_hz=SPEC.sample_rate_hz, window=SIZE, stride=3, gap=3),
        not_in_bundle=["V2.1 validation", "V2.1 locked test", "GMDCSA24 pilot", "MCFD", "Le2i"],
        recordings=exported))


def read_bundle(root, mode):
    manifest = json.loads((root/"manifest.json").read_text())
    config = manifest["pose_config"]
    if (config != dict(model_complexity=1, smooth_landmarks=True, coordinate_space=SPEC.coordinate_space,
                       sample_rate_hz=SPEC.sample_rate_hz, window=SIZE, stride=3, gap=3)
            or manifest["pose_asset_sha256"] != "e9a5c5cb17f736fafd4c2ec1da3b3d331d6edbe8a0d32395855aeb2cdfd64b9f"):
        raise ValueError("Unexpected pose extractor configuration")
    if (manifest["version"] != VERSION or manifest["upstream_manifest"] != MANIFEST
            or manifest["model"] != "full" or manifest["mediapipe"] != "0.10.14"
            or manifest["joint_order"] != list(SPEC.keypoints) or manifest["schema_version"] != SPEC.schema_version):
        raise ValueError("Unexpected bundle contract")
    rows = manifest["recordings"]
    validate_partition(rows)
    if len({r["video_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate recording IDs")
    if any(r["dataset"] not in LICENSES or r["split"] not in ("train", "val")
           or (r["y"] != int(r["event"] is not None)) for r in rows):
        raise ValueError("Unexpected recording provenance or label")
    selected = [r for r in rows if mode == "multi" or r["dataset"] == "caucafall"]
    streams = {}
    for row in selected:
        path = root/Path(row["feature_file"]).name
        if digest(path) != row["feature_sha256"]:
            raise ValueError("Feature hash mismatch")
        with np.load(path, allow_pickle=False) as values:
            times, points = values["stamps"], values["points"]
        if (times.ndim != 1 or points.shape != (len(times), 17, 3) or not len(times)
                or points.dtype != np.float32 or not np.isfinite(points).all()
                or not np.isfinite(times).all() or np.any(np.diff(times) <= 0)
                or np.any((points[..., 2] < 0) | (points[..., 2] > 1))):
            raise ValueError("Invalid source pose tensor")
        streams[row["video_id"]] = times, points
    return selected, streams


def train(args):
    cfg = json.loads(args.config.read_text())
    if cfg["epochs"] < 1 or cfg["batch_size"] < 1 or cfg["patience"] < 0 or cfg["learning_rate"] <= 0:
        raise ValueError("Invalid training configuration")
    if subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"],
                               text=True).strip() != UPSTREAM_REVISION:
        raise ValueError("Unexpected upstream implementation")
    sys.path.insert(0, str(args.upstream.resolve()))
    from src.model import CTRGCN

    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    if args.require_gpu and device.type != "cuda":
        raise RuntimeError("Kaggle GPU accelerator is required")
    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    rows, streams = read_bundle(args.bundle, args.mode)
    train_rows, val = [r for r in rows if r["split"] == "train"], [r for r in rows if r["split"] == "val"]
    recordings = []
    for row in train_rows:
        stamps, points = streams[row["video_id"]]
        grid = normalize_sequence(resample_keypoints(stamps, points))
        recordings.append((row, stamps[0]+np.arange(len(grid))/SPEC.sample_rate_hz, grid, grid[:, 2::3].any(axis=1)))
    samples, ids, labels = training_examples(recordings, SIZE, 3)
    if set(labels) != {0, 1} or {r["y"] for r in val} != {0, 1}:
        raise ValueError("Train and internal validation both require two classes")
    if args.mode == "multi" and len({k.split(":")[0] for k in ids}) < 2:
        raise ValueError("Multi-source training lost a dataset after window preflight")
    x = graph_input(torch.from_numpy(samples)).to(device)
    y = torch.tensor(labels, dtype=torch.float32, device=device)
    w = torch.tensor(recording_weights(ids, labels, set()), dtype=torch.float32, device=device)
    model = CTRGCN(base_channels=8).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"])
    identity = dict(bundle_sha=digest(args.bundle/"manifest.json"), mode=args.mode, seed=args.seed,
                    recipe=cfg, upstream=UPSTREAM_REVISION, device=device.type, torch=str(torch.__version__))
    print(identity, flush=True)

    @torch.inference_mode()
    def score(inputs):
        return model(graph_input(torch.from_numpy(inputs)).to(device)).sigmoid().item()

    def evaluate(cold=False):
        return [replay(r, score, max(0., r["event"][0]-.5) if cold else None,
                       poses=streams[r["video_id"]]) for r in val if not cold or r["event"]]

    last, best = args.output/"last.pt", args.output/"best.pt"
    start, history, best_f2, best_epoch, best_state = 0, [], -1., 0, None
    if args.resume:
        state = torch.load(last, map_location=device, weights_only=True)
        if state["identity"] != identity:
            raise ValueError("Resume provenance mismatch")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        history, start, best_f2, best_epoch, best_state = (
            state[k] for k in ("history", "epoch", "best_f2", "best_epoch", "best_state"))
    else:
        args.output.mkdir(mode=0o700)

    def save(path, payload):
        temp = path.with_suffix(".tmp")
        torch.save(payload, temp)
        temp.replace(path)

    for epoch in range(start, cfg["epochs"]):
        if cfg["patience"] and epoch-best_epoch >= cfg["patience"]:
            break
        model.train()
        generator = torch.Generator().manual_seed(args.seed+epoch)
        loss_sum = 0.
        for indices in torch.randperm(len(x), generator=generator).split(cfg["batch_size"]):
            indices = indices.to(device)
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                model(x[indices]), y[indices], weight=w[indices])
            loss.backward()
            optimizer.step()
            loss_sum += loss.item()*len(indices)
        model.eval()
        summary = summarize(evaluate(), "baseline")
        history.append(dict(epoch=epoch+1, train_loss=loss_sum/len(x), validation=summary))
        if summary["f2"] > best_f2:
            best_f2, best_epoch = summary["f2"], epoch+1
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        save(last, dict(identity=identity, model=model.state_dict(), optimizer=optimizer.state_dict(),
                        history=json.loads(json.dumps(history)), epoch=epoch+1,
                        best_f2=best_f2, best_epoch=best_epoch,
                        best_state=best_state))
        write_json(args.output/"history.json", history)
        print(epoch+1, summary, flush=True)
        if cfg["patience"] and epoch+1-best_epoch >= cfg["patience"]:
            break
    model.load_state_dict(best_state)
    model.eval()
    save(best, dict(identity=identity, state_dict=best_state, epoch=best_epoch, width=8))
    recordings, cold = evaluate(), evaluate(cold=True)
    outcome = summarize(recordings, "baseline")
    tp, fp, fn = (outcome[k] for k in ("tp", "fp", "fn"))
    outcome["f1"] = 2*tp / (2*tp+fp+fn)
    walks = [r for r in train_rows if r["scene_id"] == "Walk" and not r["y"]]
    limits = [np.percentile(angles, 90) for r in walks
              if (angles := [a for pose in streams[r["video_id"]][1]
                             if (a := torso_angle(pose)) is not None])]
    episode = None
    if limits:
        limit = float(np.median(limits))
        for row in recordings:
            alerts = filter_alerts(row, *streams[row["id"]], limit)
            row["events"]["episode"] = alerts
            row["evaluation"]["episode"] = evaluate_alerts(
                row["event"], alerts, row["evaluation"]["baseline"]["covered"])
        episode = dict(upright_limit=limit, metrics=summarize(recordings, "episode"))
    write_json(args.output/"evaluation.json", dict(identity=identity, best_epoch=best_epoch,
        checkpoint_sha256=digest(best), training_recordings=sorted(set(ids)),
        windows_by_source=dict(Counter(key.split(":")[0] for key in ids)),
        validation=outcome, episode_ablation=episode, cold=summarize(cold, "baseline"), recordings=recordings, status="DEVELOPMENT"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    for field in ("data", "full_cache", "output"):
        build.add_argument(field, type=Path)
    fit = commands.add_parser("train")
    for field in ("bundle", "upstream", "config", "output"):
        fit.add_argument(field, type=Path)
    fit.add_argument("--mode", choices=("single", "multi"), required=True)
    fit.add_argument("--seed", type=int, default=42)
    fit.add_argument("--resume", action="store_true")
    fit.add_argument("--cpu", action="store_true")
    fit.add_argument("--require-gpu", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.data, args.full_cache, args.output)
    else:
        train(args)


if __name__ == "__main__":
    main()
