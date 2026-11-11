"""Quản lý kết nối Loa Bluetooth chuyên dụng cho Raspberry Pi 4 (AnNhà Edge).

Quy tắc phần cứng nghiêm ngặt:
  - Chỉ định tuyến âm thanh tới đúng Sink Bluetooth (`bluez` / `BT_SPEAKER_MAC` / `BT_SPEAKER_NAME`)
    qua PipeWire (`wpctl`) hoặc PulseAudio (`pactl`).
  - Hỗ trợ quét thiết bị Bluetooth xung quanh (`scan_devices`), liệt kê thiết bị đã ghép đôi (`list_cached_devices`),
    kết nối (`connect_device`) và ngắt kết nối (`disconnect_device`) trực tiếp từ giao diện Web UI.
  - Ở chế độ phần cứng thực (`mock_mode=False`), nếu Loa Bluetooth bị ngắt kết nối hoặc tắt nguồn,
    hệ thống ghi cảnh báo rõ ràng và TUYỆT ĐỐI KHÔNG tự đẩy âm thanh ra cổng 3.5mm hay HDMI.
  - Ở chế độ giả lập trên PC (`mock_mode=True`), mô phỏng trạng thái kết nối loa Bluetooth sạch sẽ
    để phục vụ kiểm thử tự động và demo giao diện Web.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


def _is_raspberry_pi() -> bool:
    try:
        model_path = "/proc/device-tree/model"
        with open(model_path, "r", encoding="utf-8", errors="ignore") as fh:
            if "raspberry pi" in fh.read().lower():
                return True
    except OSError:
        pass
    return platform.machine().lower().startswith(("aarch64", "armv7"))


def get_audio_env() -> dict[str, str]:
    """Đảm bảo biến môi trường PipeWire/PulseAudio (`XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`) luôn sẵn sàng."""
    env = dict(os.environ)
    try:
        uid = os.getuid()
        runtime_dir = f"/run/user/{uid}"
        if not env.get("XDG_RUNTIME_DIR") and os.path.isdir(runtime_dir):
            env["XDG_RUNTIME_DIR"] = runtime_dir
        bus_path = f"{runtime_dir}/bus"
        if not env.get("DBUS_SESSION_BUS_ADDRESS") and os.path.exists(bus_path):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
    except AttributeError:
        pass
    return env


MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _is_mac_like_name(addr: str, name: str) -> bool:
    if not name:
        return True
    norm_addr = addr.upper().replace(":", "").replace("-", "").strip()
    norm_name = name.upper().replace(":", "").replace("-", "").strip()
    return norm_addr == norm_name


class BluetoothSpeakerManager:
    """Quản lý kết nối `bluetoothctl` tự động, quét thiết bị và định tuyến âm thanh Bluetooth Sink."""

    def __init__(
        self,
        speaker_mac: str = "",
        speaker_name: str = "",
        *,
        force_mock: bool | None = None,
        reconnect_interval_s: float = 12.0,
        env_file_path: Path | None = None,
    ) -> None:
        raw_mac = (speaker_mac or "").strip().upper()
        if raw_mac and not MAC_RE.fullmatch(raw_mac):
            logger.warning("[BluetoothAudio] Địa chỉ BT_SPEAKER_MAC không hợp lệ (%r) -> bỏ qua.", speaker_mac)
            raw_mac = ""
        self.speaker_mac = raw_mac
        self.speaker_name = (speaker_name or "").strip()
        self.reconnect_interval_s = max(3.0, float(reconnect_interval_s))
        self.env_file_path = env_file_path or (Path(__file__).resolve().parents[2] / ".env.edge")

        self._has_bluetoothctl = shutil.which("bluetoothctl") is not None
        self._has_wpctl = shutil.which("wpctl") is not None
        self._has_pactl = shutil.which("pactl") is not None

        if force_mock is not None:
            self.mock_mode = bool(force_mock)
        else:
            # Trên máy tính phát triển không cấu hình MAC loa & không phải Pi -> tự vào chế độ Mock
            self.mock_mode = not _is_raspberry_pi() and not self.speaker_mac

        self._lock = threading.Lock()
        self._active_sink: str | None = "mock:bluez_sink" if self.mock_mode else None
        self._active_backend: str = "mock" if self.mock_mode else "none"
        self._running = False
        self._thread: threading.Thread | None = None
        self._mock_connected: bool = True
        self._last_scanned_devices: list[dict[str, Any]] = []

    def set_mock_connected(self, connected: bool) -> None:
        """Hỗ trợ kiểm thử kịch bản mất kết nối loa Bluetooth."""
        with self._lock:
            self._mock_connected = bool(connected)
            if self.mock_mode:
                self._active_sink = "mock:bluez_sink" if connected else None

    def start(self) -> "BluetoothSpeakerManager":
        if self.mock_mode:
            logger.info("[BluetoothAudio] Chạy ở chế độ Mock Bluetooth Speaker.")
            return self

        self.refresh_sink(attempt_connect=True)
        self._running = True
        self._thread = threading.Thread(
            target=self._reconnect_loop,
            name="BluetoothReconnectThread",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _reconnect_loop(self) -> None:
        while self._running:
            try:
                if not self.is_speaker_ready() and self.speaker_mac:
                    self.refresh_sink(attempt_connect=True)
            except Exception as exc:
                logger.debug("[BluetoothAudio] Lỗi vòng lặp tự kết nối lại Bluetooth: %s", exc)
            deadline = time.monotonic() + self.reconnect_interval_s
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    def get_connected_info(self) -> dict[str, Any]:
        """Lấy thông tin thực tế của loa Bluetooth đang kết nối tới Pi qua `bluetoothctl info`."""
        if self.mock_mode:
            with self._lock:
                connected = bool(self._mock_connected)
            return {
                "connected": connected,
                "deviceName": (self.speaker_name or "Mock Bluetooth Speaker") if connected else "",
                "address": (self.speaker_mac or "59:0B:5F:F3:D9:C9") if connected else "",
                "status": "connected" if connected else "disconnected",
            }

        if not self._has_bluetoothctl:
            return {
                "connected": False,
                "deviceName": "",
                "address": "",
                "status": "disconnected",
            }

        try:
            res = subprocess.run(
                ["bluetoothctl", "info"],
                capture_output=True,
                text=True,
                timeout=2.5,
                env=get_audio_env(),
            )
            if res.returncode == 0 and "Connected: yes" in (res.stdout or ""):
                device_name = ""
                device_alias = ""
                device_addr = ""
                for raw_line in res.stdout.splitlines():
                    line = raw_line.strip()
                    if line.startswith("Name:"):
                        device_name = line.split(":", 1)[1].strip()
                    elif line.startswith("Alias:"):
                        device_alias = line.split(":", 1)[1].strip()
                    elif line.startswith("Device "):
                        parts = line.split()
                        if len(parts) >= 2 and MAC_RE.fullmatch(parts[1]):
                            device_addr = parts[1].upper()
                final_name = device_name or device_alias or self.speaker_name or "Bluetooth Speaker"
                if final_name or device_addr:
                    return {
                        "connected": True,
                        "deviceName": final_name,
                        "address": device_addr,
                        "status": "connected",
                    }
        except Exception as exc:
            logger.debug("[BluetoothAudio] Lỗi đọc bluetoothctl info: %s", exc)

        return {
            "connected": False,
            "deviceName": "",
            "address": "",
            "status": "disconnected",
        }

    def list_cached_devices(self) -> list[dict[str, Any]]:
        """Đọc danh sách thiết bị Bluetooth đã biết và đã ghép đôi (nhanh < 0.3s)."""
        if self.mock_mode:
            conn_info = self.get_connected_info()
            mock_devs = [
                {
                    "name": self.speaker_name or "SRS-XB13",
                    "address": self.speaker_mac or "59:0B:5F:F3:D9:C9",
                    "connected": conn_info["connected"],
                    "paired": True,
                },
                {
                    "name": "HAVIT TW958 PRO",
                    "address": "01:08:51:ED:08:B9",
                    "connected": False,
                    "paired": True,
                },
            ]
            return mock_devs

        if not self._has_bluetoothctl:
            return []

        devices_by_addr: dict[str, dict[str, Any]] = {}
        env = get_audio_env()

        # Giữ lại các thiết bị vừa tìm thấy từ lần quét chủ động gần nhất
        with self._lock:
            for prev in self._last_scanned_devices:
                addr = str(prev.get("address") or "").upper()
                name = str(prev.get("name") or "").strip()
                if addr and MAC_RE.fullmatch(addr) and not _is_mac_like_name(addr, name):
                    devices_by_addr[addr] = {
                        "name": name,
                        "address": addr,
                        "connected": False,
                        "paired": bool(prev.get("paired")),
                    }

        try:
            res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=3.0, env=env)
            if res.returncode == 0:
                for raw_line in res.stdout.splitlines():
                    clean = ANSI_ESCAPE_RE.sub("", raw_line).strip()
                    if clean.startswith("Device "):
                        parts = clean.split(maxsplit=2)
                        if len(parts) >= 3 and MAC_RE.fullmatch(parts[1]):
                            addr = parts[1].upper()
                            name = parts[2].strip()
                            if not _is_mac_like_name(addr, name):
                                devices_by_addr[addr] = {
                                    "name": name,
                                    "address": addr,
                                    "connected": False,
                                    "paired": False,
                                }
        except Exception as exc:
            logger.debug("[BluetoothAudio] Lỗi đọc bluetoothctl devices: %s", exc)

        paired_addrs: set[str] = set()
        try:
            res_p = subprocess.run(
                ["bluetoothctl", "devices", "Paired"],
                capture_output=True,
                text=True,
                timeout=3.0,
                env=env,
            )
            if res_p.returncode != 0 or not res_p.stdout.strip():
                res_p = subprocess.run(
                    ["bluetoothctl", "paired-devices"],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    env=env,
                )
            if res_p.returncode == 0:
                for raw_line in res_p.stdout.splitlines():
                    clean = ANSI_ESCAPE_RE.sub("", raw_line).strip()
                    if clean.startswith("Device "):
                        parts = clean.split(maxsplit=2)
                        if len(parts) >= 2 and MAC_RE.fullmatch(parts[1]):
                            addr = parts[1].upper()
                            paired_addrs.add(addr)
                            if len(parts) >= 3 and addr not in devices_by_addr:
                                name = parts[2].strip()
                                if not _is_mac_like_name(addr, name):
                                    devices_by_addr[addr] = {
                                        "name": name,
                                        "address": addr,
                                        "connected": False,
                                        "paired": True,
                                    }
        except Exception:
            pass

        conn_info = self.get_connected_info()
        conn_addr = (conn_info.get("address") or "").upper()
        if conn_info.get("connected") and conn_addr and conn_addr not in devices_by_addr:
            devices_by_addr[conn_addr] = {
                "name": conn_info.get("deviceName") or "Bluetooth Speaker",
                "address": conn_addr,
                "connected": True,
                "paired": True,
            }

        result = []
        for addr, item in devices_by_addr.items():
            item["paired"] = addr in paired_addrs or item.get("paired", False)
            item["connected"] = bool(conn_info.get("connected") and addr == conn_addr)
            result.append(item)

        result.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        return result

    def scan_devices(self, duration_s: float = 4.5) -> list[dict[str, Any]]:
        """Quét chủ động các thiết bị Bluetooth đang mở xung quanh Pi 4."""
        if self.mock_mode:
            return self.list_cached_devices()

        if not self._has_bluetoothctl:
            return []

        env = get_audio_env()
        try:
            subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, text=True, timeout=2.0, env=env)
        except Exception:
            pass

        discovered: dict[str, dict[str, Any]] = {}
        proc = None
        try:
            proc = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            if proc.stdin:
                proc.stdin.write("power on\n")
                proc.stdin.write("default-agent\n")
                proc.stdin.write("scan on\n")
                proc.stdin.flush()

            time.sleep(max(2.0, min(10.0, float(duration_s))))

            if proc.stdin:
                proc.stdin.write("devices\n")
                proc.stdin.write("scan off\n")
                proc.stdin.write("quit\n")
                proc.stdin.flush()

            stdout_data, _ = proc.communicate(timeout=4.0)
            skip_prefixes = (
                "RSSI:",
                "TxPower:",
                "UUIDs:",
                "ManufacturerData",
                "ServiceData",
                "Paired:",
                "Connected:",
                "Trusted:",
                "Blocked:",
                "Alias:",
                "LegacyPairing:",
                "Icon:",
                "Class:",
                "Modalias:",
            )
            for raw_line in (stdout_data or "").splitlines():
                clean = ANSI_ESCAPE_RE.sub("", raw_line).strip()
                m = re.search(r"Device\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s+(.+)$", clean)
                if m:
                    addr = m.group(1).upper()
                    name = m.group(2).strip()
                    if any(name.startswith(pfx) for pfx in skip_prefixes):
                        continue
                    if not _is_mac_like_name(addr, name):
                        discovered[addr] = {
                            "name": name,
                            "address": addr,
                            "connected": False,
                            "paired": False,
                        }
        except Exception as exc:
            logger.warning("[BluetoothAudio] Lỗi khi quét thiết bị Bluetooth: %s", exc)
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass

        with self._lock:
            self._last_scanned_devices = list(discovered.values())

        merged = self.list_cached_devices()
        with self._lock:
            self._last_scanned_devices = list(merged)
        logger.info("[BluetoothAudio] Quét hoàn tất: phát hiện %d thiết bị Bluetooth.", len(merged))
        return merged

    def _persist_speaker_to_env(self, mac: str, name: str) -> None:
        """Lưu địa chỉ MAC và tên loa Bluetooth đã chọn vào `.env.edge` để tự nhớ sau khi khởi động lại."""
        if not self.env_file_path or not self.env_file_path.exists():
            return
        safe_mac = re.sub(r"[\r\n]", "", mac).strip()
        safe_name = re.sub(r"[\r\n]", "", name).strip()
        try:
            lines = self.env_file_path.read_text(encoding="utf-8").splitlines()
            updated_mac = False
            updated_name = False
            new_lines: list[str] = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("BT_SPEAKER_MAC="):
                    new_lines.append(f"BT_SPEAKER_MAC={safe_mac}")
                    updated_mac = True
                elif stripped.startswith("BT_SPEAKER_NAME="):
                    new_lines.append(f"BT_SPEAKER_NAME={safe_name}")
                    updated_name = True
                else:
                    new_lines.append(line)
            if not updated_mac:
                new_lines.append(f"BT_SPEAKER_MAC={safe_mac}")
            if not updated_name:
                new_lines.append(f"BT_SPEAKER_NAME={safe_name}")
            self.env_file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.debug("[BluetoothAudio] Không thể lưu cấu hình loa vào .env.edge: %s", exc)

    def connect_device(self, address: str, name: str = "") -> dict[str, Any]:
        """Ghép đôi (pair), tin cậy (trust), kết nối (connect) và kích hoạt Sink âm thanh cho loa Bluetooth."""
        clean_addr = (address or "").strip().upper()
        clean_name = (name or "").strip()
        if not MAC_RE.fullmatch(clean_addr):
            return {
                "success": False,
                "connected": False,
                "address": clean_addr,
                "deviceName": clean_name,
                "status": "disconnected",
                "error": f"Địa chỉ MAC không hợp lệ: {address!r}",
            }

        self.speaker_mac = clean_addr
        if clean_name:
            self.speaker_name = clean_name

        if self.mock_mode:
            self.set_mock_connected(True)
            return {
                "success": True,
                "connected": True,
                "address": clean_addr,
                "deviceName": clean_name or "Mock Bluetooth Speaker",
                "status": "connected",
            }

        env = get_audio_env()
        try:
            subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, text=True, timeout=2.0, env=env)
        except Exception:
            pass

        connected = False
        error_detail = ""
        try:
            subprocess.run(["bluetoothctl", "trust", clean_addr], capture_output=True, text=True, timeout=4.0, env=env)
            subprocess.run(["bluetoothctl", "pair", clean_addr], capture_output=True, text=True, timeout=7.0, env=env)
            res = subprocess.run(
                ["bluetoothctl", "connect", clean_addr],
                capture_output=True,
                text=True,
                timeout=10.0,
                env=env,
            )
            out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
            info_res = subprocess.run(
                ["bluetoothctl", "info", clean_addr],
                capture_output=True,
                text=True,
                timeout=3.0,
                env=env,
            )
            info_out = info_res.stdout or ""
            connected = "Connected: yes" in info_out or "Connection successful" in out
            if not connected and out:
                error_detail = out.splitlines()[-1]
        except Exception as exc:
            error_detail = str(exc)
            logger.warning("[BluetoothAudio] Lỗi khi kết nối tới %s: %s", clean_addr, exc)

        if connected:
            # Chờ PipeWire / PulseAudio khởi tạo A2DP sink cho loa vừa kết nối
            for _ in range(4):
                time.sleep(0.5)
                sink = self.refresh_sink(attempt_connect=False)
                if sink:
                    break
            conn_info = self.get_connected_info()
            resolved_name = conn_info.get("deviceName") or clean_name or "Bluetooth Speaker"
            self.speaker_name = resolved_name
            self._persist_speaker_to_env(clean_addr, resolved_name)
            logger.info("[BluetoothAudio] ✅ Đã kết nối thành công loa Bluetooth: %s (%s)", resolved_name, clean_addr)
            return {
                "success": True,
                "connected": True,
                "address": clean_addr,
                "deviceName": resolved_name,
                "status": "connected",
            }

        return {
            "success": False,
            "connected": False,
            "address": clean_addr,
            "deviceName": clean_name,
            "status": "disconnected",
            "error": error_detail or "Không thể kết nối loa Bluetooth. Hãy bật nguồn loa và đặt ở chế độ Pairing.",
        }

    def disconnect_device(self, address: str = "") -> dict[str, Any]:
        """Ngắt kết nối loa Bluetooth hiện tại và tắt tự động nối lại cho đến khi người dùng chọn lại."""
        target = (address or self.speaker_mac or "").strip().upper()
        self.speaker_mac = ""
        self.speaker_name = ""
        self._persist_speaker_to_env("", "")

        if self.mock_mode:
            self.set_mock_connected(False)
            return {
                "success": True,
                "connected": False,
                "address": "",
                "deviceName": "",
                "status": "disconnected",
            }

        env = get_audio_env()
        try:
            if target and MAC_RE.fullmatch(target):
                subprocess.run(["bluetoothctl", "disconnect", target], capture_output=True, text=True, timeout=5.0, env=env)
            else:
                conn_info = self.get_connected_info()
                if conn_info.get("address"):
                    subprocess.run(
                        ["bluetoothctl", "disconnect", conn_info["address"]],
                        capture_output=True,
                        text=True,
                        timeout=5.0,
                        env=env,
                    )
                else:
                    subprocess.run(["bluetoothctl", "disconnect"], capture_output=True, text=True, timeout=5.0, env=env)
        except Exception as exc:
            logger.debug("[BluetoothAudio] Lỗi khi ngắt kết nối Bluetooth: %s", exc)

        with self._lock:
            self._active_sink = None
            self._active_backend = "none"

        logger.info("[BluetoothAudio] Đã ngắt kết nối loa Bluetooth (%s).", target or "mặc định")
        return {
            "success": True,
            "connected": False,
            "address": "",
            "deviceName": "",
            "status": "disconnected",
        }

    def get_bluetooth_report(self, devices_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Tổng hợp trạng thái kết nối Bluetooth & danh sách thiết bị để đồng bộ lên Web UI."""
        conn_info = self.get_connected_info()
        devices = devices_override if devices_override is not None else self.list_cached_devices()
        with self._lock:
            sink = self._active_sink
            backend = self._active_backend
        return {
            "connected": bool(conn_info.get("connected")),
            "deviceName": conn_info.get("deviceName") or "",
            "address": conn_info.get("address") or "",
            "status": conn_info.get("status") or ("connected" if conn_info.get("connected") else "disconnected"),
            "sink": sink,
            "backend": backend,
            "devices": devices,
        }

    def _bluetoothctl_connect(self) -> bool:
        if not self._has_bluetoothctl or not self.speaker_mac:
            return False
        env = get_audio_env()
        try:
            subprocess.run(
                ["bluetoothctl", "trust", self.speaker_mac],
                capture_output=True,
                text=True,
                timeout=4.0,
                env=env,
            )
            res = subprocess.run(
                ["bluetoothctl", "connect", self.speaker_mac],
                capture_output=True,
                text=True,
                timeout=8.0,
                env=env,
            )
            out = (res.stdout or "") + (res.stderr or "")
            if res.returncode == 0 or "Connection successful" in out or "Connected: yes" in out:
                logger.info("[BluetoothAudio] Đã kết nối bluetoothctl tới loa %s.", self.speaker_mac)
                time.sleep(0.8)  # Chờ PipeWire/PulseAudio đăng ký A2DP sink
                return True
        except Exception as exc:
            logger.debug("[BluetoothAudio] Lệnh bluetoothctl connect thất bại: %s", exc)
        return False

    def _matches_bluetooth_node(
        self,
        text: str,
        *,
        extra_name: str = "",
        extra_mac: str = "",
        bluez_names: set[str] | None = None,
    ) -> bool:
        low = text.lower().strip()
        # Tuyệt đối loại trừ HDMI / jack 3.5mm / webcam mic nội bộ trên Pi
        if any(
            bad in low
            for bad in (
                "built-in audio",
                "wed camera",
                "bcm2835",
                "hdmi",
                "vc4-hdmi",
                "analog-stereo",
                "dummy",
            )
        ):
            if "bluez" not in low:
                return False

        if "bluez" in low:
            return True

        if bluez_names:
            for bname in bluez_names:
                if bname and (bname in low or low in bname):
                    return True

        for mac in (self.speaker_mac, extra_mac):
            if mac:
                mac_colon = mac.lower()
                mac_under = mac_colon.replace(":", "_")
                mac_plain = mac_colon.replace(":", "")
                if mac_colon in low or mac_under in low or mac_plain in low:
                    return True

        for name in (self.speaker_name, extra_name):
            if name and name.lower().strip() in low:
                return True

        if any(
            kw in low
            for kw in (
                "srs-",
                "xb13",
                "havit",
                "hoco",
                "tw9",
                "airpod",
                "jbl",
                "marshall",
                "edifier",
                "bose",
                "soundcore",
                "bluetooth",
            )
        ):
            return True
        return False

    def detect_bluetooth_sink(self) -> tuple[str | None, str]:
        """Dò tìm Sink Bluetooth đang hoạt động trên PipeWire (`wpctl`) hoặc PulseAudio (`pactl`)."""
        if self.mock_mode:
            with self._lock:
                return (("mock:bluez_sink", "mock") if self._mock_connected else (None, "mock"))

        env = get_audio_env()
        conn_info = self.get_connected_info()
        conn_name = conn_info.get("deviceName") or ""
        conn_addr = conn_info.get("address") or ""

        # Nếu có loa đang kết nối mà chưa lưu speaker_mac thì tự động đồng bộ
        if conn_info.get("connected") and conn_addr and not self.speaker_mac:
            self.speaker_mac = conn_addr
            if conn_name:
                self.speaker_name = conn_name

        # 1. PipeWire / WirePlumber (Raspberry Pi OS Bookworm mặc định)
        if self._has_wpctl:
            try:
                res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=2.0, env=env)
                if res.returncode == 0:
                    bluez_device_names: set[str] = set()
                    in_devices = False
                    in_sinks = False
                    for line in res.stdout.splitlines():
                        if "Devices:" in line and not in_sinks:
                            in_devices = True
                            continue
                        if "Sinks:" in line:
                            in_devices = False
                            in_sinks = True
                            continue
                        if in_devices:
                            if "[bluez" in line.lower():
                                m_dev = re.search(r"\b\d+\.\s+(.+?)\s*\[bluez", line, re.IGNORECASE)
                                if m_dev:
                                    bluez_device_names.add(m_dev.group(1).strip().lower())
                        elif in_sinks:
                            if any(hdr in line for hdr in ("Sink endpoints:", "Sources:", "Streams:", "Filters:", "Video")):
                                break
                            m = re.search(r"\b(\d+)\.\s+(.+?)(?:\[|$)", line)
                            if m:
                                node_id, node_label = m.group(1), m.group(2).strip()
                                if self._matches_bluetooth_node(
                                    node_label,
                                    extra_name=conn_name,
                                    extra_mac=conn_addr,
                                    bluez_names=bluez_device_names,
                                ):
                                    return node_id, "wpctl"
            except Exception as exc:
                logger.debug("[BluetoothAudio] Lỗi kiểm tra wpctl: %s", exc)

        # 2. PulseAudio / pipewire-pulse (`pactl`)
        if self._has_pactl:
            try:
                res = subprocess.run(
                    ["pactl", "list", "short", "sinks"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    env=env,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.split()
                        if len(parts) >= 2 and self._matches_bluetooth_node(
                            parts[1],
                            extra_name=conn_name,
                            extra_mac=conn_addr,
                        ):
                            return parts[1], "pactl"
            except Exception as exc:
                logger.debug("[BluetoothAudio] Lỗi kiểm tra pactl: %s", exc)

        return None, "none"

    def refresh_sink(self, *, attempt_connect: bool = False) -> str | None:
        """Làm mới trạng thái Sink Bluetooth; thử kết nối lại qua `bluetoothctl` nếu cần."""
        sink, backend = self.detect_bluetooth_sink()
        if sink is None and attempt_connect and not self.mock_mode:
            if self._bluetoothctl_connect():
                sink, backend = self.detect_bluetooth_sink()

        with self._lock:
            self._active_sink = sink
            self._active_backend = backend

        if sink and not self.mock_mode:
            env = get_audio_env()
            try:
                if backend == "wpctl":
                    subprocess.run(["wpctl", "set-default", sink], check=False, timeout=1.5, env=env)
                elif backend == "pactl":
                    subprocess.run(["pactl", "set-default-sink", sink], check=False, timeout=1.5, env=env)
                    subprocess.run(["pactl", "set-sink-mute", sink, "0"], check=False, timeout=1.5, env=env)
            except Exception:
                pass
        return sink

    def is_speaker_ready(self) -> bool:
        """Kiểm tra Loa Bluetooth đã sẵn sàng nhận âm thanh chưa."""
        if self.mock_mode:
            with self._lock:
                return bool(self._mock_connected)
        sink = self.refresh_sink(attempt_connect=False)
        return sink is not None

    def apply_volume(self, volume: int) -> bool:
        """Đặt âm lượng trực tiếp lên đúng Sink Bluetooth (tuyệt đối không chạm `amixer` 3.5mm/HDMI)."""
        vol = max(0, min(100, int(volume)))
        if self.mock_mode:
            return self.is_speaker_ready()

        sink = self.refresh_sink(attempt_connect=False)
        if not sink:
            return False

        with self._lock:
            backend = self._active_backend

        env = get_audio_env()
        try:
            if backend == "wpctl":
                subprocess.run(
                    ["wpctl", "set-volume", sink, f"{vol / 100.0:.2f}"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                    env=env,
                )
                subprocess.run(
                    ["wpctl", "set-mute", sink, "0"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                    env=env,
                )
                return True
            if backend == "pactl":
                subprocess.run(
                    ["pactl", "set-sink-volume", sink, f"{vol}%"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                    env=env,
                )
                subprocess.run(
                    ["pactl", "set-sink-mute", sink, "0"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                    env=env,
                )
                return True
        except Exception as exc:
            logger.debug("[BluetoothAudio] Lỗi đặt âm lượng Bluetooth sink %s: %s", sink, exc)
        return False

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ready": bool(self._mock_connected) if self.mock_mode else (self._active_sink is not None),
                "mock_mode": self.mock_mode,
                "sink": self._active_sink,
                "backend": self._active_backend,
                "speaker_mac": self.speaker_mac,
                "speaker_name": self.speaker_name,
            }
