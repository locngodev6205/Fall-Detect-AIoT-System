from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.hybrid_fall import FallState, HybridFall, MotionEvidence, TORSO, motion_adjustment


def test_single_high_score_alerts_and_recovery_rearms():
    engine = HybridFall()
    assert not engine.update(1, 0.44)
    assert engine.state == FallState.SUSPECTED_FALL
    assert engine.update(1.3, 0.95)
    assert not engine.update(1.6, 0.96)
    for stamp in (1.9, 2.2, 2.5, 2.8):
        assert not engine.update(stamp, 0.1)
    assert engine.state == FallState.NORMAL
    assert engine.update(3.1, 0.95)


def test_missing_pose_cannot_rearm_or_emit_alert():
    engine = HybridFall()
    assert engine.update(1, 0.9)
    assert not engine.update(1.3, 0.1)
    assert not engine.update(1.6, None)
    assert engine.state == FallState.FALL_CONFIRMED
    assert not engine.update(10, 0.95)


def test_motion_features_use_raw_hip_coordinates_and_expire():
    motion = MotionEvidence()
    pose = np.zeros((17, 3))
    pose[list(TORSO)] = ((0.4, 0.3, 1), (0.6, 0.3, 1), (0.4, 0.5, 1), (0.6, 0.5, 1))
    motion.observe(1, pose)
    pose[list(TORSO), 1] += 0.1
    motion.observe(1.2, pose)
    pose[list(TORSO), 1] += 0.1
    motion.observe(1.4, pose)
    features = motion.features(1.4)
    assert features["hip_descent_velocity"] > 2
    assert features["body_displacement"] > 0.9
    assert abs(motion_adjustment(features)) <= 0.025
    assert motion.features(1.8) is None
    assert motion_adjustment(None) == 0


def test_soft_motion_does_not_veto_a_high_score():
    low_motion = {
        "hip_descent_velocity": 0,
        "torso_inclination": 0,
        "angular_velocity": 0,
        "posture_transition": 0,
        "body_displacement": 0,
    }
    assert HybridFall().update(1, 0.9, low_motion)
