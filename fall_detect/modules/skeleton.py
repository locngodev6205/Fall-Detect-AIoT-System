#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: skeleton.py
Mô tả:
  Định nghĩa hệ thống 17 điểm khớp xương MediaPipe BlazePose,
  ánh xạ chỉ số tra cứu và thuật toán chuẩn hóa không gian bất biến (Centroid + Torso Scaling).
"""

import numpy as np
import mediapipe as mp

mp_pose = mp.solutions.pose

# Danh sách 33 khớp chuẩn ban đầu của MediaPipe Pose
KEYPOINT_NAMES_ORIGINAL = [
    'Nose', 'Left Eye Inner', 'Left Eye', 'Left Eye Outer', 'Right Eye Inner', 'Right Eye', 'Right Eye Outer',
    'Left Ear', 'Right Ear', 'Mouth Left', 'Mouth Right',
    'Left Shoulder', 'Right Shoulder', 'Left Elbow', 'Right Elbow', 'Left Wrist', 'Right Wrist',
    'Left Pinky', 'Right Pinky', 'Left Index', 'Right Index', 'Left Thumb', 'Right Thumb',
    'Left Hip', 'Right Hip', 'Left Knee', 'Right Knee', 'Left Ankle', 'Right Ankle',
    'Left Heel', 'Right Heel', 'Left Foot Index', 'Right Foot Index'
]

# Ánh xạ từ enum MediaPipe sang 17 tên khớp dùng cho mô hình
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

# 17 tên khớp cơ thể dùng trong huấn luyện
YOUR_KEYPOINT_NAMES_TRAINING = [
    'Nose', 'Left Eye', 'Right Eye', 'Left Ear', 'Right Ear',
    'Left Shoulder', 'Right Shoulder', 'Left Elbow', 'Right Elbow',
    'Left Wrist', 'Right Wrist', 'Left Hip', 'Right Hip',
    'Left Knee', 'Right Knee', 'Left Ankle', 'Right Ankle'
]

# Sắp xếp theo bảng chữ cái để khớp với thứ tự ma trận feature (training order)
SORTED_YOUR_KEYPOINT_NAMES = sorted(YOUR_KEYPOINT_NAMES_TRAINING)
KEYPOINT_DICT_TRAINING = {name: i for i, name in enumerate(SORTED_YOUR_KEYPOINT_NAMES)}
NUM_KEYPOINTS_TRAINING = len(KEYPOINT_DICT_TRAINING)
NUM_FEATURES = NUM_KEYPOINTS_TRAINING * 3  # 17 * 3 = 51 đặc trưng


def get_kpt_indices_training_order(keypoint_name):
    """
    Trả về chỉ số (x_idx, y_idx, c_idx) của một điểm khớp theo thứ tự sắp xếp của mô hình.
    """
    if keypoint_name not in KEYPOINT_DICT_TRAINING:
        available_keys = list(KEYPOINT_DICT_TRAINING.keys())
        error_msg = f"Keypoint '{keypoint_name}' không tồn tại trong từ điển. Khớp có sẵn: {available_keys}"
        raise ValueError(error_msg)
    kp_idx = KEYPOINT_DICT_TRAINING[keypoint_name]
    return kp_idx * 3, kp_idx * 3 + 1, kp_idx * 3 + 2


def normalize_skeleton_frame(frame_features_sorted, min_confidence=0.3):
    """
    Chuẩn hóa khung xương cho một frame (51 đặc trưng):
    1. Dịch chuyển gốc tọa độ về trung điểm 2 khớp hông (Mid-Hip).
    2. Co giãn tỉ lệ cơ thể theo khoảng cách giữa trung điểm vai và trung điểm hông (Torso Height).
    """
    normalized_frame = np.copy(frame_features_sorted)
    ref_kp_names = {
        'ls': 'Left Shoulder', 'rs': 'Right Shoulder',
        'lh': 'Left Hip',      'rh': 'Right Hip'
    }

    try:
        ls_x_idx, ls_y_idx, ls_c_idx = get_kpt_indices_training_order(ref_kp_names['ls'])
        rs_x_idx, rs_y_idx, rs_c_idx = get_kpt_indices_training_order(ref_kp_names['rs'])
        lh_x_idx, lh_y_idx, lh_c_idx = get_kpt_indices_training_order(ref_kp_names['lh'])
        rh_x_idx, rh_y_idx, rh_c_idx = get_kpt_indices_training_order(ref_kp_names['rh'])
    except ValueError:
        return frame_features_sorted

    ls_x, ls_y, ls_c = frame_features_sorted[ls_x_idx], frame_features_sorted[ls_y_idx], frame_features_sorted[ls_c_idx]
    rs_x, rs_y, rs_c = frame_features_sorted[rs_x_idx], frame_features_sorted[rs_y_idx], frame_features_sorted[rs_c_idx]
    lh_x, lh_y, lh_c = frame_features_sorted[lh_x_idx], frame_features_sorted[lh_y_idx], frame_features_sorted[lh_c_idx]
    rh_x, rh_y, rh_c = frame_features_sorted[rh_x_idx], frame_features_sorted[rh_y_idx], frame_features_sorted[rh_c_idx]

    # Xác định trung điểm vai (Mid-Shoulder)
    mid_shoulder_x, mid_shoulder_y = np.nan, np.nan
    valid_ls, valid_rs = ls_c > min_confidence, rs_c > min_confidence
    if valid_ls and valid_rs:
        mid_shoulder_x, mid_shoulder_y = (ls_x + rs_x) / 2.0, (ls_y + rs_y) / 2.0
    elif valid_ls:
        mid_shoulder_x, mid_shoulder_y = ls_x, ls_y
    elif valid_rs:
        mid_shoulder_x, mid_shoulder_y = rs_x, rs_y

    # Xác định trung điểm hông (Mid-Hip)
    mid_hip_x, mid_hip_y = np.nan, np.nan
    valid_lh, valid_rh = lh_c > min_confidence, rh_c > min_confidence
    if valid_lh and valid_rh:
        mid_hip_x, mid_hip_y = (lh_x + rh_x) / 2.0, (lh_y + rh_y) / 2.0
    elif valid_lh:
        mid_hip_x, mid_hip_y = lh_x, lh_y
    elif valid_rh:
        mid_hip_x, mid_hip_y = rh_x, rh_y

    # Nếu không xác định được hông, giữ nguyên tọa độ gốc
    if np.isnan(mid_hip_x) or np.isnan(mid_hip_y):
        return frame_features_sorted

    # Chiều dài thân người (Torso Height)
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


def extract_and_normalize_features(pose_landmarks, min_confidence=0.3):
    """
    Trích xuất tọa độ 17 khớp từ đối tượng pose_landmarks của MediaPipe,
    sắp xếp đúng thứ tự đặc trưng và thực hiện chuẩn hóa không gian.
    
    Trả về:
        np.ndarray: Vector 51 chiều (17 khớp x 3: x, y, confidence)
    """
    frame_features_sorted = np.zeros(NUM_FEATURES, dtype=np.float32)

    if pose_landmarks:
        landmarks = pose_landmarks.landmark
        for mp_landmark_enum, your_kp_name in MEDIAPIPE_TO_YOUR_KEYPOINTS_MAPPING.items():
            if your_kp_name in KEYPOINT_DICT_TRAINING:
                try:
                    lm = landmarks[mp_landmark_enum.value]
                    x_idx, y_idx, c_idx = get_kpt_indices_training_order(your_kp_name)
                    frame_features_sorted[x_idx] = lm.x
                    frame_features_sorted[y_idx] = lm.y
                    frame_features_sorted[c_idx] = lm.visibility
                except (IndexError, Exception):
                    pass

    return normalize_skeleton_frame(frame_features_sorted, min_confidence=min_confidence)
