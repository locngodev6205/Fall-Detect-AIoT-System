#!/usr/bin/env python3
"""Trình khởi chạy hợp nhất Thiết bị biên Raspberry Pi 4 — Hệ thống AnNhà AIoT.

Hợp nhất 5 phân hệ chạy đa luồng (Hardware-First + Auto-Fallback Mock khi chạy trên PC):
  1. **Camera AI & Live Stream**: Thu hình OpenCV + MediaPipe Pose + TFLite Transformer (`FallDetector`),
     tự động chuyển sang bộ tạo khung hình HUD trực tiếp bằng Pillow nếu chạy trên PC chưa cài camera/AI.
     Truyền JPEG thời gian thực lên Web qua `/ws/device/frames` và gửi snapshot định kỳ.
  2. **Arduino USB Serial Bridge**: Đọc cảm biến `DHT11` (D2) + `MQ-2` (A0) mỗi 2s và điều khiển mượt
     2 động cơ Servo Pan (D9, 30°–150°) & Tilt (D10, 45°–135°).
  3. **AI Pose Pan-Tilt Tracking & Web PTZ**: Tự động xoay camera bám theo tâm cơ thể người; hỗ trợ
     nút xoay D-Pad từ Web (`ptz_move`, `ptz_center`) và ngắt xung PWM khi tắt Tracking / Chế độ ban đêm.
  4. **Loa Bluetooth Chuyên dụng & Còi Khẩn cấp Tại chỗ**: Hú còi 100% âm lượng ngay tại phòng khi phát hiện
     Té ngã hoặc Khí gas vượt ngưỡng (`gas >= gas_high`), hoạt động độc lập cả khi mất mạng Internet.
  5. **Lịch nhắc Offline & Chế độ Ban đêm (`22:00–06:00`)**: Phát lời nhắc từ cache cục bộ, tự tạm hoãn
     lời nhắc sinh hoạt thường vào ban đêm nhưng giữ nguyên 100% cảnh báo khẩn cấp.

Cách chạy:
  $ cd Fall-Detect-AIoT-System/fall_detect
  $ python3 -m edge.main_edge --env-file .env.edge
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
import io
import logging
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any
import warnings

# Tắt cảnh báo cú pháp cũ không cần thiết của google.protobuf khi chạy với MediaPipe
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf")
warnings.filterwarnings("ignore", message=".*SymbolDatabase.GetPrototype.*")

FALL_DETECT_DIR = Path(__file__).resolve().parents[1]
if str(FALL_DETECT_DIR) not in sys.path:
    sys.path.insert(0, str(FALL_DETECT_DIR))

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

try:
    import cv2  # type: ignore[import-not-found]
except ImportError:
    cv2 = None  # type: ignore[assignment]

try:
    import mediapipe as mp  # type: ignore[import-not-found]
except ImportError:
    mp = None  # type: ignore[assignment]

from edge.audio.audio_player import AudioPlayer  # noqa: E402
from edge.audio.bluetooth_manager import BluetoothSpeakerManager  # noqa: E402
from edge.audio.scheduler import ReminderScheduler  # noqa: E402
from edge.client.device_client import DeviceClient  # noqa: E402
from edge.client.live_streamer import LiveStreamer  # noqa: E402
from edge.pairing import pair_device  # noqa: E402
from edge.sensors.arduino_bridge import ArduinoBridge  # noqa: E402
from edge.tracking.pan_tilt_tracker import PanTiltTracker  # noqa: E402

logger = logging.getLogger("annha.edge")


def load_env_file(path: Path) -> dict[str, str]:
    """Đọc file `.env.edge` nhẹ nhàng không cần phụ thuộc bắt buộc vào `python-dotenv`."""
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        loaded[key] = val
        if key not in os.environ:
            os.environ[key] = val
    return loaded


def render_synthetic_hud_jpeg(
    *,
    width: int = 640,
    height: int = 360,
    person_cx: float = 0.5,
    person_cy: float = 0.52,
    servo_pan: int = 90,
    servo_tilt: int = 90,
    temp_c: float | None = 28.5,
    hum_pct: float | None = 65.0,
    gas_val: float | None = 185.0,
    fall_enabled: bool = True,
    tracking_status: str = "active",
) -> bytes:
    """ Vẽ khung hình JPEG trực quan (HUD) khi chạy chế độ giả lập không có Webcam/OpenCV."""
    if Image is None or ImageDraw is None:
        return b""
    img = Image.new("RGB", (width, height), (20, 44, 52))
    draw = ImageDraw.Draw(img)

    # Nền lưới phòng trực quan
    for x in range(0, width, 64):
        draw.line([(x, 0), (x, height)], fill=(29, 59, 69), width=1)
    for y in range(0, height, 60):
        draw.line([(0, y), (width, y)], fill=(29, 59, 69), width=1)

    # Khung vùng chết trung tâm (Deadzone)
    dz_w, dz_h = int(width * 0.08), int(height * 0.08)
    cx_mid, cy_mid = width // 2, height // 2
    draw.rectangle(
        [cx_mid - dz_w, cy_mid - dz_h, cx_mid + dz_w, cy_mid + dz_h],
        outline=(45, 130, 122),
        width=1,
    )

    # Vẽ hình đại diện người di chuyển trong phòng
    px = int(person_cx * width)
    py = int(person_cy * height)
    head_r = 16
    draw.ellipse([px - head_r, py - 58 - head_r, px + head_r, py - 58 + head_r], outline=(117, 229, 164), width=3)
    draw.rounded_rectangle([px - 22, py - 38, px + 22, py + 28], radius=8, outline=(117, 229, 164), width=3)
    draw.line([(px - 12, py + 28), (px - 16, py + 76)], fill=(117, 229, 164), width=3)
    draw.line([(px + 12, py + 28), (px + 16, py + 76)], fill=(117, 229, 164), width=3)

    # Thanh thông tin HUD trên cùng
    draw.rectangle([0, 0, width, 34], fill=(12, 28, 34))
    ts_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    hud_top = (
        f"AnNha Pi4 Edge | {ts_str} | Pan:{servo_pan}d Tilt:{servo_tilt}d | "
        f"AI:{'ON' if fall_enabled else 'OFF'} Track:{tracking_status}"
    )
    draw.text((12, 10), hud_top, fill=(224, 245, 241))

    # Thanh cảm biến môi trường dưới cùng
    draw.rectangle([0, height - 32, width, height], fill=(12, 28, 34))
    t_txt = f"{temp_c:.1f}C" if temp_c is not None else "--"
    h_txt = f"{hum_pct:.0f}%" if hum_pct is not None else "--"
    g_txt = f"{gas_val:.0f} ADC" if gas_val is not None else "--"
    draw.text(
        (12, height - 22),
        f"DHT11 Temp: {t_txt}  |  Humidity: {h_txt}  |  MQ-2 Gas: {g_txt}",
        fill=(148, 226, 213),
    )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=78)
    return buf.getvalue()


class AnNhaEdgeRuntime:
    """Bộ điều phối hợp nhất toàn bộ phần cứng & kết nối thời gian thực trên Pi 4."""

    def __init__(
        self,
        *,
        base_url: str,
        device_token: str,
        serial_port: str | None = None,
        baudrate: int = 115200,
        pan_direction: int = -1,
        tilt_direction: int = 1,
        gas_unit: str = "ADC",
        bt_speaker_mac: str = "",
        bt_speaker_name: str = "",
        camera_id: int = 0,
        live_fps: float = 5.0,
        heartbeat_interval_s: float = 10.0,
        telemetry_interval_s: float = 10.0,
        command_poll_interval_s: float = 2.0,
        snapshot_interval_s: float = 30.0,
        thingsboard_enabled: bool = False,
        tb_host: str = "127.0.0.1",
        tb_port: int = 1883,
        tb_token: str = "",
        cache_dir: Path | None = None,
        force_mock_hardware: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_token = device_token.strip()
        self.camera_id = int(camera_id)
        self.heartbeat_interval_s = max(3.0, float(heartbeat_interval_s))
        self.telemetry_interval_s = max(3.0, float(telemetry_interval_s))
        self.command_poll_interval_s = max(0.5, float(command_poll_interval_s))
        self.snapshot_interval_s = max(5.0, float(snapshot_interval_s))
        if cache_dir is None:
            cache_dir = FALL_DETECT_DIR / "edge_cache"
            if self.device_token:
                # Configuration versions and reminder history belong to one pairing.
                identity = hashlib.sha256(
                    f"{self.base_url}\n{self.device_token}".encode()
                ).hexdigest()
                cache_dir = cache_dir / identity
        self.cache_dir = cache_dir
        self.force_mock_hardware = bool(force_mock_hardware)

        port_arg = None if (not serial_port or serial_port.lower() == "auto") else serial_port
        self.bridge = ArduinoBridge(
            port=port_arg,
            baudrate=baudrate,
            pan_direction=pan_direction,
            tilt_direction=tilt_direction,
            gas_unit=gas_unit,
            force_mock=force_mock_hardware,
        )
        self.tracker = PanTiltTracker(bridge=self.bridge)
        self.bt = BluetoothSpeakerManager(
            speaker_mac=bt_speaker_mac,
            speaker_name=bt_speaker_name,
            force_mock=True if force_mock_hardware else None,
        )
        self.audio = AudioPlayer(self.bt, cache_dir=self.cache_dir / "audio")

        self.client = DeviceClient(
            base_url=self.base_url,
            device_token=self.device_token,
            cache_dir=self.cache_dir,
            thingsboard_enabled=thingsboard_enabled,
            tb_host=tb_host,
            tb_port=tb_port,
            tb_token=tb_token,
        )
        self.scheduler = ReminderScheduler(
            self.audio,
            cache_dir=self.cache_dir,
            asset_resolver=self.client.ensure_asset_cached,
            execution_reporter=self.client.report_execution,
        )
        self.streamer = LiveStreamer(
            base_url=self.base_url,
            device_token=self.device_token,
            fps_limit=live_fps,
            on_ptt_audio_file=self._handle_ptt_file,
        )

        self._env_thresholds: dict[str, Any] = {
            "gas_high": 450.0,
            "temperature_high": 38.0,
            "temperature_low": 15.0,
        }
        self._observation: str = "clear"
        self._camera_ok: bool = True
        self._stop_event = threading.Event()
        self._workers: list[threading.Thread] = []

        self.client.on_config_updated(self._on_config_updated)
        self.client.set_command_handler(self._on_web_command)

    def _on_config_updated(self, cfg: dict[str, Any]) -> None:
        self.tracker.update_smart_modes(cfg.get("smart_modes"))
        self.scheduler.apply_config(cfg)
        env = cfg.get("environment")
        if isinstance(env, dict):
            self._env_thresholds.update(env)

    def _on_web_command(self, cmd: dict[str, Any]) -> tuple[bool, str]:
        kind = str(cmd.get("kind") or "")
        if kind in ("ptz_move", "ptz_center"):
            return self.tracker.execute_ptz_command(cmd)
        if kind in ("play_audio", "test_speaker", "silence"):
            return self.audio.execute_audio_command(cmd, asset_resolver=self.client.ensure_asset_cached)
        if kind in ("bt_scan", "bt_connect", "bt_disconnect"):
            return self._execute_bluetooth_command(cmd)
        return False, f"Không hỗ trợ loại lệnh: {kind!r}"

    def _execute_bluetooth_command(self, cmd: dict[str, Any]) -> tuple[bool, str]:
        kind = str(cmd.get("kind") or "")
        payload = cmd.get("payload") or {}
        if kind == "bt_scan":
            devices = self.bt.scan_devices(duration_s=4.5)
            report = self.bt.get_bluetooth_report(devices_override=devices)
            self.client.send_bluetooth_state(report)
            return True, f"Đã quét tìm thấy {len(devices)} thiết bị Bluetooth"
        if kind == "bt_connect":
            addr = str(payload.get("bt_address") or "").strip()
            name = str(payload.get("bt_name") or "").strip()
            if not addr:
                return False, "Thiếu địa chỉ MAC của thiết bị Bluetooth"
            res = self.bt.connect_device(addr, name)
            report = self.bt.get_bluetooth_report()
            self.client.send_bluetooth_state(report)
            if res.get("connected"):
                dev_label = res.get("deviceName") or name or addr
                return True, f"Đã kết nối loa Bluetooth: {dev_label} ({addr})"
            return False, str(res.get("error") or f"Không thể kết nối tới {name or addr}")
        if kind == "bt_disconnect":
            addr = str(payload.get("bt_address") or "").strip()
            self.bt.disconnect_device(addr)
            report = self.bt.get_bluetooth_report()
            self.client.send_bluetooth_state(report)
            return True, "Đã ngắt kết nối loa Bluetooth"
        return False, f"Lệnh Bluetooth không hợp lệ: {kind!r}"

    def _handle_ptt_file(self, path: Path, _mime: str) -> None:
        self.audio.play_file(
            path,
            volume=85,
            priority=1,
            label="push_to_talk",
            cleanup_after_play=True,
        )

    def _evaluate_local_autonomous_safety(self, readings: dict[str, dict[str, Any]]) -> None:
        """Kiểm tra ngưỡng khí gas độc lập ngay tại biên mỗi 1.5s — hú còi tại chỗ kể cả khi rớt mạng!"""
        gas_info = readings.get("gas") or {}
        if gas_info.get("quality") == "valid" and gas_info.get("value") is not None:
            gas_val = float(gas_info["value"])
            gas_high = float(self._env_thresholds.get("gas_high") or 450.0)
            if gas_val >= gas_high:
                logger.critical("[LocalSafety] CẢNH BÁO RÒ RỈ KHÍ GAS: %.1f >= %.1f!", gas_val, gas_high)
                siren_ok, _ = self.audio.trigger_emergency_siren(
                    "gas",
                    "Cảnh báo khẩn cấp! Phát hiện nồng độ khí gas vượt ngưỡng an toàn!",
                )
                if siren_ok and self.device_token:
                    now_m = time.monotonic()
                    last_ev = getattr(self, "_last_gas_event_ts", -1e9)
                    if now_m - last_ev >= 60.0:
                        self._last_gas_event_ts = now_m
                        self.client.send_event(
                            kind="environment",
                            severity="critical",
                            observation="abnormal",
                            reason=f"Nồng độ khí gas vượt ngưỡng nguy hiểm ({gas_val:.0f} >= {gas_high:.0f}).",
                        )

    def handle_fall_detected(self, confidence: float, reason: str, jpeg_evidence: bytes | None = None) -> None:
        """Xử lý tức thời khi AI phát hiện té ngã: Hú còi tại phòng trước -> Gửi Event + Ảnh lên Backend."""
        if not self.tracker.is_fall_detection_enabled():
            return
        # 1. Còi báo động tại chỗ NGAY LẬP TỨC (0 độ trễ mạng)
        self.audio.trigger_emergency_siren("fall", "Cảnh báo! Phát hiện người thân có dấu hiệu té ngã!")

        # 2. Đẩy sự kiện & ảnh bằng chứng lên Backend AnNhà (nếu có cấu hình token)
        if not self.device_token:
            return
        ev = self.client.send_event(
            kind="fall",
            severity="critical",
            observation="abnormal",
            reason=reason,
            confidence=confidence,
        )
        if ev and ev.get("id") and jpeg_evidence:
            self.client.upload_evidence(
                jpeg_evidence,
                mime_type="image/jpeg",
                filename="fall_evidence.jpg",
                internal_event_id=str(ev["id"]),
            )

    def _safety_loop(self) -> None:
        """Luồng giám sát an toàn rò rỉ khí gas độc lập hoàn toàn (1.5s), không bị nghẽn bởi I/O mạng hay lệnh âm thanh."""
        while not self._stop_event.is_set():
            try:
                readings = self.bridge.get_telemetry_readings()
                self._evaluate_local_autonomous_safety(readings)
            except Exception as exc:
                logger.debug("[EdgeRuntime] Lỗi chu kỳ an toàn khí gas: %s", exc)
            self._stop_event.wait(1.5)

    def _background_io_loop(self) -> None:
        next_hb = 0.0
        next_tel = 0.0
        next_cmd = 0.0
        next_sched = 0.0
        next_snap = time.monotonic() + 2.0

        while not self._stop_event.is_set():
            now = time.monotonic()
            try:
                # 1. Gửi Telemetry môi trường định kỳ
                if self.device_token and now >= next_tel:
                    readings = self.bridge.get_telemetry_readings()
                    self.client.send_telemetry(readings)
                    next_tel = now + self.telemetry_interval_s

                # 2. Heartbeat & đồng bộ cấu hình
                if self.device_token and now >= next_hb:
                    sensors_ok = bool(self.bridge.is_hardware_connected or self.force_mock_hardware)
                    self.client.send_heartbeat(
                        observation=self._observation,
                        camera_ok=self._camera_ok,
                        speaker_ok=self.bt.is_speaker_ready(),
                        sensors_ok=sensors_ok,
                        bluetooth=self.bt.get_bluetooth_report(),
                    )
                    next_hb = now + self.heartbeat_interval_s

                # 3. Nhận lệnh điều khiển PTZ / Âm thanh từ Web
                if self.device_token and now >= next_cmd:
                    self.client.poll_and_execute_commands()
                    next_cmd = now + self.command_poll_interval_s

                # 4. Kiểm tra lịch nhắc sinh hoạt Offline mỗi 5s
                if now >= next_sched:
                    self.scheduler.evaluate_due()
                    next_sched = now + 5.0

                # 5. Cập nhật ảnh Snapshot đại diện phòng định kỳ
                if self.device_token and now >= next_snap:
                    frame_jpg = self.streamer.get_latest_jpeg()
                    if frame_jpg:
                        self.client.upload_evidence(frame_jpg, filename="room_snapshot.jpg")
                        next_snap = now + self.snapshot_interval_s
                    else:
                        next_snap = now + 2.0
            except Exception as exc:
                logger.warning("[EdgeRuntime] Lỗi chu kỳ nền: %s", exc)

            self._stop_event.wait(0.25)

    def _vision_loop(self) -> None:
        """Luồng thu hình Camera + AI Pose + Pan-Tilt Tracking (tự chuyển sang HUD Mock nếu thiếu Webcam/OpenCV)."""
        use_real_camera = not self.force_mock_hardware and cv2 is not None
        cap = None
        if use_real_camera:
            try:
                cap = cv2.VideoCapture(self.camera_id)
                if not cap.isOpened():
                    cap.release()
                    cap = None
            except Exception:
                cap = None

        if cap is not None:
            w_cam = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h_cam = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            logger.info("[Vision] Mở camera thành công: kích thước nguyên bản %dx%d px (tỷ lệ %.2f:1).", w_cam, h_cam, w_cam / h_cam if h_cam else 1.0)
            if mp is not None:
                logger.info("[Vision] Đang chạy luồng Camera thực + MediaPipe Pose (camera_id=%d).", self.camera_id)
                self._run_opencv_mediapipe_loop(cap)
            else:
                logger.info("[Vision] Đang chạy luồng Camera thực không MediaPipe (Live Stream + Web PTZ).")
                self._run_opencv_stream_loop(cap)
        else:
            logger.info("[Vision] Không phát hiện Webcam -> Tự động chạy bộ tạo hình trực tiếp HUD Mock.")
            self._run_mock_hud_loop()

    def _run_opencv_stream_loop(self, cap: Any) -> None:
        """Thu hình trực tiếp từ USB Webcam khi không dùng MediaPipe (vẫn truyền Live Stream & Web PTZ đầy đủ)."""
        fps_frames = 0
        fps_t0 = time.monotonic()
        current_fps = 0.0
        last_log_ts = time.monotonic()
        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    self._camera_ok = False
                    self._observation = "camera_error"
                    self._stop_event.wait(0.5)
                    continue
                self._camera_ok = True
                self._observation = "clear"

                now_m = time.monotonic()
                fps_frames += 1
                if now_m - fps_t0 >= 1.0:
                    current_fps = fps_frames / (now_m - fps_t0)
                    fps_frames = 0
                    fps_t0 = now_m

                if now_m - last_log_ts >= 2.0:
                    last_log_ts = now_m
                    servo_st = self.bridge.get_servo_state()
                    logger.info("[Vision] 🎥 FPS: %4.1f | Pan=%d° Tilt=%d°", current_fps, int(servo_st.get("pan", 90)), int(servo_st.get("tilt", 90)))

                # Vẽ OSD FPS ở góc dưới bên phải
                h_f, w_f = frame.shape[:2]
                box_w, box_h = 180, 32
                bx1, by1 = max(10, w_f - box_w - 15), max(10, h_f - box_h - 15)
                cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (18, 28, 36), -1)
                cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (0, 230, 150), 1)
                cv2.putText(frame, f"FPS: {current_fps:4.1f}", (bx1 + 14, by1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 180), 1, cv2.LINE_AA)

                ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok_enc:
                    self.streamer.update_frame_jpeg(buf.tobytes())
                self._stop_event.wait(0.18)
        finally:
            cap.release()

    def _run_opencv_mediapipe_loop(self, cap: Any) -> None:
        from modules.detector import FallDetector
        from modules.skeleton import NUM_FEATURES, extract_and_normalize_features, is_person_present
        import config as fd_cfg

        model_path = fd_cfg.MODEL_PATH
        if not os.path.exists(model_path):
            candidate = FALL_DETECT_DIR / "models" / "fall_detection_transformer.tflite"
            if candidate.exists():
                model_path = str(candidate)

        latest_jpg_holder: dict[str, bytes | None] = {"jpg": None}

        def _on_fall(confidence: float = 0.92, **_kw: Any) -> None:
            self.handle_fall_detected(
                confidence=float(confidence),
                reason="Mô hình AI phát hiện chuyển động té ngã trên camera.",
                jpeg_evidence=latest_jpg_holder["jpg"],
            )

        detector = None
        if os.path.exists(model_path):
            try:
                detector = FallDetector(
                    model_path=model_path,
                    input_timesteps=fd_cfg.INPUT_TIMESTEPS,
                    num_features=NUM_FEATURES,
                    confidence_threshold=fd_cfg.FALL_CONFIDENCE_THRESHOLD,
                    event_cooldown=fd_cfg.FALL_EVENT_COOLDOWN,
                    on_fall_alert=_on_fall,
                )
            except Exception as exc:
                logger.warning("[Vision] Không khởi tạo được TFLite FallDetector (%s) -> chỉ chạy Pose Tracking.", exc)

        mp_pose = mp.solutions.pose
        mp_drawing = getattr(mp, "solutions", None) and getattr(mp.solutions, "drawing_utils", None)
        mp_styles = getattr(mp, "solutions", None) and getattr(mp.solutions, "drawing_styles", None)
        fps_frames = 0
        fps_t0 = time.monotonic()
        current_fps = 0.0
        last_log_ts = time.monotonic()

        try:
            with mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,
                smooth_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            ) as pose:
                while not self._stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        self._camera_ok = False
                        self._observation = "camera_error"
                        self._stop_event.wait(0.5)
                        continue

                    self._camera_ok = True
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    rgb.flags.writeable = False
                    pose_res = pose.process(rgb)

                    present = is_person_present(pose_res.pose_landmarks)
                    self._observation = "clear" if present else "no_person"

                    # Tính toán FPS tức thời
                    now_m = time.monotonic()
                    fps_frames += 1
                    if now_m - fps_t0 >= 1.0:
                        current_fps = fps_frames / (now_m - fps_t0)
                        fps_frames = 0
                        fps_t0 = now_m

                    servo_st = self.bridge.get_servo_state()
                    pan_val = int(servo_st.get("pan", 90))
                    tilt_val = int(servo_st.get("tilt", 90))

                    # In log định kỳ mỗi 2 giây lên terminal
                    if now_m - last_log_ts >= 2.0:
                        last_log_ts = now_m
                        logger.info(
                            "[Vision] 🎥 FPS: %4.1f | Người: %s | Servo: Pan=%d° Tilt=%d° | Bám: %s",
                            current_fps,
                            "CÓ NGƯỜI" if present else "TRỐNG",
                            pan_val,
                            tilt_val,
                            self.tracker.tracking_status(),
                        )

                    # Luôn gọi update_from_pose kể cả khi không có người để ngắt xung PWM khi tắt Tracking / giờ đêm
                    try:
                        self.tracker.update_from_pose(pose_res if present else None)
                    except Exception as exc:
                        logger.warning("[Vision] Lỗi tracking: %s", exc)

                    if detector is not None and self.tracker.is_fall_detection_enabled():
                        try:
                            feats = extract_and_normalize_features(pose_res.pose_landmarks) if present else None
                            detector.update(feats, person_present=present)
                        except Exception as exc:
                            logger.warning("[Vision] Lỗi FallDetector: %s", exc)

                    # 1. Vẽ khung xương MediaPipe lên khung hình khi phát hiện người
                    if present and pose_res.pose_landmarks and mp_drawing and mp_styles:
                        try:
                            mp_drawing.draw_landmarks(
                                frame,
                                pose_res.pose_landmarks,
                                mp_pose.POSE_CONNECTIONS,
                                landmark_drawing_spec=mp_styles.get_default_pose_landmarks_style(),
                            )
                        except Exception:
                            pass

                    # 2. Vẽ OSD hiển thị FPS, trạng thái và góc Servo góc dưới bên phải (vùng tối)
                    osd_text = f"FPS: {current_fps:4.1f} | Pan: {pan_val}d | Tilt: {tilt_val}d"
                    h_f, w_f = frame.shape[:2]
                    box_w, box_h = 320, 32
                    bx1, by1 = max(10, w_f - box_w - 15), max(10, h_f - box_h - 15)
                    cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (18, 28, 36), -1)
                    cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (0, 230, 150), 1)
                    cv2.putText(
                        frame,
                        osd_text,
                        (bx1 + 12, by1 + 22),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 255, 180),
                        1,
                        cv2.LINE_AA,
                    )

                    ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    if ok_enc:
                        jpg_bytes = buf.tobytes()
                        latest_jpg_holder["jpg"] = jpg_bytes
                        self.streamer.update_frame_jpeg(jpg_bytes)
        finally:
            cap.release()

    def _run_mock_hud_loop(self) -> None:
        t0 = time.monotonic()
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - t0
            # Mô phỏng người đi lại nhẹ nhàng trong phòng để kiểm chứng cả Pan-Tilt Tracking & Live Stream
            cx = 0.5 + 0.22 * math.sin(elapsed * 0.45)
            cy = 0.52 + 0.08 * math.cos(elapsed * 0.30)
            self._observation = "clear"
            self.tracker.update_from_pose((cx, cy))

            servo = self.bridge.get_servo_state()
            raw = self.bridge.get_raw_readings() or {}
            jpg = render_synthetic_hud_jpeg(
                person_cx=cx,
                person_cy=cy,
                servo_pan=int(servo.get("pan", 90)),
                servo_tilt=int(servo.get("tilt", 90)),
                temp_c=raw.get("temp"),
                hum_pct=raw.get("hum"),
                gas_val=raw.get("gas"),
                fall_enabled=self.tracker.is_fall_detection_enabled(),
                tracking_status=self.tracker.tracking_status(),
            )
            if jpg:
                self.streamer.update_frame_jpeg(jpg)
            self._stop_event.wait(0.20)

    def start(self) -> "AnNhaEdgeRuntime":
        logger.info("==========================================================")
        logger.info(" KHỞI ĐỘNG ANNHÀ AIoT EDGE NODE -> %s", self.base_url)
        logger.info("==========================================================")
        self.bridge.start()
        self.bridge.center()
        self.bt.start()
        self.client.start()
        if self.device_token:
            self.streamer.start()

        t_safe = threading.Thread(target=self._safety_loop, name="annha-edge-safety", daemon=True)
        t_io = threading.Thread(target=self._background_io_loop, name="annha-edge-io", daemon=True)
        t_vis = threading.Thread(target=self._vision_loop, name="annha-edge-vision", daemon=True)
        t_safe.start()
        t_io.start()
        t_vis.start()
        self._workers = [t_safe, t_io, t_vis]
        return self

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._workers:
            if t.is_alive():
                t.join(timeout=2.0)
        self.streamer.stop()
        self.audio.stop()
        self.bridge.detach()
        self.bridge.stop()
        self.bt.stop()
        self.client.stop()
        logger.info("[EdgeRuntime] Đã dừng toàn bộ các phân hệ an toàn.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AnNhà AIoT — Raspberry Pi 4 Unified Edge Runner")
    parser.add_argument(
        "--env-file",
        default=str(FALL_DETECT_DIR / ".env.edge"),
        help="Đường dẫn tới file cấu hình .env.edge",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Chạy giới hạn N giây rồi tự dừng sạch (0 = chạy liên tục vĩnh viễn)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Ép chạy toàn bộ phần cứng ở chế độ giả lập (Mock) để kiểm thử nhanh trên PC",
    )
    parser.add_argument('--pair', action='store_true', help='Lấy mã ghép nối cho Pi chưa đăng ký')
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    env_path = Path(args.env_file)
    load_env_file(env_path)
    base_url = os.getenv('ANNHA_BASE_URL') or os.getenv('BACKEND_URL')
    token = os.getenv("DEVICE_TOKEN", "").strip()
    pairing_filename = '.env.edge.pairing.json'
    if env_path.name != '.env.edge':
        pairing_filename = f'.env.edge.pairing-{env_path.name}.json'
    pairing_path = env_path.with_name(pairing_filename)
    if not token and (args.pair or pairing_path.exists()):
        if not base_url:
            parser.error('Đặt ANNHA_BASE_URL trước khi ghép nối.')
        try:
            token = pair_device(base_url, pairing_path, start_pairing=args.pair)
        except KeyboardInterrupt:
            return 130
        except (OSError, ValueError, KeyError) as error:
            parser.exit(1, f'Không thể ghép nối Pi: {error}\n')
    if not token:
        logger.warning(
            "Chưa có DEVICE_TOKEN trong %s! Thiết bị sẽ chỉ chạy bảo vệ nội bộ Offline (Còi tại chỗ & Tracking).",
            args.env_file,
        )

    runtime = AnNhaEdgeRuntime(
        base_url=base_url or "http://localhost:8188",
        device_token=token,
        serial_port=os.getenv("ARDUINO_SERIAL_PORT", "auto"),
        baudrate=int(os.getenv("ARDUINO_BAUDRATE", "115200")),
        pan_direction=int(os.getenv("PAN_DIRECTION", "-1")),
        tilt_direction=int(os.getenv("TILT_DIRECTION", "1")),
        gas_unit=os.getenv("GAS_UNIT", "ADC"),
        bt_speaker_mac=os.getenv("BT_SPEAKER_MAC", ""),
        bt_speaker_name=os.getenv("BT_SPEAKER_NAME", ""),
        camera_id=int(os.getenv("CAMERA_ID", "0")),
        live_fps=float(os.getenv("LIVE_STREAM_FPS", "5.0")),
        heartbeat_interval_s=float(os.getenv("HEARTBEAT_INTERVAL_S", "10.0")),
        telemetry_interval_s=float(os.getenv("TELEMETRY_INTERVAL_S", "10.0")),
        command_poll_interval_s=float(os.getenv("COMMAND_POLL_INTERVAL_S", "2.0")),
        snapshot_interval_s=float(os.getenv("SNAPSHOT_INTERVAL_S", "30.0")),
        thingsboard_enabled=os.getenv("THINGSBOARD_ENABLED", "false").lower() == "true",
        tb_host=os.getenv("TB_HOST", "127.0.0.1"),
        tb_port=int(os.getenv("TB_PORT", "1883")),
        tb_token=os.getenv("TB_TOKEN", ""),
        force_mock_hardware=bool(args.mock),
    )

    stop_flag = threading.Event()

    def _sig_handler(*_a: Any) -> None:
        stop_flag.set()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    runtime.start()
    try:
        if args.duration > 0:
            stop_flag.wait(float(args.duration))
        else:
            while not stop_flag.is_set():
                stop_flag.wait(1.0)
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
