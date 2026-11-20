"""Regression checks for the research window gate and event metrics."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ml.pr04_experiment import load_pinned, metrics, starts


def test_window_gate_requires_event_onset_and_overlap():
    stamps = np.arange(60) / 10
    valid = np.ones(60, dtype=bool)
    candidates, available = starts(stamps, valid, 30, (2.5, 3.4))
    assert available == candidates
    assert 0 not in available  # overlap is below the required half-duration
    assert 3 in available
    assert 27 not in available  # this window starts after onset


@pytest.mark.parametrize(('missing', 'accepted'), [
    ([10, 11, 12], True),
    ([10, 11, 12, 13], False),
    ([10, 12], False),
    ([0], False),
    ([29], False),
])
def test_gap_policy_preserves_valid_endpoints_and_one_short_run(missing, accepted):
    stamps = np.arange(30) / 10
    valid = np.ones(30, dtype=bool)
    valid[missing] = False
    assert starts(stamps, valid, 30, None, gap=0) == ([0], [])
    assert starts(stamps, valid, 30, None, gap=3) == ([0], [0] if accepted else [])


def test_metrics_keep_missed_events_and_serialize_numpy_predictions():
    result = metrics([1, 1, 0, 0, 1], np.array([True, False, True, False, False]))
    assert result == dict(tp=1, fp=1, fn=2, tn=1, recall=1/3,
                          precision=.5, f1=.4, f2=5/14)
    assert json.loads(json.dumps(result)) == result


def test_pinned_inputs_reject_modified_manifests(tmp_path):
    path = tmp_path / 'manifest.json'
    path.write_text('{"seed": 42}')
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_pinned(path, checksum) == {'seed': 42}
    path.write_text('{"seed": 43}')
    with pytest.raises(ValueError, match='Unexpected checksum'):
        load_pinned(path, checksum)
