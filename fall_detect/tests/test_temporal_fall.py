"""Tests for the causal, optional Fall detector and its alert boundary."""
from pathlib import Path
import sys
from unittest.mock import Mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.temporal_fall import TemporalFall
from modules.temporal_stream import EventEngine, Stream, valid_window
from modules.temporal_features import JOINTS


def test_confirmed_fall_allows_second_episode_after_score_recovers():
    engine = EventEngine(confirmations=2)
    inputs = [(0., .9), (.3, .2), (.6, .9), (.9, .9), (1.2, .95),
              (1.5, .1), (3., .95), (3.3, .95)]
    alerts = [stamp for stamp, score in inputs
              if ('simulated_alert', stamp) in engine.update(stamp, score)]
    assert alerts == [.9, 3.3]


def test_contiguous_missing_pose_budget():
    mask = np.ones(20, dtype=bool)
    mask[3:6] = False
    assert valid_window(mask)
    mask[12] = False
    assert not valid_window(mask)
    mask[5] = True
    assert not valid_window(mask)


def test_adapter_dispatches_real_callback_once_and_does_not_replay_old_window():
    from types import SimpleNamespace

    adapter = TemporalFall.__new__(TemporalFall)
    adapter.stream = Stream(lambda _: .92)
    alert = Mock()
    points = [SimpleNamespace(x=.5, y=.75, visibility=.99) for _ in range(33)]
    for name, i in JOINTS:
        if 'Shoulder' in name:
            points[i].y = .4
        if name.startswith('Left'):
            points[i].x = .4
        if name.startswith('Right'):
            points[i].x = .6
    pose = SimpleNamespace(landmark=points)
    for i in range(35):
        adapter.update(i / 10, pose, alert)
    alert.assert_called_once_with(.92, '92.00%')
    adapter.reset()
    for i in range(60, 90):
        adapter.update(i / 10, pose, alert)
    alert.assert_called_once()


def test_rejects_wrong_model_hash_before_loading_ort_session(monkeypatch, tmp_path):
    from types import SimpleNamespace

    engine = Mock()
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(InferenceSession=engine))
    model = tmp_path / 'model.onnx'
    model.write_bytes(b'wrong model')
    with pytest.raises(ValueError, match='SHA-256'):
        TemporalFall('ctr_gcn_40_2026', model)
    engine.assert_not_called()
