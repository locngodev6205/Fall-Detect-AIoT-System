"""Isolated timestamped pose inference. Alerts are returned as data."""
from collections import deque
from dataclasses import dataclass
import math
import time

import numpy as np

from .temporal_features import EMPTY, SPEC, SHAPE, _TimestampSampler, normalize_sequence

SIZE, STRIDE, GAP = 20, 3, 3

def valid_window(mask):
    lost = np.flatnonzero(~mask)
    return bool(mask[0] and mask[-1] and len(lost) <= GAP
                and (len(lost) < 2 or np.all(np.diff(lost) == 1)))


class EventEngine:
    def __init__(self, threshold=.5, cooldown=2., confirmations=1):
        if not 0 < threshold < 1 or cooldown < 0 or confirmations < 1:
            raise ValueError('Invalid event configuration')
        self.threshold, self.cooldown, self.confirmations = threshold, cooldown, confirmations
        self.last_alert = -math.inf
        self.state = 'MONITORING'
        self.streak = 0

    def person_lost(self):
        self.state = 'MONITORING'
        self.streak = 0

    def unavailable(self):
        # Hold the high latch across missing pose. An unfinished candidate must reconfirm.
        self.streak = 0
        if self.state == 'FALL_CANDIDATE':
            self.state = 'MONITORING'

    def update(self, stamp, score):
        if score < self.threshold:
            self.state = 'MONITORING'
            self.streak = 0
            return ()
        if self.state == 'COOLDOWN':
            return ()
        self.streak += 1
        transitions = []
        if self.state != 'FALL_CANDIDATE':
            self.state = 'FALL_CANDIDATE'
            transitions.append(('candidate', stamp))
        if self.streak >= self.confirmations and stamp - self.last_alert >= self.cooldown:
            transitions.extend((('confirmed', stamp), ('simulated_alert', stamp)))
            self.last_alert = stamp
            self.state = 'COOLDOWN'
        return tuple(transitions)


@dataclass
class Window:
    start: float
    end: float
    arrival: float
    mask: np.ndarray
    inputs: np.ndarray
    score: float | None
    events: tuple
    inference_ms: float
    completed_monotonic: float | None
    error: str | None


class Stream:
    def __init__(self, model, *, confirmations=1):
        self.model = model
        self.confirmations = confirmations
        self.preprocess_ms = 0.
        self.last_stamp = None
        self.resets = []
        self.model_errors = 0
        self.invalid_poses = 0
        self.engine = EventEngine(confirmations=confirmations)
        self.reset('initial')

    def reset(self, reason):
        self.resets.append((reason, self.last_stamp))
        self.sampler = _TimestampSampler(SPEC)
        self.buffer = deque(maxlen=SIZE)
        self.engine.unavailable()
        self.empty_count = 0

    def push(self, stamp, pose):
        if not math.isfinite(stamp) or (self.last_stamp is not None and stamp <= self.last_stamp):
            raise ValueError('Timestamps must be finite and strictly increasing')
        if pose is not None and np.shape(pose) != SHAPE:
            raise ValueError('Expected pose shape (17, 3)')
        if self.sampler.previous is not None and stamp-self.last_stamp > SPEC.max_gap_s:
            self.reset('timestamp_gap')
        self.last_stamp = stamp
        if pose is not None and not np.isfinite(pose).all():
            self.invalid_poses += 1
            pose = None
        begin = time.perf_counter()
        first_index = self.sampler.index
        samples = self.sampler.push(stamp, EMPTY if pose is None else pose)
        normalized = normalize_sequence(samples)
        self.preprocess_ms = (time.perf_counter()-begin)*1000
        windows = []
        for index, sample in enumerate(normalized, first_index):
            self.buffer.append(sample)
            self.empty_count = 0 if sample[2::3].any() else self.empty_count + 1
            if self.empty_count == SIZE:
                # No usable pose for a complete window. Preserve grid/stride for parity.
                self.engine.person_lost()
            if len(self.buffer) < SIZE or (index-SIZE+1) % STRIDE:
                continue
            inputs = np.stack(self.buffer)
            mask = inputs[:,2::3].any(axis=1)
            end = self.sampler.origin + index/SPEC.sample_rate_hz
            start = self.sampler.origin + (index-SIZE+1)/SPEC.sample_rate_hz
            score, events, inference_ms = None, (), 0.
            completed, error = None, None
            if valid_window(mask):
                begin = time.monotonic()
                try:
                    score = float(self.model(inputs))
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError('Invalid model probability')
                except Exception as exc:
                    error = type(exc).__name__
                    self.model_errors += 1
                    score = None
                    self.engine.unavailable()
                else:
                    events = self.engine.update(end, score)
                completed = time.monotonic()
                inference_ms = (completed-begin)*1000
            else:
                self.engine.unavailable()
            windows.append(Window(start,end,stamp,mask,inputs,score,events,inference_ms,completed,error))
        return windows
