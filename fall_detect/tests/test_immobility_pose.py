"""Exercise the boundary between person presence and usable immobility pose."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.immobility import ImmobilityDetector, State, image_points
from modules.skeleton import is_person_present


def landmarks(standing=True):
    """MediaPipe-style coordinates for a standing or seated fixture."""
    data = [SimpleNamespace(x=.5, y=.2, visibility=.95) for _ in range(33)]
    for left_index, right_index, y in (
        (11, 12, .35),
        (13, 14, .44),
        (15, 16, .53),
        (23, 24, .61),
        (25, 26, .76 if standing else .66),
        (27, 28, .91 if standing else .83),
    ):
        for index, x in ((left_index, .43), (right_index, .57)):
            data[index].x = x
            data[index].y = y
    return SimpleNamespace(landmark=data)


def observe(detector, pose, first_frame, n_frames):
    # Same public pose adapter and presence predicate used by the vision loop.
    points = image_points(pose) if is_person_present(pose) else None
    return [detector.update(i / 10, points) for i in range(first_frame, first_frame + n_frames)]


@pytest.mark.parametrize(
    "visible_body, out_of_frame",
    [
        pytest.param((11, 12, 13, 14, 23), None, id="only-five-body-joints"),
        pytest.param((11, 12, 13, 14, 15, 16, 25, 26), None, id="only-two-visible-torso-joints"),
        pytest.param((11, 12, 13, 14, 16, 23), 23, id="visible-hip-outside-image"),
    ],
)
def test_visible_person_can_lack_usable_body_pose(visible_body, out_of_frame):
    pose = landmarks()
    for index in (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28):
        if index not in visible_body:
            pose.landmark[index].visibility = .2
    if out_of_frame is not None:
        pose.landmark[out_of_frame].x = 1.1
    assert is_person_present(pose)

    detector = ImmobilityDetector(duration_s=30)
    readings = observe(detector, pose, 0, 360)
    assert all(r.state is State.UNKNOWN and r.duration_s == 0 for r in readings)
    assert not any(r.transition for r in readings)


@pytest.mark.parametrize("standing", [True, False], ids=["standing", "seated"])
def test_usable_pose_with_cropped_ankles_reaches_still(standing):
    pose = landmarks(standing)
    for index in (27, 28):
        pose.landmark[index].y = 1.1
        pose.landmark[index].visibility = .2
    assert is_person_present(pose)

    detector = ImmobilityDetector(duration_s=30)
    readings = observe(detector, pose, 0, 40)
    assert readings[0].state is State.UNKNOWN
    assert readings[-1].state is State.STILL
    assert readings[-1].duration_s > 0
    assert not any(r.transition for r in readings)


def test_torso_diagnostics_reports_each_rejection_separately():
    from modules.immobility import torso_diagnostics

    pose = landmarks()
    pose.landmark[11].visibility = .2
    pose.landmark[12].x = 1.1
    pose.landmark[23].y = float("nan")
    pose.landmark[24] = None
    low, cropped, invalid, missing = torso_diagnostics(pose)
    assert low[3:] == (.2, True, True, "LOW_VISIBILITY")
    assert cropped[1] == 1.1
    assert cropped[-3:] == (True, False, "OUT_OF_FRAME")
    assert invalid[-3:] == (False, None, "NON_FINITE")
    assert missing == (24, "MISSING_LANDMARK")
