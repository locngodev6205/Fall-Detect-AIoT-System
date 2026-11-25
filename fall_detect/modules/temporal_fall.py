"""Opt-in CPU inference for the two validated research checkpoint exports."""
import hashlib
from pathlib import Path

import numpy as np

from .temporal_features import extract_keypoints
from .temporal_stream import Stream

# (MediaPipe model_complexity, ONNX SHA-256)
CTR_GCN_SHA256 = "547b55b5a915f0629916a3167a24ee62cad4089a07993ddce45d0353261bf676"
MODELS = {
    "ctr_gcn_40_2026": (1, CTR_GCN_SHA256),
    "ctr_gcn_40_2026_lite": (0, CTR_GCN_SHA256),
    "gru_e4_42": (0, "e57db9a4858cfcc445935d2980365895c94ee5310fc757d96d97eb053784a10a"),
}


class TemporalFall:
    def __init__(self, name, path):
        import onnxruntime as ort

        self.pose_complexity, expected_hash = MODELS[name]
        graph = Path(path).read_bytes()
        if hashlib.sha256(graph).hexdigest() != expected_hash:
            raise ValueError("Unexpected temporal Fall ONNX SHA-256")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(graph, sess_options=options, providers=["CPUExecutionProvider"])
        self.probe()
        self.stream = Stream(self.score)

    def probe(self):
        score = self.score(np.zeros((20, 51), dtype=np.float32))
        if not 0 <= score <= 1:
            raise ValueError("Invalid temporal Fall inference probe score")

    def score(self, window):
        return self.session.run(["score"], {"window": window[None]})[0].item()

    def reset(self):
        self.stream.reset("camera_or_config_reset")
        self.stream.last_stamp = None

    def update(self, stamp, landmarks, alert):
        windows = self.stream.push(stamp, extract_keypoints(landmarks) if landmarks is not None else None)
        for window in windows:
            if window.error is not None:
                raise RuntimeError(f"Temporal Fall inference failed: {window.error}")
            if any(kind == "simulated_alert" for kind, _ in window.events):
                alert(window.score, f"{window.score:.2%}")
        return any(window.score is not None for window in windows)
