"""Isolated timestamped pose inference. Alerts are returned as data."""
from collections import deque
from dataclasses import dataclass
import hashlib
import logging
import math
import time

import numpy as np

from ml.features import EMPTY, SPEC, SHAPE, _TimestampSampler, normalize_sequence

SIZE, STRIDE, GAP = 20, 3, 3
CHECKPOINT_SHA = '5ef559faee3374f57e240b389ad413c336449f85866b4ef357581abef13bb7ac'


def valid_window(mask):
    lost = np.flatnonzero(~mask)
    return bool(mask[0] and mask[-1] and len(lost) <= GAP
                and (len(lost) < 2 or np.all(np.diff(lost) == 1)))


def load_model(path, *, schema=SPEC.schema_version):
    if schema != SPEC.schema_version:
        raise ValueError('Unexpected feature schema')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != CHECKPOINT_SHA:
            raise ValueError('Unexpected research checkpoint SHA-256')
    import torch

    class GRU(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.temporal = torch.nn.GRU(51, 32, batch_first=True)
            self.out = torch.nn.Linear(32, 1)

        def forward(self, x):
            return self.out(self.temporal(x)[0][:, -1]).squeeze(-1)

    model = GRU()
    model.load_state_dict(torch.load(path, map_location='cpu', weights_only=True))
    model.eval()
    logging.info('Loaded full-E4-42 GRU checkpoint with %s', schema)

    @torch.inference_mode()
    def score(window):
        if window.shape != (SIZE, 51) or window.dtype != np.float32:
            raise ValueError('Expected float32 input shape (20, 51)')
        return model(torch.from_numpy(window[None])).sigmoid().item()

    return score


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


class Stream:
    def __init__(self, model, *, confirmations=1):
        self.model = model
        self.confirmations = confirmations
        self.preprocess_ms = 0.
        self.last_stamp = None
        self.resets = []
        self.reset('initial')

    def reset(self, reason):
        self.resets.append((reason, self.last_stamp))
        self.sampler = _TimestampSampler(SPEC)
        self.buffer = deque(maxlen=SIZE)
        self.engine = EventEngine(confirmations=self.confirmations)
        self.empty_count = 0

    def push(self, stamp, pose):
        if not math.isfinite(stamp) or (self.last_stamp is not None and stamp <= self.last_stamp):
            raise ValueError('Timestamps must be finite and strictly increasing')
        if pose is not None and np.shape(pose) != SHAPE:
            raise ValueError('Expected pose shape (17, 3)')
        if self.last_stamp is not None and stamp-self.last_stamp > SPEC.max_gap_s:
            self.reset('timestamp_gap')
        self.last_stamp = stamp
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
            if valid_window(mask):
                begin = time.perf_counter()
                score = self.model(inputs)
                inference_ms = (time.perf_counter()-begin)*1000
                events = self.engine.update(end, score)
            else:
                self.engine.unavailable()
            windows.append(Window(start,end,stamp,mask,inputs,score,events,inference_ms))
        return windows
