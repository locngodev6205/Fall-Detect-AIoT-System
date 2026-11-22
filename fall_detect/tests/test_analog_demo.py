"""Analog routing fixtures. No audio devices are touched."""
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fall_detect.edge.audio.audio_player import AudioPlayer
from fall_detect.edge.audio.bluetooth_manager import BluetoothSpeakerManager


class AnalogDemoTests(unittest.TestCase):
    def setUp(self):
        self.bt = BluetoothSpeakerManager(force_mock=False, output_mode="analog_demo")
        self.bt._has_wpctl = True
        self.status = "Audio\n ├─ Sinks:\n │   20. HDMI\n │   59. Built-in Audio\n ├─ Sources:\n"

    def test_selects_headphone_serial_and_never_changes_default(self):
        props = 'api.alsa.card.name = "bcm2835 Headphones"\nobject.serial = "123"'
        with patch("fall_detect.edge.audio.bluetooth_manager.subprocess.run", side_effect=[
            SimpleNamespace(stdout=self.status), SimpleNamespace(stdout='api.alsa.card.name = "HDMI"'),
            SimpleNamespace(stdout=props),
        ]) as run:
            self.assertEqual(self.bt.refresh_sink(attempt_connect=True), "123")
            self.assertEqual(self.bt.resolve_live_target("123", "wpctl"), "123")
            self.assertTrue(self.bt.apply_volume(75, refresh=False))
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             [["wpctl", "status"], ["wpctl", "inspect", "20"], ["wpctl", "inspect", "59"]])

    def test_missing_analog_never_uses_bluetooth(self):
        with patch.object(self.bt, "_detect_analog_sink", return_value=(None, "none")), \
             patch.object(self.bt, "detect_bluetooth_sink") as bluetooth:
            self.assertFalse(self.bt.is_speaker_ready())
            bluetooth.assert_not_called()

    def test_bluetooth_mode_never_looks_for_analog(self):
        bt = BluetoothSpeakerManager(force_mock=False)
        with patch.object(bt, "detect_bluetooth_sink", return_value=(None, "none")), \
             patch.object(bt, "_detect_analog_sink") as analog:
            self.assertFalse(bt.is_speaker_ready())
            analog.assert_not_called()

    def test_file_siren_and_stream_use_same_target(self):
        with tempfile.TemporaryDirectory() as directory:
            player = AudioPlayer(self.bt, Path(directory))
            self.addCleanup(player.stop)
            with patch.object(self.bt, "_detect_analog_sink", return_value=("123", "wpctl")), \
                 patch.object(player, "_spawn_bluetooth_player",
                              side_effect=lambda *a, **kw: subprocess.Popen(["true"])) as spawn:
                result = player.play_file(player.chime_path, wait_for_completion=True)
                self.assertTrue(result[0], result)
                self.assertEqual(spawn.call_args.args[1:], ("123", "wpctl"))
                self.assertLessEqual(spawn.call_args.kwargs["stream_volume"], 0.25)
                self.assertTrue(player.trigger_emergency_siren("gas")[0])
                self.assertEqual(spawn.call_args.args[1:], ("123", "wpctl"))
                proc = player._current_proc
                if proc:
                    proc.wait(timeout=2)
            with patch.object(self.bt, "_detect_analog_sink", return_value=("123", "wpctl")), \
                 patch("fall_detect.edge.audio.audio_player.LiveInput") as live:
                self.assertIs(player.start_live_stream("audio/webm"), live.return_value)
                live.assert_called_once_with("audio/webm", "123", "wpctl", stream_volume=0.2125)
                player.finish_live_stream(live.return_value)
