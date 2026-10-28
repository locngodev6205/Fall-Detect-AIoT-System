"""
Package modules chứa các thành phần cốt lõi của hệ thống nhận diện té ngã:
- skeleton: Trích xuất tọa độ 17 khớp xương MediaPipe và chuẩn hóa không gian.
- detector: Quản lý nạp mô hình TFLite, cửa sổ trượt 30 frames, suy luận té ngã & theo dõi bất động.
- notifier: Hệ thống ghi log và gửi cảnh báo thời gian thực qua MQTT và Telegram.
- visualizer: Vẽ khung xương và giao diện hiển thị trạng thái cảnh báo trên khung hình.
"""

from .skeleton import (
    extract_and_normalize_features,
    normalize_skeleton_frame,
    get_kpt_indices_training_order,
    KEYPOINT_DICT_TRAINING,
    SORTED_YOUR_KEYPOINT_NAMES,
    NUM_KEYPOINTS_TRAINING,
    NUM_FEATURES
)
from .notifier import Notifier
from .detector import FallDetector, DetectionResult
from .visualizer import Visualizer

__all__ = [
    'extract_and_normalize_features',
    'normalize_skeleton_frame',
    'get_kpt_indices_training_order',
    'KEYPOINT_DICT_TRAINING',
    'SORTED_YOUR_KEYPOINT_NAMES',
    'NUM_KEYPOINTS_TRAINING',
    'NUM_FEATURES',
    'Notifier',
    'FallDetector',
    'DetectionResult',
    'Visualizer'
]
