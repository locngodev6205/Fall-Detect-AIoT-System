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

import cv2
import mediapipe as mp
import numpy as np
import tflite_runtime.interpreter as tflite
import time
from collections import deque
import requests # สำหรับ Telegram
import argparse # สำหรับ command-line arguments
from dotenv import load_dotenv
import os

import json
import config

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# --- Configuration loaded from config.py ---
MODEL_PATH = config.MODEL_PATH if os.path.exists(config.MODEL_PATH) else 'fall_detection_transformer.tflite'
INPUT_TIMESTEPS = config.INPUT_TIMESTEPS
FALL_CONFIDENCE_THRESHOLD = config.FALL_CONFIDENCE_THRESHOLD
FALL_EVENT_COOLDOWN = config.FALL_EVENT_COOLDOWN
DEVICE_ID = config.DEVICE_ID

ENABLE_MQTT = config.ENABLE_MQTT and MQTT_AVAILABLE
MQTT_BROKER = config.MQTT_BROKER
MQTT_PORT = config.MQTT_PORT
MQTT_TOPIC_FALL_ALERT = config.MQTT_TOPIC_FALL_ALERT

ENABLE_TELEGRAM_ALERTS = config.ENABLE_TELEGRAM
ENABLE_IMMOBILITY_DETECTION = getattr(config, 'ENABLE_IMMOBILITY_DETECTION', True)
IMMOBILITY_TIMEOUT_SECONDS = getattr(config, 'IMMOBILITY_TIMEOUT_SECONDS', 60)
TARGET_AUDIENCE = getattr(config, 'TARGET_AUDIENCE', 'elderly')
TELEGRAM_BOT_TOKEN = config.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = config.TELEGRAM_CHAT_ID

MIN_KEYPOINT_CONFIDENCE_FOR_NORMALIZATION = 0.3
mp_pose = mp.solutions.pose
pose_complexity = 1
use_static_image_mode = False

CAMERA_INDEX = 0
FRAME_WIDTH = config.FRAME_WIDTH
FRAME_HEIGHT = config.FRAME_HEIGHT
DISPLAY_WINDOW_NAME = f"SmartFall Edge Monitor - {DEVICE_ID}"
LOG_FILE = "fall_detection_log.txt"

# ----- 0. KEYPOINT DEFINITIONS (จากโค้ดของคุณ) -----
KEYPOINT_NAMES_ORIGINAL = [
    'Nose', 'Left Eye Inner', 'Left Eye', 'Left Eye Outer', 'Right Eye Inner', 'Right Eye', 'Right Eye Outer',
    'Left Ear', 'Right Ear', 'Mouth Left', 'Mouth Right',
    'Left Shoulder', 'Right Shoulder', 'Left Elbow', 'Right Elbow', 'Left Wrist', 'Right Wrist',
    'Left Pinky', 'Right Pinky', 'Left Index', 'Right Index', 'Left Thumb', 'Right Thumb',
    'Left Hip', 'Right Hip', 'Left Knee', 'Right Knee', 'Left Ankle', 'Right Ankle',
    'Left Heel', 'Right Heel', 'Left Foot Index', 'Right Foot Index'
]

MEDIAPIPE_TO_YOUR_KEYPOINTS_MAPPING = {
    mp_pose.PoseLandmark.NOSE: 'Nose',
    mp_pose.PoseLandmark.LEFT_EYE: 'Left Eye',
    mp_pose.PoseLandmark.RIGHT_EYE: 'Right Eye',
    mp_pose.PoseLandmark.LEFT_EAR: 'Left Ear',
    mp_pose.PoseLandmark.RIGHT_EAR: 'Right Ear',
    mp_pose.PoseLandmark.LEFT_SHOULDER: 'Left Shoulder',
    mp_pose.PoseLandmark.RIGHT_SHOULDER: 'Right Shoulder',
    mp_pose.PoseLandmark.LEFT_ELBOW: 'Left Elbow',
    mp_pose.PoseLandmark.RIGHT_ELBOW: 'Right Elbow',
    mp_pose.PoseLandmark.LEFT_WRIST: 'Left Wrist',
    mp_pose.PoseLandmark.RIGHT_WRIST: 'Right Wrist',
    mp_pose.PoseLandmark.LEFT_HIP: 'Left Hip',
    mp_pose.PoseLandmark.RIGHT_HIP: 'Right Hip',
    mp_pose.PoseLandmark.LEFT_KNEE: 'Left Knee',
    mp_pose.PoseLandmark.RIGHT_KNEE: 'Right Knee',
    mp_pose.PoseLandmark.LEFT_ANKLE: 'Left Ankle',
    mp_pose.PoseLandmark.RIGHT_ANKLE: 'Right Ankle'
}
YOUR_KEYPOINT_NAMES_TRAINING = [
    'Nose', 'Left Eye', 'Right Eye', 'Left Ear', 'Right Ear',
    'Left Shoulder', 'Right Shoulder', 'Left Elbow', 'Right Elbow',
    'Left Wrist', 'Right Wrist', 'Left Hip', 'Right Hip',
    'Left Knee', 'Right Knee', 'Left Ankle', 'Right Ankle'
]
SORTED_YOUR_KEYPOINT_NAMES = sorted(YOUR_KEYPOINT_NAMES_TRAINING)
KEYPOINT_DICT_TRAINING = {name: i for i, name in enumerate(SORTED_YOUR_KEYPOINT_NAMES)}
NUM_KEYPOINTS_TRAINING = len(KEYPOINT_DICT_TRAINING)
NUM_FEATURES = NUM_KEYPOINTS_TRAINING * 3

print("--- Initializing Keypoint Definitions for Inference ---")
print(f"SORTED_YOUR_KEYPOINT_NAMES (used for ordering features): {SORTED_YOUR_KEYPOINT_NAMES}")
print(f"KEYPOINT_DICT_TRAINING: {KEYPOINT_DICT_TRAINING}")
print(f"NUM_KEYPOINTS_TRAINING: {NUM_KEYPOINTS_TRAINING}")
print(f"NUM_FEATURES for model input: {NUM_FEATURES}")
if NUM_FEATURES != 51:
    print(f"WARNING: NUM_FEATURES is {NUM_FEATURES}, but model expects 51. Check keypoint definitions.")
print("-----------------------------------------------------")


# --- Global Variables (ต่อ) ---
feature_sequence = deque(maxlen=INPUT_TIMESTEPS)
last_fall_event_time = 0
prev_features = None
immobility_start_time = None
last_immobility_alert_time = 0

# --- Load TFLite Model ---
try:
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    print(f"TFLite Model Loaded: {MODEL_PATH}")
    model_expected_shape = tuple(input_details[0]['shape'])
    if model_expected_shape != (1, INPUT_TIMESTEPS, NUM_FEATURES):
        print(f"FATAL ERROR: Model's expected input shape {model_expected_shape} "
              f"does not match configured shape (1, {INPUT_TIMESTEPS}, {NUM_FEATURES}).")
        print("Please check INPUT_TIMESTEPS and NUM_KEYPOINTS_TRAINING/NUM_FEATURES.")
        exit()
except Exception as e:
    print(f"Error loading TFLite model: {e}")
    exit()

# --- Helper Functions (log, telegram) ---
def log_message(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    log_entry = f"[{timestamp}] {message}"
    print(log_entry) # แสดงผลใน console
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"Error writing to log file: {e}")


mqtt_client = None
if ENABLE_MQTT:
    try:
        mqtt_client = mqtt.Client(client_id=f"{DEVICE_ID}_EdgeClient")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        print(f"INFO: Connected to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        print(f"WARNING: Could not connect to MQTT Broker: {e}")
        mqtt_client = None

def send_mqtt_alert(confidence, confidence_str):
    if not mqtt_client:
        return
    payload = {
        "device_id": DEVICE_ID,
        "event": "FALL_DETECTED",
        "confidence": float(confidence),
        "confidence_pct": confidence_str,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }
    try:
        mqtt_client.publish(MQTT_TOPIC_FALL_ALERT, json.dumps(payload), qos=1)
        print(f"INFO: MQTT Fall Alert published to {MQTT_TOPIC_FALL_ALERT}")
    except Exception as e:
        print(f"WARNING: Failed to publish MQTT alert: {e}")

def send_mqtt_immobility_alert(duration_s):
    if not mqtt_client:
        return
    payload = {
        "device_id": DEVICE_ID,
        "target_audience": TARGET_AUDIENCE,
        "event": "PROLONGED_IMMOBILITY_DETECTED",
        "immobility_duration_s": int(duration_s),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }
    try:
        mqtt_client.publish(MQTT_TOPIC_FALL_ALERT, json.dumps(payload), qos=1)
        print(f"INFO: MQTT Immobility Alert published: {duration_s:.1f}s inactive")
    except Exception as e:
        print(f"WARNING: Failed to publish MQTT immobility alert: {e}")

def send_telegram_message(message):
    if not ENABLE_TELEGRAM_ALERTS or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or TELEGRAM_CHAT_ID == "YOUR_TELEGRAM_CHAT_ID":
        # log_message("Telegram alert skipped (not configured or disabled).") # Commented out to reduce log spam if not configured
        if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or TELEGRAM_CHAT_ID == "YOUR_TELEGRAM_CHAT_ID":
             print("INFO: Telegram not configured (BOT_TOKEN or CHAT_ID is placeholder). Alerts will not be sent.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        # log_message(f"Telegram message sent. Response: {response.json().get('ok', False)}") # Can be verbose
        if response.json().get('ok', False):
            print(f"INFO: Telegram message sent successfully.")
        else:
            log_message(f"WARNING: Telegram message sent, but API reported not OK. Response: {response.text}")
    except requests.exceptions.RequestException as e:
        log_message(f"Error sending Telegram message: {e}")


# ----- 1. HELPER FUNCTION FOR KEYPOINT INDICES  -----
def get_kpt_indices_training_order(keypoint_name):
    if keypoint_name not in KEYPOINT_DICT_TRAINING:
        available_keys = list(KEYPOINT_DICT_TRAINING.keys())
        error_msg = f"Keypoint name '{keypoint_name}' not found in KEYPOINT_DICT_TRAINING. Available: {available_keys}"
        raise ValueError(error_msg)
    kp_idx_in_sorted_list = KEYPOINT_DICT_TRAINING[keypoint_name]
    return kp_idx_in_sorted_list * 3, kp_idx_in_sorted_list * 3 + 1, kp_idx_in_sorted_list * 3 + 2


# ----- 2. SKELETON NORMALIZATION FUNCTION  -----
def normalize_skeleton_frame(frame_features_sorted, min_confidence=MIN_KEYPOINT_CONFIDENCE_FOR_NORMALIZATION):
    normalized_frame = np.copy(frame_features_sorted)
    ref_kp_names = {
        'ls': 'Left Shoulder', 'rs': 'Right Shoulder',
        'lh': 'Left Hip', 'rh': 'Right Hip'
    }
    for ref_kp_key, ref_kp_name_val in ref_kp_names.items():
        if ref_kp_name_val not in KEYPOINT_DICT_TRAINING:
            # log_message(f"WARNING in normalize_skeleton_frame: Ref keypoint '{ref_kp_name_val}' not in KEYPOINT_DICT_TRAINING.")
            return frame_features_sorted

    try:
        ls_x_idx, ls_y_idx, ls_c_idx = get_kpt_indices_training_order(ref_kp_names['ls'])
        rs_x_idx, rs_y_idx, rs_c_idx = get_kpt_indices_training_order(ref_kp_names['rs'])
        lh_x_idx, lh_y_idx, lh_c_idx = get_kpt_indices_training_order(ref_kp_names['lh'])
        rh_x_idx, rh_y_idx, rh_c_idx = get_kpt_indices_training_order(ref_kp_names['rh'])
    except ValueError as e:
        # log_message(f"Error getting kpt indices for normalization: {e}")
        return frame_features_sorted

    ls_x, ls_y, ls_c = frame_features_sorted[ls_x_idx], frame_features_sorted[ls_y_idx], frame_features_sorted[ls_c_idx]
    rs_x, rs_y, rs_c = frame_features_sorted[rs_x_idx], frame_features_sorted[rs_y_idx], frame_features_sorted[rs_c_idx]
    lh_x, lh_y, lh_c = frame_features_sorted[lh_x_idx], frame_features_sorted[lh_y_idx], frame_features_sorted[lh_c_idx]
    rh_x, rh_y, rh_c = frame_features_sorted[rh_x_idx], frame_features_sorted[rh_y_idx], frame_features_sorted[rh_c_idx]

    mid_shoulder_x, mid_shoulder_y = np.nan, np.nan
    valid_ls, valid_rs = ls_c > min_confidence, rs_c > min_confidence
    if valid_ls and valid_rs: mid_shoulder_x, mid_shoulder_y = (ls_x + rs_x) / 2, (ls_y + rs_y) / 2
    elif valid_ls: mid_shoulder_x, mid_shoulder_y = ls_x, ls_y
    elif valid_rs: mid_shoulder_x, mid_shoulder_y = rs_x, rs_y

    mid_hip_x, mid_hip_y = np.nan, np.nan
    valid_lh, valid_rh = lh_c > min_confidence, rh_c > min_confidence
    if valid_lh and valid_rh: mid_hip_x, mid_hip_y = (lh_x + rh_x) / 2, (lh_y + rh_y) / 2
    elif valid_lh: mid_hip_x, mid_hip_y = lh_x, lh_y
    elif valid_rh: mid_hip_x, mid_hip_y = rh_x, rh_y

    if np.isnan(mid_hip_x) or np.isnan(mid_hip_y):
        return frame_features_sorted

    reference_height = np.nan
    if not np.isnan(mid_shoulder_y) and not np.isnan(mid_hip_y):
        reference_height = np.abs(mid_shoulder_y - mid_hip_y)

    perform_scaling = not (np.isnan(reference_height) or reference_height < 1e-5)

    for kp_name_sorted in SORTED_YOUR_KEYPOINT_NAMES:
        x_col, y_col, _ = get_kpt_indices_training_order(kp_name_sorted)

        normalized_frame[x_col] -= mid_hip_x
        normalized_frame[y_col] -= mid_hip_y
        if perform_scaling:
            normalized_frame[x_col] /= reference_height
            normalized_frame[y_col] /= reference_height

    return normalized_frame


# ----- ADAPTED FEATURE EXTRACTION with MediaPipe Pose -----
def extract_and_normalize_features(pose_results):
    frame_features_sorted = np.zeros(NUM_FEATURES, dtype=np.float32)

    if pose_results.pose_landmarks:
        landmarks = pose_results.pose_landmarks.landmark

        for mp_landmark_enum, your_kp_name in MEDIAPIPE_TO_YOUR_KEYPOINTS_MAPPING.items():
            if your_kp_name in KEYPOINT_DICT_TRAINING:
                try:
                    lm = landmarks[mp_landmark_enum.value]
                    x_idx, y_idx, c_idx = get_kpt_indices_training_order(your_kp_name)

                    frame_features_sorted[x_idx] = lm.x
                    frame_features_sorted[y_idx] = lm.y
                    frame_features_sorted[c_idx] = lm.visibility
                except IndexError:
                    # log_message(f"Warning: MediaPipe landmark index {mp_landmark_enum.value} for '{your_kp_name}' out of bounds.") # Can be verbose
                    pass # Let it be zero
                except Exception as e:
                    # log_message(f"Error processing landmark {your_kp_name}: {e}") # Can be verbose
                    pass # Let it be zero
    else:
        pass # No landmarks, frame_features_sorted remains zeros

    normalized_features = normalize_skeleton_frame(frame_features_sorted.copy())
    return normalized_features


# --- Process Frame and Predict (Updated Display Logic) ---
def process_frame(frame, pose_estimator): # frame is BGR
    global feature_sequence, last_fall_event_time

    # 1. Create a BGR copy for display. This will be modified.
    processed_frame_display = frame.copy()

    # 2. Convert to RGB for MediaPipe
    image_rgb_for_mediapipe = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image_rgb_for_mediapipe.flags.writeable = False
    results = pose_estimator.process(image_rgb_for_mediapipe)

    # 3. Extract and Normalize Features
    current_features = extract_and_normalize_features(results)
    feature_sequence.append(current_features)

    # --- Immobility Detection Logic (Người già & Trẻ nhỏ) ---
    global prev_features, immobility_start_time, last_immobility_alert_time
    if ENABLE_IMMOBILITY_DETECTION and current_features is not None:
        if prev_features is not None:
            movement_delta = np.mean(np.abs(current_features - prev_features))
            # Ngưỡng vi sai chuyển động nhỏ (< 0.008 là hầu như không nhúc nhích)
            if movement_delta < 0.008:
                if immobility_start_time is None:
                    immobility_start_time = time.time()
                else:
                    immobile_duration = time.time() - immobility_start_time
                    if immobile_duration >= IMMOBILITY_TIMEOUT_SECONDS:
                        if (time.time() - last_immobility_alert_time) > FALL_EVENT_COOLDOWN:
                            immobile_msg = f"⚠️ CẢNH BÁO BẤT ĐỘNG! Đối tượng ({TARGET_AUDIENCE}) nằm im {immobile_duration:.0f}s!"
                            log_message(immobile_msg)
                            send_telegram_message(immobile_msg)
                            send_mqtt_immobility_alert(immobile_duration)
                            last_immobility_alert_time = time.time()
            else:
                # Có chuyển động rõ ràng -> reset timer bất động
                immobility_start_time = None
        prev_features = current_features.copy()

    # 4. Prediction Logic
    prediction_label_for_alert = "no_fall"
    prediction_probability_fall = 0.0
    display_confidence_value = 0.0
    current_status_text_for_log = "Status: Collecting data..."

    if len(feature_sequence) == INPUT_TIMESTEPS:
        model_input_data = np.array(feature_sequence, dtype=np.float32)
        model_input_data = np.expand_dims(model_input_data, axis=0)

        expected_shape = tuple(input_details[0]['shape'])
        if model_input_data.shape != expected_shape or model_input_data.dtype != input_details[0]['dtype']:
            log_message(f"Model input error. Exp {expected_shape} dtype {input_details[0]['dtype']}, got {model_input_data.shape} dtype {model_input_data.dtype}")
            current_status_text_for_log = "Status: Model Input Error"
        else:
            try:
                interpreter.set_tensor(input_details[0]['index'], model_input_data)
                interpreter.invoke()
                output_data = interpreter.get_tensor(output_details[0]['index'])
                prediction_probability_fall = output_data[0][0] # Raw probability 0.0 - 1.0

                if prediction_probability_fall >= FALL_CONFIDENCE_THRESHOLD:
                    prediction_label_for_alert = "fall"
                    display_confidence_value = prediction_probability_fall # For screen display (0.0-1.0)
                else:
                    prediction_label_for_alert = "no_fall"
                    display_confidence_value = 1.0 - prediction_probability_fall # For screen display (0.0-1.0)

                current_status_text_for_log = f"Status: {prediction_label_for_alert.upper()} (Conf: {display_confidence_value:.2f})"

                if prediction_label_for_alert == "fall":
                    current_time_event = time.time()
                    if (current_time_event - last_fall_event_time) > FALL_EVENT_COOLDOWN:
                        confidence_percentage_str = f"{prediction_probability_fall * 100:.2f}%"
                        fall_message = f"🚨 FALL DETECTED! Confidence: {confidence_percentage_str}"

                        # Debug print (uncomment to use for debugging the 0.91 issue)
                        print(f"DEBUG_TELEGRAM: Raw P(Fall)={prediction_probability_fall:.4f}, DisplayConfOnScreen={display_confidence_value:.2f}, AlertConfToTelegram={confidence_percentage_str}")

                        log_message(fall_message)
                        send_telegram_message(fall_message)
                        send_mqtt_alert(prediction_probability_fall, confidence_percentage_str)
                        last_fall_event_time = current_time_event
            except Exception as e:
                log_message(f"Error during model prediction: {e}")
                current_status_text_for_log = "Status: Prediction Error"

    # 5. Draw Landmarks (if any) on processed_frame_display (BGR)
    if results.pose_landmarks:
        temp_rgb_to_draw_landmarks = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).copy()
        mp.solutions.drawing_utils.draw_landmarks(
            temp_rgb_to_draw_landmarks,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=mp.solutions.drawing_styles.get_default_pose_landmarks_style()
        )
        processed_frame_display = cv2.cvtColor(temp_rgb_to_draw_landmarks, cv2.COLOR_RGB2BGR)

    # 6. Draw Text on processed_frame_display (BGR) - right side
    font_face = cv2.FONT_HERSHEY_DUPLEX
    font_scale_status = 0.6
    thickness_status = 1
    font_scale_alert = 1.0
    thickness_alert = 2
    padding = 30

    # Text for screen display (uses display_confidence_value, e.g., "FALL (Conf: 0.92)")
    text_to_show_on_frame = f"{prediction_label_for_alert.upper()} (Conf: {display_confidence_value:.2f})"
    if "Collecting" in current_status_text_for_log or "Error" in current_status_text_for_log:
         text_to_show_on_frame = current_status_text_for_log.replace("Status: ", "")

    (text_w, text_h), _ = cv2.getTextSize(text_to_show_on_frame, font_face, font_scale_status, thickness_status)
    text_x_status = processed_frame_display.shape[1] - text_w - padding
    text_y_status = padding + text_h

    status_color_bgr = (255, 255, 255) # Default White for NO_FALL
    if "Error" in text_to_show_on_frame:
        status_color_bgr = (0,0,255) # Red for Error
    elif "Collecting" in text_to_show_on_frame :
        status_color_bgr = (255,255,0) # Cyan for Collecting
    elif prediction_label_for_alert == "fall":
         status_color_bgr = (0, 165, 255) # Orange for FALL status

    cv2.putText(processed_frame_display, text_to_show_on_frame, (text_x_status, text_y_status), font_face, font_scale_status, status_color_bgr, thickness_status, cv2.LINE_AA)

    if prediction_label_for_alert == "fall" and \
       last_fall_event_time != 0 and \
       (time.time() - last_fall_event_time < FALL_EVENT_COOLDOWN):
        alert_text = "FALL DETECTED!"
        (alert_w, alert_h), _ = cv2.getTextSize(alert_text, font_face, font_scale_alert, thickness_alert)
        alert_x_pos = processed_frame_display.shape[1] - alert_w - padding
        alert_y_pos = text_y_status + alert_h + padding // 2
        cv2.putText(processed_frame_display, alert_text, (alert_x_pos, alert_y_pos), font_face, font_scale_alert, (0, 0, 255), thickness_alert, cv2.LINE_AA) # Red

    return processed_frame_display


# --- Main Function ---
def main(source_type, file_path=None, no_display=False, camera_id=0):
    log_message("Starting Fall Detection System...")
    active_camera_id = camera_id if camera_id is not None else CAMERA_INDEX
    if source_type == "webcam":
        cap = cv2.VideoCapture(active_camera_id)
        if not cap.isOpened():
            log_message(f"Error: Cannot open webcam {active_camera_id}")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    elif source_type == "file":
        if file_path and not os.path.exists(file_path):
            sample_path = os.path.join(os.path.dirname(__file__), "sample_videos", os.path.basename(file_path))
            if os.path.exists(sample_path):
                file_path = sample_path
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            log_message(f"Error: Cannot open video file {file_path}")
            return
    else: # Should not happen due to argparse choices
        log_message(f"Error: Invalid source type '{source_type}'")
        return


    with mp_pose.Pose(
            static_image_mode=use_static_image_mode,
            model_complexity=pose_complexity,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5) as pose:

        frame_counter = 0
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                if source_type == "file": log_message("End of video file.")
                else: log_message("Failed to grab frame from webcam.")
                break

            frame_counter += 1

            processed_frame = process_frame(frame, pose)
            if not no_display:
                cv2.imshow(DISPLAY_WINDOW_NAME, processed_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    log_message("Exiting program...")
                    break

    cap.release()
    if not no_display:
        cv2.destroyAllWindows()
    log_message("Fall Detection System Stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time Fall Detection System")
    parser.add_argument("--source", type=str, default="webcam", choices=["webcam", "file"],
                        help="Input source: 'webcam' or 'file'")
    parser.add_argument("--file", type=str, default=None,
                        help="Path to the video file if source is 'file'")
    parser.add_argument("--no-display", action="store_true",
                        help="Run in headless mode without GUI window (ideal for Raspberry Pi via SSH)")
    parser.add_argument("--camera-id", type=int, default=0,
                        help="Webcam/Camera device index (default: 0)")
    args = parser.parse_args()
    if args.source == "file" and not args.file:
        parser.error("--file argument is required when source is 'file'")
    main(source_type=args.source, file_path=args.file, no_display=args.no_display, camera_id=args.camera_id)