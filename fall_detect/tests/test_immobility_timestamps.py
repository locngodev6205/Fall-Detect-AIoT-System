"""Exercise capture-time sampling with a Raspberry Pi-like frame cadence."""

from itertools import cycle
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.immobility import ImmobilityDetector, State


def standing_pose():
    return np.array([(0.40 + i / 100, 0.25 + i / 35, 0.95) for i in range(17)])


def irregular_frames(start, count):
    intervals = cycle((0.091, 0.125, 0.105, 0.099, 0.115, 0.095))
    stamp = start
    for interval in intervals:
        yield stamp
        count -= 1
        if count <= 0:
            return
        stamp += interval


def test_irregular_pi_cadence_acquires_still_before_immobility_timeout():
    detector = ImmobilityDetector(duration_s=30)
    pose = standing_pose()
    start = 1000.0
    readings = [(stamp, detector.update(stamp, pose)) for stamp in irregular_frames(start, 45)]
    still_stamp, first_still = next((stamp, r) for stamp, r in readings if r.state is State.STILL)

    assert detector.window_s <= still_stamp - start <= detector.window_s + .35
    assert first_still.duration_s == 0
    assert readings[-1][1].state is State.STILL
    assert readings[-1][1].duration_s >= 2
    assert all(reading.transition is None for _, reading in readings)


def test_irregular_capture_gap_restarts_observation_without_counting_missing_time():
    detector = ImmobilityDetector(duration_s=30)
    pose = standing_pose()
    stamps = list(irregular_frames(1000.0, 40))
    for stamp in stamps:
        before_gap = detector.update(stamp, pose)
    assert before_gap.state is State.STILL
    assert before_gap.duration_s > 1

    resumed_at = stamps[-1] + .7
    resumed = [(stamp, detector.update(stamp, pose)) for stamp in irregular_frames(resumed_at, 26)]
    assert all(reading.state is State.UNKNOWN for stamp, reading in resumed
               if stamp - resumed_at < detector.window_s)
    assert resumed[-1][1].state is State.STILL
    assert resumed[-1][1].duration_s < 1
    assert all(reading.transition is None for _, reading in resumed)
