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

    def test_hot_switch_waits_for_live_and_emergency_and_restores_from_cache(self):
        from fall_detect.edge.client.device_client import ConfigDeferred, DeviceClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bt = BluetoothSpeakerManager(force_mock=True)
            player = AudioPlayer(bt, root / 'sound')
            client = DeviceClient('http://fixture', 'fixture', cache_dir=root)

            def apply(config):
                if not player.select_output(config['audio_output']):
                    raise ConfigDeferred()

            client.on_config_updated(apply)
            revision = {'audio_output': 'analog', 'version': 2}
            requests = []

            def request(method, path, **kwargs):
                requests.append((path, kwargs.get('json_body')))
                return SimpleNamespace(status_code=200, json=lambda: revision)

            client._request = request
            stream = player.start_live_stream('audio/webm')
            self.assertIsNotNone(stream)
            self.assertIsNone(client.sync_config())
            self.assertEqual(bt.output_mode, 'bluetooth')
            self.assertFalse((root / 'device_config.json').exists())
            player.finish_live_stream(stream)

            player._siren_in_flight.add('gas')
            self.assertIsNone(client.sync_config())
            self.assertEqual([path for path, _ in requests], ['/api/device/config'] * 2)
            player._siren_in_flight.clear()
            self.assertEqual(client.sync_config(), revision)
            self.assertEqual(bt.output_mode, 'analog')
            self.assertEqual(requests[-1][1]['version'], 2)

            report = {'mode': 'analog', 'ready': True, 'error': ''}
            client.send_heartbeat(audio_output=report)
            self.assertIn(('/api/device/heartbeat', {
                'observation': 'clear',
                'capabilities': {'camera': True, 'speaker': True, 'sensors': True},
                'audio_output': {**report, 'version': 2},
            }), requests)
            client.stop()
            player.stop()

            restarted = DeviceClient('http://fixture', '', cache_dir=root)
            fallback = BluetoothSpeakerManager(force_mock=True, output_mode='analog_demo')
            self.assertEqual(fallback.output_mode, 'analog')
            fallback.select_output('bluetooth')
            restarted.on_config_updated(lambda cfg: fallback.select_output(cfg['audio_output']))
            self.assertEqual(fallback.output_mode, 'analog')
            self.assertEqual(restarted.applied_version, 2)
            restarted.stop()
