"""Local process fixtures for audio acceptance. No hardware or audible output."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fall_detect.edge.audio.audio_player import AudioPlayer
from fall_detect.edge.audio.bluetooth_manager import BluetoothSpeakerManager
from fall_detect.edge.audio.live_input import LiveInput
from fall_detect.edge.client.device_client import DeviceClient


class PreemptionTests(unittest.TestCase):
    def test_emergency_process_preemption_matrix(self):
        for kind in ("gas", "fall"):
            for source in ("file", "ptt"):
                with self.subTest(kind=kind, source=source), tempfile.TemporaryDirectory() as directory:
                    bt = BluetoothSpeakerManager(force_mock=True)
                    player = AudioPlayer(bt, Path(directory))
                    bt.mock_mode = False
                    children = []

                    def stubborn():
                        proc = subprocess.Popen(
                            [sys.executable, "-u", "-c",
                             "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                             "print('ready'); time.sleep(20)"],
                            stdout=subprocess.PIPE,
                        )
                        children.append(proc)
                        self.assertEqual(proc.stdout.readline(), b"ready\n")
                        return proc

                    def spawn(path, *_):
                        if path == player.chime_path:
                            return stubborn()
                        spawned_at.append(time.monotonic())
                        return subprocess.Popen(["true"])

                    spawned_at = []
                    live = None
                    try:
                        with (
                            patch.object(bt, "is_speaker_ready", return_value=True),
                            patch.object(bt, "apply_volume", return_value=True),
                            patch.object(bt, "get_status", return_value={
                                "sink": "fixture", "backend": "wpctl", "mock_mode": False,
                            }),
                            patch.object(player, "_spawn_bluetooth_player", side_effect=spawn),
                        ):
                            if source == "file":
                                self.assertTrue(player.play_file(player.chime_path)[0])
                            else:
                                live = LiveInput("audio/webm", "fixture", "mock")
                                live.decoder, live.output = stubborn(), stubborn()
                                player._live_input = live
                            started = time.monotonic()
                            self.assertTrue(player.trigger_emergency_siren(kind)[0])
                            if live is not None:
                                player.finish_live_stream(live)
                            end = time.monotonic()
                            self.assertTrue(all(child.poll() is not None for child in children))
                            spawn_ms = (spawned_at[0] - started) * 1000
                            complete_ms = (end - started) * 1000
                            print(f"{kind}/{source}: emergency spawn {spawn_ms:.1f} ms, "
                                  f"old children reaped and call completed by {complete_ms:.1f} ms",
                                  flush=True)
                            self.assertLess(complete_ms, 500, "fixture acceptance budget")
                    finally:
                        player.stop()
                        for child in children:
                            if child.poll() is None:
                                child.kill()
                            child.wait(timeout=2)
                            child.stdout.close()


class ReceiptCapacityTests(unittest.TestCase):
    def test_capacity_preserves_unconfirmed_receipts_and_recovers_after_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            client = DeviceClient("http://fixture", "fixture", cache_dir=directory)
            self.addCleanup(client.stop)
            client.set_command_handler(Mock(return_value=(True, "done")))
            commands = [{"id": f"cmd{i}", "kind": "test_speaker", "status": "pending"} for i in range(4)]
            stall = True

            def request(method, path, **kwargs):
                if method == "GET":
                    return SimpleNamespace(status_code=200, json=lambda: commands)
                status = kwargs["json_body"]["status"]
                if stall and status == "executed":
                    return SimpleNamespace(status_code=404)
                return SimpleNamespace(status_code=200, json=lambda: {"status": status})

            client._request = Mock(side_effect=request)
            with patch("fall_detect.edge.client.device_client.MAX_PENDING_AUDIO_RECEIPTS", 2):
                self.assertEqual(client.poll_and_execute_commands(), 2)
                self.assertEqual(client.poll_and_execute_commands(), 0)
                with sqlite3.connect(client._audio_db) as db:
                    rows = db.execute("SELECT id FROM command_receipts ORDER BY id").fetchall()
                    self.assertEqual(rows, [("cmd0",), ("cmd1",)])
                    db.execute("UPDATE command_receipts SET retry_at=0")
                stall = False
                self.assertEqual(client.poll_and_execute_commands(), 2)
                self.assertEqual(client._command_handler.call_count, 4)

    def test_startup_caps_only_reconciled_history(self):
        with tempfile.TemporaryDirectory() as directory:
            client = DeviceClient("http://fixture", "fixture", cache_dir=directory)
            for name in ("old", "recent", "pending"):
                client._store_audio_receipt(name, "executed")
            with sqlite3.connect(client._audio_db) as db:
                db.execute("UPDATE command_receipts SET backend_status='expired' WHERE id != 'pending'")
            client.stop()
            with patch("fall_detect.edge.client.device_client.MAX_RECONCILED_AUDIO_RECEIPTS", 1):
                restarted = DeviceClient("http://fixture", "fixture", cache_dir=directory)
            try:
                with sqlite3.connect(restarted._audio_db) as db:
                    self.assertEqual(db.execute(
                        "SELECT id,backend_status FROM command_receipts ORDER BY rowid"
                    ).fetchall(), [("recent", "expired"), ("pending", None)])
            finally:
                restarted.stop()
