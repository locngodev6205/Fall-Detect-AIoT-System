#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: detector.py
Mô tả:
  Đóng gói công cụ suy luận TensorFlow Lite (TFLite Interpreter),
  quản lý bộ đệm chuỗi cửa sổ trượt (Sliding Window 30 frames),
  thuật toán phát hiện té ngã và cơ chế giám sát nằm bất động kéo dài.
"""

import time
from collections import deque
from dataclasses import dataclass
import numpy as np
import tflite_runtime.interpreter as tflite


@dataclass
class DetectionResult:
    status_text: str          # Văn bản trạng thái hiển thị
    label: str                # 'fall' hoặc 'no_fall'
    confidence: float         # Độ tin cậy hiển thị (0.0 - 1.0)
    raw_fall_prob: float      # Xác suất P(fall) thô từ sigmoid (0.0 - 1.0)
    is_fall: bool             # True nếu model dự đoán ngã
    is_alert_active: bool     # True nếu đang trong thời gian hiển thị cảnh báo ngã
    immobile_duration: float  # Số giây đối tượng đang nằm bất động liên tục


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
        self.last_fall_event_time = 0.0
        self.prev_features = None
        self.immobility_start_time = None
        self.last_immobility_alert_time = 0.0

        # Khởi tạo mô hình TFLite
        self._init_model()

    def _init_model(self):
        self.interpreter = tflite.Interpreter(model_path=self.model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        expected_shape = tuple(self.input_details[0]['shape'])
        target_shape = (1, self.input_timesteps, self.num_features)
        if expected_shape != target_shape:
            raise ValueError(
                f"Kích thước đầu vào TFLite {expected_shape} không khớp với cấu hình {target_shape}."
            )
        print(f"[Detector] Đã nạp thành công mô hình TFLite: {self.model_path}")

    def update(self, current_features):
        """
        Nhận vector 51 đặc trưng của frame hiện tại,
        cập nhật bộ đệm, kiểm tra bất động và chạy suy luận té ngã.
        
        Trả về:
            DetectionResult: Kết quả phán đoán hoàn chỉnh của frame
        """
        # 1. Cập nhật bộ đệm chuỗi
        self.sequence_buffer.append(current_features)

        # 2. Xử lý logic phát hiện bất động kéo dài (FN-AI-05)
        immobile_duration = 0.0
        if self.enable_immobility and current_features is not None:
            if self.prev_features is not None:
                # Tính biến thiên trung bình giữa 2 frame liên tiếp
                movement_delta = np.mean(np.abs(current_features - self.prev_features))
                # Ngưỡng vi sai < 0.008 được xem là hoàn toàn bất động
                if movement_delta < 0.008:
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
            self.prev_features = current_features.copy()

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

                if raw_fall_prob >= self.confidence_threshold:
                    label = "fall"
                    confidence = raw_fall_prob
                    is_fall = True
                else:
                    label = "no_fall"
                    confidence = 1.0 - raw_fall_prob
                    is_fall = False

                status_text = f"{label.upper()} (Conf: {confidence:.2f})"

                # 4. Kích hoạt cảnh báo té ngã nếu vượt ngưỡng và hết thời gian cooldown
                if is_fall:
                    now = time.time()
                    if (now - self.last_fall_event_time) > self.event_cooldown:
                        confidence_pct_str = f"{raw_fall_prob * 100:.2f}%"
                        if self.on_fall_alert:
                            self.on_fall_alert(raw_fall_prob, confidence_pct_str)
                        self.last_fall_event_time = now

            except Exception as e:
                status_text = f"Prediction Error: {e}"

        # Kiểm tra xem có đang trong thời gian kích hoạt banner cảnh báo không
        is_alert_active = (
            self.last_fall_event_time != 0.0 and
            (time.time() - self.last_fall_event_time < self.event_cooldown)
        )

        return DetectionResult(
            status_text=status_text,
            label=label,
            confidence=confidence,
            raw_fall_prob=raw_fall_prob,
            is_fall=is_fall,
            is_alert_active=is_alert_active,
            immobile_duration=immobile_duration
        )
