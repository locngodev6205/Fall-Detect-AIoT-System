"""Bộ điều khiển Pan-Tilt bám theo người trong khung hình & thực thi PTZ từ Web UI.

Thiết kế:
  - Tính tâm cơ thể `(cx, cy) ∈ [0.0, 1.0]²` trực tiếp từ tọa độ khung ảnh MediaPipe Pose
    (ưu tiên 4 khớp thân người `11, 12, 23, 24`, dự phòng khớp mũi `0`), KHÔNG dùng tọa độ
    đã chuẩn hóa gốc hông `(0, 0)` của bộ phân loại té ngã.
  - Bộ điều khiển tỷ lệ (P-controller) có vùng chết (deadzone), lọc mượt EMA và giới hạn tần số
    gửi lệnh Serial (~5.5 Hz) để phối hợp êm ái với cơ chế bước mượt không chặn trên Arduino.
  - Tuân thủ công tắc thông minh từ Web UI (`servo_tracking`) và Chế độ ban đêm (`night_mode_enabled`,
    khung giờ mặc định `22:00 - 06:00`): tự động gửi lệnh `DETACH` ngắt PWM để triệt tiêu 100% tiếng ồn
    động cơ trong phòng ngủ.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..sensors.arduino_bridge import ArduinoBridge, camera_delta

logger = logging.getLogger(__name__)

TORSO_LANDMARK_INDICES = (11, 12, 23, 24)
FALLBACK_LANDMARK_INDICES = (0, 11, 12)


def _parse_hhmm(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        parts = str(value).strip().split(":")
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
    except (TypeError, ValueError):
        pass
    return fallback


def is_night_mode_active(
    smart_modes: dict[str, Any] | None,
    now_dt: datetime | None = None,
    tz_name: str = "Asia/Ho_Chi_Minh",
) -> bool:
    """Kiểm tra hiện tại có đang nằm trong khung giờ Chế độ ban đêm hay không."""
    modes = smart_modes or {}
    if not bool(modes.get("night_mode_enabled", True)):
        return False

    start_h, start_m = _parse_hhmm(modes.get("night_start", "22:00"), (22, 0))
    end_h, end_m = _parse_hhmm(modes.get("night_end", "06:00"), (6, 0))
    start_mins = start_h * 60 + start_m
    end_mins = end_h * 60 + end_m
    if start_mins == end_mins:
        return False

    if now_dt is None:
        try:
            now_dt = datetime.now(ZoneInfo(tz_name))
        except Exception:
            now_dt = datetime.now().astimezone()
    elif now_dt.tzinfo is not None and tz_name:
        try:
            now_dt = now_dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass

    cur_mins = now_dt.hour * 60 + now_dt.minute
    if start_mins < end_mins:
        return start_mins <= cur_mins < end_mins
    # Khung giờ qua nửa đêm (ví dụ 22:00 -> 06:00)
    return cur_mins >= start_mins or cur_mins < end_mins


def extract_person_center(
    pose_or_point: Any,
    min_visibility: float = 0.4,
) -> tuple[float, float] | None:
    """Trích xuất tâm người chuẩn hóa `(cx, cy)` trong hệ tọa độ ảnh `[0.0, 1.0]²`.

    Hỗ trợ cả:
      1. Đối tượng `pose_results` từ `mp.solutions.pose` (`pose_landmarks.landmark`).
      2. Tuple/dict tọa độ `(cx, cy)` truyền trực tiếp (phục vụ camera mô phỏng / kiểm thử).
    """
    if pose_or_point is None:
        return None

    if isinstance(pose_or_point, (tuple, list)) and len(pose_or_point) >= 2:
        try:
            cx, cy = float(pose_or_point[0]), float(pose_or_point[1])
            return max(0.0, min(1.0, cx)), max(0.0, min(1.0, cy))
        except (TypeError, ValueError):
            return None

    if isinstance(pose_or_point, dict) and "cx" in pose_or_point and "cy" in pose_or_point:
        try:
            cx, cy = float(pose_or_point["cx"]), float(pose_or_point["cy"])
            return max(0.0, min(1.0, cx)), max(0.0, min(1.0, cy))
        except (TypeError, ValueError):
            return None

    landmarks_container = getattr(pose_or_point, "pose_landmarks", pose_or_point)
    landmarks = getattr(landmarks_container, "landmark", None)
    if not landmarks:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for idx in TORSO_LANDMARK_INDICES:
        if idx < len(landmarks):
            lm = landmarks[idx]
            vis = float(getattr(lm, "visibility", 1.0))
            if vis >= min_visibility:
                xs.append(float(lm.x))
                ys.append(float(lm.y))

    if len(xs) < 2:
        xs.clear()
        ys.clear()
        for idx in FALLBACK_LANDMARK_INDICES:
            if idx < len(landmarks):
                lm = landmarks[idx]
                vis = float(getattr(lm, "visibility", 1.0))
                if vis >= min_visibility * 0.75:
                    xs.append(float(lm.x))
                    ys.append(float(lm.y))

    if not xs:
        return None

    cx = max(0.0, min(1.0, sum(xs) / len(xs)))
    cy = max(0.0, min(1.0, sum(ys) / len(ys)))
    return cx, cy


class PanTiltTracker:
    """Bộ điều khiển bám đối tượng tự động kết hợp xử lý lệnh PTZ thủ công từ Web."""

    def __init__(
        self,
        bridge: ArduinoBridge,
        deadzone_x: float = 0.08,
        deadzone_y: float = 0.08,
        kp_pan: float = 16.0,
        kp_tilt: float = 12.0,
        max_step_deg: int = 8,
        min_interval_s: float = 0.18,
        ema_alpha: float = 0.45,
        manual_override_hold_s: float = 4.0,
        timezone_name: str = "Asia/Ho_Chi_Minh",
    ) -> None:
        self.bridge = bridge
        self.deadzone_x = float(deadzone_x)
        self.deadzone_y = float(deadzone_y)
        self.kp_pan = float(kp_pan)
        self.kp_tilt = float(kp_tilt)
        self.max_step_deg = max(1, int(max_step_deg))
        self.min_interval_s = max(0.05, float(min_interval_s))
        self.ema_alpha = max(0.05, min(1.0, float(ema_alpha)))
        self.manual_override_hold_s = max(0.0, float(manual_override_hold_s))
        self.timezone_name = timezone_name

        self._lock = threading.Lock()
        self._smart_modes: dict[str, Any] = {
            "fall_detection": True,
            "servo_tracking": True,
            "night_mode_enabled": True,
            "night_start": "22:00",
            "night_end": "06:00",
        }
        self._ema_cx: float | None = None
        self._ema_cy: float | None = None
        self._last_step_ts: float = 0.0
        self._manual_hold_until: float = 0.0
        self._detached_by_policy: bool = False

    def update_smart_modes(self, smart_modes: dict[str, Any] | None, now_dt: datetime | None = None) -> dict[str, Any]:
        """Cập nhật chế độ thông minh từ cấu hình đồng bộ `/api/device/config`."""
        with self._lock:
            if isinstance(smart_modes, dict):
                self._smart_modes.update(smart_modes)
            current = dict(self._smart_modes)

        # Nếu vừa tắt Servo Tracking hoặc đang trong khung giờ ban đêm -> ngắt PWM ngay lập tức
        if not current.get("servo_tracking", True) or is_night_mode_active(current, now_dt=now_dt, tz_name=self.timezone_name):
            self._ensure_detached()
        else:
            with self._lock:
                self._detached_by_policy = False
        return current

    def get_smart_modes(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._smart_modes)

    def is_fall_detection_enabled(self) -> bool:
        with self._lock:
            return bool(self._smart_modes.get("fall_detection", True))

    def is_night_mode(self, now_dt: datetime | None = None) -> bool:
        with self._lock:
            modes = dict(self._smart_modes)
        return is_night_mode_active(modes, now_dt=now_dt, tz_name=self.timezone_name)

    def tracking_status(self, now_dt: datetime | None = None, now_monotonic: float | None = None) -> str:
        """Trả về trạng thái hiện tại của bộ bám: `manual_hold` | `disabled` | `night_mode` | `active`."""
        mono = time.monotonic() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            modes = dict(self._smart_modes)
            hold_until = self._manual_hold_until
        if mono < hold_until:
            return "manual_hold"
        if not bool(modes.get("servo_tracking", True)):
            return "disabled"
        if is_night_mode_active(modes, now_dt=now_dt, tz_name=self.timezone_name):
            return "night_mode"
        return "active"

    def _ensure_detached(self) -> None:
        with self._lock:
            already = self._detached_by_policy
            self._detached_by_policy = True
            self._ema_cx = None
            self._ema_cy = None
        if not already or bool(self.bridge.get_servo_state().get("enabled", False)):
            self.bridge.detach()

    def update_from_pose(
        self,
        pose_or_point: Any,
        now_dt: datetime | None = None,
        now_monotonic: float | None = None,
    ) -> dict[str, Any]:
        """Cập nhật góc quay Servo tự động dựa trên vị trí người trong khung hình."""
        mono = time.monotonic() if now_monotonic is None else float(now_monotonic)
        status = self.tracking_status(now_dt=now_dt, now_monotonic=mono)
        if status == "manual_hold":
            return {"moved": False, "reason": "manual_hold", "servo": self.bridge.get_servo_state()}
        if status in ("disabled", "night_mode"):
            self._ensure_detached()
            return {"moved": False, "reason": status, "servo": self.bridge.get_servo_state()}

        center = extract_person_center(pose_or_point)
        if center is None:
            with self._lock:
                self._ema_cx = None
                self._ema_cy = None
            return {"moved": False, "reason": "no_person", "servo": self.bridge.get_servo_state()}

        raw_cx, raw_cy = center
        with self._lock:
            if self._ema_cx is None or self._ema_cy is None:
                cx, cy = raw_cx, raw_cy
            else:
                cx = self.ema_alpha * raw_cx + (1.0 - self.ema_alpha) * self._ema_cx
                cy = self.ema_alpha * raw_cy + (1.0 - self.ema_alpha) * self._ema_cy
            self._ema_cx, self._ema_cy = cx, cy

            if mono - self._last_step_ts < self.min_interval_s:
                return {
                    "moved": False,
                    "reason": "rate_limited",
                    "center": (cx, cy),
                    "servo": self.bridge.get_servo_state(),
                }

        err_x = cx - 0.5
        err_y = cy - 0.5

        d_pan = 0
        d_tilt = 0

        if abs(err_x) > self.deadzone_x:
            step_x = max(1, min(self.max_step_deg, int(round(abs(err_x) * self.kp_pan))))
            horiz_dir = "RIGHT" if err_x > 0 else "LEFT"
            dp, _ = camera_delta(horiz_dir, step_x, self.bridge.pan_direction, self.bridge.tilt_direction)
            d_pan += dp

        if abs(err_y) > self.deadzone_y:
            step_y = max(1, min(self.max_step_deg, int(round(abs(err_y) * self.kp_tilt))))
            vert_dir = "DOWN" if err_y > 0 else "UP"
            _, dt = camera_delta(vert_dir, step_y, self.bridge.pan_direction, self.bridge.tilt_direction)
            d_tilt += dt

        if d_pan == 0 and d_tilt == 0:
            return {
                "moved": False,
                "reason": "in_deadzone",
                "center": (cx, cy),
                "servo": self.bridge.get_servo_state(),
            }

        with self._lock:
            self._last_step_ts = mono
            self._detached_by_policy = False

        try:
            state = self.bridge.move_relative(d_pan, d_tilt)
        except Exception as exc:
            logger.warning("[PanTiltTracker] Lỗi di chuyển servo: %s", exc)
            state = self.bridge.get_servo_state()
        return {
            "moved": True,
            "reason": "tracking",
            "center": (cx, cy),
            "delta": (d_pan, d_tilt),
            "servo": state,
        }

    def execute_ptz_command(
        self,
        command: dict[str, Any],
        now_dt: datetime | None = None,
    ) -> tuple[bool, str]:
        """Thực thi lệnh điều khiển PTZ thủ công (`ptz_move` / `ptz_center`) từ Web UI.

        Trả về `(success, detail)` để gửi ACK về `/api/device/commands/{id}/ack`.
        """
        kind = command.get("kind")
        payload = command.get("payload") or {}

        # Khi người dùng chủ động bấm nút xoay trên Web, giữ thời gian manual_hold để Arduino hoàn tất bước quay mượt
        with self._lock:
            self._manual_hold_until = time.monotonic() + self.manual_override_hold_s
            self._detached_by_policy = False

        if kind == "ptz_center":
            state = self.bridge.center()
            return True, f"Đã đưa camera về chính giữa (Pan={state['pan']}°, Tilt={state['tilt']}°)."

        if kind == "ptz_move":
            direction = str(payload.get("direction") or "").upper().strip()
            if direction not in ("LEFT", "RIGHT", "UP", "DOWN"):
                return False, f"Hướng xoay PTZ không hợp lệ: {direction!r}"
            try:
                degrees = max(1, min(45, int(payload.get("degrees") or 6)))
            except (TypeError, ValueError):
                degrees = 6
            state = self.bridge.move_camera(direction, degrees)
            return (
                True,
                f"Đã xoay camera {direction} {degrees}° (Pan={state['pan']}°, Tilt={state['tilt']}°).",
            )

        return False, f"Loại lệnh PTZ không hỗ trợ: {kind!r}"
