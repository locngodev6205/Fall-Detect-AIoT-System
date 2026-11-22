"""Causal research policy for confirming high GRU scores."""
from collections import deque
import math

import numpy as np

from ml.features import SPEC

TORSO = [SPEC.keypoints.index(name) for name in (
    "Left Shoulder", "Right Shoulder", "Left Hip", "Right Hip",
)]


class MotionVerification:
    """Confirm recent downward motion with a lowered or tilted torso."""

    def __init__(self):
        self.history = deque()
        self.latched = False
        self.upright_since = None

    def observe(self, stamp, pose):
        while self.history and stamp-self.history[0][0] > .85:
            self.history.popleft()
        if pose is None:
            self.upright_since = None
            return
        torso = np.asarray(pose)[TORSO]
        if not np.isfinite(torso).all() or min(torso[:, 2]) < SPEC.minimum_visibility:
            self.upright_since = None
            return
        shoulder, hip = torso[:2, :2].mean(axis=0), torso[2:, :2].mean(axis=0)
        delta = shoulder-hip
        angle = math.degrees(math.atan2(abs(delta[0]), max(0., -delta[1])))
        self.history.append((stamp, float(hip[1]), angle))
        if angle > 25:
            self.upright_since = None

    def update(self, stamp, score):
        if not self.history or stamp-self.history[-1][0] > .15:
            self.upright_since = None
            return False
        _, hip, angle = self.history[-1]
        if self.latched:
            if angle <= 25 and score is not None and score < .5:
                if self.upright_since is None:
                    self.upright_since = stamp
                elif stamp-self.upright_since >= .4:
                    self.latched = False
            else:
                self.upright_since = None
            return False
        if score is None or score < .5:
            return False
        prior = [y for t, y, a in self.history if stamp-t >= .15 and a <= 35]
        if not prior or hip-min(prior) < .07 or angle < 35:
            return False
        self.latched = True
        self.upright_since = None
        return True
