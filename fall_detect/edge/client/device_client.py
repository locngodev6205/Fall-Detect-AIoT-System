"""Client giao tiếp chuẩn hợp đồng `docs/api/DEVICE_API.md` giữa Raspberry Pi 4 và Backend AnNhà.

Bao gồm:
  1. Heartbeat định kỳ 15s (`POST /api/device/heartbeat`) + tự động đồng bộ `desired_version`.
  2. Telemetry cảm biến (`POST /api/device/telemetry`) + Dual-pipeline ThingsBoard MQTT khi bật cờ.
  3. Gửi sự kiện an toàn (`POST /api/device/events`) & upload ảnh bằng chứng (`POST /api/device/evidence`).
  4. Bộ đệm Outbox khi đứt mạng tạm thời (gửi bù giữ nguyên `message_id` / `event_id` chống trùng lặp).
  5. Nhận & phản hồi tiến trình lệnh điều khiển từ Web (`GET /api/device/commands`, `POST .../ack`).
  6. Tải tài nguyên âm thanh (`GET /api/device/assets/{id}`) & báo cáo phát lịch (`POST /api/device/executions`).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable
import urllib.parse
import uuid

import requests

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None  # type: ignore[assignment]

logger = logging.getLogger("annha.edge.client")

ALLOWED_OBSERVATIONS = {"unknown", "clear", "no_person", "occluded", "camera_error"}


def iso_now_local() -> str:
    """Trả về chuỗi thời gian ISO-8601 chuẩn UTC (đồng nhất với `db.now()` của Backend)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ThingsBoardPublisher:
    """Bắn song song dữ liệu cảm biến lên ThingsBoard qua MQTT khi `THINGSBOARD_ENABLED=true`."""

    def __init__(
        self,
        enabled: bool = False,
        host: str = "127.0.0.1",
        port: int = 1883,
        access_token: str = "",
        topic: str = "v1/devices/me/telemetry",
    ) -> None:
        self.enabled = bool(enabled and access_token and mqtt is not None)
        self.host = host
        self.port = int(port)
        self.access_token = access_token
        self.topic = topic
        self._client: Any = None
        self._connected = False

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except AttributeError:
                client = mqtt.Client()
            client.username_pw_set(self.access_token)

            def _on_connect(_c: Any, _u: Any, _f: Any, rc: Any, *_a: Any) -> None:
                code = rc if isinstance(rc, int) else getattr(rc, "value", 0)
                self._connected = code == 0
                if self._connected:
                    logger.info("[ThingsBoard] Đã kết nối MQTT %s:%d", self.host, self.port)

            def _on_disconnect(*_a: Any) -> None:
                self._connected = False

            client.on_connect = _on_connect
            client.on_disconnect = _on_disconnect
            client.connect_async(self.host, self.port, keepalive=60)
            client.loop_start()
            self._client = client
        except Exception as exc:
            logger.warning("[ThingsBoard] Không thể khởi tạo MQTT (%s).", exc)
            self._client = None

    def publish_readings(self, readings: dict[str, dict[str, Any]], observed_at: str) -> bool:
        if not self.enabled or self._client is None:
            return False
        flat: dict[str, Any] = {"observed_at": observed_at}
        for key, item in readings.items():
            if isinstance(item, dict) and item.get("quality") == "valid" and item.get("value") is not None:
                flat[key] = item["value"]
        if len(flat) <= 1:
            return False
        try:
            info = self._client.publish(self.topic, json.dumps(flat), qos=1)
            return bool(info.rc == 0)
        except Exception as exc:
            logger.debug("[ThingsBoard] Gửi MQTT lỗi: %s", exc)
            return False

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
            self._connected = False


class DeviceClient:
    """Client HTTP chuẩn xác thực `Bearer <device_token>` cho thiết bị Pi 4."""

    def __init__(
        self,
        base_url: str,
        device_token: str,
        *,
        cache_dir: str | Path | None = None,
        thingsboard_enabled: bool = False,
        tb_host: str = "127.0.0.1",
        tb_port: int = 1883,
        tb_token: str = "",
        request_timeout: float = 8.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_token = device_token.strip()
        self.request_timeout = float(request_timeout)
        self.cache_dir = Path(cache_dir or (Path(__file__).resolve().parents[2] / "edge_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir = self.cache_dir / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._lock = threading.Lock()

        self.applied_version: int = 0
        self.current_config: dict[str, Any] = self._load_cached_config()
        if isinstance(self.current_config.get("version"), int):
            self.applied_version = int(self.current_config["version"])

        self._config_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._command_handler: Callable[[dict[str, Any]], tuple[bool, str]] | None = None
        self._processed_commands: deque[str] = deque(maxlen=256)
        self._outbox_telemetry: deque[dict[str, Any]] = deque(maxlen=200)
        self._outbox_events: deque[dict[str, Any]] = deque(maxlen=200)
        self._outbox_executions: deque[dict[str, Any]] = deque(maxlen=200)

        self.tb = ThingsBoardPublisher(
            enabled=thingsboard_enabled,
            host=tb_host,
            port=tb_port,
            access_token=tb_token,
        )

    def start(self) -> "DeviceClient":
        self.tb.start()
        return self

    def stop(self) -> None:
        self.tb.stop()
        self._session.close()

    def on_config_updated(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Đăng ký hàm callback nhận cấu hình mới từ Backend (lịch nhắc, ngưỡng môi trường, chế độ AI)."""
        self._config_listeners.append(callback)
        if self.current_config:
            try:
                callback(self.current_config)
            except Exception as exc:
                logger.warning("[DeviceClient] Lỗi áp dụng config cache ban đầu: %s", exc)

    def set_command_handler(self, handler: Callable[[dict[str, Any]], tuple[bool, str]]) -> None:
        """Đăng ký hàm thực thi lệnh từ Web (`play_audio`, `test_speaker`, `silence`, `ptz_*`)."""
        self._command_handler = handler

    # ------------------------------------------------------------------
    # HTTP Helpers (Không gửi Origin để vượt chuẩn CSRF/Origin check dành cho trình duyệt)
    # ------------------------------------------------------------------

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        if not self.device_token:
            raise RuntimeError("Thiếu DEVICE_TOKEN để xác thực với Backend AnNhà.")
        hdrs = {"Authorization": f"Bearer {self.device_token}"}
        if extra:
            hdrs.update(extra)
        return hdrs

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = self._session.request(
            method=method,
            url=url,
            json=json_body,
            data=data,
            headers=self._headers(headers),
            timeout=self.request_timeout,
            stream=stream,
        )
        return resp

    def _config_cache_file(self) -> Path:
        return self.cache_dir / "device_config.json"

    def _load_cached_config(self) -> dict[str, Any]:
        cfg_file = self._config_cache_file()
        if cfg_file.exists():
            try:
                return json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_cached_config(self, cfg: dict[str, Any]) -> None:
        try:
            self._config_cache_file().write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("[DeviceClient] Không lưu được cache cấu hình: %s", exc)

    # ------------------------------------------------------------------
    # 1. Heartbeat & Đồng bộ Cấu hình (`desired_version`)
    # ------------------------------------------------------------------

    def send_heartbeat(
        self,
        observation: str = "clear",
        *,
        camera_ok: bool = True,
        speaker_ok: bool = True,
        sensors_ok: bool = True,
        bluetooth: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        obs = observation if observation in ALLOWED_OBSERVATIONS else "unknown"
        body: dict[str, Any] = {
            "observation": obs,
            "capabilities": {
                "camera": bool(camera_ok),
                "speaker": bool(speaker_ok),
                "sensors": bool(sensors_ok),
            },
        }
        if bluetooth is not None:
            body["bluetooth"] = bluetooth
        try:
            resp = self._request("POST", "/api/device/heartbeat", json_body=body)
            if resp.status_code != 200:
                logger.warning("[DeviceClient] Heartbeat HTTP %d: %s", resp.status_code, resp.text[:200])
                return None
            result = resp.json()
            desired = int(result.get("desired_version") or 0)
            if desired > self.applied_version or (desired >= 1 and not self.current_config):
                self.sync_config()
            self._flush_outbox()
            return result
        except Exception as exc:
            logger.warning("[DeviceClient] Mất kết nối tạm thời khi gửi Heartbeat: %s", exc)
            return None

    def send_bluetooth_state(self, bt_report: dict[str, Any]) -> bool:
        """Đồng bộ trạng thái Loa Bluetooth và danh sách thiết bị quét được lên Backend."""
        try:
            resp = self._request("POST", "/api/device/bluetooth", json_body=bt_report)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("[DeviceClient] Lỗi gửi trạng thái Bluetooth: %s", exc)
            return False

    def sync_config(self) -> dict[str, Any] | None:
        """Tải cấu hình mới nhất, lưu bền vững, nạp file audio lịch nhắc và gửi ACK."""
        try:
            resp = self._request("GET", "/api/device/config")
            if resp.status_code != 200:
                logger.warning("[DeviceClient] Lỗi tải config HTTP %d: %s", resp.status_code, resp.text[:200])
                return None
            cfg = resp.json()
            version = int(cfg.get("version") or 0)

            # Tải sẵn các file âm thanh của lịch nhắc đang bật để chạy Offline
            for rem in cfg.get("reminders") or []:
                if rem.get("enabled") and rem.get("asset_id"):
                    self.ensure_asset_cached(str(rem["asset_id"]))

            errors: list[str] = []
            for listener in self._config_listeners:
                try:
                    listener(cfg)
                except Exception as exc:
                    errors.append(str(exc))

            if errors:
                err_msg = "; ".join(errors)[:480]
                logger.error("[DeviceClient] Áp dụng config v%d lỗi: %s", version, err_msg)
                if version >= 1:
                    self._request(
                        "POST",
                        "/api/device/config/ack",
                        json_body={"version": version, "success": False, "error": err_msg},
                    )
                return cfg

            self.current_config = cfg
            self._save_cached_config(cfg)
            if version >= 1:
                ack_resp = self._request(
                    "POST",
                    "/api/device/config/ack",
                    json_body={"version": version, "success": True, "error": ""},
                )
                if ack_resp.status_code in (200, 409):
                    self.applied_version = max(self.applied_version, version)
                    logger.info("[DeviceClient] Đã đồng bộ & xác nhận cấu hình phiên bản v%d.", version)
            return cfg
        except Exception as exc:
            logger.warning("[DeviceClient] Lỗi đồng bộ cấu hình: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 2. Telemetry Môi trường (AnNhà REST + ThingsBoard MQTT Dual-Pipeline)
    # ------------------------------------------------------------------

    def send_telemetry(
        self,
        readings: dict[str, dict[str, Any]],
        *,
        observed_at: str | None = None,
        message_id: str | None = None,
    ) -> bool:
        obs_ts = observed_at or iso_now_local()
        msg_id = message_id or f"tel-{uuid.uuid4().hex}"
        payload = {
            "message_id": msg_id,
            "observed_at": obs_ts,
            "readings": readings,
        }

        # Gửi song song lên ThingsBoard nếu bật cờ
        self.tb.publish_readings(readings, obs_ts)

        try:
            resp = self._request("POST", "/api/device/telemetry", json_body=payload)
            if resp.status_code == 200:
                return True
            logger.warning("[DeviceClient] Telemetry HTTP %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.warning("[DeviceClient] Đứt mạng khi gửi Telemetry -> Xếp vào Outbox (%s).", exc)
            with self._lock:
                self._outbox_telemetry.append(payload)
            return False

    # ------------------------------------------------------------------
    # 3. Sự kiện An toàn & Upload Ảnh Bằng chứng / Snapshot
    # ------------------------------------------------------------------

    def send_event(
        self,
        *,
        kind: str,
        severity: str,
        observation: str,
        reason: str,
        event_id: str | None = None,
        sequence: int = 1,
        duration_s: float | None = None,
        confidence: float | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        src_id = event_id or f"{kind}-{uuid.uuid4().hex[:16]}"
        body: dict[str, Any] = {
            "event_id": src_id,
            "sequence": int(sequence),
            "kind": kind,
            "severity": severity,
            "observed_at": observed_at or iso_now_local(),
            "observation": observation,
            "reason": reason[:1000],
            "config_version": int(self.applied_version) if self.applied_version > 0 else 0,
        }
        if duration_s is not None:
            body["duration_s"] = round(max(0.0, float(duration_s)), 2)
        if confidence is not None:
            body["confidence"] = round(min(1.0, max(0.0, float(confidence))), 4)

        try:
            resp = self._request("POST", "/api/device/events", json_body=body)
            if resp.status_code in (200, 201):
                return resp.json()
            logger.warning("[DeviceClient] Gửi sự kiện HTTP %d: %s", resp.status_code, resp.text[:240])
            return None
        except Exception as exc:
            logger.warning("[DeviceClient] Đứt mạng khi gửi sự kiện '%s' -> Xếp vào Outbox (%s).", kind, exc)
            with self._lock:
                self._outbox_events.append(body)
            return None

    def upload_evidence(
        self,
        binary_data: bytes,
        *,
        mime_type: str = "image/jpeg",
        filename: str = "evidence.jpg",
        internal_event_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Upload ảnh bằng chứng gắn với `internal_event_id` (hoặc snapshot khi để trống)."""
        path = "/api/device/evidence"
        if internal_event_id:
            path += f"?event_id={urllib.parse.quote(internal_event_id)}"
        headers = {
            "Content-Type": mime_type,
            "X-File-Name": urllib.parse.quote(filename),
        }
        try:
            resp = self._request("POST", path, data=binary_data, headers=headers)
            if resp.status_code in (200, 201):
                return resp.json()
            logger.warning("[DeviceClient] Upload evidence HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as exc:
            logger.warning("[DeviceClient] Upload evidence lỗi: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 4. Tải Cache Âm thanh, Báo cáo Lịch nhắc & Xử lý Lệnh Thủ công
    # ------------------------------------------------------------------

    def ensure_asset_cached(self, asset_id: str) -> Path | None:
        """Tải file âm thanh từ `/api/device/assets/{asset_id}` về đĩa cục bộ của Pi 4."""
        import re
        safe_id = (asset_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", safe_id):
            logger.warning("[DeviceClient] Từ chối asset_id không hợp lệ: %r", asset_id)
            return None
        assets_root = self.assets_dir.resolve()
        for candidate in self.assets_dir.iterdir():
            if candidate.stem == safe_id and candidate.resolve().parent == assets_root and candidate.stat().st_size > 0:
                return candidate

        try:
            resp = self._request("GET", f"/api/device/assets/{urllib.parse.quote(safe_id)}", stream=True)
            if resp.status_code != 200:
                logger.warning("[DeviceClient] Chưa tải được asset %s (HTTP %d)", safe_id, resp.status_code)
                return None
            mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext_map = {
                "audio/wav": ".wav",
                "audio/x-wav": ".wav",
                "audio/mpeg": ".mp3",
                "audio/ogg": ".ogg",
                "audio/webm": ".webm",
            }
            ext = ext_map.get(mime, ".wav")
            dest = (self.assets_dir / f"{safe_id}{ext}").resolve()
            if dest.parent != assets_root:
                return None
            tmp = self.assets_dir / f".{safe_id}.part"
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=16384):
                    if chunk:
                        fh.write(chunk)
            tmp.replace(dest)
            return dest
        except Exception as exc:
            logger.warning("[DeviceClient] Lỗi tải asset %s: %s", safe_id, exc)
            return None

    def report_execution(
        self,
        reminder_id: str,
        occurrence: str,
        status: str,
        detail: str = "",
    ) -> bool:
        body = {
            "reminder_id": reminder_id,
            "occurrence": occurrence[:200],
            "status": status,
            "detail": detail[:1000],
        }
        try:
            resp = self._request("POST", "/api/device/executions", json_body=body)
            return resp.status_code == 200
        except Exception:
            with self._lock:
                self._outbox_executions.append(body)
            return False

    def poll_and_execute_commands(self) -> int:
        """Nhận danh sách lệnh đang chờ từ Web và thực thi tuần tự với đầy đủ ACK."""
        if self._command_handler is None:
            return 0
        try:
            resp = self._request("GET", "/api/device/commands")
            if resp.status_code != 200:
                return 0
            commands = resp.json()
        except Exception:
            return 0

        handled = 0
        now_epoch = time.time()
        for cmd in commands:
            cmd_id = str(cmd.get("id") or "")
            if not cmd_id or cmd_id in self._processed_commands:
                continue
            expires = float(cmd.get("expires") or 0)
            if expires and expires <= now_epoch:
                continue

            # Tiến trình bắt buộc: pending -> accepted -> executing -> executed/failed
            if cmd.get("status") == "pending":
                self._ack_command(cmd_id, "accepted", "")
            self._ack_command(cmd_id, "executing", "")

            try:
                ok, detail = self._command_handler(cmd)
            except Exception as exc:
                ok, detail = False, str(exc)

            self._ack_command(cmd_id, "executed" if ok else "failed", detail)
            self._processed_commands.append(cmd_id)
            handled += 1
        return handled

    def _ack_command(self, command_id: str, status: str, detail: str) -> None:
        try:
            self._request(
                "POST",
                f"/api/device/commands/{urllib.parse.quote(command_id)}/ack",
                json_body={"status": status, "detail": (detail or "")[:1000]},
            )
        except Exception as exc:
            logger.debug("[DeviceClient] Lỗi ACK command %s (%s): %s", command_id, status, exc)

    def _flush_outbox(self) -> None:
        with self._lock:
            ev_batch = [self._outbox_events.popleft() for _ in range(min(10, len(self._outbox_events)))]
            tel_batch = [self._outbox_telemetry.popleft() for _ in range(min(10, len(self._outbox_telemetry)))]
            exe_batch = [self._outbox_executions.popleft() for _ in range(min(10, len(self._outbox_executions)))]
        for item in ev_batch:
            try:
                r = self._request("POST", "/api/device/events", json_body=item)
                if r.status_code >= 500:
                    with self._lock:
                        self._outbox_events.appendleft(item)
                    break
            except Exception:
                with self._lock:
                    self._outbox_events.appendleft(item)
                break
        for item in tel_batch:
            try:
                r = self._request("POST", "/api/device/telemetry", json_body=item)
                if r.status_code >= 500:
                    with self._lock:
                        self._outbox_telemetry.appendleft(item)
                    break
            except Exception:
                with self._lock:
                    self._outbox_telemetry.appendleft(item)
                break
        for item in exe_batch:
            try:
                self._request("POST", "/api/device/executions", json_body=item)
            except Exception:
                with self._lock:
                    self._outbox_executions.appendleft(item)
                break
