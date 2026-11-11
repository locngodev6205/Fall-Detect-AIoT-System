"""Cầu nối USB Serial giữa Raspberry Pi 4 và Arduino (Cảm biến DHT11/MQ-2 + 2 Servo Pan-Tilt).

Đặc điểm thiết kế:
  - Hardware-First + Auto-Fallback sang MockArduinoDevice khi chạy trên PC hoặc chưa cắm cáp USB.
  - Hỗ trợ đồng thời đọc dòng JSON (`{"temp":28.5,"hum":65,"gas":180}`) và dự phòng CSV (`28.5,65,180`).
  - Bảo toàn quy ước chiều cơ khí từ CameraPanTilt (`PAN_DIRECTION=-1`, `TILT_DIRECTION=1`).
  - Thread-safe tuyệt đối cho phép luồng AI Tracking, luồng Web PTZ và luồng Telemetry chạy song song.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import queue
import re
import threading
import time
from typing import Any

from .mock_sensors import (
    PAN_CENTER,
    PAN_MAX,
    PAN_MIN,
    TILT_CENTER,
    TILT_MAX,
    TILT_MIN,
    MockArduinoDevice,
)

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # pragma: no cover - fallback khi chưa cài pyserial
    serial = None  # type: ignore[assignment]

logger = logging.getLogger("annha.edge.arduino")

# Quy ước chiều đã hiệu chuẩn trên bộ gá Pan-Tilt thực tế:
# Tăng góc PAN (+) xoay sang TRÁI -> camera sang PHẢI cần delta âm (-1).
# Tăng góc TILT (+) ngửa LÊN -> camera LÊN cần delta dương (+1).
DEFAULT_PAN_DIRECTION = int(os.getenv("PAN_DIRECTION", "-1")) or -1
DEFAULT_TILT_DIRECTION = int(os.getenv("TILT_DIRECTION", "1")) or 1

STATUS_RE = re.compile(
    r"^STATUS PAN=(-?\d+) TILT=(-?\d+) TARGET_PAN=(-?\d+) TARGET_TILT=(-?\d+)"
    r"(?: ENABLED=([01]))? MOVING=([01])$"
)


def camera_delta(
    direction: str,
    degrees: int,
    pan_direction: int = DEFAULT_PAN_DIRECTION,
    tilt_direction: int = DEFAULT_TILT_DIRECTION,
) -> tuple[int, int]:
    """Ánh xạ hướng nhìn vật lý của camera (LEFT/RIGHT/UP/DOWN) sang độ lệch góc Servo."""
    if not isinstance(degrees, int) or isinstance(degrees, bool) or degrees < 0:
        raise ValueError("Số độ dịch chuyển phải là số nguyên không âm.")
    pan_sign = -1 if pan_direction < 0 else 1
    tilt_sign = -1 if tilt_direction < 0 else 1
    mapping = {
        "LEFT": (-pan_sign, 0),
        "RIGHT": (pan_sign, 0),
        "UP": (0, tilt_sign),
        "DOWN": (0, -tilt_sign),
    }
    key = (direction or "").strip().upper()
    if key not in mapping:
        raise ValueError(f"Hướng điều khiển không hợp lệ: {direction!r}")
    dp, dt = mapping[key]
    return dp * degrees, dt * degrees


def _to_optional_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    s = str(val).strip()
    if not s or s.lower() in ("null", "nan", "none", "err", "error"):
        return None
    try:
        f = float(s)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    except ValueError:
        return None


def parse_sensor_line(line: str) -> dict[str, Any] | None:
    """Phân tích dòng dữ liệu cảm biến từ Arduino (ưu tiên JSON, dự phòng CSV / key=value).

    Trả về dict chuẩn hóa `{"temp": float|None, "hum": float|None, "gas": float|None, "gas_warmup": bool, ...}`
    hoặc `None` nếu dòng là phản hồi giao thức (OK/ERR/STATUS/READY/PONG).
    """
    text = (line or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper in ("READY", "PONG") or upper.startswith(("OK ", "OK\t", "ERR ", "STATUS ", "HELP ")):
        return None

    # 1. Định dạng JSON chuẩn: {"temp":28.5,"hum":65.0,"gas":180,"gas_warmup":0}
    json_candidate = text[7:].strip() if upper.startswith("SENSOR ") else text
    if json_candidate.startswith("{") and json_candidate.endswith("}"):
        try:
            obj = json.loads(json_candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        temp = _to_optional_float(obj.get("temp", obj.get("temperature")))
        hum = _to_optional_float(obj.get("hum", obj.get("humidity")))
        gas = _to_optional_float(obj.get("gas", obj.get("mq2")))
        if temp is None and hum is None and gas is None and not any(
            k in obj for k in ("temp", "temperature", "hum", "humidity", "gas", "mq2")
        ):
            return None
        result: dict[str, Any] = {
            "temp": temp,
            "hum": hum,
            "gas": gas,
            "gas_warmup": bool(obj.get("gas_warmup", obj.get("warming_up", 0))),
        }
        if "pan" in obj and _to_optional_float(obj["pan"]) is not None:
            result["pan"] = int(round(float(obj["pan"])))
        if "tilt" in obj and _to_optional_float(obj["tilt"]) is not None:
            result["tilt"] = int(round(float(obj["tilt"])))
        return result

    # 2. Định dạng dự phòng CSV: "28.5,65.0,180" hoặc "TEMP:28.5,HUM:65.0,GAS:180"
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 3:
        cleaned: list[str] = []
        for p in parts:
            cleaned.append(p.split(":", 1)[1].strip() if ":" in p else p)
        vals = [_to_optional_float(x) for x in cleaned]
        if any(v is not None for v in vals):
            return {
                "temp": vals[0],
                "hum": vals[1],
                "gas": vals[2],
                "gas_warmup": False,
            }
    return None


def format_telemetry_readings(raw: dict[str, Any] | None, gas_unit: str = "ADC") -> dict[str, dict[str, Any]]:
    """Chuyển dữ liệu thô sang đúng hợp đồng `POST /api/device/telemetry` của AnNhà.

    Tuân thủ nghiêm ngặt `docs/api/DEVICE_API.md`:
      - Giá trị lỗi đặt `value: None, quality: "error"` (tuyệt đối không thay bằng 0).
      - Cảm biến gas đang sấy nóng 20s đầu đặt `quality: "warming_up"`.
    """
    unit = "ppm" if gas_unit == "ppm" else "ADC"
    if not raw:
        return {
            "temperature": {"value": None, "unit": "C", "quality": "error"},
            "humidity": {"value": None, "unit": "%", "quality": "error"},
            "gas": {"value": None, "unit": unit, "quality": "error"},
        }

    temp = raw.get("temp")
    hum = raw.get("hum")
    gas = raw.get("gas")
    gas_warmup = bool(raw.get("gas_warmup", False))

    return {
        "temperature": {
            "value": round(float(temp), 1) if temp is not None else None,
            "unit": "C",
            "quality": "valid" if temp is not None else "error",
        },
        "humidity": {
            "value": round(float(hum), 1) if hum is not None else None,
            "unit": "%",
            "quality": "valid" if hum is not None else "error",
        },
        "gas": {
            "value": round(float(gas), 1) if gas is not None else None,
            "unit": unit,
            "quality": ("warming_up" if gas_warmup else "valid") if gas is not None else "error",
        },
    }


class ArduinoBridge:
    """Quản lý kết nối Serial USB với Arduino và tự động chuyển sang Mock khi không có phần cứng."""

    def __init__(
        self,
        port: str | None = "auto",
        baudrate: int = 115200,
        timeout: float = 1.0,
        force_mock: bool = False,
        gas_unit: str = "ADC",
        pan_direction: int = DEFAULT_PAN_DIRECTION,
        tilt_direction: int = DEFAULT_TILT_DIRECTION,
    ) -> None:
        self.requested_port = (port or "auto").strip()
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.force_mock = bool(force_mock or self.requested_port.lower() == "mock")
        self.gas_unit = gas_unit
        self.pan_direction = pan_direction
        self.tilt_direction = tilt_direction

        self._mock = MockArduinoDevice()
        self._serial: Any = None
        self._connected_port: str | None = None
        self._running = False
        self._reader_thread: threading.Thread | None = None

        self._io_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._reply_queue: queue.Queue[str] = queue.Queue(maxsize=32)

        self._latest_raw: dict[str, Any] | None = None
        self._latest_ts: float = 0.0
        self._servo_state: dict[str, Any] = {
            "pan": PAN_CENTER,
            "tilt": TILT_CENTER,
            "target_pan": PAN_CENTER,
            "target_tilt": TILT_CENTER,
            "enabled": False,
            "moving": 0,
        }

    @property
    def is_hardware_connected(self) -> bool:
        with self._state_lock:
            return self._serial is not None and self._connected_port is not None

    @property
    def active_mode(self) -> str:
        return f"serial:{self._connected_port}" if self.is_hardware_connected else "mock"

    @property
    def mock_device(self) -> MockArduinoDevice:
        return self._mock

    def start(self) -> "ArduinoBridge":
        """Khởi động cầu nối: thử kết nối USB Serial thật trước, nếu không có thì chạy Mock."""
        if self._running:
            return self
        self._running = True
        if self.force_mock or serial is None:
            reason = "cấu hình MOCK" if self.force_mock else "chưa cài đặt pyserial"
            logger.info("[ArduinoBridge] Chạy chế độ giả lập (Mock) do %s.", reason)
            return self

        if not self._try_connect_once():
            logger.warning(
                "[ArduinoBridge] Không tìm thấy Arduino qua USB Serial (port=%s) -> Tự động chuyển sang chế độ Mock (sẽ tự kết nối lại nếu cắm cáp).",
                self.requested_port,
            )

        self._reader_thread = threading.Thread(
            target=self._background_loop, name="arduino-serial-bridge", daemon=True
        )
        self._reader_thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        self._close_serial()

    def _candidate_ports(self) -> list[str]:
        if self.requested_port.lower() not in ("", "auto"):
            return [self.requested_port]
        ports: list[str] = []
        if serial is not None:
            for info in serial.tools.list_ports.comports():
                dev = info.device or ""
                desc = (info.description or "").lower()
                if "bluetooth" in desc:
                    continue
                if any(tag in dev for tag in ("ttyUSB", "ttyACM", "COM", "cu.usb")):
                    ports.append(dev)
        for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
            for path in sorted(glob.glob(pattern)):
                if path not in ports:
                    ports.append(path)
        return ports

    def _try_connect_once(self) -> bool:
        if serial is None:
            return False
        for candidate in self._candidate_ports():
            conn = None
            try:
                conn = serial.Serial(
                    port=None,
                    baudrate=self.baudrate,
                    timeout=0.1,
                    write_timeout=self.timeout,
                )
                conn.dtr = False
                conn.rts = False
                conn.port = candidate
                conn.open()

                # Chờ READY tự nhiên sau DTR reset (~1.5s) trước khi gửi PING tránh chạm bootloader optiboot
                deadline = time.monotonic() + 3.8
                next_ping = time.monotonic() + 1.8
                buf = bytearray()
                ready = False
                while time.monotonic() < deadline:
                    chunk = conn.read(1)
                    if chunk:
                        if chunk == b"\n":
                            line = bytes(buf).rstrip(b"\r").decode("utf-8", errors="ignore").strip()
                            buf.clear()
                            parsed = parse_sensor_line(line)
                            if parsed is not None:
                                self._record_sensor_data(parsed)
                                ready = True
                                break
                            if line in ("READY", "PONG") or line.startswith("STATUS "):
                                ready = True
                                break
                        elif len(buf) < 256:
                            buf.extend(chunk)
                    if time.monotonic() >= next_ping:
                        conn.write(b"PING\n")
                        next_ping = time.monotonic() + 0.6

                if ready:
                    with self._state_lock:
                        self._serial = conn
                        self._connected_port = candidate
                    logger.info("[ArduinoBridge] Đã kết nối phần cứng Arduino tại %s (%d baud).", candidate, self.baudrate)
                    return True
                conn.close()
            except Exception as exc:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                logger.debug("[ArduinoBridge] Bỏ qua cổng %s: %s", candidate, exc)
        return False

    def _close_serial(self) -> None:
        with self._state_lock:
            conn, self._serial = self._serial, None
            self._connected_port = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _record_sensor_data(self, parsed: dict[str, Any]) -> None:
        with self._state_lock:
            self._latest_raw = parsed
            self._latest_ts = time.monotonic()
            if "pan" in parsed:
                self._servo_state["pan"] = parsed["pan"]
            if "tilt" in parsed:
                self._servo_state["tilt"] = parsed["tilt"]

    def _handle_incoming_line(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        parsed = parse_sensor_line(text)
        if parsed is not None:
            self._record_sensor_data(parsed)
            return

        match = STATUS_RE.match(text)
        if match:
            pan, tilt, tpan, ttilt, enabled, moving = match.groups()
            with self._state_lock:
                self._servo_state.update(
                    pan=int(pan),
                    tilt=int(tilt),
                    target_pan=int(tpan),
                    target_tilt=int(ttilt),
                    enabled=bool(int(enabled)) if enabled is not None else True,
                    moving=int(moving),
                )

        try:
            self._reply_queue.put_nowait(text)
        except queue.Full:
            try:
                self._reply_queue.get_nowait()
                self._reply_queue.put_nowait(text)
            except queue.Empty:
                pass

    def _background_loop(self) -> None:
        buf = bytearray()
        last_reconnect_attempt = 0.0
        while self._running:
            with self._state_lock:
                conn = self._serial
            if conn is None:
                now = time.monotonic()
                if now - last_reconnect_attempt >= 5.0:
                    last_reconnect_attempt = now
                    self._try_connect_once()
                time.sleep(0.25)
                continue

            try:
                byte = conn.read(1)
                if not byte:
                    continue
                if byte == b"\n":
                    line = bytes(buf).rstrip(b"\r").decode("utf-8", errors="ignore")
                    buf.clear()
                    self._handle_incoming_line(line)
                elif len(buf) < 256:
                    buf.extend(byte)
                else:
                    buf.clear()
            except Exception as exc:
                logger.warning("[ArduinoBridge] Mất kết nối USB Serial (%s) -> Tạm chuyển sang Mock và chờ kết nối lại.", exc)
                buf.clear()
                self._close_serial()

    def _send_command(self, command: str, expected_prefix: str | None = "OK ") -> str | None:
        """Gửi lệnh ASCII xuống Arduino một cách an toàn đa luồng."""
        with self._io_lock:
            with self._state_lock:
                conn = self._serial
            if conn is None:
                return None
            # Xóa phản hồi cũ tồn đọng trước khi gửi lệnh mới
            while not self._reply_queue.empty():
                try:
                    self._reply_queue.get_nowait()
                except queue.Empty:
                    break
            try:
                payload = (command.strip() + "\n").encode("ascii")
                conn.write(payload)
                conn.flush()
            except Exception as exc:
                logger.warning("[ArduinoBridge] Lỗi ghi Serial (%s), đóng kết nối.", exc)
                self._close_serial()
                return None

            if expected_prefix is None:
                return None

            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                remaining = max(0.01, deadline - time.monotonic())
                try:
                    reply = self._reply_queue.get(timeout=min(0.15, remaining))
                except queue.Empty:
                    continue
                if reply == "READY" or reply == "PONG" and expected_prefix != "PONG":
                    continue
                if reply.startswith("ERR "):
                    logger.warning("[ArduinoBridge] Arduino phản hồi lỗi cho lệnh '%s': %s", command, reply)
                    return None
                if reply.startswith(expected_prefix):
                    return reply
            return None

    # ------------------------------------------------------------------
    # Public API cho Telemetry & Local Safety Siren
    # ------------------------------------------------------------------

    def get_raw_readings(self) -> dict[str, Any]:
        """Trả về dict số đo thô mới nhất (`temp`, `hum`, `gas`, `is_mock`)."""
        if self.is_hardware_connected:
            with self._state_lock:
                # Nếu chưa nhận mẫu đầu tiên trong 3s đầu, yêu cầu SENSORS ngay
                raw = dict(self._latest_raw) if self._latest_raw else None
                age = time.monotonic() - self._latest_ts if self._latest_ts else 999.0
            if raw is None or age > 10.0:
                self._send_command("SENSORS", expected_prefix=None)
                time.sleep(0.08)
                with self._state_lock:
                    raw = dict(self._latest_raw) if self._latest_raw else None
            if raw is not None:
                raw["is_mock"] = False
                return raw
            return {"temp": None, "hum": None, "gas": None, "gas_warmup": False, "is_mock": False}

        mock_raw = self._mock.read_raw()
        mock_raw["is_mock"] = True
        return mock_raw

    def get_telemetry_readings(self, gas_unit: str | None = None) -> dict[str, dict[str, Any]]:
        """Trả về cấu trúc `readings` chuẩn cho `POST /api/device/telemetry`."""
        raw = self.get_raw_readings()
        return format_telemetry_readings(raw, gas_unit=gas_unit or self.gas_unit)

    # ------------------------------------------------------------------
    # Public API cho Điều khiển 2 Động cơ Servo (AI Tracking & Manual PTZ)
    # ------------------------------------------------------------------

    def send_servo(self, pan: int, tilt: int) -> dict[str, Any]:
        """Đặt góc tuyệt đối cho 2 trục Servo (kẹp trong giới hạn cơ khí an toàn)."""
        clamped_pan = max(PAN_MIN, min(PAN_MAX, int(round(pan))))
        clamped_tilt = max(TILT_MIN, min(TILT_MAX, int(round(tilt))))

        if self.is_hardware_connected:
            with self._state_lock:
                if (
                    self._servo_state.get("enabled")
                    and self._servo_state.get("target_pan") == clamped_pan
                    and self._servo_state.get("target_tilt") == clamped_tilt
                ):
                    return self.get_servo_state()
            reply = self._send_command(f"SERVO:{clamped_pan},{clamped_tilt}", expected_prefix="OK ")
            if reply is not None:
                with self._state_lock:
                    self._servo_state.update(
                        pan=clamped_pan,
                        tilt=clamped_tilt,
                        target_pan=clamped_pan,
                        target_tilt=clamped_tilt,
                        enabled=True,
                    )
            return self.get_servo_state()

        self._mock.set_angles(clamped_pan, clamped_tilt)
        return self.get_servo_state()

    def move_relative(self, delta_pan: int, delta_tilt: int) -> dict[str, Any]:
        """Dịch chuyển tương đối theo góc Servo thô, tự kẹp biên an toàn."""
        dp = int(round(delta_pan))
        dt = int(round(delta_tilt))
        if dp == 0 and dt == 0:
            return self.get_servo_state()

        if self.is_hardware_connected:
            with self._state_lock:
                cur_pan = int(self._servo_state.get("target_pan", PAN_CENTER))
                cur_tilt = int(self._servo_state.get("target_tilt", TILT_CENTER))
            new_pan = max(PAN_MIN, min(PAN_MAX, cur_pan + dp))
            new_tilt = max(TILT_MIN, min(TILT_MAX, cur_tilt + dt))
            eff_dp = new_pan - cur_pan
            eff_dt = new_tilt - cur_tilt
            if eff_dp != 0 or eff_dt != 0:
                reply = self._send_command(f"MOVE {eff_dp} {eff_dt}", expected_prefix="OK ")
                if reply is not None:
                    with self._state_lock:
                        self._servo_state.update(
                            pan=new_pan,
                            tilt=new_tilt,
                            target_pan=new_pan,
                            target_tilt=new_tilt,
                            enabled=True,
                        )
            return self.get_servo_state()

        self._mock.move_relative(dp, dt)
        return self.get_servo_state()

    def move_camera(self, direction: str, degrees: int = 6) -> dict[str, Any]:
        """Xoay camera theo hướng nhìn thực tế: LEFT, RIGHT, UP, DOWN."""
        dp, dt = camera_delta(direction, int(degrees), self.pan_direction, self.tilt_direction)
        return self.move_relative(dp, dt)

    def center(self) -> dict[str, Any]:
        """Đưa camera về góc chính diện mặc định (90°, 90°)."""
        if self.is_hardware_connected:
            self._send_command("CENTER", expected_prefix="OK ")
            with self._state_lock:
                self._servo_state.update(
                    pan=PAN_CENTER,
                    tilt=TILT_CENTER,
                    target_pan=PAN_CENTER,
                    target_tilt=TILT_CENTER,
                    enabled=True,
                )
            return self.get_servo_state()

        self._mock.center()
        return self.get_servo_state()

    def detach(self) -> dict[str, Any]:
        """Ngắt xung PWM để động cơ Servo đứng yên hoàn toàn, không kêu ro ro (dùng khi tắt Tracking / Night Mode)."""
        if self.is_hardware_connected:
            try:
                self._send_command("DETACH", expected_prefix="OK ")
            except ValueError:
                # Tương thích ngược với firmware CameraPanTilt gốc dùng lệnh 'OFF'
                try:
                    self._send_command("OFF", expected_prefix="OK ")
                except Exception as exc:
                    logger.debug("[ArduinoBridge] Lệnh ngắt PWM (DETACH/OFF) lỗi: %s", exc)
            with self._state_lock:
                self._servo_state["enabled"] = False
            return self.get_servo_state()

        self._mock.detach()
        return self.get_servo_state()

    def get_servo_state(self) -> dict[str, Any]:
        if self.is_hardware_connected:
            with self._state_lock:
                return {**self._servo_state, "is_mock": False}
        return self._mock.get_state()
