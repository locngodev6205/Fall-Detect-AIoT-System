"""Record and compare cross-device traces for an approved development pose CSV."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from ml.dataset import read_keypoints_csv
from .streaming import CHECKPOINT_SHA, Stream, load_model

SCORE_TOLERANCE = 1e-5
TENSOR_TOLERANCE = 2e-5


def trace(csv, checkpoint, *, include_tensors=False):
    import torch
    torch.set_num_threads(2)
    times, poses = read_keypoints_csv(csv)
    engine = Stream(load_model(checkpoint))
    windows = []
    for stamp, pose in zip(times, poses, strict=True):
        for result in engine.push(stamp, pose):
            windows.append(dict(
                start=result.start, end=result.end, mask=result.mask.tolist(),
                tensor_sha256=hashlib.sha256(result.inputs.astype('<f4').tobytes()).hexdigest(),
                score=result.score, events=[list(event) for event in result.events]))
            if include_tensors:
                windows[-1]['tensor'] = result.inputs.tolist()
    return dict(checkpoint_sha256=CHECKPOINT_SHA, torch=torch.__version__,
                windows=windows, model_errors=engine.model_errors)


def compare(reference, observed):
    if reference['checkpoint_sha256'] != observed['checkpoint_sha256']:
        raise ValueError('Checkpoint hashes differ')
    expected, actual = reference['windows'], observed['windows']
    structural = tensor = decisions = near = score_mismatches = 0
    max_delta = max_tensor_delta = 0.
    tensor_hash_differences = 0
    for left, right in zip(expected, actual):
        structural += int(any(left[key] != right[key] for key in ('start','end','mask')))
        if left['tensor_sha256'] != right['tensor_sha256']:
            tensor_hash_differences += 1
            if 'tensor' not in left or 'tensor' not in right:
                tensor += 1
            else:
                a_tensor, b_tensor = np.asarray(left['tensor']), np.asarray(right['tensor'])
                if a_tensor.shape != (20, 51) or b_tensor.shape != a_tensor.shape:
                    raise ValueError('Invalid diagnostic tensor shape')
                error = float(np.max(np.abs(a_tensor-b_tensor)))
                if not math.isfinite(error):
                    raise ValueError('Non-finite diagnostic tensor difference')
                max_tensor_delta = max(max_tensor_delta, error)
                tensor += int(error > TENSOR_TOLERANCE)
        decisions += int(left['events'] != right['events'])
        a, b = left['score'], right['score']
        if a is None or b is None:
            score_mismatches += int(a is not b)
            continue
        delta = abs(a-b)
        max_delta = max(max_delta, delta)
        score_mismatches += int(not math.isfinite(delta) or delta > SCORE_TOLERANCE)
        near += int(min(abs(a-.5),abs(b-.5)) <= SCORE_TOLERANCE)
    passed = not (len(expected) != len(actual) or structural or tensor or decisions
                  or score_mismatches or reference['model_errors'] or observed['model_errors'])
    return dict(passed=passed, reference_windows=len(expected), observed_windows=len(actual),
                structural_mismatches=structural, tensor_mismatches=tensor,
                tensor_hash_differences=tensor_hash_differences,
                max_tensor_delta=max_tensor_delta, tensor_tolerance=TENSOR_TOLERANCE,
                decision_mismatches=decisions, scores_near_threshold=near,
                score_mismatches=score_mismatches, max_score_delta=max_delta,
                score_tolerance=SCORE_TOLERANCE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    record = commands.add_parser('trace')
    record.add_argument('csv', type=Path)
    record.add_argument('checkpoint', type=Path)
    record.add_argument('output', type=Path)
    record.add_argument('--include-tensors', action='store_true',
                        help='Include research features in local diagnostic JSON')
    check = commands.add_parser('compare')
    check.add_argument('reference', type=Path)
    check.add_argument('observed', type=Path)
    args = parser.parse_args()
    if args.command == 'trace':
        result = trace(args.csv, args.checkpoint, include_tensors=args.include_tensors)
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
    else:
        result = compare(json.loads(args.reference.read_text()), json.loads(args.observed.read_text()))
        print(json.dumps(result, indent=2))
        if not result['passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
