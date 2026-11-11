"""Kiểm thử tự động Nhóm 4: Loa Bluetooth chuyên dụng + Còi khẩn cấp tại chỗ + Lịch nhắc Offline & Night Mode."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from zoneinfo import ZoneInfo

FALL_DETECT_ROOT = Path(__file__).resolve().parents[1]
if str(FALL_DETECT_ROOT) not in sys.path:
    sys.path.insert(0, str(FALL_DETECT_ROOT))

from edge.audio.audio_player import AudioPlayer  # noqa: E402
from edge.audio.bluetooth_manager import BluetoothSpeakerManager  # noqa: E402
from edge.audio.scheduler import ReminderScheduler  # noqa: E402


class Group4AudioAndSchedulerTests(unittest.TestCase):
    def test_wav_synthesis_valid_riff_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bt = BluetoothSpeakerManager(force_mock=True)
            player = AudioPlayer(bt, cache_dir=Path(tmp) / "audio")
            for wav_path in (player.chime_path, player.siren_path):
                self.assertTrue(wav_path.exists())
                with wave.open(str(wav_path), "rb") as wf:
                    self.assertEqual(wf.getnchannels(), 1)
                    self.assertEqual(wf.getsampwidth(), 2)
                    self.assertEqual(wf.getframerate(), 24000)
                    self.assertGreater(wf.getnframes(), 10000)

    def test_strict_bluetooth_only_blocks_playback_when_disconnected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bt = BluetoothSpeakerManager(force_mock=True)
            player = AudioPlayer(bt, cache_dir=Path(tmp) / "audio")

            # Khi loa Bluetooth kết nối -> phát thành công
            ok1, _ = player.execute_audio_command({"kind": "test_speaker", "payload": {"volume": 80}})
            self.assertTrue(ok1)

            # Khi loa Bluetooth đứt kết nối -> từ chối phát, tuyệt đối không fallback 3.5mm/HDMI
            bt.set_mock_connected(False)
            ok2, detail2 = player.execute_audio_command({"kind": "test_speaker", "payload": {"volume": 80}})
            self.assertFalse(ok2)
            self.assertIn("Loa Bluetooth chưa kết nối", detail2)

            # Kiểm tra bộ lọc node loại trừ triệt để HDMI / Analog 3.5mm nội bộ của Raspberry Pi
            bt_real = BluetoothSpeakerManager(speaker_mac="AA:BB:CC:11:22:33", force_mock=False)
            self.assertFalse(bt_real._matches_bluetooth_node("alsa_output.platform-bcm2835_audio.analog-stereo"))
            self.assertFalse(bt_real._matches_bluetooth_node("alsa_output.platform-fef00700.hdmi.hdmi-stereo"))
            self.assertTrue(bt_real._matches_bluetooth_node("bluez_output.AA_BB_CC_11_22_33.1"))

    def test_emergency_siren_and_gas_leak_never_silenced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bt = BluetoothSpeakerManager(force_mock=True)
            player = AudioPlayer(bt, cache_dir=Path(tmp) / "audio", siren_cooldown_s=1.0)

            # Còi báo té ngã phát ở mức âm lượng tối đa 100%
            ok_fall, _ = player.trigger_emergency_siren("fall", "Cảnh báo có người ngã!", now_monotonic=10.0)
            self.assertTrue(ok_fall)
            self.assertEqual(player.history[-1]["volume"], 100)
            self.assertEqual(player.history[-1]["label"], "emergency_fall")

            # Người dùng bấm nút Tắt âm tạm thời (`silence`) trên Web
            ok_sil, _ = player.execute_audio_command({"kind": "silence", "payload": {}})
            self.assertTrue(ok_sil)
            self.assertTrue(player.is_silenced())

            # Sự kiện té ngã tiếp theo trong thời gian silence được tạm ngắt
            ok_fall_muted, _ = player.trigger_emergency_siren("fall", now_monotonic=25.0)
            self.assertFalse(ok_fall_muted)

            # NHƯNG rò rỉ khí Gas vượt ngưỡng nguy hiểm PHẢI XUYÊN QUA `silence` (theo chuẩn DEVICE_API.md)!
            ok_gas, _ = player.trigger_emergency_siren("gas", "Cảnh báo rò rỉ khí gas!", now_monotonic=26.0)
            self.assertTrue(ok_gas)
            self.assertEqual(player.history[-1]["label"], "emergency_gas")
            self.assertEqual(player.history[-1]["volume"], 100)

    def test_offline_scheduler_persistence_and_night_mode_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "edge_cache"
            bt = BluetoothSpeakerManager(force_mock=True)
            player = AudioPlayer(bt, cache_dir=cache_dir / "audio")
            reported: list[tuple[str, str, str, str]] = []

            scheduler = ReminderScheduler(
                player,
                cache_dir=cache_dir,
                execution_reporter=lambda rid, occ, st, det: reported.append((rid, occ, st, det)),
            )
            config = {
                "smart_modes": {
                    "night_mode_enabled": True,
                    "night_start": "22:00",
                    "night_end": "06:00",
                },
                "reminders": [
                    {
                        "id": "rem-morning-meds",
                        "name": "Uống thuốc huyết áp",
                        "time": "07:30",
                        "weekdays": [0, 1, 2, 3, 4, 5, 6],
                        "once_date": None,
                        "timezone": "Asia/Ho_Chi_Minh",
                        "enabled": True,
                        "source": "tts",
                        "text": "Bác ơi nhớ uống thuốc huyết áp buổi sáng nhé.",
                        "volume": 75,
                        "version": 1,
                        "late_seconds": 120,
                    },
                    {
                        "id": "rem-late-water",
                        "name": "Uống nước tối muộn",
                        "time": "23:15",
                        "weekdays": [0, 1, 2, 3, 4, 5, 6],
                        "once_date": None,
                        "timezone": "Asia/Ho_Chi_Minh",
                        "enabled": True,
                        "source": "tts",
                        "text": "Nhắc uống nước.",
                        "volume": 65,
                        "version": 1,
                        "late_seconds": 60,
                    },
                ],
            }
            scheduler.apply_config(config)

            tz = ZoneInfo("Asia/Ho_Chi_Minh")
            # 1. Lúc 07:30:15 sáng -> Phát lời nhắc thành công (`played`)
            morning_dt = datetime(2026, 11, 9, 7, 30, 15, tzinfo=tz)
            due1 = scheduler.evaluate_due(now_utc=morning_dt)
            self.assertEqual(len(due1), 1)
            self.assertEqual(due1[0]["status"], "played")
            self.assertEqual(reported[-1][0], "rem-morning-meds")
            self.assertEqual(reported[-1][2], "played")

            # 2. Giả lập Pi khởi động lại lúc 07:30:45 -> Đọc file lưu vết trên đĩa, KHÔNG phát lặp lần 2!
            scheduler_restarted = ReminderScheduler(player, cache_dir=cache_dir)
            scheduler_restarted.apply_config(config)
            due_dup = scheduler_restarted.evaluate_due(now_utc=datetime(2026, 11, 9, 7, 30, 45, tzinfo=tz))
            self.assertEqual(len(due_dup), 0)

            # 3. Lúc 23:15:10 đêm -> Đang trong Chế độ ban đêm (22:00-06:00) -> Tự động tạm hoãn (`skipped`)!
            night_dt = datetime(2026, 11, 9, 23, 15, 10, tzinfo=tz)
            due_night = scheduler.evaluate_due(now_utc=night_dt)
            self.assertEqual(len(due_night), 1)
            self.assertEqual(due_night[0]["status"], "skipped")
            self.assertEqual(reported[-1][0], "rem-late-water")
            self.assertEqual(reported[-1][2], "skipped")


if __name__ == "__main__":
    unittest.main()
