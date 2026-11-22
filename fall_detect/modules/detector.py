#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: detector.py
Mô tả:
  Đóng gói công cụ suy luận TensorFlow Lite (TFLite Interpreter),
  quản lý bộ đệm chuỗi cửa sổ trượt (Sliding Window 30 frames),
  thuật toán phát hiện té ngã và cơ chế giám sát nằm bất động kéo dài.
"""

import hashlib
import json
import logging
import math
from pathlib import Path
import time
from collections import deque
from dataclasses import dataclass
import numpy as np
import tflite_runtime.interpreter as tflite

from ml.features import NUM_FEATURES, SPEC, PoseSampler, extract_keypoints


@dataclass
class DetectionResult:
    status_text: str          # Văn bản trạng thái hiển thị
    label: str                # 'fall', 'no_fall', hoặc 'no_person'
    confidence: float         # Độ tin cậy hiển thị (0.0 - 1.0)
    raw_fall_prob: float      # Xác suất P(fall) thô từ sigmoid (0.0 - 1.0)
    is_fall: bool             # True nếu model dự đoán ngã
    is_alert_active: bool     # True nếu đang trong thời gian hiển thị cảnh báo ngã
    immobile_duration: float  # Số giây đối tượng đang nằm bất động liên tục
    person_present: bool = False  # True nếu phát hiện có người trong khung hình


class FallDetector:
    def __init__(
        self,
        model_path,
        input_timesteps=30,
        num_features=51,
        confidence_threshold=0.50,
        event_cooldown=10,
        enable_immobility=True,
        immobility_timeout_seconds=60,
        on_fall_alert=None,
        on_immobility_alert=None
    ):
        self.model_path = model_path
        self.input_timesteps = input_timesteps
        self.num_features = num_features
        self.confidence_threshold = confidence_threshold
        self.event_cooldown = event_cooldown

        self.enable_immobility = enable_immobility
        self.immobility_timeout_seconds = immobility_timeout_seconds

        # Callback khi phát hiện sự kiện
        self.on_fall_alert = on_fall_alert
        self.on_immobility_alert = on_immobility_alert

        # Bộ đệm chuỗi cửa sổ trượt
        self.sequence_buffer = deque(maxlen=self.input_timesteps)

        # Trạng thái thời gian
        self.last_fall_event_time = None
        self._last_callback_error = -math.inf
        self.prev_features = None
        self.immobility_start_time = None
        self.last_immobility_alert_time = 0.0

        # Khởi tạo mô hình TFLite
        self._init_model()

    def _init_model(self):
        model_path = Path(self.model_path)
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        self.model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.feature_sampler = None
        self.last_pose_result = None
        manifest = model_path.with_suffix(".manifest.json")
        if manifest.exists():
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            if metadata["sha256"] != self.model_sha256:
                raise ValueError("Fall model SHA-256 does not match manifest")
            self.confidence_threshold = float(metadata["fall_threshold"])
            schema = metadata.get("feature_schema_version", "legacy")
            if schema == SPEC.schema_version:
                if (metadata.get("sample_rate_hz") != SPEC.sample_rate_hz
                        or metadata.get("window_size") != self.input_timesteps
                        or self.num_features != NUM_FEATURES):
                    raise ValueError("Fall model manifest disagrees with pose sampling or tensor dimensions")
                self.feature_sampler = PoseSampler()
            elif schema != "legacy":
                raise ValueError(f"Unsupported fall feature schema: {schema}")
        else:
            logging.getLogger(__name__).warning(
                "No fall model manifest; using legacy threshold %.3f (sha256=%s)",
                self.confidence_threshold, self.model_sha256,
            )
        if not 0 < self.confidence_threshold <= 1:
            raise ValueError("Fall threshold must be in (0, 1]")
        self.interpreter = tflite.Interpreter(model_path=self.model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        if len(self.input_details) != 1 or len(self.output_details) != 1:
            raise ValueError('Fall model requires one input and one output')
        if any(tensor['dtype'] != np.float32 for tensor in (self.input_details[0], self.output_details[0])):
            raise ValueError('Fall model requires float32 input and output')
        if tuple(self.output_details[0]['shape']) != (1, 1):
            raise ValueError('Fall output must have shape (1, 1)')
        expected_shape = tuple(self.input_details[0]['shape'])
        target_shape = (1, self.input_timesteps, self.num_features)
        if expected_shape != target_shape:
            raise ValueError(
                f"Kích thước đầu vào TFLite {expected_shape} không khớp với cấu hình {target_shape}."
            )
        print(f"[Detector] Đã nạp thành công mô hình TFLite: {self.model_path}")

    def update_pose(self, pose_landmarks, person_present, timestamp):
        """Select preprocessing by the model manifest; legacy models keep their original path."""
        if self.feature_sampler is None:
            from modules.skeleton import extract_and_normalize_features
            features = extract_and_normalize_features(pose_landmarks) if person_present else None
            return self.update(features, person_present=person_present)

        keypoints = extract_keypoints(pose_landmarks)
        for vector in self.feature_sampler.push(timestamp, keypoints):
            self.last_pose_result = self.update(vector, person_present=bool(vector[2::3].any()))
        return self.last_pose_result

    def reset_pose_stream(self):
        if self.feature_sampler is not None:
            self.feature_sampler = PoseSampler()
            self.last_pose_result = None
            self.update(None, person_present=False)

    def update_immobility(self, current_features):
        # 2. Xử lý logic phát hiện bất động kéo dài (chỉ tính khi có người trong khung hình)
        immobile_duration = 0.0
        if self.enable_immobility:
            # Chỉ lấy tọa độ không gian (x, y) của 17 khớp để đo độ dịch chuyển, bỏ qua kênh confidence
            curr_xy = np.delete(current_features, np.arange(2, len(current_features), 3))
            if self.prev_features is not None:
                prev_xy = np.delete(self.prev_features, np.arange(2, len(self.prev_features), 3))
                # Tính biến thiên tọa độ (x, y) trung bình giữa 2 frame liên tiếp
                movement_delta = float(np.mean(np.abs(curr_xy - prev_xy)))
                # Ngưỡng vi sai < 0.012 được xem là nằm/ngồi bất động
                if movement_delta < 0.012:
                    if self.immobility_start_time is None:
                        self.immobility_start_time = time.time()
                    else:
                        immobile_duration = time.time() - self.immobility_start_time
                        if immobile_duration >= self.immobility_timeout_seconds:
                            now = time.time()
                            if (now - self.last_immobility_alert_time) > self.event_cooldown:
                                if self.on_immobility_alert:
                                    self.on_immobility_alert(immobile_duration)
                                self.last_immobility_alert_time = now
                else:
                    # Có chuyển động rõ ràng -> reset timer bất động
                    self.immobility_start_time = None
            else:
                self.immobility_start_time = time.time()
            self.prev_features = current_features.copy()

        return immobile_duration

    def update(self, current_features, person_present=True):
        """
        Nhận vector 51 đặc trưng của frame hiện tại và cờ person_present,
        cập nhật bộ đệm, kiểm tra bất động và chạy suy luận té ngã.
        Khi không có người trong khung hình (person_present=False), hệ thống sẽ
        reset bộ đếm bất động và không cảnh báo nhầm.
        
        Trả về:
            DetectionResult: Kết quả phán đoán hoàn chỉnh của frame
        """
        # 0. Nếu không có người trong khung hình -> Reset bộ đếm bất động & không tích lũy vector 0
        if not person_present or current_features is None:
            self.immobility_start_time = None
            self.prev_features = None
            self.sequence_buffer.clear()
            return DetectionResult(
                status_text="NO PERSON",
                label="no_person",
                confidence=0.0,
                raw_fall_prob=0.0,
                is_fall=False,
                is_alert_active=False,
                immobile_duration=0.0,
                person_present=False
            )

        # 1. Cập nhật bộ đệm chuỗi (chỉ khi thực sự có người trong hình)
        self.sequence_buffer.append(current_features)

        immobile_duration = self.update_immobility(current_features)

        # 3. Phán đoán mô hình khi bộ đệm đủ 30 frames
        label = "no_fall"
        raw_fall_prob = 0.0
        confidence = 0.0
        is_fall = False
        status_text = "Collecting data..."

        if len(self.sequence_buffer) == self.input_timesteps:
            input_tensor = np.array(self.sequence_buffer, dtype=np.float32)
            input_tensor = np.expand_dims(input_tensor, axis=0)

            try:
                self.interpreter.set_tensor(self.input_details[0]['index'], input_tensor)
                self.interpreter.invoke()
                output_tensor = self.interpreter.get_tensor(self.output_details[0]['index'])
                raw_fall_prob = float(output_tensor[0][0])
                if not 0.0 <= raw_fall_prob <= 1.0:
                    raise ValueError("Invalid model probability")

                if raw_fall_prob >= self.confidence_threshold:
                    label = "fall"
                    confidence = raw_fall_prob
                    is_fall = True
                else:
                    label = "no_fall"
                    confidence = 1.0 - raw_fall_prob
                    is_fall = False

                status_text = f"{label.upper()} (Conf: {confidence:.2f})"

            except Exception as error:
                status_text = f"Prediction Error: {type(error).__name__}"
                raw_fall_prob = 0.0

        # Delivery has its own failure boundary and must not alter the prediction.
        now = time.monotonic()
        last = self.last_fall_event_time
        if is_fall and (last is None or now - last >= self.event_cooldown):
            self.last_fall_event_time = now
            if self.on_fall_alert:
                try:
                    self.on_fall_alert(raw_fall_prob, f"{raw_fall_prob * 100:.2f}%")
                except Exception:
                    if now - self._last_callback_error >= 30:
                        self._last_callback_error = now
                        logging.getLogger(__name__).error("Fall notification callback failed", exc_info=True)

        last = self.last_fall_event_time
        is_alert_active = last is not None and now - last < self.event_cooldown

        return DetectionResult(
            status_text=status_text,
            label=label,
            confidence=confidence,
            raw_fall_prob=raw_fall_prob,
            is_fall=is_fall,
            is_alert_active=is_alert_active,
            immobile_duration=immobile_duration,
            person_present=True
        )
