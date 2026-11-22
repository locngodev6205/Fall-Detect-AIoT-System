"""No-hardware regression tests for Linux camera discovery and frame invalidation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from fall_detect.edge.camera_discovery import (
    normalize_camera_id, camera_sources, open_working_camera,
)
from fall_detect.edge.client.live_streamer import LiveStreamer


class CameraDiscoveryTests(TestCase):
    def test_auto_and_explicit_configuration(self):
        self.assertEqual(normalize_camera_id(None), "auto")
        self.assertEqual(normalize_camera_id(" AUTO "), "auto")
        self.assertEqual(normalize_camera_id("2"), 2)
        for invalid in ("-1", "by-id/not-a-camera", "abc"):
            with self.assertRaises(ValueError):
                normalize_camera_id(invalid)

    def test_prefer_stable_device_and_skip_duplicate_index(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "video1").touch()
            (root / "video2").touch()
            stable = root / "v4l" / "by-id"
            stable.mkdir(parents=True)
            (stable / "usb-webcam-video-index0").symlink_to(
                (root / "video1").resolve()
            )
            self.assertEqual(camera_sources("auto", root), [
                str(stable / "usb-webcam-video-index0"), str(root / "video2"),
            ])
            self.assertEqual(camera_sources(2, root), [2])

    def test_read_frame_required_and_failed_probes_released(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "video0").touch()
            (root / "video1").touch()
            bad = Mock()
            bad.isOpened.return_value = True
            bad.read.return_value = (False, None)
            good = Mock()
            good.isOpened.return_value = True
            good.read.return_value = (True, SimpleNamespace(size=150))
            cv2 = Mock(CAP_V4L2=200)
            cv2.VideoCapture.side_effect = [bad, good]
            cap, source = open_working_camera(cv2, "auto", device_root=root, probe_reads=2)
            self.assertIs(cap, good)
            self.assertEqual(source, str(root / "video1"))
            bad.release.assert_called_once()
            good.release.assert_not_called()
            self.assertEqual(cv2.VideoCapture.call_count, 2)

    def test_no_camera_and_failed_open_return_none(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(open_working_camera(Mock(), "auto", device_root=root), (None, None))
            failing = Mock()
            failing.isOpened.return_value = False
            (root / "video0").touch()
            cv2 = Mock(CAP_V4L2=200)
            cv2.VideoCapture.return_value = failing
            self.assertEqual(open_working_camera(cv2, "auto", device_root=root), (None, None))
            failing.release.assert_called_once()

    def test_streamer_clears_last_camera_frame(self):
        streamer = LiveStreamer("http://localhost:8188", "")
        streamer.update_frame_jpeg(b"\\xff\\xd8\\xffexample")
        self.assertIsNotNone(streamer.get_latest_jpeg())
        streamer.clear_frame()
        self.assertIsNone(streamer.get_latest_jpeg())
