"""Versioned pose contract shared by dataset generation, training and Edge."""
from dataclasses import dataclass
import math

import numpy as np

JOINTS = (
    ('Nose', 0), ('Left Eye', 2), ('Right Eye', 5), ('Left Ear', 7), ('Right Ear', 8),
    ('Left Shoulder', 11), ('Right Shoulder', 12), ('Left Elbow', 13), ('Right Elbow', 14),
    ('Left Wrist', 15), ('Right Wrist', 16), ('Left Hip', 23), ('Right Hip', 24),
    ('Left Knee', 25), ('Right Knee', 26), ('Left Ankle', 27), ('Right Ankle', 28),
)


@dataclass(frozen=True)
class SkeletonFeatureSpec:
    schema_version: str = 'annha-pose-v2'
    keypoints: tuple = tuple(name for name, _ in JOINTS)
    channels: tuple = ('x', 'y', 'visibility')
    coordinate_space: str = 'normalized_image'
    normalization: str = 'midhip_euclidean_torso'
    sample_rate_hz: int = 10
    window_size: int = 30
    max_gap_s: float = .25
    minimum_visibility: float = .3


SPEC = SkeletonFeatureSpec()
SHAPE = (len(JOINTS), 3)
NUM_FEATURES = math.prod(SHAPE)
EMPTY = np.zeros(SHAPE, dtype=np.float32)


def video_frame_timestamp(position_ms, fps, previous):
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('Video FPS must be finite and positive')
    current = position_ms / 1000
    if not math.isfinite(current) or current < 0 or (previous is not None and current <= previous):
        return 0.0 if previous is None else previous + 1 / fps
    return current


def extract_keypoints(pose_landmarks):
    if pose_landmarks is None:
        return EMPTY.copy()
    landmarks = pose_landmarks.landmark
    return np.asarray([(landmarks[i].x, landmarks[i].y, landmarks[i].visibility)
                       for _, i in JOINTS], dtype=np.float32)


def _clean(raw):
    points = np.asarray(raw, dtype=np.float32).reshape(SHAPE).copy()
    valid = np.isfinite(points).all(axis=1) & (np.abs(points[:, :2]) <= 4).all(axis=1)
    points[~valid] = 0
    points[:, 2] = points[:, 2].clip(0, 1)
    points[points[:, 2] == 0, :2] = 0
    return points


def normalize_sequence(raw_sequence, spec=SPEC, *, image_size=None):
    """Normalize one sequence. Supply (width, height) when input is in pixels."""
    if image_size is not None:
        size = np.asarray(image_size, dtype=np.float64)
        if size.shape != (2,) or not np.isfinite(size).all() or (size <= 0).any():
            raise ValueError('Image dimensions must be finite and positive')
    result = np.zeros((len(raw_sequence), NUM_FEATURES), dtype=np.float32)
    indices = {name: i for i, name in enumerate(spec.keypoints)}
    shoulder = [indices['Left Shoulder'], indices['Right Shoulder']]
    hip = [indices['Left Hip'], indices['Right Hip']]
    for destination, raw in zip(result, raw_sequence):
        if image_size is not None:
            raw = np.asarray(raw, dtype=np.float64).reshape(SHAPE).copy()
            raw[:, :2] /= size
        points = _clean(raw)
        visible = points[:, 2] >= spec.minimum_visibility
        shoulders = points[shoulder][visible[shoulder], :2]
        hips = points[hip][visible[hip], :2]
        if not len(shoulders) or not len(hips):
            continue
        center = hips.mean(axis=0)
        scale = np.linalg.norm(shoulders.mean(axis=0) - center)
        if scale < 1e-4:
            continue
        points[:, :2] = np.clip((points[:, :2] - center) / scale, -20, 20)
        points[~visible] = 0
        destination[:] = points.ravel()
    return result


class _TimestampSampler:
    def __init__(self, spec):
        self.spec = spec
        self.previous = None
        self.origin = None
        self.index = 0

    def push(self, timestamp, keypoints, *, collapse_gap=False):
        if not math.isfinite(timestamp) or (self.previous and timestamp <= self.previous[0]):
            raise ValueError('Pose timestamps must be finite and strictly increasing')
        current = _clean(keypoints)
        if self.previous is None:
            self.origin = timestamp
            self.previous = timestamp, current
            self.index = 1
            return [current]
        last_time, previous = self.previous
        output = []
        target = self.origin + self.index / self.spec.sample_rate_hz
        if collapse_gap and timestamp - last_time > self.spec.max_gap_s:
            if target < timestamp - 1e-8:
                output.append(EMPTY.copy())
            self.index = math.ceil((timestamp - self.origin - 1e-8) * self.spec.sample_rate_hz)
            target = self.origin + self.index / self.spec.sample_rate_hz
        while target <= timestamp + 1e-8:
            if abs(target - timestamp) <= 1e-8:
                output.append(current)
            elif timestamp - last_time > self.spec.max_gap_s:
                output.append(EMPTY.copy())
            else:
                weight = (target - last_time) / (timestamp - last_time)
                sample = previous + weight * (current - previous)
                sample[np.minimum(previous[:, 2], current[:, 2]) < self.spec.minimum_visibility] = 0
                output.append(sample)
            self.index += 1
            target = self.origin + self.index / self.spec.sample_rate_hz
        self.previous = timestamp, current
        return output


def resample_keypoints(timestamps, raw_keypoints, spec=SPEC):
    sampler = _TimestampSampler(spec)
    samples = [sample for t, pose in zip(timestamps, raw_keypoints, strict=True)
               for sample in sampler.push(float(t), pose)]
    return np.asarray(samples, dtype=np.float32).reshape((-1, *SHAPE))


class PoseSampler:
    """Streaming adapter using the same target grid and normalization as training."""
    def __init__(self, spec=SPEC):
        self.spec = spec
        self.sampler = _TimestampSampler(spec)

    def push(self, timestamp, pose):
        return normalize_sequence(self.sampler.push(timestamp, pose, collapse_gap=True), self.spec)
