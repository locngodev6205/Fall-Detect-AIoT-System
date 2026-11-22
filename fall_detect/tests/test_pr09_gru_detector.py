from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ml.features import JOINTS
from modules import gru_detector


def landmarks():
    points = [SimpleNamespace(x=.5, y=.5, visibility=.95) for _ in range(33)]
    for name, index in JOINTS:
        if "Shoulder" in name:
            points[index].y = .25
        elif "Hip" in name:
            points[index].y = .5
    return SimpleNamespace(landmark=points)


def test_one_alert_for_continuous_high_score_and_reset(monkeypatch):
    load = Mock(return_value=lambda _: .9)
    monkeypatch.setattr(gru_detector, "load_model", load)
    callback = Mock()
    adapter = gru_detector.GruDetector("candidate.pt", callback)
    result = adapter.update_pose(landmarks(), True, 0.)
    assert result.label == "warming_up"
    for frame in range(1, 42):
        result = adapter.update_pose(landmarks(), True, frame/10)
    assert result.is_fall
    callback.assert_called_once_with(.9, "90.00%")
    assert adapter.update_pose(landmarks(), True, 8.).label == "warming_up"
    callback.assert_called_once()
    adapter.reset_pose_stream()
    assert adapter.update_pose(landmarks(), True, 9.).label == "warming_up"


def test_no_pose_does_not_create_a_fall(monkeypatch):
    monkeypatch.setattr(gru_detector, "load_model", lambda path: lambda _: .99)
    callback = Mock()
    adapter = gru_detector.GruDetector("candidate.pt", callback)
    for frame in range(30):
        result = adapter.update_pose(None, False, frame/10)
    assert result.label == "no_person"
    callback.assert_not_called()


def test_invalid_checkpoint_is_rejected(tmp_path):
    artifact = tmp_path/"bad.pt"
    artifact.write_bytes(b"wrong checkpoint")
    with pytest.raises(ValueError, match="SHA-256"):
        gru_detector.GruDetector(artifact, Mock())
