#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: visualizer.py
Mô tả:
  Đảm nhận hiển thị trực quan đồ họa:
  - Vẽ khung xương và khớp nối của cơ thể bằng MediaPipe Drawing Utils.
  - Vẽ nhãn trạng thái, điểm tin cậy và banner cảnh báo màu đỏ nổi bật.
"""

import cv2
import mediapipe as mp

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_pose = mp.solutions.pose


class Visualizer:
    def __init__(self, window_title="SmartFall Edge Monitor"):
        self.window_title = window_title
        self.font_face = cv2.FONT_HERSHEY_DUPLEX
        self.font_scale_status = 0.6
        self.thickness_status = 1
        self.font_scale_alert = 1.0
        self.thickness_alert = 2
        self.padding = 30

    def draw(self, frame_bgr, pose_landmarks, detection_result):
        """
        Vẽ toàn bộ thông tin trực quan lên khung hình:
        1. Các điểm khớp và đường nối khung xương.
        2. Bảng trạng thái nhận diện góc trên bên phải.
        3. Cảnh báo té ngã nổi bật nếu có sự kiện ngã.
        
        Trả về:
            np.ndarray: Khung hình BGR đã được vẽ thông tin
        """
        display_frame = frame_bgr.copy()

        # 1. Vẽ các điểm khớp xương và đường nối
        if pose_landmarks:
            temp_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            mp_drawing.draw_landmarks(
                temp_rgb,
                pose_landmarks,
                mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style()
            )
            display_frame = cv2.cvtColor(temp_rgb, cv2.COLOR_RGB2BGR)

        # 2. Xác định màu sắc theo trạng thái
        status_text = detection_result.status_text
        if "Error" in status_text:
            status_color = (0, 0, 255)      # Đỏ cho lỗi
        elif "Collecting" in status_text:
            status_color = (255, 255, 0)    # Xanh lơ khi đang gom dữ liệu
        elif detection_result.label == "fall":
            status_color = (0, 165, 255)    # Cam cho trạng thái ngã
        else:
            status_color = (255, 255, 255)  # Trắng cho bình thường (no_fall)

        # 3. Vẽ nhãn trạng thái ở góc trên bên phải
        (text_w, text_h), _ = cv2.getTextSize(
            status_text, self.font_face, self.font_scale_status, self.thickness_status
        )
        text_x = display_frame.shape[1] - text_w - self.padding
        text_y = self.padding + text_h

        cv2.putText(
            display_frame, status_text, (text_x, text_y),
            self.font_face, self.font_scale_status, status_color,
            self.thickness_status, cv2.LINE_AA
        )

        # 4. Vẽ banner cảnh báo lớn màu đỏ nếu đang có sự kiện Té Ngã
        if detection_result.is_alert_active:
            alert_text = "FALL DETECTED!"
            (alert_w, alert_h), _ = cv2.getTextSize(
                alert_text, self.font_face, self.font_scale_alert, self.thickness_alert
            )
            alert_x = display_frame.shape[1] - alert_w - self.padding
            alert_y = text_y + alert_h + self.padding // 2
            cv2.putText(
                display_frame, alert_text, (alert_x, alert_y),
                self.font_face, self.font_scale_alert, (0, 0, 255),
                self.thickness_alert, cv2.LINE_AA
            )

        # 5. Hiển thị cảnh báo nếu đang nằm bất động
        if detection_result.immobile_duration > 5.0:
            immobile_text = f"Inactive: {detection_result.immobile_duration:.0f}s"
            cv2.putText(
                display_frame, immobile_text, (self.padding, text_y),
                self.font_face, self.font_scale_status, (0, 165, 255),
                self.thickness_status, cv2.LINE_AA
            )

        return display_frame
