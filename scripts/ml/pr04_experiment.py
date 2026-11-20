"""Research-only CPU baselines and data-quality experiments for Dataset V2.1."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
from ml.dataset import read_keypoints_csv
from ml.features import SPEC, normalize_sequence, resample_keypoints
from ml.integrity import digest, fall_window

MANIFEST = '3c2b4f2930ad678a7fb6cf8621d67916f3a416300d07c590b8d8c7ba92b28dd3'
RAW_TEST = '4a33a4bf6d42e6df891fcaeafb5d7231807b5b64b1ce3f4a5d8972970c0d7fd2'
DEV = ('train', 'val')
SEED = 42


def load_pinned(path, sha256):
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError(f'Unexpected checksum: {path.name}')
    return json.loads(content)


def grids(row):
    path = Path(row['keypoint_csv'])
    times, points = read_keypoints_csv(path)
    features = normalize_sequence(resample_keypoints(times, points))
    stamps = times[0] + np.arange(len(features)) / SPEC.sample_rate_hz
    return stamps, features, features[:, 2::3].any(axis=1)


def starts(stamps, valid, size, event, gap=0):
    label_starts, usable = [], []
    for i in range(0, len(stamps) - size + 1, 3):
        if event and not fall_window(stamps[i:i + size], *event):
            continue
        label_starts.append(i)
        mask = valid[i:i + size]
        missing = np.flatnonzero(~mask)
        if (len(missing) <= gap and mask[0] and mask[-1]
                and (not len(missing) or np.all(np.diff(missing) == 1))):
            usable.append(i)
    return label_starts, usable


def audit(root):
    inventory = load_pinned(root / 'locked-raw-test-inventory.json', RAW_TEST)
    output = []
    for row in inventory['recordings']:
        if row['label'] != 'fall' or row['pose_preflight'] == 'PASS':
            continue
        native_time, native_pose = read_keypoints_csv(Path(row['keypoint_csv']))
        samples = resample_keypoints(native_time, native_pose)
        stamps = native_time[0] + np.arange(len(samples)) / SPEC.sample_rate_hz
        valid = normalize_sequence(samples)[:, 2::3].any(axis=1)
        event = float(row['event_start']), float(row['event_end'])
        possible, usable = starts(stamps, valid, 30, event)
        _, anywhere = starts(stamps, valid, 30, None)
        in_event = (stamps >= event[0]) & (stamps <= event[1])
        torso = lambda names: (samples[:, [SPEC.keypoints.index(name) for name in names], 2]
                                >= SPEC.minimum_visibility).any(axis=1)
        anchored = torso(('Left Shoulder', 'Right Shoulder')) & torso(('Left Hip', 'Right Hip'))
        has_landmarks = (samples[..., 2] > 0).any(axis=1)
        native_event = (native_time >= event[0]) & (native_time <= event[1])
        output.append(dict(action=row['scene_id'], subject=row['subject_id'],
                           video_id=row['video_id'], preflight=row['pose_preflight'],
                           annotation_candidates=len(possible), valid_anywhere=len(anywhere),
                           valid_event=len(usable), onset=event[0], end=event[1],
                           grid_samples=len(stamps), missing_total=int((~valid).sum()),
                           missing_during_event=int((~valid & in_event).sum()),
                           event_samples=int(in_event.sum()),
                           grid_no_landmarks=int((in_event & ~has_landmarks).sum()),
                           grid_no_torso_anchor=int((in_event & has_landmarks & ~anchored).sum()),
                           grid_failed_normalization=int((in_event & anchored & ~valid).sum()),
                           native_no_landmarks=int((native_event & ~(native_pose[..., 2] > 0).any(axis=1)).sum()),
                           native_event_samples=int(native_event.sum()),
                           native_timestamp_gaps=int((np.diff(native_time) > SPEC.max_gap_s).sum()),
                           fewest_missing_in_candidate=min(
                               (int((~valid[i:i+30]).sum()) for i in possible), default=None)))
    if len(output) != 9 or any(r['valid_event'] for r in output):
        raise ValueError('Raw Test exclusions do not reproduce')
    return output


def development(root, manifest):
    source = {row['video_id']: row for row in manifest['sources'] if row['split'] in DEV}
    subjects = {row['subject_id']: row['split'] for row in source.values()
                if row['source_dataset'] == 'caucafall'}
    for field in ('group_id', 'video_sha256', 'decoded_sha256', 'subject_id'):
        values = defaultdict(set)
        for row in source.values():
            if row[field]:
                values[(row['source_dataset'] if field == 'subject_id' else '', row[field])].add(row['split'])
        if any(len(splits) > 1 for splits in values.values()):
            raise ValueError(f'Development overlap: {field}')
    # Identify permitted recordings by subject and recording ID, then read only their pose files.
    rows = []
    with (root / 'sources-official.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            split = (subjects.get(row['subject_id']) if row['source_dataset'] == 'caucafall'
                     else source.get(row['video_id'], {}).get('split'))
            if split not in DEV:
                continue
            y = int(row['label'] == 'fall')
            original = source.get(row['video_id'])
            artifact = original or next(
                (x for x in manifest['group_context'] if x['video_id'] == row['video_id']), None)
            if artifact is None or artifact['label'] != y or artifact['subject_id'] != (row['subject_id'] or None):
                raise ValueError('Unexpected development recording')
            if row['annotation_status'] != 'UPSTREAM_VERIFIED' or digest(row['keypoint_csv']) != artifact['keypoint_sha256']:
                raise ValueError('Unverified development annotation or pose artifact')
            event = (float(row['event_start']), float(row['event_end'])) if y else None
            if event and event != (artifact['event_start'], artifact['event_end']):
                raise ValueError('Unexpected development Fall interval')
            rows.append(dict(row, split=split, y=y, event=event))
    return source, rows


def metrics(truth, predicted):
    tp = sum(int(y == 1 and p) for y, p in zip(truth, predicted, strict=True))
    fp = sum(int(y == 0 and p) for y, p in zip(truth, predicted, strict=True))
    fn = sum(int(y == 1 and not p) for y, p in zip(truth, predicted, strict=True))
    ratio = lambda a, b: a / b if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=len(truth)-tp-fp-fn, recall=ratio(tp,tp+fn),
                precision=ratio(tp,tp+fp), f1=ratio(2*tp,2*tp+fp+fn), f2=ratio(5*tp,5*tp+fp+4*fn))


def make_model(torch, architecture, size):
    nn = torch.nn
    if architecture == 'transformer':
        class Transformer(nn.Module):
            def __init__(self):
                super().__init__()
                self.project = nn.Linear(51, 32)
                self.position = nn.Parameter(torch.zeros(1, size, 32))
                self.encoder = nn.TransformerEncoder(
                    nn.TransformerEncoderLayer(32, 4, 64, .1, batch_first=True), 2)
                self.out = nn.Linear(32, 1)

            def forward(self, x):
                return self.out(self.encoder(self.project(x) + self.position).mean(dim=1)).squeeze(-1)
        return Transformer()
    if architecture == 'tcn':
        class TCN(nn.Module):
            def __init__(self):
                super().__init__()
                self.temporal = nn.Sequential(
                    nn.Conv1d(51, 32, 3, padding=1), nn.ReLU(),
                    nn.Conv1d(32, 32, 3, dilation=2, padding=2), nn.ReLU(),
                    nn.Conv1d(32, 32, 3, dilation=4, padding=4), nn.ReLU())
                self.out = nn.Linear(32, 1)

            def forward(self, x):
                return self.out(self.temporal(x.transpose(1, 2)).mean(dim=2)).squeeze(-1)
        return TCN()
    class GRU(nn.Module):
        def __init__(self):
            super().__init__()
            self.temporal = nn.GRU(51, 32, batch_first=True)
            self.out = nn.Linear(32, 1)

        def forward(self, x):
            return self.out(self.temporal(x)[0][:, -1]).squeeze(-1)
    return GRU()


def val_summary(probabilities, identities, rows):
    scores = defaultdict(list)
    by_id = {row['video_id']: row for row in rows if row['split'] == 'val'}
    truth = [by_id[identity]['y'] for identity in identities]
    for identity, score in zip(identities, probabilities, strict=True):
        scores[identity].append(float(score))
    recordings = [dict(id=key, subject=row['subject_id'], action=row['scene_id'], y=row['y'],
                       windows=len(scores[key]), score=max(scores[key], default=None))
                  for key, row in sorted(by_id.items())]
    def summarize(items):
        return metrics([r['y'] for r in items],
                       [r['score'] is not None and r['score'] >= .5 for r in items])
    available = [r for r in recordings if r['windows']]
    subject = {key: summarize([r for r in recordings if r['subject'] == key])
               for key in sorted({r['subject'] for r in recordings})}
    return dict(windows=metrics(truth, probabilities >= .5), eligible_recordings=summarize(available),
                all_development_recordings=summarize(recordings), subjects=subject,
                forward=summarize([r for r in recordings if r['action'] == 'Fall forward']),
                forward_covered=sum(r['action'] == 'Fall forward' for r in available),
                negative_unscored=sum(not r['windows'] and not r['y'] for r in recordings),
                recordings=recordings)


def fit(torch, archive, architecture, rows, size, epochs, output):
    torch.manual_seed(SEED)
    generator = torch.Generator().manual_seed(SEED)
    tensors = {}
    labels = {row['video_id']: row['y'] for row in rows}
    for split in DEV:
        data, ids = archive[split]
        tensors[split] = torch.from_numpy(np.stack(data).astype(np.float32)), ids
    x, train_ids = tensors['train']
    y = torch.tensor([labels[key] for key in train_ids], dtype=torch.float32)
    counts = Counter(train_ids)
    classes = Counter(labels[key] for key in counts)
    if len(classes) < 2:
        raise ValueError('Train lacks a class')
    weights = torch.tensor([len(train_ids)/(2*counts[key]*classes[labels[key]]) for key in train_ids])
    model = make_model(torch, architecture, size)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001)
    losses = []
    for _ in range(epochs):
        model.train()
        total = 0.
        for index in torch.randperm(len(x), generator=generator).split(32):
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(model(x[index]), y[index],
                                                                         weight=weights[index])
            loss.backward()
            optimizer.step()
            total += loss.item()*len(index)
        losses.append(total/len(x))
    model.eval()
    val_x, val_ids = tensors['val']
    with torch.no_grad():
        scores = model(val_x).sigmoid().numpy()
    result = val_summary(scores, val_ids, rows)
    checkpoint = output / f'{architecture}.pt'
    torch.save(model.state_dict(), checkpoint)
    result.update(losses=losses, parameters=sum(p.numel() for p in model.parameters()),
                  train_windows=len(x), train_recordings=len(counts), checkpoint_sha256=digest(checkpoint))
    return result


def train(root, output, epochs):
    import torch
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    dataset = root / 'annha-v2.1'
    manifest = load_pinned(dataset / 'manifest.json', MANIFEST)
    source, rows = development(root, manifest)
    quality = Counter((row['split'], row['scene_id'], row['video_id'] in source) for row in rows)
    print('Development provenance and subject audit passed:', sorted(quality.items()), flush=True)
    archive = {split: ([], []) for split in DEV}
    for row in manifest['windows']:
        if row['split'] not in DEV:
            continue
        path = dataset / row['path']
        if digest(path) != row['sha256'] or row['video_id'] not in source:
            raise ValueError('Unexpected development window')
        array = normalize_sequence(np.load(path, allow_pickle=False))
        archive[row['split']][0].append(array)
        archive[row['split']][1].append(row['video_id'])
    output.mkdir()
    report = dict(dataset_manifest_sha256=MANIFEST, seed=SEED, epochs=epochs, threshold=.5,
                  torch_version=torch.__version__, features='annha-pose-v2',
                  label_audit=[dict(split=k[0], action=k[1], admitted=k[2], count=v)
                               for k,v in sorted(quality.items())], experiments={})
    for mode, size, gap in (('baseline30',30,0), ('gap_mask30',30,3), ('short20',20,0),
                            ('short10',10,0), ('short20_mask',20,3)):
        if mode != 'baseline30':
            archive = {split: ([], []) for split in DEV}
            for row in rows:
                stamps, features, valid = grids(row)
                _, usable = starts(stamps, valid, size, row['event'], gap)
                for i in usable:
                    archive[row['split']][0].append(features[i:i+size])
                    archive[row['split']][1].append(row['video_id'])
        stage = output / mode
        stage.mkdir()
        report['experiments'][mode] = {}
        for architecture in (('transformer','tcn','gru') if mode == 'baseline30' else ('gru',)):
            measured = fit(torch, archive, architecture, rows, size, epochs, stage)
            report['experiments'][mode][architecture] = measured
            print(mode,architecture,measured['all_development_recordings'],measured['forward'],flush=True)
    return report



def scan_validation(root, experiments):
    """Scan validation causally without using the event interval to select candidate windows."""
    import torch
    torch.set_num_threads(2)
    manifest = load_pinned(root / 'annha-v2.1' / 'manifest.json', MANIFEST)
    _, rows = development(root, manifest)
    run = json.loads((experiments / 'results.json').read_text())
    if run['dataset_manifest_sha256'] != MANIFEST:
        raise ValueError('Checkpoint run does not match the development dataset')
    recordings = [(row, *grids(row)) for row in rows if row['split'] == 'val']
    results = {}
    for mode, size, gap in (('baseline30', 30, 0), ('gap_mask30', 30, 3),
                            ('short20', 20, 0), ('short10', 10, 0), ('short20_mask', 20, 3)):
        results[mode] = {}
        architectures = ('transformer', 'tcn', 'gru') if mode == 'baseline30' else ('gru',)
        for architecture in architectures:
            checkpoint = experiments / mode / f'{architecture}.pt'
            if digest(checkpoint) != run['experiments'][mode][architecture]['checkpoint_sha256']:
                raise ValueError(f'Checkpoint changed: {checkpoint}')
            model = make_model(torch, architecture, size)
            model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True))
            model.eval()
            predictions = []
            for row, stamps, features, valid in recordings:
                _, candidate = starts(stamps, valid, size, None, gap)
                event = row['event']
                alert_times = []
                if candidate:
                    batch = torch.from_numpy(np.stack([features[i:i+size] for i in candidate]))
                    with torch.no_grad():
                        probabilities = model(batch).sigmoid().numpy()
                    alert_times = [float(stamps[i+size-1]) for i, p in zip(candidate, probabilities)
                                   if p >= .5]
                matched = [t for t in alert_times if event and event[0] <= t <= event[1] + 1]
                predictions.append(dict(id=row['video_id'], subject=row['subject_id'],
                                        action=row['scene_id'], y=row['y'],
                                        candidate_count=len(candidate), alert_count=len(alert_times),
                                        detected=bool(matched if event else alert_times),
                                        before_onset=bool(event and any(t < event[0] for t in alert_times)),
                                        delay_s=(matched[0]-event[0]) if matched else None))
            def summarize(items):
                return metrics([item['y'] for item in items], [item['detected'] for item in items])
            results[mode][checkpoint.stem] = dict(
                total=summarize(predictions),
                subjects={person: summarize([p for p in predictions if p['subject'] == person])
                          for person in sorted({p['subject'] for p in predictions})},
                forward=summarize([p for p in predictions if p['action'] == 'Fall forward']),
                recordings=predictions)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('train', 'scan-validation', 'audit-test-exclusions'))
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--epochs', type=int, default=30)
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error('--epochs must be positive')
    if args.action == 'train':
        result = train(args.root, args.output, args.epochs)
        path = args.output / 'results.json'
    elif args.action == 'scan-validation':
        result, path = scan_validation(args.root, args.output), args.output / 'validation-scan.json'
    else:
        result, path = audit(args.root), args.output
    with path.open('x') as stream:
        json.dump(result, stream, indent=2)


if __name__ == '__main__':
    main()
