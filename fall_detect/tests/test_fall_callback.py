"""Regression coverage for fall detection and notification isolation."""
from pathlib import Path
import sys
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.detector import FallDetector


def test_notification_failure_preserves_inference_and_cooldown(tmp_path, monkeypatch):
    import modules.detector as module

    model = tmp_path / "fixture.tflite"
    model.touch()
    interpreter = Mock()
    interpreter.get_input_details.return_value = [{"shape": [1, 2, 3], "dtype": np.float32, "index": 0}]
    interpreter.get_output_details.return_value = [{"shape": [1, 1], "dtype": np.float32, "index": 1}]
    interpreter.get_tensor.return_value = np.array([[0.95]], dtype=np.float32)
    monkeypatch.setattr(module.tflite, "Interpreter", Mock(return_value=interpreter))
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(module.time, "monotonic", clock)
    callback = Mock(side_effect=TypeError("callback regression"))
    detector = FallDetector(str(model), input_timesteps=2, num_features=3,
                            enable_immobility=False, on_fall_alert=callback)
    frame = np.zeros(3, dtype=np.float32)

    detector.update(frame)
    result = detector.update(frame)
    assert result.is_fall
    assert result.status_text.startswith("FALL")
    detector.update(frame)
    assert callback.call_count == 1
    assert callback.call_args.args[1] == "95.00%"
    clock.return_value = 111.0
    detector.update(frame)
    assert callback.call_count == 2


def test_detector_to_edge_audio_and_network_retry(tmp_path, monkeypatch):
    import threading
    import time
    from edge.main_edge import AnNhaEdgeRuntime
    import modules.detector as module

    runtime = AnNhaEdgeRuntime(base_url="http://127.0.0.1:1", device_token="test-only",
                               cache_dir=tmp_path / "cache", force_mock_hardware=True)
    runtime.fall_alerts.retry_delay = 0.01
    calls = []
    delivered = threading.Event()

    def send(**payload):
        calls.append(payload)
        assert runtime.audio.trigger_emergency_siren.called
        return None if len(calls) == 1 else {"id": "verified-backend-id"}

    runtime.audio.trigger_emergency_siren = Mock()
    runtime.client.send_event = Mock(side_effect=send)
    runtime.client.upload_evidence = Mock(side_effect=lambda *a, **kw: delivered.set())
    model = tmp_path / "fixture.tflite"
    model.touch()
    interpreter = Mock()
    interpreter.get_input_details.return_value = [{"shape": [1, 2, 3], "dtype": np.float32, "index": 0}]
    interpreter.get_output_details.return_value = [{"shape": [1, 1], "dtype": np.float32, "index": 1}]
    interpreter.get_tensor.return_value = np.array([[0.95]], dtype=np.float32)
    monkeypatch.setattr(module.tflite, "Interpreter", Mock(return_value=interpreter))
    detector = FallDetector(str(model), input_timesteps=2, num_features=3, enable_immobility=False,
                            on_fall_alert=runtime.make_fall_callback(lambda: b"jpeg-fixture"))

    workers = runtime.fall_alerts.start()
    try:
        frame = np.zeros(3, dtype=np.float32)
        detector.update(frame)
        assert detector.update(frame).is_fall
        detector.update(frame)
        assert delivered.wait(2)
        assert len(calls) == 2
        assert calls[0]["event_id"] == calls[1]["event_id"]
        assert calls[0]["observed_at"] == calls[1]["observed_at"]
        assert "95.00%" in calls[0]["reason"]
        runtime.audio.trigger_emergency_siren.assert_called_once()
        assert runtime.client.upload_evidence.call_args.kwargs["internal_event_id"] == "verified-backend-id"
        deadline = time.monotonic() + 1
        while runtime.unreported_alert and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not runtime.unreported_alert

        runtime.tracker.update_smart_modes({"fall_detection": False})
        runtime.make_fall_callback(lambda: None)(0.96, "96.00%")
        assert not runtime.unreported_alert
        runtime.audio.trigger_emergency_siren.assert_called_once()
    finally:
        runtime._stop_event.set()
        for worker in workers:
            worker.join(1)


def test_missing_hash_or_invalid_shape_fails_closed(tmp_path, monkeypatch):
    import json
    import pytest
    import modules.detector as module

    model = tmp_path / "fixture.tflite"
    callback = Mock()
    with pytest.raises(FileNotFoundError):
        FallDetector(str(model), on_fall_alert=callback)
    model.touch()
    manifest = model.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({"sha256": "0" * 64, "fall_threshold": 0.5}))
    with pytest.raises(ValueError, match="SHA-256"):
        FallDetector(str(model), on_fall_alert=callback)
    manifest.unlink()
    interpreter = Mock()
    interpreter.get_input_details.return_value = [{"shape": [1, 60, 51], "dtype": np.float32}]
    interpreter.get_output_details.return_value = [{"shape": [1, 1], "dtype": np.float32}]
    monkeypatch.setattr(module.tflite, "Interpreter", Mock(return_value=interpreter))
    with pytest.raises(ValueError, match="Kích thước đầu vào"):
        FallDetector(str(model), on_fall_alert=callback)
    callback.assert_not_called()
