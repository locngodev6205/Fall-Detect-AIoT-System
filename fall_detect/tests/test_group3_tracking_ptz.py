"""Kiểm thử tự động Nhóm 3: AI Pose Pan-Tilt Tracking + Night Mode + Web PTZ D-Pad & Smart Modes."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

import requests

FALL_DETECT_ROOT = Path(__file__).resolve().parents[1]
if str(FALL_DETECT_ROOT) not in sys.path:
    sys.path.insert(0, str(FALL_DETECT_ROOT))

from edge.client.device_client import DeviceClient  # noqa: E402
from edge.sensors.arduino_bridge import ArduinoBridge  # noqa: E402
from edge.tracking.pan_tilt_tracker import (  # noqa: E402
    PanTiltTracker,
    extract_person_center,
    is_night_mode_active,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _fake_mediapipe_pose(cx: float, cy: float, visibility: float = 0.95) -> SimpleNamespace:
    landmarks = [SimpleNamespace(x=0.5, y=0.5, visibility=0.1) for _ in range(33)]
    for idx in (11, 12, 23, 24):
        landmarks[idx] = SimpleNamespace(x=cx, y=cy, visibility=visibility)
    return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=landmarks))


class Group3TrackingAndPtzTests(unittest.TestCase):
    def test_extract_person_center_from_mediapipe_torso(self) -> None:
        pose = _fake_mediapipe_pose(0.22, 0.74)
        center = extract_person_center(pose)
        self.assertIsNotNone(center)
        assert center is not None
        self.assertAlmostEqual(center[0], 0.22, places=3)
        self.assertAlmostEqual(center[1], 0.74, places=3)

        # Tất cả khớp bị che khuất -> trả về None
        occluded = _fake_mediapipe_pose(0.2, 0.8, visibility=0.05)
        self.assertIsNone(extract_person_center(occluded))

    def test_night_mode_window_overnight_and_daytime(self) -> None:
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
        modes = {"night_mode_enabled": True, "night_start": "22:00", "night_end": "06:00"}
        self.assertTrue(is_night_mode_active(modes, datetime(2026, 11, 9, 23, 15, tzinfo=tz)))
        self.assertTrue(is_night_mode_active(modes, datetime(2026, 11, 9, 5, 45, tzinfo=tz)))
        self.assertFalse(is_night_mode_active(modes, datetime(2026, 11, 9, 10, 30, tzinfo=tz)))
        self.assertFalse(is_night_mode_active({**modes, "night_mode_enabled": False}, datetime(2026, 11, 9, 23, 0, tzinfo=tz)))

    def test_proportional_tracking_deadzone_and_night_detach(self) -> None:
        bridge = ArduinoBridge(force_mock=True)
        tracker = PanTiltTracker(
            bridge=bridge,
            deadzone_x=0.08,
            deadzone_y=0.08,
            kp_pan=20.0,
            kp_tilt=15.0,
            min_interval_s=0.05,
            ema_alpha=1.0,
            manual_override_hold_s=0.1,
        )
        daytime = datetime(2026, 11, 9, 14, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        nighttime = datetime(2026, 11, 9, 23, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

        # 1. Người ở giữa khung hình (trong vùng chết) -> Servo giữ nguyên 90°, 90°
        res_mid = tracker.update_from_pose(_fake_mediapipe_pose(0.52, 0.49), now_dt=daytime, now_monotonic=10.0)
        self.assertFalse(res_mid["moved"])
        self.assertEqual(res_mid["reason"], "in_deadzone")
        self.assertEqual(bridge.get_servo_state()["pan"], 90)
        self.assertEqual(bridge.get_servo_state()["tilt"], 90)

        # 2. Người lệch sang TRÁI (cx=0.20) và XUỐNG DƯỚI (cy=0.80)
        # Với PAN_DIRECTION=-1 -> xoay LEFT làm pan tăng (>90); TILT_DIRECTION=1 -> xoay DOWN làm tilt giảm (<90)
        res_move = tracker.update_from_pose(_fake_mediapipe_pose(0.20, 0.80), now_dt=daytime, now_monotonic=11.0)
        self.assertTrue(res_move["moved"])
        self.assertGreater(res_move["servo"]["pan"], 90)
        self.assertLess(res_move["servo"]["tilt"], 90)

        # 3. Bước sang giờ ban đêm (23:30) -> Tự khóa bám người & ngắt xung PWM (enabled=False)
        res_night = tracker.update_from_pose(_fake_mediapipe_pose(0.15, 0.85), now_dt=nighttime, now_monotonic=12.0)
        self.assertFalse(res_night["moved"])
        self.assertEqual(res_night["reason"], "night_mode")
        self.assertFalse(bridge.get_servo_state()["enabled"])

        # 4. Tắt công tắc `servo_tracking` ngay cả ban ngày -> Vẫn ngắt xung PWM
        bridge.center()
        self.assertTrue(bridge.get_servo_state()["enabled"])
        tracker.update_smart_modes({"servo_tracking": False}, now_dt=daytime)
        self.assertFalse(bridge.get_servo_state()["enabled"])
        res_off = tracker.update_from_pose(_fake_mediapipe_pose(0.85, 0.20), now_dt=daytime, now_monotonic=13.0)
        self.assertEqual(res_off["reason"], "disabled")

    def test_end_to_end_backend_smart_modes_and_web_ptz_commands(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        cname = f"annha-test-group3-{port}"
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    cname,
                    "-p",
                    f"127.0.0.1:{port}:8000",
                    "-e",
                    "DATABASE_BACKEND=sqlite",
                    "-e",
                    "MQTT_ENABLED=false",
                    "-e",
                    "WORKER_ENABLED=false",
                    "-e",
                    "MEDIA_STORAGE_PROVIDER=local",
                    "-e",
                    f"APP_ORIGINS={base_url}",
                    "-e",
                    f"PUBLIC_URL={base_url}",
                    "annha-backend:latest",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            for _ in range(40):
                try:
                    if requests.get(f"{base_url}/api/health", timeout=1.0).status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.15)

            setup_py = """
import json, time
from src import db, security, services
db.initialize()
uid, hid, rid = db.uid(), db.uid(), db.uid()
sess, csrf = "sess-group3-token-123456", "csrf-group3-token-123456"
with db.connect() as conn:
    conn.execute("INSERT INTO users(id,email,name,password,verified,created_at) VALUES(?,?,?,?,1,?)",
                 (uid, "owner3@test.local", "Chủ nhà", security.password_hash("Pass123!"), db.now()))
    conn.execute("INSERT INTO homes(id,name,timezone,settings) VALUES(?,?,?,?)",
                 (hid, "Nhà Kiểm Thử Nhóm 3", "Asia/Ho_Chi_Minh", "{}"))
    conn.execute("INSERT INTO memberships(home_id,user_id,role,scopes,rights) VALUES(?,?,'owner','[]','{}')",
                 (hid, uid))
    conn.execute("INSERT INTO rooms(id,home_id,name) VALUES(?,?,?)", (rid, hid, "Phòng ngủ"))
    conn.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)",
                 (security.digest(sess), uid, csrf, time.time() + 3600))
prov = services.provision_device("Pi 4 Phòng ngủ")
print(json.dumps({"home_id": hid, "room_id": rid, "session": sess, "csrf": csrf, "prov": prov}))
"""
            out = subprocess.run(
                ["docker", "exec", cname, "python", "-c", setup_py],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            meta = json.loads(out.splitlines()[-1])

            web = requests.Session()
            web.cookies.set("annha_session", meta["session"])
            headers = {"X-CSRF-Token": meta["csrf"], "Origin": base_url}

            claim_res = web.post(
                f"{base_url}/api/homes/{meta['home_id']}/cameras/claim",
                json={
                    "code": meta["prov"]["pairing_code"],
                    "name": "Pi 4 Phòng ngủ",
                    "room_id": meta["room_id"],
                },
                headers=headers,
                timeout=5,
            )
            self.assertIn(claim_res.status_code, (200, 201), claim_res.text)
            cam_id = claim_res.json()["id"]

            bridge = ArduinoBridge(force_mock=True)
            tracker = PanTiltTracker(bridge=bridge)

            def on_cmd(cmd: dict) -> tuple[bool, str]:
                if cmd["kind"] in ("ptz_move", "ptz_center"):
                    return tracker.execute_ptz_command(cmd)
                return False, "Unsupported"

            client = DeviceClient(
                base_url=base_url,
                device_token=meta["prov"]["device_token"],
                cache_dir=Path(tmp.name) / "edge_cache",
            )
            client.set_command_handler(on_cmd)
            client.on_config_updated(lambda cfg: tracker.update_smart_modes(cfg.get("smart_modes")))

            # Đồng bộ cấu hình mặc định ban đầu (version 1)
            hb1 = client.send_heartbeat(observation="clear")
            assert hb1 is not None
            self.assertEqual(hb1["desired_version"], 1)
            self.assertTrue(tracker.is_fall_detection_enabled())

            # Chủ nhà tắt Fall Detection + tắt Servo Tracking + đặt giờ đêm 21:30-05:30 trên Web
            put_modes = web.put(
                f"{base_url}/api/cameras/{cam_id}/smart-modes",
                json={
                    "fall_detection": False,
                    "servo_tracking": False,
                    "night_mode_enabled": True,
                    "night_start": "21:30",
                    "night_end": "05:30",
                },
                headers=headers,
                timeout=5,
            )
            self.assertEqual(put_modes.status_code, 200, put_modes.text)
            self.assertEqual(put_modes.json()["desired_version"], 2)

            # Thiết bị nhận config mới qua heartbeat -> tự cập nhật tracker & ngắt PWM servo
            hb2 = client.send_heartbeat(observation="clear")
            assert hb2 is not None
            self.assertEqual(hb2["desired_version"], 2)
            self.assertFalse(tracker.is_fall_detection_enabled())
            self.assertEqual(tracker.get_smart_modes()["night_start"], "21:30")
            self.assertFalse(bridge.get_servo_state()["enabled"])

            # Chủ nhà bấm nút D-Pad xoay TRÁI 12° rồi bấm Giữa 90°
            cmd_left = web.post(
                f"{base_url}/api/cameras/{cam_id}/commands",
                json={
                    "kind": "ptz_move",
                    "direction": "LEFT",
                    "degrees": 12,
                    "idempotency_key": "ptz-left-test-0001",
                },
                headers=headers,
                timeout=5,
            )
            self.assertEqual(cmd_left.status_code, 201, cmd_left.text)
            handled1 = client.poll_and_execute_commands()
            self.assertEqual(handled1, 1)
            self.assertEqual(bridge.get_servo_state()["pan"], 102)  # 90 + (-1 * -12) = 102°

            cmd_center = web.post(
                f"{base_url}/api/cameras/{cam_id}/commands",
                json={
                    "kind": "ptz_center",
                    "idempotency_key": "ptz-center-test-0002",
                },
                headers=headers,
                timeout=5,
            )
            self.assertEqual(cmd_center.status_code, 201, cmd_center.text)
            handled2 = client.poll_and_execute_commands()
            self.assertEqual(handled2, 1)
            self.assertEqual(bridge.get_servo_state()["pan"], 90)
            self.assertEqual(bridge.get_servo_state()["tilt"], 90)

            # Kiểm tra lịch sử lệnh trên Web đã chuyển sang 'executed'
            cmd_list = web.get(f"{base_url}/api/cameras/{cam_id}/commands", timeout=5).json()
            statuses = {c["idempotency_key"]: c["status"] for c in cmd_list}
            self.assertEqual(statuses["ptz-left-test-0001"], "executed")
            self.assertEqual(statuses["ptz-center-test-0002"], "executed")
        finally:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
