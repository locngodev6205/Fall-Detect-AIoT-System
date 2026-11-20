from types import SimpleNamespace

import numpy as np
import pytest

from ml.features import SPEC, PoseSampler, extract_keypoints, normalize_sequence, resample_keypoints
from ml.dataset import read_keypoints_csv, write_keypoints_csv, jitter_coordinates


def landmarks(t=0):
    points = [SimpleNamespace(x=i / 100 + t / 10, y=.5, visibility=.75) for i in range(33)]
    return SimpleNamespace(landmark=points)


def test_mapping_and_csv_live_parity(tmp_path):
    raw = extract_keypoints(landmarks())
    np.testing.assert_allclose(raw[:5, 0], [0, .02, .05, .07, .08])
    path = tmp_path / 'pose.csv'
    timestamps = np.arange(31) / 15
    rows = np.array([extract_keypoints(landmarks(t)) for t in timestamps])
    write_keypoints_csv(path, timestamps, rows, source='fixture', fps=15, image_size=(640, 480), mediapipe_version='fixture')
    _, offline = read_keypoints_csv(path)
    live = PoseSampler()
    streamed = [vector for t in timestamps for vector in live.push(t, extract_keypoints(landmarks(t)))]
    expected = normalize_sequence(resample_keypoints(timestamps, offline))
    np.testing.assert_allclose(streamed, expected, atol=1e-5)
    assert expected.shape[1] == 51 and expected.dtype == np.float32
    np.testing.assert_allclose(expected[0, 2::3], .75)


@pytest.mark.parametrize('fps', [30, 15, 10])
def test_resampling_uses_elapsed_time(fps):
    times = np.arange(2 * fps + 1) / fps
    rows = np.array([extract_keypoints(landmarks(t)) for t in times])
    output = resample_keypoints(times, rows)
    assert len(output) == 2 * SPEC.sample_rate_hz + 1
    np.testing.assert_allclose(output[:, 0, 0], np.arange(len(output)) / SPEC.sample_rate_hz / 10, atol=1e-6)
    with pytest.raises(ValueError):
        resample_keypoints(times[::-1], rows)


def test_horizontal_torso_missing_joints_and_jitter():
    row = extract_keypoints(landmarks())
    row[0, 0] = np.nan
    normalized = normalize_sequence([row])[0].reshape(17, 3)
    assert np.isfinite(normalized).all()
    np.testing.assert_equal(normalized[0], 0)
    assert np.linalg.norm(normalized[5, :2]) > 0
    row[5:7, 2] = 0
    np.testing.assert_equal(normalize_sequence([row]), 0)
    finite = np.nan_to_num(row).reshape(1, 51)
    first = jitter_coordinates(finite, np.random.default_rng(17))
    second = jitter_coordinates(finite, np.random.default_rng(17))
    np.testing.assert_equal(first, second)
    np.testing.assert_equal(first[:, 2::3], finite[:, 2::3])


def test_long_missing_gap_is_not_interpolated():
    times = [0, .1, .8]
    raw = np.array([extract_keypoints(landmarks(t)) for t in times])
    sampled = resample_keypoints(times, raw)
    np.testing.assert_equal(sampled[2:-1], 0)
    assert sampled[-1, 0, 2] > 0


def test_pixel_and_normalized_inputs_match_across_aspects():
    normalized = extract_keypoints(landmarks())
    for size in ((640, 480), (1920, 1080)):
        pixels = normalized.copy()
        pixels[:, :2] *= size
        np.testing.assert_allclose(
            normalize_sequence([pixels], image_size=size), normalize_sequence([normalized]), atol=1e-5,
        )
    collapsed = normalized.copy()
    collapsed[:, :2] = .4
    np.testing.assert_equal(normalize_sequence([collapsed]), 0)


def test_model_manifest_routes_npy_window_and_live_pose_to_same_tensor(tmp_path, monkeypatch):
    import hashlib
    import json
    from unittest.mock import Mock

    from ml.dataset import generate_sequences
    from modules import detector

    folder = tmp_path / 'Fall/Keypoints_CSV_v2'
    folder.mkdir(parents=True)
    poses = [landmarks(t) for t in np.arange(30) / 10]
    write_keypoints_csv(folder / 'video.csv', np.arange(30) / 10,
                        [extract_keypoints(pose) for pose in poses],
                        source='video.mp4', fps=10, image_size=(640, 480), mediapipe_version='fixture')
    output = tmp_path / 'windows'
    generate_sequences(tmp_path, output, window_size=30, stride=3)
    raw = np.load(output / 'fall/video_seq_0000.npy', allow_pickle=False)

    model = tmp_path / 'model.tflite'
    model.write_bytes(b'fixture')
    manifest = model.with_suffix('.manifest.json')
    config = {'sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'fall_threshold': .85,
              'feature_schema_version': SPEC.schema_version, 'window_size': 30, 'sample_rate_hz': 10}
    manifest.write_text(json.dumps({**config, 'sample_rate_hz': 15}))
    with pytest.raises(ValueError, match='manifest disagrees'):
        detector.FallDetector(str(model))
    manifest.write_text(json.dumps(config))
    interpreter = Mock()
    interpreter.get_input_details.return_value = [{'shape': [1, 30, 51], 'dtype': np.float32, 'index': 0}]
    interpreter.get_output_details.return_value = [{'shape': [1, 1], 'dtype': np.float32, 'index': 1}]
    interpreter.get_tensor.return_value = np.array([[.1]], dtype=np.float32)
    monkeypatch.setattr(detector.tflite, 'Interpreter', Mock(return_value=interpreter))
    runtime = detector.FallDetector(str(model), enable_immobility=False)
    for t, pose in zip(np.arange(30) / 10, poses, strict=True):
        runtime.update_pose(pose, True, float(t))
    interpreter.set_tensor.assert_called_once()
    np.testing.assert_allclose(interpreter.set_tensor.call_args.args[1][0], normalize_sequence(raw), atol=1e-5)
