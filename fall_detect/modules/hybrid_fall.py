"""Causal experimental fall decision policy for replay."""
from collections import deque
from enum import Enum
import math

import numpy as np

from .temporal_features import SPEC


class FallState(str, Enum):
    NORMAL = "NORMAL"
    SUSPECTED_FALL = "SUSPECTED_FALL"
    FALL_CONFIRMED = "FALL_CONFIRMED"
    RECOVERY = "RECOVERY"


TORSO = tuple(SPEC.keypoints.index(joint) for joint in (
    "Left Shoulder", "Right Shoulder", "Left Hip", "Right Hip",
))


class MotionEvidence:
    """Use image coordinates, scaled by torso length before movement."""

    def __init__(self):
        self.history = deque()

    def observe(self, stamp, pose, *, aspect=1.0):
        while self.history and stamp - self.history[0][0] > 0.8:
            self.history.popleft()
        if pose is None:
            return
        torso = np.asarray(pose)[list(TORSO)]
        if not np.isfinite(torso).all() or (torso[:, 2] < SPEC.minimum_visibility).any():
            return
        shoulder, hip = torso[:2, :2].mean(axis=0), torso[2:, :2].mean(axis=0)
        dx, dy = (hip[0] - shoulder[0]) * aspect, hip[1] - shoulder[1]
        length = math.hypot(dx, dy)
        if length <= 1e-4:
            return
        angle = math.degrees(math.atan2(abs(dx), dy))
        if self.history and stamp - self.history[-1][0] > SPEC.max_gap_s:
            self.history.clear()
        self.history.append((stamp, float(hip[0]) * aspect, float(hip[1]), angle, length))

    def features(self, stamp):
        if not self.history or stamp - self.history[-1][0] > SPEC.max_gap_s:
            return None
        oldest, current = self.history[0], self.history[-1]
        duration = current[0] - oldest[0]
        if duration < 0.2:
            return None
        descent = (current[2] - oldest[2]) / oldest[4]
        angle_change = current[3] - oldest[3]
        return {
            "hip_descent_velocity": descent / duration,
            "torso_inclination": current[3],
            "angular_velocity": angle_change / duration,
            "posture_transition": angle_change,
            "body_displacement": math.hypot(current[1] - oldest[1], current[2] - oldest[2]) / oldest[4],
        }


def motion_adjustment(features):
    """A bounded soft vote, with missing measurements treated as neutral."""
    if features is None:
        return 0.0
    references = {
        "hip_descent_velocity": 1.0,
        "torso_inclination": 65.0,
        "angular_velocity": 75.0,
        "posture_transition": 50.0,
        "body_displacement": 1.0,
    }
    strength = sum(
        min(1.0, max(0.0, features[key] / reference))
        for key, reference in references.items()
    ) / len(references)
    return 0.05 * (strength - 0.5)


class HybridFall:
    """Emit once per episode and rearm on sustained observed low scores."""

    def __init__(self, threshold=0.5, *, use_motion=True):
        self.threshold = threshold
        self.use_motion = use_motion
        self.state = FallState.NORMAL
        self.average = None
        self.previous = None
        self.recovery_since = None

    def update(self, stamp, score, features=None):
        gap = math.inf if self.previous is None else stamp - self.previous
        if gap <= 0:
            raise ValueError("Decision timestamps must be strictly increasing")
        self.previous = stamp
        if score is None or gap > 0.5:
            self.average = None
            self.recovery_since = None
            if self.state == FallState.RECOVERY:
                self.state = FallState.FALL_CONFIRMED
            elif self.state == FallState.SUSPECTED_FALL:
                self.state = FallState.NORMAL
        if score is None:
            return False
        weight = 1 - math.exp(-gap / 0.35)
        self.average = score if self.average is None else self.average + weight * (score - self.average)
        smoothing = min(0.03, max(-0.03, 0.25 * (self.average - score)))
        adjustment = motion_adjustment(features) if self.use_motion else 0.0
        decision = score + smoothing + adjustment
        if self.state in (FallState.FALL_CONFIRMED, FallState.RECOVERY):
            if decision > self.threshold - 0.10:
                self.state = FallState.FALL_CONFIRMED
                self.recovery_since = None
            elif self.recovery_since is None:
                self.state = FallState.RECOVERY
                self.recovery_since = stamp
            elif stamp - self.recovery_since >= 0.6 - 1e-9:
                self.state = FallState.NORMAL
                self.recovery_since = None
            return False
        if decision >= self.threshold:
            self.state = FallState.FALL_CONFIRMED
            return True
        if decision >= self.threshold - 0.08:
            self.state = FallState.SUSPECTED_FALL
        elif decision < self.threshold - 0.12:
            self.state = FallState.NORMAL
        return False
