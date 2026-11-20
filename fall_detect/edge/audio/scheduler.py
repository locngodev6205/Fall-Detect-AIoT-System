"""Bộ lập lịch phát lời nhắc sinh hoạt Offline & tích hợp Chế độ ban đêm yên tĩnh.

Đặc điểm:
  - Đọc danh sách `reminders` từ cấu hình đã lưu cục bộ (`edge_cache/device_config.json`),
    hoạt động độc lập ngay cả khi mất mạng Internet.
  - Hỗ trợ đầy đủ: `weekdays` (`0=Thứ Hai .. 6=Chủ Nhật`), `once_date` (`YYYY-MM-DD`),
    `time` (`HH:MM`), `timezone` (`Asia/Ho_Chi_Minh`), và độ trễ cho phép `late_seconds`.
  - Lưu vết `occurrence` đã xử lý xuống đĩa (`executed_reminders.json`) để chống phát lặp khi khởi động lại.
  - Tích hợp **Chế độ ban đêm (`22:00 - 06:00`)**: tự động tạm hoãn lời nhắc thường trong giờ ngủ
    và gửi báo cáo `status="skipped"` về Backend (`POST /api/device/executions`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..tracking.pan_tilt_tracker import is_night_mode_active
from .audio_player import AudioPlayer

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Bộ lập lịch kiểm tra và phát lời nhắc Offline trên Pi 4."""

    def __init__(
        self,
        audio_player: AudioPlayer,
        *,
        cache_dir: str | Path | None = None,
        asset_resolver: Callable[[str], Path | None] | None = None,
        execution_reporter: Callable[[str, str, str, str], Any] | None = None,
        submit_audio: Callable | None = None,
        execution_started: Callable[[str, str], None] | None = None,
    ) -> None:
        self.audio_player = audio_player
        self.cache_dir = Path(cache_dir or (Path(__file__).resolve().parents[2] / "edge_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.cache_dir / "executed_reminders.json"
        self.asset_resolver = asset_resolver
        self.execution_reporter = execution_reporter
        self.submit_audio = submit_audio
        self.execution_started = execution_started
        self._queued: set[str] = set()

        self._lock = threading.Lock()
        self._reminders: list[dict[str, Any]] = []
        self._smart_modes: dict[str, Any] = {
            "night_mode_enabled": True,
            "night_start": "22:00",
            "night_end": "06:00",
        }
        self._ledger_available = True
        self._executed: set[str] = self._load_executed()

    def _load_executed(self) -> set[str]:
        if not self.state_file.exists():
            return set()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
                raise ValueError("Unexpected reminder ledger format")
            return set(data)
        except (OSError, ValueError):
            self._ledger_available = False
            logger.exception("[ReminderScheduler] Tạm dừng lịch vì không đọc được sổ lần phát.")
            return set()

    def _save_executed(self) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(sorted(self._executed, key=lambda key: key.partition(":")[2]), stream)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(self.state_file)
        directory = os.open(self.cache_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def apply_config(self, config: dict[str, Any]) -> None:
        """Cập nhật danh sách lịch nhắc và khung giờ Chế độ ban đêm từ `/api/device/config`."""
        with self._lock:
            reminders = config.get("reminders")
            if isinstance(reminders, list):
                self._reminders = [dict(r) for r in reminders if isinstance(r, dict)]
            modes = config.get("smart_modes")
            if isinstance(modes, dict):
                self._smart_modes.update(modes)

    def evaluate_due(self, now_utc: datetime | None = None) -> list[dict[str, Any]]:
        """Kiểm tra tất cả lịch nhắc đến hạn tại thời điểm `now_utc` và thực thi."""
        if not self._ledger_available:
            return []
        base_now = now_utc or datetime.now(timezone.utc)
        with self._lock:
            reminders = list(self._reminders)

        results: list[dict[str, Any]] = []
        for rem in reminders:
            if not rem.get("enabled", True):
                continue
            reminder_id = str(rem.get("id") or "").strip()
            time_str = str(rem.get("time") or "").strip()
            if not reminder_id or len(time_str) != 5 or ":" not in time_str:
                continue

            tz_name = str(rem.get("timezone") or "Asia/Ho_Chi_Minh")
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("Asia/Ho_Chi_Minh")

            local_now = base_now.astimezone(tz)
            try:
                hour, minute = map(int, time_str.split(":"))
                scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
                if scheduled.timestamp() > local_now.timestamp():
                    scheduled -= timedelta(days=1)
                if scheduled.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != scheduled.replace(tzinfo=None):
                    continue  # A wall-clock time in a DST gap has no occurrence.
                delta = local_now.timestamp() - scheduled.timestamp()
                late = int(rem.get("late_seconds") or 0)
            except (ValueError, TypeError):
                continue
            if delta < 0 or (delta >= 60 and delta > late):
                continue

            day = scheduled.date().isoformat()
            once_date = rem.get("once_date")
            if once_date:
                if str(once_date) != day:
                    continue
            elif scheduled.weekday() not in (rem.get("weekdays") or []):
                continue

            occurrence = f"{day}T{time_str}:v{int(rem.get('version') or 1)}"
            key = f"{reminder_id}:{occurrence}"
            with self._lock:
                if key in self._executed or key in self._queued:
                    continue
                self._queued.add(key)
            args = (rem, key, occurrence, scheduled, base_now)
            if self.submit_audio is None:
                results.append(self._execute(*args))
            elif self.submit_audio(self._execute, *args) is None:
                with self._lock:
                    self._queued.discard(key)
        return results

    def _execute(self, rem, key, occurrence, scheduled, evaluation_time):
        reminder_id = str(rem["id"])
        try:
            with self._lock:
                self._queued.discard(key)
                if not any(r == rem for r in self._reminders):
                    return {}
                self._executed.add(key)
                self._save_executed()
                smart_modes = dict(self._smart_modes)
            now = evaluation_time if self.submit_audio is None else datetime.now(timezone.utc)
            delay = now.timestamp() - scheduled.timestamp()
            if delay < 0 or (delay >= 60 and delay > int(rem.get("late_seconds") or 0)):
                status, detail = "skipped", "Đã hết thời gian phát lời nhắc."
            elif is_night_mode_active(smart_modes, now_dt=now, tz_name=scheduled.tzinfo.key):
                status, detail = "skipped", "Đã bỏ qua lời nhắc trong Chế độ ban đêm."
            else:
                if self.execution_started is not None:
                    self.execution_started(reminder_id, occurrence)
                status, detail = self._play_reminder(rem, scheduled, evaluation_time)
        except Exception as exc:
            status, detail = "failed", str(exc)
        if self.execution_reporter is not None:
            try:
                self.execution_reporter(reminder_id, occurrence, status, detail)
            except Exception:
                logger.exception("[ReminderScheduler] Không lưu được báo cáo lời nhắc.")
        return dict(reminder_id=reminder_id, name=rem.get("name", ""), occurrence=occurrence,
                    status=status, detail=detail)

    def _play_reminder(self, rem: dict[str, Any], scheduled: datetime, evaluation_time: datetime) -> tuple[str, str]:
        def still_due():
            now = evaluation_time if self.submit_audio is None else datetime.now(timezone.utc)
            delay = now.timestamp() - scheduled.timestamp()
            with self._lock:
                current = rem in self._reminders
                night = is_night_mode_active(self._smart_modes, now_dt=now, tz_name=scheduled.tzinfo.key)
            return current and not night and 0 <= delay and (delay < 60 or delay <= int(rem.get("late_seconds") or 0))

        used_local_tts = False
        volume = int(rem.get("volume") if rem.get("volume") is not None else 70)
        asset_id = str(rem.get("asset_id") or "").strip()
        audio_path: Path | None = None

        if asset_id and self.asset_resolver is not None:
            audio_path = self.asset_resolver(asset_id)

        if audio_path is None or not audio_path.exists():
            if rem.get("source") == "audio" or (asset_id and rem.get("source") != "tts"):
                return "failed", "Không có file âm thanh đã chọn trong bộ nhớ đệm hoặc trên máy chủ."
            text = str(rem.get("text") or rem.get("name") or "").strip()
            audio_path = self.audio_player.synthesize_tts_wav(text)
            used_local_tts = True
            if audio_path == self.audio_player.chime_path:
                return "failed", "Không thể tổng hợp giọng nói tiếng Việt ngoại tuyến."

        ok, detail = self.audio_player.play_file(
            audio_path,
            volume=volume,
            priority=1,
            wait_for_completion=True,
            start_guard=still_due,
            label=f"reminder:{rem.get('name', rem.get('id', ''))}",
        )
        if ok and used_local_tts:
            detail = "TTS ngoại tuyến. " + detail
        return ("played" if ok else "failed"), detail
