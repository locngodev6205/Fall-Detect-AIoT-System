from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.immobility import ImmobilityDetector, State
from edge.immobility_events import ImmobilityEvents


def pose(x=.4, visibility=.95):
    return np.tile((x, .5, visibility), (17, 1))


def feed(detector, start, count, points=pose(), step=.2):
    return [detector.update(start+i*step, points(i) if callable(points) else points)
            for i in range(count)]


def test_jitter_variable_fps_emits_once_and_recovers():
    detector = ImmobilityDetector(3)
    stamp = 0.
    transitions = []
    for i in range(180):
        stamp += [.06, .13, .19, .31][i % 4]
        reading = detector.update(stamp, pose(.4+(.003 if i%2 else -.003)))
        if reading.transition:
            transitions.append(reading.transition)
    assert transitions == [State.INACTIVE]
    assert reading.duration_s >= 3
    restored = feed(detector, stamp+.2, 12, lambda i: pose(.4+(.035*i)))
    assert sum(x.transition == State.RECOVERED for x in restored) == 1


def test_walking_never_qualifies():
    detector = ImmobilityDetector(2)
    readings = feed(detector, 0., 100, lambda i: pose(.25+.015*(i%30)))
    assert any(r.state == State.ACTIVE for r in readings)
    assert all(r.transition is None for r in readings)


@pytest.mark.parametrize("pause", [.2, 20.])
def test_loss_resets_duration_and_never_confirms_it(pause):
    detector = ImmobilityDetector(3)
    assert all(r.transition is None for r in feed(detector, 0., 24))
    assert detector.update(4.8).state == State.UNKNOWN
    resumed = feed(detector, 4.8+pause, 26)
    assert all(r.transition is None for r in resumed[:25])
    assert resumed[-1].transition == State.INACTIVE


def test_servo_and_low_confidence_never_count_as_stillness():
    detector = ImmobilityDetector(2)
    for i in range(50):
        assert detector.update(i*.2, pose(), camera_moving=True).state == State.UNKNOWN
    assert detector.update(10., pose()).state == State.UNKNOWN
    assert detector.update(11., pose(visibility=.1)).state == State.UNKNOWN
    assert detector.update(11.2, pose()).state == State.UNKNOWN


def test_outage_does_not_create_another_episode_without_observed_recovery():
    detector = ImmobilityDetector(2)
    assert sum(r.transition == State.INACTIVE for r in feed(detector, 0., 40)) == 1
    assert detector.update(20.).state == State.UNKNOWN
    assert all(r.transition is None for r in feed(detector, 20.2, 60))


def test_frame_timestamp_gap_and_bad_clock():
    detector = ImmobilityDetector(3)
    feed(detector, 0., 24)
    assert detector.update(22., pose()).state == State.UNKNOWN
    with pytest.raises(ValueError, match="monotonic"):
        detector.update(21., pose())


def test_delivery_retries_in_order_with_one_id():
    from unittest.mock import Mock

    detector = ImmobilityDetector(2)
    events = ImmobilityEvents()
    for reading in feed(detector, 0., 32):
        events.submit(reading)
    for reading in feed(detector, 6.4, 10, lambda i: pose(.4+.03*i)):
        events.submit(reading)
    client = Mock()
    client.send_event.side_effect = [None, {"id": "event"}, {"id": "event"}]
    for stamp in (0., 2., 5., 6.):
        events.flush(client, stamp)
    a, b, c = [call.kwargs for call in client.send_event.call_args_list]
    assert a == b
    assert a["event_id"] == c["event_id"]
    assert (a["sequence"], c["sequence"]) == (1, 2)
    assert (a["observation"], c["observation"]) == ("abnormal", "recovered")


def test_fall_inference_reaches_edge_event_once_during_cooldown(monkeypatch, tmp_path):
    import config
    from edge import main_edge
    from modules import detector as fall, skeleton

    model = tmp_path / "fixture.tflite"
    model.touch()
    monkeypatch.setattr(config, "MODEL_PATH", str(model))
    monkeypatch.setattr(config, "INPUT_TIMESTEPS", 2)
    monkeypatch.setattr(config, "FALL_CONFIDENCE_THRESHOLD", .85)
    monkeypatch.setattr(config, "FALL_EVENT_COOLDOWN", 10)

    interpreter = Mock()
    interpreter.get_input_details.return_value = [
        {"shape": (1, 2, 51), "index": 0, "dtype": np.float32},
    ]
    interpreter.get_output_details.return_value = [{"index": 1}]
    interpreter.get_tensor.return_value = [[.9]]
    monkeypatch.setattr(fall.tflite, "Interpreter", Mock(return_value=interpreter))

    results = []
    original_update = fall.FallDetector.update

    def capture_result(self, *args, **kwargs):
        result = original_update(self, *args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(fall.FallDetector, "update", capture_result)
    runtime = main_edge.AnNhaEdgeRuntime(
        base_url="http://127.0.0.1:1", device_token="fixture",
        cache_dir=tmp_path, force_mock_hardware=True,
    )
    monkeypatch.setattr(runtime.tracker, "is_fall_detection_enabled", Mock(return_value=True))
    monkeypatch.setattr(runtime.audio, "trigger_emergency_siren", Mock())
    monkeypatch.setattr(runtime.client, "send_event", Mock(return_value={"id": "fixture-event"}))
    monkeypatch.setattr(runtime.client, "upload_evidence", Mock())
    monkeypatch.setattr(runtime, "_observe_immobility", Mock())
    monkeypatch.setattr(skeleton, "is_person_present", Mock(return_value=True))
    monkeypatch.setattr(skeleton, "extract_and_normalize_features", Mock(return_value=np.zeros(51)))
    pose_context = MagicMock()
    pose_context.__enter__.return_value.process.return_value = SimpleNamespace(pose_landmarks=None)
    monkeypatch.setattr(main_edge, "mp", SimpleNamespace(
        solutions=SimpleNamespace(pose=SimpleNamespace(Pose=Mock(return_value=pose_context))),
    ))
    monkeypatch.setattr(main_edge, "draw_ota_version_badge", Mock())
    camera = Mock()
    camera.read.return_value = True, np.zeros((480, 640, 3), dtype=np.uint8)
    frames = iter((Mock(), Mock(), runtime._stop_event.set))
    monkeypatch.setattr(runtime.streamer, "update_frame_jpeg", Mock(
        side_effect=lambda _: next(frames)()
    ))

    runtime._run_opencv_mediapipe_loop(camera)

    assert [result.is_fall for result in results] == [False, True, True]
    assert all("Prediction Error" not in result.status_text for result in results), results
    runtime.audio.trigger_emergency_siren.assert_called_once()
    runtime.client.send_event.assert_called_once()
    event = runtime.client.send_event.call_args.kwargs
    assert event["kind"] == "fall"
    assert isinstance(event["confidence"], float)
    assert event["confidence"] == pytest.approx(.9)
    assert event["jpeg_evidence"] is None
    runtime.client.upload_evidence.assert_not_called()
    camera.release.assert_called_once()


def test_unknown_diagnostics_identify_pose_motion_and_sample_gap():
    detector = ImmobilityDetector(30)
    assert detector.update(0).reason == "no_pose"
    low_quality = detector.update(.1, pose(visibility=.1))
    assert (low_quality.reason, low_quality.valid_body, low_quality.valid_torso) == ("invalid_pose", 0, 0)

    settling = detector.update(.2, pose(), camera_moving=True)
    assert settling.reason == "camera_settling"
    warmup = detector.update(1.3, pose())
    assert (warmup.reason, warmup.window_span_s) == ("window_warmup", 0)
    after_gap = detector.update(2.1, pose())
    assert after_gap.reason == "sample_gap"
    assert after_gap.sample_gap_s == pytest.approx(.8)
    assert after_gap.valid_body == 12
    assert after_gap.valid_torso == 4
