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

from datetime import datetime
import json
import logging
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
    ) -> None:
        self.audio_player = audio_player
        self.cache_dir = Path(cache_dir or (Path(__file__).resolve().parents[2] / "edge_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.cache_dir / "executed_reminders.json"
        self.asset_resolver = asset_resolver
        self.execution_reporter = execution_reporter

        self._lock = threading.Lock()
        self._reminders: list[dict[str, Any]] = []
        self._smart_modes: dict[str, Any] = {
            "night_mode_enabled": True,
            "night_start": "22:00",
            "night_end": "06:00",
        }
        self._executed: set[str] = self._load_executed()

    def _load_executed(self) -> set[str]:
        if not self.state_file.exists():
            return set()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(x) for x in data[-500:]}
        except Exception:
            pass
        return set()

    def _save_executed(self) -> None:
        try:
            recent = sorted(self._executed)[-500:]
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(recent, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception as exc:
            logger.debug("[ReminderScheduler] Không thể lưu trạng thái lịch nhắc: %s", exc)

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
        base_now = now_utc or datetime.now().astimezone()
        with self._lock:
            reminders = list(self._reminders)
            smart_modes = dict(self._smart_modes)

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
            today_iso = local_now.date().isoformat()

            once_date = rem.get("once_date")
            if once_date:
                if str(once_date) != today_iso:
                    continue
            else:
                weekdays = rem.get("weekdays") or []
                if local_now.weekday() not in weekdays:
                    continue

            try:
                sched_h, sched_m = (int(x) for x in time_str.split(":", 1))
                sched_dt = local_now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
            except ValueError:
                continue

            delta_s = (local_now - sched_dt).total_seconds()
            # Cho phép cửa sổ kích hoạt tối thiểu 60s (hoặc `late_seconds` nếu cấu hình lớn hơn)
            grace_s = max(60, int(rem.get("late_seconds") or 0))
            if delta_s < 0 or delta_s > grace_s:
                continue

            version = int(rem.get("version") or 1)
            occurrence = f"{today_iso}T{time_str}:v{version}"
            dedup_key = f"{reminder_id}:{occurrence}"

            with self._lock:
                if dedup_key in self._executed:
                    continue
                self._executed.add(dedup_key)
                self._save_executed()

            # Kiểm tra Chế độ ban đêm yên tĩnh: tạm hoãn lời nhắc sinh hoạt thường
            if is_night_mode_active(smart_modes, now_dt=local_now, tz_name=tz_name):
                status = "skipped"
                detail = "Tạm hoãn lời nhắc sinh hoạt trong khung giờ Chế độ ban đêm yên tĩnh."
                logger.info("[ReminderScheduler] Bỏ qua lời nhắc '%s' do Chế độ ban đêm.", rem.get("name"))
            else:
                status, detail = self._play_reminder(rem)
                log_result = logger.info if status == "played" else logger.warning
                log_result(
                    "[ReminderScheduler] Lời nhắc %r, lịch %s %s (%s): %s",
                    rem.get("name") or reminder_id,
                    today_iso,
                    time_str,
                    tz.key,
                    detail,
                )

            if self.execution_reporter is not None:
                try:
                    self.execution_reporter(reminder_id, occurrence, status, detail)
                except Exception as exc:
                    logger.warning("[ReminderScheduler] Lỗi gửi báo cáo execution: %s", exc)

            results.append(
                {
                    "reminder_id": reminder_id,
                    "name": rem.get("name", ""),
                    "occurrence": occurrence,
                    "status": status,
                    "detail": detail,
                }
            )
        return results

    def _play_reminder(self, rem: dict[str, Any]) -> tuple[str, str]:
        volume = int(rem.get("volume") if rem.get("volume") is not None else 70)
        asset_id = str(rem.get("asset_id") or "").strip()
        audio_path: Path | None = None

        if asset_id and self.asset_resolver is not None:
            audio_path = self.asset_resolver(asset_id)

        if audio_path is None or not audio_path.exists():
            text = str(rem.get("text") or rem.get("name") or "Lời nhắc sinh hoạt").strip()
            audio_path = self.audio_player.synthesize_tts_wav(text)

        ok, detail = self.audio_player.play_file(
            audio_path,
            volume=volume,
            priority=1,
            label=f"reminder:{rem.get('name', rem.get('id', ''))}",
        )
        return ("played" if ok else "failed"), detail
