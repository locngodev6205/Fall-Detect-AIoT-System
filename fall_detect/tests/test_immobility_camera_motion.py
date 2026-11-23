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
