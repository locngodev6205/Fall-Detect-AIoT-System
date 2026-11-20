"""Audio regression tests with no physical speaker, network, or provider dependency."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from fall_detect.edge.audio import live_input
from fall_detect.edge.audio.audio_player import AudioPlayer
from fall_detect.edge.audio.bluetooth_manager import BluetoothSpeakerManager
from fall_detect.edge.audio.scheduler import ReminderScheduler
from fall_detect.edge.audio.worker import AudioWorker
from fall_detect.edge.client.device_client import DeviceClient
from fall_detect.edge.client.live_streamer import LiveStreamer


class AudioHardeningTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bt = BluetoothSpeakerManager(force_mock=True)
        self.player = AudioPlayer(self.bt, self.root / "audio")
        self.addCleanup(self.player.stop)

    def test_once_midnight_asset_failure_and_restart_dedup(self):
        rem = dict(id="audio-1", time="23:59", once_date="2026-11-20", version=4,
                   late_seconds=90, timezone="Asia/Ho_Chi_Minh", asset_id="missing", source="audio")
        for restart in (False, True):
            scheduler = ReminderScheduler(self.player, cache_dir=self.root)
            scheduler.apply_config(dict(reminders=[rem], smart_modes=dict(night_mode_enabled=False)))
            with patch.object(self.player, "synthesize_tts_wav") as tts:
                results = scheduler.evaluate_due(datetime(2026, 11, 20, 17, 0, 15, tzinfo=timezone.utc))
                tts.assert_not_called()
            if restart:
                self.assertEqual(results, [])
            else:
                self.assertEqual(results[0]["status"], "failed")
                self.assertEqual(results[0]["occurrence"], "2026-11-20T23:59:v4")

    def test_zero_late_and_tts_unavailable(self):
        scheduler = ReminderScheduler(self.player, cache_dir=self.root)
        self.player._has_espeak = None
        scheduler.apply_config(dict(reminders=[dict(id="tts", time="10:00", weekdays=[4],
                                                    timezone="UTC", source="tts", text="Xin chào")]))
        self.assertEqual(scheduler.evaluate_due(datetime(2026, 11, 20, 10, 1, tzinfo=timezone.utc)), [])
        results = scheduler.evaluate_due(datetime(2026, 11, 20, 10, 0, 59, tzinfo=timezone.utc))
        self.assertEqual(results[0]["status"], "failed")
        self.assertIn("tổng hợp", results[0]["detail"])

    def test_dst_gap_skipped_and_fold_has_single_occurrence(self):
        scheduler = ReminderScheduler(self.player, cache_dir=self.root,
                                      asset_resolver=lambda _: self.player.chime_path)
        scheduler.apply_config(dict(reminders=[dict(id="dst", time="02:30", weekdays=[6],
                                                    timezone="Europe/Berlin", source="audio",
                                                    asset_id="local", late_seconds=3600)],
                                    smart_modes=dict(night_mode_enabled=False)))
        self.assertEqual(scheduler.evaluate_due(datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)), [])
        self.assertEqual(scheduler.evaluate_due(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc))[0]["status"],
                         "played")
        self.assertEqual(scheduler.evaluate_due(datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)), [])

    def test_command_poll_returns_during_long_playback_and_acks_after(self):
        client = DeviceClient("http://fixture", "fixture", cache_dir=self.root)
        self.addCleanup(client.stop)
        worker = AudioWorker(capacity=1)
        release = threading.Event()
        self.addCleanup(worker.join)
        self.addCleanup(worker.stop)
        self.addCleanup(release.set)
        future = worker.submit(lambda: (release.wait(5), "finished"))
        command = {"id": "id", "status": "pending", "kind": "play_audio"}
        client._request = Mock(side_effect=lambda method, path, **kwargs: SimpleNamespace(
            status_code=200, json=lambda: [command] if path == "/api/device/commands" else {}))
        client.set_command_handler(Mock(return_value=future))
        self.assertTrue(worker.is_busy())
        self.assertIsNone(worker.submit(lambda: None))
        self.assertEqual(client.poll_and_execute_commands(), 1)
        self.assertFalse(future.done())
        client.poll_and_execute_commands()
        self.assertEqual(client.send_heartbeat(), {})
        statuses = lambda: [call.kwargs["json_body"]["status"] for call in client._request.call_args_list
                            if call.args[1].endswith("/ack")]
        self.assertEqual(statuses(), ["accepted", "executing"])
        recorded = threading.Event()
        future.add_done_callback(lambda _: recorded.set())
        release.set()
        self.assertTrue(recorded.wait(2))
        self.assertFalse(worker.is_busy())
        client.poll_and_execute_commands()
        self.assertEqual(statuses(), ["accepted", "executing", "executed"])

    def test_execution_outbox_restarts_and_retries_non_200(self):
        client = DeviceClient("http://fixture", "fixture", cache_dir=self.root)
        for key in ("occ-a", "occ-b"):
            client.report_execution("id", key, "played")
        client._request = Mock(side_effect=requests.ConnectionError)
        with patch("fall_detect.edge.client.device_client.time.time", return_value=100):
            client._flush_executions()
        client.stop()
        restarted = DeviceClient("http://fixture", "fixture", cache_dir=self.root)
        self.addCleanup(restarted.stop)
        restarted._request = Mock(return_value=SimpleNamespace(status_code=200))
        with patch("fall_detect.edge.client.device_client.time.time", return_value=200):
            restarted._flush_executions()
            restarted._flush_executions()
        self.assertCountEqual(
            [call.kwargs["json_body"]["occurrence"] for call in restarted._request.call_args_list],
            ["occ-a", "occ-b"])

    def test_restart_reports_unknown_outcome_and_does_not_reexecute_command(self):
        client = DeviceClient("http://fixture", "fixture", cache_dir=self.root)
        client.begin_execution("id", "occ")
        client._store_audio_receipt("command", "executing")
        client._request = Mock()
        client._flush_executions()
        client._request.assert_not_called()
        client.stop()

        restarted = DeviceClient("http://fixture", "fixture", cache_dir=self.root)
        self.addCleanup(restarted.stop)
        handler = Mock()
        restarted.set_command_handler(handler)
        restarted._request = Mock(return_value=SimpleNamespace(
            status_code=200, json=lambda: [{"id": "command", "kind": "play_audio"}]))
        restarted.poll_and_execute_commands()
        restarted._flush_executions()
        handler.assert_not_called()
        self.assertCountEqual(
            [call.kwargs["json_body"]["status"] for call in restarted._request.call_args_list
             if "json_body" in call.kwargs], ["failed", "failed"])

    def test_emergency_preempts_live_mock_and_cannot_resume_old_stream(self):
        stream = self.player.start_live_stream("audio/webm")
        self.assertIsNotNone(stream)
        self.assertTrue(self.player.trigger_emergency_siren("fall")[0])
        with self.assertRaises(ConnectionError):
            asyncio.run(stream.write(b"data"))
        self.player.finish_live_stream(stream)

    def test_file_output_exit_codes_and_preemption(self):
        self.bt.mock_mode = False
        with patch.object(self.bt, "is_speaker_ready", return_value=True), \
             patch.object(self.bt, "get_status", return_value=dict(sink="fixture", ready=True, mock_mode=False,
                                                                 backend="wpctl")), \
             patch.object(self.bt, "apply_volume", return_value=True), \
             patch.object(self.player, "_spawn_bluetooth_player",
                          side_effect=lambda *args: subprocess.Popen(["sh", "-c", "exit 7"])):
            result = self.player.play_file(self.player.chime_path, wait_for_completion=True)
            self.assertFalse(result[0])
            self.assertIn("mã 7", result[1])

        file_started = threading.Event()
        def spawn(path, *_):
            proc = subprocess.Popen(["sleep", "120"] if path == self.player.chime_path else ["true"])
            if path == self.player.chime_path:
                file_started.set()
            return proc
        worker = AudioWorker()
        self.addCleanup(worker.join)
        self.addCleanup(worker.stop)
        self.addCleanup(self.player.stop)
        with patch.object(self.bt, "is_speaker_ready", return_value=True), \
             patch.object(self.bt, "get_status", return_value=dict(sink="fixture", ready=True, mock_mode=False,
                                                                 backend="wpctl")), \
             patch.object(self.bt, "apply_volume", return_value=True), \
             patch.object(self.player, "_spawn_bluetooth_player", side_effect=spawn):
            future = worker.submit(lambda: self.player.play_file(self.player.chime_path, wait_for_completion=True))
            self.assertTrue(file_started.wait(2))
            self.assertFalse(future.done())
            self.assertTrue(self.player.trigger_emergency_siren("gas")[0])
            self.assertIn("bị ngắt", future.result(timeout=3)[1])


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_receiver_writes_before_stop_and_cleans_up_on_disconnect(self):
        stream = Mock()
        stream.write = Mock(side_effect=lambda chunk: asyncio.sleep(0))
        finish = Mock()
        client = LiveStreamer("http://fixture", "fixture", start_ptt=lambda _: stream, finish_ptt=finish)
        client._running = True
        messages = iter([
            json.dumps(dict(type="start", mime="audio/webm", session="first")),
            b"chunk",
            json.dumps(dict(type="stop", session="first")),
            json.dumps(dict(type="start", mime="audio/ogg", session="second")),
            b"new",
        ])
        replies = []
        async def recv():
            try:
                message = next(messages)
            except StopIteration as exc:
                raise ConnectionError from exc
            if isinstance(message, str) and json.loads(message)["type"] == "stop":
                stream.write.assert_called_once_with(b"chunk")
                finish.assert_not_called()
            return message
        async def send(value):
            replies.append(json.loads(value)["type"])
        with self.assertRaises(ConnectionError):
            await client._receive_audio(SimpleNamespace(recv=recv, send=send))
        self.assertEqual(replies, ["ready", "received", "ready", "received"])
        self.assertEqual(finish.call_count, 2)

    async def test_full_decoder_pipe_times_out_and_children_are_reaped(self):
        popen = subprocess.Popen

        def start(command, **options):
            return popen(["sleep", "30"], **options)

        with patch.object(live_input.subprocess, "Popen", side_effect=start):
            stream = live_input.LiveInput("audio/webm", "fixture", "wpctl")
        try:
            with self.assertRaises(TimeoutError):
                for _ in range(8):
                    await stream.write(bytes(live_input.MAX_CHUNK))
        finally:
            stream.close()
        self.assertIsNotNone(stream.decoder.poll())
        self.assertIsNotNone(stream.output.poll())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("cat"), "Requires local FFmpeg and cat")
    async def test_ffmpeg_outputs_pcm_before_end_of_webm_and_ogg(self):
        for mime, format_name in live_input.FORMATS.items():
            with self.subTest(mime=mime), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "stream"
                source = subprocess.check_output([
                    "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "4", "-c:a", "libopus", "-cluster_time_limit" if format_name == "webm" else
                    "-page_duration", "100" if format_name == "webm" else "100000",
                    "-f", format_name, "pipe:1",
                ])
                real_popen = subprocess.Popen
                with path.open("wb") as pcm:
                    def start(command, **kwargs):
                        if command[0] == "pw-cat":
                            return real_popen(["cat"], stdin=kwargs["stdin"], stdout=pcm)
                        return real_popen(command, **kwargs)
                    with patch.object(live_input.subprocess, "Popen", side_effect=start):
                        stream = live_input.LiveInput(mime, "fixture", "wpctl")
                    try:
                        prefix = source[:len(source) // 2]
                        for offset in range(0, len(prefix), 1800):
                            await stream.write(prefix[offset:offset + 1800])
                            await asyncio.sleep(.01)
                        for _ in range(100):
                            if path.stat().st_size > 1024:
                                break
                            await asyncio.sleep(.01)
                        self.assertGreater(path.stat().st_size, 1024)
                        self.assertIsNone(stream.decoder.poll())
                    finally:
                        stream.close()
