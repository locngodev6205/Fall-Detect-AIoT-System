import numpy as np

from research.motion_verification import MotionVerification, TORSO


def pose(hip, leaning=False):
    data = np.ones((17, 3), dtype=np.float32)
    shoulder = (.7, hip-.08) if leaning else (.5, hip-.2)
    data[TORSO, :2] = [shoulder, shoulder, (.5, hip), (.5, hip)]
    return data


def test_requires_causal_evidence_and_latches_episode():
    policy = MotionVerification()
    policy.observe(1., pose(.4))
    assert not policy.update(1., .99)
    policy.observe(1.2, pose(.52, leaning=True))
    assert policy.update(1.2, .99)
    policy.observe(1.3, pose(.53, leaning=True))
    assert not policy.update(1.3, .99)


def test_missing_pose_alone_does_not_raise_an_alert():
    policy = MotionVerification()
    policy.observe(1., pose(.4))
    policy.observe(1.4, None)
    assert not policy.update(1.4, .99)


def test_recovery_allows_a_new_episode():
    policy = MotionVerification()
    policy.observe(1., pose(.4))
    policy.observe(1.2, pose(.53, leaning=True))
    assert policy.update(1.2, .99)
    for t in (1.4, 1.7, 1.85):
        policy.observe(t, pose(.41))
        assert not policy.update(t, .1)
    policy.observe(2.1, pose(.56, leaning=True))
    assert policy.update(2.1, .99)


def test_camera_reconnect_reapplies_requested_resolution(monkeypatch):
    from types import SimpleNamespace
    import cv2
    import mediapipe as mp
    from research import benchmark as bench

    captures = []

    class Capture:
        def __init__(self, source):
            self.settings = {}
            captures.append(self)

        def set(self, key, value):
            self.settings[key] = value

        def isOpened(self):
            return True

        def get(self, key):
            return 20

        def read(self):
            if self is captures[0]:
                return False, None
            return True, np.zeros((2, 2, 3), dtype=np.uint8)

        def release(self):
            pass

    class Pose:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def reset(self):
            pass

        def process(self, pixels):
            return SimpleNamespace(pose_landmarks=None)

    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    monkeypatch.setattr(mp.solutions.pose, "Pose", Pose)
    monkeypatch.setattr(bench, "device_sample", lambda *args: {"elapsed_s": 0})
    monkeypatch.setattr(bench.time, "sleep", lambda _: None)
    result = bench.benchmark(0, lambda _: 0., 0, live=True, limit=.08, resolution=(640, 480))
    assert result["interruptions"] == 1
    assert result["frames"] > 0
    assert len(captures) == 2
    assert all(c.settings == {cv2.CAP_PROP_FRAME_WIDTH: 640,
                              cv2.CAP_PROP_FRAME_HEIGHT: 480} for c in captures)
