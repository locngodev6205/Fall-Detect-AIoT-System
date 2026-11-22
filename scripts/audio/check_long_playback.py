#!/usr/bin/env python3
"""Check the Edge worker and ACK sequencing during 65 seconds of local playback.

The file is silent and FFmpeg sends it to null in real time. API responses and
Bluetooth readiness use fixtures. No hardware or remote service is contacted.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fall_detect.edge.audio.audio_player import AudioPlayer  # noqa: E402
from fall_detect.edge.audio.bluetooth_manager import BluetoothSpeakerManager  # noqa: E402
from fall_detect.edge.audio.scheduler import ReminderScheduler  # noqa: E402
from fall_detect.edge.audio.worker import AudioWorker  # noqa: E402
from fall_detect.edge.client.device_client import DeviceClient  # noqa: E402


def silent_wav(path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(bytes(65 * 8000 * 2))


def spawn_null(path, *_):
    return subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-re", "-i",
                             str(path), "-f", "null", "-"])


def exercise(root):
    sample = root / "silence.wav"
    silent_wav(sample)
    speaker = BluetoothSpeakerManager(force_mock=True)
    player = AudioPlayer(speaker, root / "media")
    client = DeviceClient("http://example.test", "fixture", cache_dir=root)
    worker = AudioWorker()
    scheduler = ReminderScheduler(player, cache_dir=root, submit_audio=worker.submit)
    acknowledgements = []
    command = {"id": "clip-65s", "status": "pending", "kind": "play_audio"}

    def request(method, path, **kwargs):
        if path.endswith("/ack"):
            acknowledgements.append(kwargs["json_body"]["status"])
        return SimpleNamespace(status_code=200,
                               json=lambda: [command] if path.endswith("/commands") else (kwargs["json_body"] if path.endswith("/ack") else {}))

    sink = {"sink": "null", "ready": True, "mock_mode": False, "backend": "wpctl"}
    client._request = request
    client.set_command_handler(lambda _: worker.submit(
        lambda: player.play_file(sample, wait_for_completion=True)))
    started = time.monotonic()
    heartbeat_count = scheduler_count = 0
    try:
        with (
            patch.object(speaker, "mock_mode", False),
            patch.object(speaker, "is_speaker_ready", return_value=True),
            patch.object(speaker, "apply_volume", return_value=True),
            patch.object(speaker, "get_status", return_value=sink),
            patch.object(player, "_spawn_bluetooth_player", side_effect=spawn_null),
        ):
            while "executed" not in acknowledgements:
                elapsed = time.monotonic() - started
                if "failed" in acknowledgements or elapsed > 82:
                    raise RuntimeError(f"Playback failed: {acknowledgements}")
                client.poll_and_execute_commands()
                if elapsed >= heartbeat_count * 5:
                    if client.send_heartbeat() != {}:
                        raise RuntimeError("Heartbeat did not receive the fixture response")
                    heartbeat_count += 1
                if elapsed >= scheduler_count:
                    scheduler.evaluate_due()
                    scheduler_count += 1
                time.sleep(0.05)
    finally:
        worker.stop()
        player.stop()
        worker.join()
        client.stop()
    elapsed = time.monotonic() - started
    if not 60 <= elapsed <= 82 or heartbeat_count < 13 or scheduler_count < 60:
        raise RuntimeError("Playback or I/O cadence was outside the expected range")
    if acknowledgements != ["accepted", "executing", "executed"]:
        raise RuntimeError(f"Unexpected command lifecycle: {acknowledgements}")
    print(f"65 s WAV to null: {elapsed:.2f} s, {heartbeat_count} heartbeats, "
          f"{scheduler_count} scheduler checks, ACKs {acknowledgements}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        exercise(Path(temp))
