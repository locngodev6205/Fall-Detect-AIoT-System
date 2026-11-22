"""Map the pinned E4-42 research stream to the existing Edge detector contract."""
import logging
from pathlib import Path

import numpy as np

from ml.features import EMPTY, extract_keypoints, normalize_sequence
from modules.detector import DetectionResult, FallDetector
from research.streaming import SIZE, Stream, load_model


class GruDetector:
    confidence_threshold = .5

    def __init__(self, checkpoint, on_fall_alert):
        import torch

        torch.set_num_threads(2)
        model = load_model(Path(checkpoint))
        if not 0. <= model(np.zeros((SIZE, 51), dtype=np.float32)) <= 1.:
            raise ValueError("Invalid GRU readiness probability")
        self.stream = Stream(model)
        self.on_fall_alert = on_fall_alert
        self.enable_immobility = True
        self.immobility_timeout_seconds = 60
        self.on_immobility_alert = None
        self.event_cooldown = 10
        self.last_immobility_alert_time = 0.
        self.reset_immobility()
        self.last_result = None

    def reset_immobility(self):
        self.prev_features = None
        self.immobility_start_time = None

    def reset_pose_stream(self):
        if self.stream.last_stamp is not None:
            self.stream = Stream(self.stream.model)
        self.last_result = None
        self.reset_immobility()

    def update_pose(self, landmarks, person_present, timestamp):
        # The model's own visibility contract decides which keypoints are usable.
        points = extract_keypoints(landmarks) if landmarks is not None else EMPTY
        normalized = normalize_sequence([points])[0]
        present = bool(normalized[2::3].any())
        resets = len(self.stream.resets)
        windows = self.stream.push(timestamp, points)
        if not present or len(self.stream.resets) != resets:
            self.last_result = None
            self.reset_immobility()
        self.last_inference_ms = [w.inference_ms for w in windows if w.score is not None]
        if present:
            immobile = FallDetector.update_immobility(self, normalized)
        else:
            immobile = 0.
        for window in windows:
            if window.error:
                raise RuntimeError(f"GRU inference failure: {window.error}")
            self.last_result = window.score
            for name, _ in window.events:
                if name == "simulated_alert" and self.on_fall_alert is not None:
                    try:
                        self.on_fall_alert(window.score, f"{window.score:.2%}")
                    except Exception:
                        logging.getLogger(__name__).exception("Fall notification callback failed")
        score = self.last_result if present else None
        fall = score is not None and score >= self.confidence_threshold
        label = "fall" if fall else ("no_fall" if score is not None else
                                    "warming_up" if present else "no_person")
        status = f"{label.upper()} (Conf: {score:.2f})" if score is not None else label.upper()
        active = timestamp - self.stream.engine.last_alert < self.stream.engine.cooldown
        return DetectionResult(status, label, (score if fall else 1-score) if score is not None else 0.,
                               score if score is not None else 0., fall, active, immobile, present)
