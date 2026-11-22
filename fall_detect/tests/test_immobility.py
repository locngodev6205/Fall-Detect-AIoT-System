from pathlib import Path
import sys

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


def test_legacy_fall_callback_still_fires_without_inline_immobility(monkeypatch):
    from modules import detector as fall

    class Interpreter:
        def __init__(self, model_path):
            self.input = None

        def allocate_tensors(self):
            pass

        def get_input_details(self):
            return [{"shape": (1, 2, 51), "index": 0}]

        def get_output_details(self):
            return [{"index": 1}]

        def set_tensor(self, index, value):
            self.input = value

        def invoke(self):
            assert self.input.shape == (1, 2, 51)

        def get_tensor(self, index):
            return [[.9]]

    monkeypatch.setattr(fall.tflite, "Interpreter", Interpreter)
    alerts = []
    detector = fall.FallDetector(
        "unused", input_timesteps=2, enable_immobility=False,
        on_fall_alert=lambda *args: alerts.append(args),
    )
    frame = np.zeros(51)
    assert not detector.update(frame).is_fall
    assert detector.update(frame).is_fall
    assert detector.update(frame).is_fall
    assert alerts == [(.9, "90.00%")]
