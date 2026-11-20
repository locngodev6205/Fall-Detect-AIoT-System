"""Opt-in local research telemetry and reproducible replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from ml.features import SPEC
from .streaming import CHECKPOINT_SHA, GAP, SIZE, STRIDE, Stream, load_model, valid_window

TOLERANCE = 1e-5


class Trace:
    def __init__(self, directory, *, scenario, include_pose=False):
        directory.mkdir(mode=0o700)
        self.directory = directory
        self.path = directory / 'trace.jsonl'
        self.include_pose = include_pose
        self.scenario = scenario

    def __enter__(self):
        self.file = open(self.path, 'x', opener=lambda path, flags: os.open(path, flags, 0o600))
        self.write(dict(kind='header', version=1, scenario=self.scenario, pose=self.include_pose,
                        schema=SPEC.schema_version, checkpoint=CHECKPOINT_SHA, rate=SPEC.sample_rate_hz,
                        window=SIZE, stride=STRIDE, gap=GAP, threshold=.5, cooldown=2, confirmations=1))
        return self

    def __exit__(self, exc_type, *_):
        self.file.close()
        if exc_type is None:
            checksum = hashlib.sha256(self.path.read_bytes()).hexdigest()
            with (self.directory/'sha256').open('x') as sidecar:
                sidecar.write(checksum+'\n')

    def write(self, value):
        self.file.write(json.dumps(value, allow_nan=False)+'\n')

    def frame(self, stream, stamp, points, present, arrived, windows):
        row = dict(kind='frame', stamp=stamp, arrival_elapsed_s=arrived, pose_valid=present,
                   preprocessing_ms=stream.preprocess_ms, resets=len(stream.resets)-1,
                   latest_reset=stream.resets[-1], state=stream.engine.state,
                   last_alert=stream.engine.last_alert if np.isfinite(stream.engine.last_alert) else None,
                   windows=[window_summary(w) for w in windows])
        if self.include_pose:
            row['pose'] = None if points is None or not np.isfinite(points).all() else points.tolist()
        self.write(row)

    def reset(self, reason):
        self.write(dict(kind='reset', reason=reason))


def window_summary(w):
    return dict(start=w.start, end=w.end, mask=w.mask.tolist(), score=w.score,
                events=[list(e) for e in w.events], inference_ms=w.inference_ms,
                eligible=valid_window(w.mask), error=w.error)


def replay(path, model):
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != (path.parent/'sha256').read_text().strip():
        raise ValueError('Trace checksum mismatch')
    rows = iter(map(json.loads, content.splitlines()))
    header = next(rows)
    expected = dict(kind='header', version=1, pose=True, schema=SPEC.schema_version,
                    checkpoint=CHECKPOINT_SHA, rate=SPEC.sample_rate_hz, window=SIZE,
                    stride=STRIDE, gap=GAP, threshold=.5, cooldown=2, confirmations=1)
    if any(header.get(k) != v for k,v in expected.items()):
        raise ValueError('Replay requires matching metadata and an opt-in pose trace')
    stream = Stream(model)
    count, delta = 0, 0.
    for row in rows:
        if row['kind'] == 'reset':
            stream.reset(row['reason'])
            continue
        if row['kind'] != 'frame':
            raise ValueError('Unexpected trace record')
        pose = None if row['pose'] is None else np.asarray(row['pose'], dtype=np.float32)
        for saved,w in zip(row['windows'],stream.push(row['stamp'],pose),strict=True):
            actual = window_summary(w)
            if any(actual[k] != saved[k] for k in ('start','end','mask','eligible','events','error')):
                raise ValueError(f'Window or decision mismatch at {w.end}')
            if saved['score'] is not None and w.score is not None:
                error = abs(saved['score']-w.score)
                if error > TOLERANCE:
                    raise ValueError(f'Score mismatch at {w.end}: {error}')
                delta = max(delta,error)
            elif saved['score'] is not w.score:
                raise ValueError('Eligibility/score mismatch')
            count += 1
    return dict(windows=count,max_score_delta=delta,score_tolerance=TOLERANCE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('replay',))
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--checkpoint',required=True,type=Path)
    args = parser.parse_args()
    import torch
    torch.set_num_threads(2)
    print(json.dumps(replay(args.input,load_model(args.checkpoint))))


if __name__ == '__main__':
    main()
