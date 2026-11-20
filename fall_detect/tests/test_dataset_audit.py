"""Audit checks for the legacy dataset and live feature contract."""
from pathlib import Path
import sys

import numpy as np

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "fall_detect"))

from scripts.ml.audit_dataset import audit
from modules import skeleton
from utils.extract_keypoint import KEYPOINT_INDICES, KEYPOINT_NAMES


def test_manifest_reports_cross_split_overlap(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text("split,label,video_id,subject_id,sha256,parent_id,total_frames,missing_pose_frames\n"
                    "train,fall,video1,subject1,hash1,original1,30,2\n"
                    "test,fall,video1,subject1,hash1,original1,30,4\n")
    result = audit(path)
    assert result["video_overlap"] == result["subject_overlap"] == 1
    assert result["duplicate_hash_overlap"] == result["parent_overlap"] == 1
    assert result["missing_pose_rate"] == 0.1


def test_legacy_extractor_uses_different_face_indices():
    indices = dict(zip(KEYPOINT_NAMES, KEYPOINT_INDICES))
    online = {name: landmark.value for landmark, name in skeleton.MEDIAPIPE_TO_YOUR_KEYPOINTS_MAPPING.items()}
    assert [online[name] for name in KEYPOINT_NAMES[:5]] == [0, 2, 5, 7, 8]
    assert [indices[name] for name in KEYPOINT_NAMES[:5]] == [0, 1, 2, 3, 4]


def test_legacy_csv_to_sequence_differs_from_live_features(tmp_path, monkeypatch):
    import csv
    import pytest
    from types import SimpleNamespace

    pytest.importorskip("pandas")
    from utils.process_csv_data import process_csv
    from utils import extract_keypoint as extractor

    points = SimpleNamespace(landmark=[
        SimpleNamespace(x=(i + 1) / 40, y=(i + 1) / 50, visibility=0.6 + i / 100)
        for i in range(33)
    ])
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frames = iter([(True, frame), (False, None)])
    monkeypatch.setattr(extractor.cv2, "VideoCapture",
                        lambda _: SimpleNamespace(read=lambda: next(frames), release=lambda: None))
    monkeypatch.setattr(extractor.mp_pose, "Pose", lambda: SimpleNamespace(
        process=lambda _: SimpleNamespace(pose_landmarks=points), close=lambda: None))
    path = tmp_path / "pose.csv"
    extractor.extract_17_keypoints("fixture", path)
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    nose = next(row for row in rows if row["Keypoint"] == "Nose")
    assert float(nose["X"]) == 16.0
    sequences, _ = process_csv(path, sequence_length=1, step_size=1, expected_features=51)
    offline = sequences[0][0]
    live = skeleton.extract_and_normalize_features(points)
    assert offline.shape == live.shape == (51,)
    assert not np.allclose(offline, live)
