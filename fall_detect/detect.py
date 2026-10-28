#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SMARTFALL EDGE MONITOR - HỆ THỐNG PHÁT HIỆN TÉ NGÃ REALTIME (TFLITE EDGE AI)
================================================================================

Mô tả:
  Script nhận diện hành vi té ngã thời gian thực dựa trên 17 điểm khớp xương MediaPipe
  kết hợp mô hình Transformer TFLite siêu nhẹ (~313 KB) chạy trực tiếp trên Raspberry Pi / PC.

--------------------------------------------------------------------------------
HƯỚNG DẪN CÁC LỆNH CHẠY (COMMAND EXECUTION GUIDE):
--------------------------------------------------------------------------------

1. Chạy với Camera / Webcam trực tiếp:
   $ python detect.py --source webcam
   $ python detect.py --source webcam --camera-id 0

2. Chạy với tệp Video có sẵn (để kiểm thử):
   $ python detect.py --source file --file sample_videos/fall_example_1.mp4
   $ python detect.py --source file --file sample_videos/fall_example_2.mp4
   $ python detect.py --source file --file /duong/dan/toi/video.mp4

3. Chạy chế độ ngầm Headless (Không mở cửa sổ GUI - Dành riêng cho Raspberry Pi qua SSH):
   $ python detect.py --source webcam --no-display
   $ python detect.py --source file --file sample_videos/fall_example_1.mp4 --no-display

4. Xem toàn bộ các tham số hỗ trợ:
   $ python detect.py --help

--------------------------------------------------------------------------------
CẤU HÌNH KẾT NỐI & CẢNH BÁO:
- Tham số cài đặt nằm trong file `config.py` hoặc file môi trường `.env`.
- Cấu hình MQTT Broker, Telegram Bot Token, Chat ID, Ngưỡng phát hiện ngã (FALL_CONFIDENCE_THRESHOLD),
  Thời gian bất động báo động (IMMOBILITY_TIMEOUT_SECONDS).
================================================================================
"""

import os
import argparse
import cv2
import mediapipe as mp

import config
from modules.skeleton import extract_and_normalize_features, NUM_FEATURES
from modules.notifier import Notifier
from modules.detector import FallDetector
from modules.visualizer import Visualizer


def main(source_type="webcam", file_path=None, no_display=False, camera_id=0):
    # 1. Xác định đường dẫn mô hình
    model_path = config.MODEL_PATH if os.path.exists(config.MODEL_PATH) else 'fall_detection_transformer.tflite'
    if not os.path.exists(model_path):
        # Tìm trong thư mục con models/
        sub_path = os.path.join(os.path.dirname(__file__), "models", "fall_detection_transformer.tflite")
        if os.path.exists(sub_path):
            model_path = sub_path

    # 2. Khởi tạo Notifier (MQTT & Telegram)
    notifier = Notifier(
        device_id=config.DEVICE_ID,
        enable_mqtt=config.ENABLE_MQTT,
        mqtt_broker=config.MQTT_BROKER,
        mqtt_port=config.MQTT_PORT,
        mqtt_topic=config.MQTT_TOPIC_FALL_ALERT,
        enable_telegram=config.ENABLE_TELEGRAM,
        telegram_token=config.TELEGRAM_BOT_TOKEN,
        telegram_chat_id=config.TELEGRAM_CHAT_ID,
        target_audience=getattr(config, 'TARGET_AUDIENCE', 'elderly')
    )
    notifier.log("Khởi động hệ thống SmartFall Edge Monitor...")

    # 3. Khởi tạo Detector (TFLite Engine & Immobility Tracking)
    detector = FallDetector(
        model_path=model_path,
        input_timesteps=config.INPUT_TIMESTEPS,
        num_features=NUM_FEATURES,
        confidence_threshold=config.FALL_CONFIDENCE_THRESHOLD,
        event_cooldown=config.FALL_EVENT_COOLDOWN,
        enable_immobility=getattr(config, 'ENABLE_IMMOBILITY_DETECTION', True),
        immobility_timeout_seconds=getattr(config, 'IMMOBILITY_TIMEOUT_SECONDS', 60),
        on_fall_alert=notifier.send_fall_alert,
        on_immobility_alert=notifier.send_immobility_alert
    )

    # 4. Khởi tạo Visualizer đồ họa
    window_title = f"SmartFall Edge Monitor - {config.DEVICE_ID}"
    visualizer = Visualizer(window_title=window_title)

    # 5. Khởi tạo nguồn thu hình (Webcam hoặc File Video)
    if source_type == "webcam":
        active_cam = camera_id if camera_id is not None else 0
        cap = cv2.VideoCapture(active_cam)
        if not cap.isOpened():
            notifier.log(f"Lỗi: Không thể mở webcam với camera-id {active_cam}")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        notifier.log(f"Đã mở Webcam thành công (Camera ID: {active_cam})")
    elif source_type == "file":
        if file_path and not os.path.exists(file_path):
            sample_path = os.path.join(os.path.dirname(__file__), "sample_videos", os.path.basename(file_path))
            if os.path.exists(sample_path):
                file_path = sample_path
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            notifier.log(f"Lỗi: Không thể mở tệp video tại: {file_path}")
            return
        notifier.log(f"Đang phát tệp video: {file_path}")
    else:
        notifier.log(f"Lỗi: Nguồn không hợp lệ: '{source_type}'")
        return

    # 6. Khởi tạo MediaPipe Pose
    mp_pose = mp.solutions.pose
    with mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        smooth_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    ) as pose:

        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                if source_type == "file":
                    notifier.log("Đã phát hết tệp video.")
                else:
                    notifier.log("Không nhận được khung hình từ webcam.")
                break

            # Tiền xử lý RGB cho MediaPipe Pose
            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image_rgb.flags.writeable = False
            pose_results = pose.process(image_rgb)

            # Trích xuất 17 khớp & Chuẩn hóa tọa độ không gian
            features = extract_and_normalize_features(pose_results.pose_landmarks)

            # Cập nhật bộ đệm và phán đoán qua mô hình TFLite
            result = detector.update(features)

            # Hiển thị đồ họa (nếu không ở chế độ Headless)
            if not no_display:
                display_frame = visualizer.draw(frame, pose_results.pose_landmarks, result)
                cv2.imshow(window_title, display_frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    notifier.log("Người dùng nhấn phím 'q' để thoát chương trình.")
                    break

    # Dọn dẹp tài nguyên
    cap.release()
    if not no_display:
        cv2.destroyAllWindows()
    notifier.disconnect()
    notifier.log("Hệ thống nhận diện té ngã đã dừng an toàn.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time Fall Detection System (TFLite)")
    parser.add_argument("--source", type=str, default="webcam", choices=["webcam", "file"],
                        help="Nguồn video: 'webcam' hoặc 'file' (mặc định: webcam)")
    parser.add_argument("--file", type=str, default=None,
                        help="Đường dẫn đến tệp video nếu source là 'file'")
    parser.add_argument("--no-display", action="store_true",
                        help="Chạy ngầm không mở cửa sổ GUI (Tối ưu cho Raspberry Pi chạy qua SSH)")
    parser.add_argument("--camera-id", type=int, default=0,
                        help="Chỉ số thiết bị camera/webcam (mặc định: 0)")
    args = parser.parse_args()

    if args.source == "file" and not args.file:
        parser.error("Bắt buộc phải truyền tham số --file khi chọn --source file")

    main(
        source_type=args.source,
        file_path=args.file,
        no_display=args.no_display,
        camera_id=args.camera_id
    )
