"""Controlled GRU experiments and offline replay of streaming decisions."""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

if __package__:
    from .pr04_experiment import MANIFEST, development, fall_window, grids, load_pinned, make_model, starts
else:
    from pr04_experiment import MANIFEST, development, fall_window, grids, load_pinned, make_model, starts
from ml.features import SPEC, normalize_sequence, _TimestampSampler

MODES = {'E1': (30, 0), 'E2': (30, 3), 'E3': (20, 0), 'E4': (20, 3)}


def eligible(mask, gap):
    missing = np.flatnonzero(~mask)
    return (mask[0] and mask[-1] and len(missing) <= gap
            and (len(missing) < 2 or np.all(np.diff(missing) == 1)))


class AlertState:
    """Suppress repeated crossings until a below-threshold sample and cooldown."""
    def __init__(self, threshold=.5, cooldown=2.):
        self.threshold = threshold
        self.cooldown = cooldown
        self.active = False
        self.last = -float('inf')

    def update(self, stamp, probability):
        if probability < self.threshold:
            self.active = False
        elif not self.active and stamp - self.last >= self.cooldown:
            self.active = True
            self.last = stamp
            return True
        return False


class StreamingGRU:
    """Independent prototype. Input is timestamped 17x3 pose, no external effects."""
    def __init__(self, model, size, gap):
        self.model, self.size, self.gap = model, size, gap
        self.reset()

    def reset(self):
        self.sampler = _TimestampSampler(SPEC)
        self.buffer = deque(maxlen=self.size)
        self.alert = AlertState()
        self.count = 0

    @torch.no_grad()
    def push(self, stamp, pose):
        previous = self.sampler.previous
        if previous and stamp - previous[0] > SPEC.max_gap_s:
            self.reset()
        results = []
        for point in self.sampler.push(stamp, pose):
            self.buffer.append(normalize_sequence([point])[0])
            index = self.count
            self.count += 1
            if len(self.buffer) != self.size or (index-self.size+1) % 3:
                continue
            data = np.stack(self.buffer)
            if eligible(data[:, 2::3].any(axis=1), self.gap):
                probability = float(self.model(torch.from_numpy(data[None])).sigmoid().item())
                # Emit at actual input arrival, even when a sampled grid point is earlier.
                results.append((stamp, probability, self.alert.update(stamp, probability)))
        return results


def training_examples(recordings, size, gap, matched=False):
    samples, identities, labels = [], [], []
    for row, stamps, features, valid in recordings:
        if matched:
            _, long = starts(stamps, valid, 30, row['event'])
            offset = 30 - size
            usable = [i+offset for i in long if row['event'] is None
                      or fall_window(stamps[i+10:i+30], *row['event'])]
        else:
            _, usable = starts(stamps, valid, size, row['event'], gap)
        for i in usable:
            samples.append(features[i:i+size])
            identities.append(row['video_id'])
            labels.append(row['y'])
    return np.stack(samples), identities, labels


def fit(examples, size, seed, visibility=False):
    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    samples, ids, labels = examples
    x = torch.from_numpy(samples.copy())
    if visibility:
        x[:, :, 0::3] = 0
        x[:, :, 1::3] = 0
    y = torch.tensor(labels, dtype=torch.float32)
    counts = Counter(ids)
    classes = Counter(dict(zip(ids, labels)).values())
    weights = torch.tensor([len(ids)/(2*counts[key]*classes[label]) for key,label in zip(ids, labels)])
    model = make_model(torch, 'gru', size)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001)
    losses = []
    for _ in range(30):
        total = 0.
        for index in torch.randperm(len(x), generator=gen).split(32):
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                model(x[index]), y[index], weight=weights[index])
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(index)
        losses.append(total / len(x))
    return model.eval(), dict(train_recordings=len(counts), train_windows=len(ids), train_loss=losses)


def event_outcome(event, scores):
    state = AlertState()
    alerts = [stamp for stamp, p in scores if state.update(stamp, p)]
    if event is None:
        return dict(tp=0, fn=0, fp=len(alerts), adl=bool(alerts), early=0, late=0,
                    duplicate=0, delay=None, covered=None, alerts=alerts)
    onset, end = event
    deadline = min(onset + 3., end + 1.)
    matched = [stamp for stamp in alerts if onset <= stamp <= deadline]
    early = sum(stamp < onset for stamp in alerts)
    late = sum(stamp > deadline for stamp in alerts)
    duplicate = max(0, len(matched)-1)
    return dict(tp=int(bool(matched)), fn=int(not matched), fp=early+late+duplicate,
                adl=False, early=early, late=late, duplicate=duplicate,
                delay=matched[0]-onset if matched else None,
                covered=any(onset <= stamp <= deadline for stamp, _ in scores), alerts=alerts)


def summarize(rows):
    tp,fp,fn = (sum(row[key] for row in rows) for key in ('tp','fp','fn'))
    delays = [row['delay'] for row in rows if row['delay'] is not None]
    negatives = [row for row in rows if row['event'] is None]
    return dict(tp=tp,fp=fp,fn=fn,recall=tp/(tp+fn), precision=tp/(tp+fp) if tp+fp else None,
                f1=2*tp/(2*tp+fp+fn), f2=5*tp/(5*tp+fp+4*fn),
                covered=sum(row['covered'] is True for row in rows),
                adl_hits=sum(row['adl'] for row in negatives), adl_total=len(negatives),
                early=sum(row['early'] for row in rows), late=sum(row['late'] for row in rows),
                duplicate=sum(row['duplicate'] for row in rows),
                delay_p50=float(np.median(delays)) if delays else None,
                delay_p95=float(np.percentile(delays,95)) if delays else None)


@torch.no_grad()
def evaluate(model, recordings, size, gap, visibility=False):
    rows = []
    for row, stamps, features, valid in recordings:
        _, usable = starts(stamps, valid, size, None, gap)
        scores = []
        if usable:
            x = np.stack([features[i:i+size] for i in usable])
            if visibility:
                x[...,0::3] = x[...,1::3] = 0
            p = model(torch.from_numpy(x)).sigmoid().numpy()
            scores = [(float(stamps[i+size-1]), float(a)) for i,a in zip(usable,p)]
        event = row['event']
        outcome = event_outcome(event, scores)
        if event:
            a,b = event
            masks = [(stamps >= a-1)&(stamps<a), (stamps>=a)&(stamps<=b), (stamps>b)&(stamps<=b+1)]
            outcome['missing'] = [(int((m&~valid).sum()),int(m.sum())) for m in masks]
        outcome.update(id=row['video_id'], subject=row['subject_id'], action=row['scene_id'],
                       event=event, scores=scores, file=row['source_file'])
        rows.append(outcome)
    return dict(total=summarize(rows), recordings=rows,
                subjects={s:summarize([r for r in rows if r['subject']==s])
                          for s in sorted({r['subject'] for r in rows})},
                types={a:summarize([r for r in rows if r['action']==a])
                       for a in sorted({r['action'] for r in rows if r['event']})})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    manifest = load_pinned(args.root/'annha-v2.1'/'manifest.json', MANIFEST)
    _, rows = development(args.root, manifest)
    train, val = ([ (row, *grids(row)) for row in rows if row['split']==split]
                  for split in ('train','val'))
    args.output.mkdir()
    results = dict(manifest_sha256=MANIFEST, feature_schema=SPEC.schema_version,
                   torch=torch.__version__, status='research_candidate_not_released', runs={})
    # Match exact recording and end time; gap has no effect on matched train inputs.
    for phase in ('matched','full','visibility'):
        for mode,(size,gap) in MODES.items():
            if phase=='visibility' and mode!='E4':
                continue
            examples = training_examples(train,size,gap,phase=='matched')
            for seed in (42,43,44):
                key = f'{phase}-{mode}-{seed}'
                model, meta = fit(examples,size,seed,phase=='visibility')
                checkpoint = args.output/f'{key}.pt'
                torch.save(model.state_dict(),checkpoint)
                results['runs'][key] = dict(**meta, **evaluate(model,val,size,gap,phase=='visibility'),
                                            size=size,gap=gap,seed=seed,threshold=.5,epochs=30,
                                            checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest())
                print(key,results['runs'][key]['total'],flush=True)
    (args.output/'results.json').write_text(json.dumps(results,indent=2))


if __name__=='__main__':
    main()
