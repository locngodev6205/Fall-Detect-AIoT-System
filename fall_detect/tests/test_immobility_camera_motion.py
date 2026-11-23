"""Exercise the Edge immobility hook with fixed and moving camera states."""
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edge.main_edge import AnNhaEdgeRuntime
from modules.immobility import State


@pytest.fixture
def runtime(tmp_path):
    edge = AnNhaEdgeRuntime(
        base_url="http://127.0.0.1:1", device_token="fixture",
        cache_dir=tmp_path, force_mock_hardware=True,
    )
    edge._on_config_updated({
        "smart_modes": {"immobility_detection": True, "immobility_timeout_seconds": 30,
                        "servo_tracking": False},
    })
    edge.immobility_events.submit = Mock()
    try:
        yield edge
    finally:
        edge.client.stop()


def observe(runtime, stamp, *, pan=90, servo_moving=0, tracking_moved=False, x_shift=0.0):
    landmarks = SimpleNamespace(landmark=[
        SimpleNamespace(x=.4+x_shift+(i % 2)*.1, y=.3+(i // 2)*.025, visibility=.99)
        for i in range(33)
    ])
    runtime._observe_immobility(
        stamp, landmarks, {"pan": pan, "tilt": 90, "moving": servo_moving},
        moved=tracking_moved,
    )
    return runtime.immobility_reading


@pytest.mark.parametrize("source", ["arduino_status", "tracking_result", "pan_delta"])
def test_camera_motion_resets_stillness_and_requires_settling(runtime, source):
    for frame in range(40):
        baseline = observe(runtime, frame/10)
    assert baseline.state == State.STILL
    assert baseline.duration_s > 1

    for frame in range(40, 65):
        moving = observe(
            runtime, frame/10,
            pan=90+(frame-39 if source == "pan_delta" else 0),
            servo_moving=int(source == "arduino_status"),
            tracking_moved=source == "tracking_result",
            x_shift=.1 if frame % 2 else 0,
        )
        assert moving.state == State.UNKNOWN
        assert moving.duration_s == 0

    final_pan = 115 if source == "pan_delta" else 90
    for frame in range(65, 74):
        assert observe(runtime, frame/10, pan=final_pan).state == State.UNKNOWN

    for frame in range(74, 104):
        resumed = observe(runtime, frame/10, pan=final_pan)
    assert resumed.state == State.STILL
    assert 0 < resumed.duration_s < baseline.duration_s
    runtime.immobility_events.submit.assert_not_called()


def test_web_ptz_interrupts_stillness_before_alert(runtime):
    for frame in range(315):
        reading = observe(runtime, frame / 10)
    assert reading.state == State.STILL
    assert 28 <= reading.duration_s < 30

    success, detail = runtime._on_web_command({
        "kind": "ptz_move", "payload": {"direction": "RIGHT", "degrees": 5},
    })
    assert success, detail
    pan = runtime.bridge.get_servo_state()["pan"]
    assert pan == 85
    assert observe(runtime, 31.5, pan=pan).state == State.UNKNOWN
    for frame in range(316, 360):
        reading = observe(runtime, frame / 10, pan=pan, x_shift=.05)
    assert reading.state == State.STILL
    assert reading.duration_s < 3
    runtime.immobility_events.submit.assert_not_called()


def test_vision_uses_immobility_pose_validation_when_presence_gate_flickers(runtime, monkeypatch, caplog):
    import logging
    import numpy as np
    from edge import main_edge
    from modules import skeleton

    # Below the general 0.4 presence threshold on intermittent frames, but
    # above the detector's 0.3 threshold with all joints in frame.
    landmarks = [
        SimpleNamespace(landmark=[
            SimpleNamespace(x=.4 + i % 2 * .1, y=.3 + i // 2 * .02,
                            visibility=.9 if frame % 6 else .35)
            for i in range(33)
        ]) for frame in range(32)
    ]
    assert not skeleton.is_person_present(landmarks[0])
    assert skeleton.is_person_present(landmarks[1])
    pose = Mock(process=Mock(side_effect=[SimpleNamespace(pose_landmarks=p) for p in landmarks]))
    context = Mock()
    context.__enter__ = Mock(return_value=pose)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(main_edge, "mp", SimpleNamespace(
        solutions=SimpleNamespace(pose=SimpleNamespace(Pose=Mock(return_value=context))),
    ))
    monkeypatch.setattr(runtime.tracker, "is_fall_detection_enabled", lambda: False)
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    stamp = 0.0
    frame_count = 0

    def capture():
        nonlocal stamp
        stamp += .12
        return True, frame.copy()

    def publish(_):
        nonlocal frame_count
        frame_count += 1
        if frame_count == len(landmarks):
            runtime._stop_event.set()

    monkeypatch.setattr(main_edge, "time", SimpleNamespace(monotonic=lambda: stamp))
    monkeypatch.setattr(runtime.streamer, "update_frame_jpeg", publish)
    with caplog.at_level(logging.INFO):
        runtime._run_opencv_mediapipe_loop(Mock(read=capture))
        for offset in (.12, .24, .36):
            runtime._observe_immobility(stamp + offset)
    assert "[Immobility] STILL" in caplog.text
    assert caplog.text.count("UNKNOWN reason=no_pose") == 1
    assert runtime.immobility_reading.state is State.UNKNOWN
    runtime.immobility_events.submit.assert_not_called()


def test_still_progress_and_motion_reset_are_distinguishable_in_logs(runtime, caplog):
    import logging
    import re

    with caplog.at_level(logging.INFO):
        for frame in range(225):
            reading = observe(runtime, frame / 10, x_shift=.001 * (frame % 3))
        assert reading.state is State.STILL
        assert reading.duration_s >= 20
        assert reading.motion_score < runtime.immobility.motion_threshold

        reading = observe(runtime, 22.6, x_shift=.08)
        assert reading.state is State.ACTIVE
        assert reading.motion_score >= runtime.immobility.motion_threshold
        active_log = next(record.message for record in caplog.records
                          if "[Immobility] ACTIVE," in record.message)
        assert "previous=STILL" in active_log
        assert float(re.search(r"previous_duration_s=([0-9.]+)", active_log)[1]) >= 20
        assert "reason=motion_above_threshold" in active_log
        assert "motion_threshold=0.0180" in active_log

        for frame in range(227, 261):
            reading = observe(runtime, frame / 10, x_shift=.08)
        assert reading.state is State.STILL
        assert any("[Immobility] STILL," in record.message and "previous=ACTIVE" in record.message
                   for record in caplog.records)
        runtime._observe_immobility(26.1)
        assert runtime.immobility_reading.state is State.UNKNOWN
        assert any("[Immobility] UNKNOWN," in record.message and "previous=STILL" in record.message
                   and "reason=no_pose" in record.message for record in caplog.records)
    assert 3 <= caplog.text.count("STILL progress") <= 4
    runtime.immobility_events.submit.assert_not_called()
