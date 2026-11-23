"""Detect sustained stillness using timestamped image-space MediaPipe landmarks."""
from collections import deque
from dataclasses import dataclass
from enum import Enum
import math

import numpy as np

# MediaPipe indices in nose-to-ankle order, including the 12 body joints below.
LANDMARKS = (0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
MIN_VISIBILITY = .3


def image_points(landmarks):
    if landmarks is None:
        return None
    return [(landmarks.landmark[i].x, landmarks.landmark[i].y, landmarks.landmark[i].visibility)
            for i in LANDMARKS]

# Exclude the face. Require a confident torso and several observable body joints.
BODY = slice(5, 17)
TORSO = [0, 1, 6, 7]


def torso_diagnostics(landmarks):
    """Describe rejected torso joints without recording a frame."""
    points = getattr(landmarks, "landmark", ())
    details = []
    for index in (11, 12, 23, 24):
        if index >= len(points) or points[index] is None:
            details.append((index, "MISSING_LANDMARK"))
            continue
        point = points[index]
        if any(getattr(point, key, None) is None for key in ("x", "y", "visibility")):
            details.append((index, "MISSING_LANDMARK"))
            continue
        x, y, visibility = map(float, np.asarray(
            [point.x, point.y, point.visibility], dtype=np.float32))
        finite = all(math.isfinite(value) for value in (x, y, visibility))
        in_frame = None if not all(map(math.isfinite, (x, y))) else 0 <= x <= 1 and 0 <= y <= 1
        reasons = []
        if not finite:
            reasons.append("NON_FINITE")
        if in_frame is False:
            reasons.append("OUT_OF_FRAME")
        if math.isfinite(visibility) and visibility < float(np.float32(MIN_VISIBILITY)):
            reasons.append("LOW_VISIBILITY")
        details.append((index, round(x, 4), round(y, 4), round(visibility, 4),
                        finite, in_frame, "|".join(reasons) or "VALID"))
    return details


class State(str, Enum):
    ACTIVE = "ACTIVE"
    STILL = "STILL"
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"
    RECOVERED = "RECOVERED"


@dataclass(frozen=True)
class Reading:
    state: State = State.UNKNOWN
    duration_s: float = 0.
    transition: State | None = None
    reason: str = ""
    valid_body: int | None = None
    valid_torso: int | None = None
    sample_gap_s: float | None = None
    window_span_s: float | None = None
    matched_samples: int | None = None


class ImmobilityDetector:
    sample_s = .2
    window_s = 2.
    max_gap_s = .65
    settle_s = 1.
    recovery_s = .4

    def __init__(self, duration_s=600, motion_threshold=.018):
        if not math.isfinite(duration_s) or not 0 < duration_s <= 604800:
            raise ValueError("Immobility duration must be in (0, 604800]")
        if not math.isfinite(motion_threshold) or motion_threshold <= 0:
            raise ValueError("Motion threshold must be positive")
        self.duration_s = duration_s
        self.motion_threshold = motion_threshold
        self.frames = deque()
        self.reading = Reading()
        self.last_sample = None
        self.last_stamp = None
        self.still_since = None
        self.moving_since = None
        self.latched_duration = None
        self.servo_until = -math.inf

    def _unknown(self, reason, **details):
        self.frames.clear()
        self.still_since = self.moving_since = self.last_sample = None
        self.reading = Reading(reason=reason, **details)
        return self.reading

    @staticmethod
    def _visible(points):
        return (np.isfinite(points).all(axis=1) & (points[:, 2] >= MIN_VISIBILITY)
                & (points[:, :2] >= 0).all(axis=1) & (points[:, :2] <= 1).all(axis=1))

    def update(self, stamp, points=None, *, camera_moving=False):
        if not math.isfinite(stamp) or (self.last_stamp is not None and stamp < self.last_stamp):
            raise ValueError("Expected a monotonic timestamp")
        self.last_stamp = stamp
        if camera_moving:
            self.servo_until = stamp+self.settle_s
        if points is None:
            return self._unknown("no_pose")
        if stamp < self.servo_until:
            return self._unknown("camera_settling")
        sample_gap = None if self.last_sample is None else stamp-self.last_sample
        gap_reset = sample_gap is not None and sample_gap > self.max_gap_s
        if gap_reset:
            self._unknown("sample_gap", sample_gap_s=sample_gap)
        current = np.asarray(points, dtype=np.float32)[BODY]
        visible = self._visible(current)
        body_count, torso_count = int(visible.sum()), int(visible[TORSO].sum())
        if body_count < 6 or torso_count < 3:
            return self._unknown("invalid_pose", valid_body=body_count,
                                 valid_torso=torso_count, sample_gap_s=sample_gap)
        if self.last_sample is not None and stamp-self.last_sample < self.sample_s-1e-8:
            return self.reading if self.reading.transition is None else Reading(
                self.reading.state, self.reading.duration_s)
        self.last_sample = stamp
        while self.frames and stamp-self.frames[0][0] > self.window_s+self.max_gap_s:
            self.frames.popleft()
        self.frames.append((stamp, current.copy(), visible))
        span = stamp-self.frames[0][0]
        if span < self.window_s-1e-8:
            self.reading = Reading(reason="sample_gap" if gap_reset else "window_warmup",
                                   valid_body=body_count, valid_torso=torso_count,
                                   sample_gap_s=sample_gap, window_span_s=span)
            return self.reading

        deltas = []
        for _, previous, previous_visible in self.frames:
            common = visible & previous_visible
            if common.sum() >= 6 and common[TORSO].sum() >= 3:
                distance = np.linalg.norm(current[common, :2]-previous[common, :2], axis=1)
                deltas.append(float(np.quantile(distance, .75)))
        if len(deltas) < 3:
            return self._unknown("insufficient_overlap", valid_body=body_count,
                                 valid_torso=torso_count, sample_gap_s=sample_gap,
                                 window_span_s=span, matched_samples=len(deltas))
        if np.quantile(deltas, .8) >= self.motion_threshold:
            self.still_since = None
            if self.moving_since is None:
                self.moving_since = stamp
            if self.latched_duration is not None and stamp-self.moving_since >= self.recovery_s-1e-8:
                self.reading = Reading(State.RECOVERED, self.latched_duration, State.RECOVERED)
                self.latched_duration = None
                self.frames.clear()
            else:
                self.reading = Reading(State.ACTIVE)
            return self.reading

        self.moving_since = None
        if self.still_since is None:
            self.still_since = stamp
        elapsed = stamp-self.still_since
        if self.latched_duration is None and elapsed >= self.duration_s-1e-8:
            self.latched_duration = min(604800., elapsed)
            self.reading = Reading(State.INACTIVE, self.latched_duration, State.INACTIVE)
        elif self.latched_duration is not None:
            self.latched_duration = min(604800., max(self.latched_duration, elapsed))
            self.reading = Reading(State.INACTIVE, self.latched_duration)
        else:
            self.reading = Reading(State.STILL, elapsed)
        return self.reading
