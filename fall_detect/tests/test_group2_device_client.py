"""Kiểm thử tích hợp tự động Nhóm 2: Provision + Claim + Heartbeat + Config Sync + Telemetry + Event Evidence + Live WS."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import requests

FALL_DETECT_ROOT = Path(__file__).resolve().parents[1]
if str(FALL_DETECT_ROOT) not in sys.path:
    sys.path.insert(0, str(FALL_DETECT_ROOT))

from edge.client.device_client import DeviceClient  # noqa: E402
from edge.client.live_streamer import LiveStreamer  # noqa: E402
from edge.sensors.arduino_bridge import ArduinoBridge  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Group2DeviceClientIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.container_name = f"annha-test-group2-{self.port}"

        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.container_name,
                "-p",
                f"127.0.0.1:{self.port}:8000",
                "-e",
                "DATABASE_BACKEND=sqlite",
                "-e",
                "MQTT_ENABLED=false",
                "-e",
                "WORKER_ENABLED=false",
                "-e",
                "MEDIA_STORAGE_PROVIDER=local",
                "-e",
                f"APP_ORIGINS={self.base_url}",
                "-e",
                f"PUBLIC_URL={self.base_url}",
                "annha-backend:latest",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # Đợi container backend cô lập sẵn sàng
        for _ in range(40):
            try:
                r = requests.get(f"{self.base_url}/api/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.15)

        # Tạo tài khoản chủ nhà + nhà + phòng + provision thiết bị trong container cô lập
        setup_script = """
import json, time
from src import db, security, services
db.initialize()
uid = db.uid()
hid = db.uid()
rid = db.uid()
sess = "test-session-token-group2-123456"
csrf = "test-csrf-token-group2-123456"
with db.connect() as conn:
    conn.execute("INSERT INTO users(id,email,name,password,verified,created_at) VALUES(?,?,?,?,1,?)",
                 (uid, "owner@test.local", "Chủ nhà", security.password_hash("Pass123!"), db.now()))
    conn.execute("INSERT INTO homes(id,name,timezone,settings) VALUES(?,?,?,?)",
                 (hid, "Nhà Kiểm Thử Nhóm 2", "Asia/Ho_Chi_Minh", "{}"))
    conn.execute("INSERT INTO memberships(home_id,user_id,role,scopes,rights) VALUES(?,?,'owner','[]','{}')",
                 (hid, uid))
    conn.execute("INSERT INTO rooms(id,home_id,name) VALUES(?,?,?)",
                 (rid, hid, "Phòng khách"))
    conn.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)",
                 (security.digest(sess), uid, csrf, time.time() + 3600))
prov = services.provision_device("Camera Pi 4 Phòng khách")
print(json.dumps({"home_id": hid, "room_id": rid, "session": sess, "csrf": csrf, "provision": prov}))
"""
        proc = subprocess.run(
            ["docker", "exec", self.container_name, "python", "-c", setup_script],
            check=True,
            capture_output=True,
            text=True,
        )
        info = json.loads(proc.stdout.strip().splitlines()[-1])
        self.home_id = info["home_id"]
        self.room_id = info["room_id"]
        self.session_token = info["session"]
        self.csrf_token = info["csrf"]
        self.provision = info["provision"]

    def tearDown(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        self._tmp.cleanup()

    def test_end_to_end_claim_heartbeat_telemetry_event_and_ws_stream(self) -> None:
        web = requests.Session()
        web.cookies.set("annha_session", self.session_token)

        # 1. Chủ nhà ghép nối thiết bị bằng pairing_code trên Web API
        claim_resp = web.post(
            f"{self.base_url}/api/homes/{self.home_id}/cameras/claim",
            headers={"Origin": self.base_url, "X-CSRF-Token": self.csrf_token},
            json={
                "code": self.provision["pairing_code"],
                "name": "Pi 4 Phòng khách",
                "room_id": self.room_id,
            },
            timeout=5,
        )
        self.assertEqual(claim_resp.status_code, 201, claim_resp.text)
        camera_id = claim_resp.json()["id"]

        bridge = ArduinoBridge(force_mock=True).start()
        client = DeviceClient(
            self.base_url,
            self.provision["device_token"],
            cache_dir=Path(self._tmp.name) / "edge_cache",
        ).start()
        streamer = LiveStreamer(self.base_url, self.provision["device_token"]).start()
        try:
            # 2. Heartbeat -> Online + tự động đồng bộ config v1
            hb = client.send_heartbeat("clear", camera_ok=True, speaker_ok=True, sensors_ok=True)
            self.assertIsNotNone(hb)
            self.assertEqual(client.applied_version, 1)

            cams = web.get(f"{self.base_url}/api/homes/{self.home_id}/cameras", timeout=5).json()
            self.assertEqual(len(cams), 1)
            self.assertTrue(cams[0]["online"])
            self.assertEqual(cams[0]["applied_version"], 1)

            # 3. Đẩy Telemetry DHT11 + MQ-2 -> Kiểm tra biểu đồ /telemetry-summary
            for _ in range(3):
                self.assertTrue(client.send_telemetry(bridge.get_telemetry_readings()))

            summary = web.get(f"{self.base_url}/api/cameras/{camera_id}/telemetry-summary?hours=1", timeout=5)
            self.assertEqual(summary.status_code, 200, summary.text)
            sum_json = summary.json()
            self.assertEqual(sum_json["sample_count"], 3)
            self.assertEqual(sum_json["latest"]["payload"]["readings"]["temperature"]["quality"], "valid")
            self.assertEqual(sum_json["latest"]["payload"]["readings"]["gas"]["quality"], "valid")

            # 4. Đẩy khung hình JPEG qua WebSocket /ws/device/frames
            minimal_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
            streamer.update_frame_jpeg(minimal_jpeg)
            time.sleep(0.35)

            # 5. Gửi sự kiện té ngã + Upload ảnh JPEG bằng chứng
            ev = client.send_event(
                kind="fall",
                severity="critical",
                observation="abnormal",
                reason="Phát hiện té ngã (Độ tin cậy 94.5%)",
                confidence=0.945,
            )
            self.assertIsNotNone(ev)
            assert ev is not None
            asset = client.upload_evidence(minimal_jpeg, internal_event_id=ev["id"], filename="fall.jpg")
            self.assertIsNotNone(asset)

            active = web.get(f"{self.base_url}/api/homes/{self.home_id}/active-events?page_size=5", timeout=5).json()
            self.assertEqual(active["count"], 1)
            self.assertEqual(active["items"][0]["kind"], "fall")
            self.assertEqual(len(active["items"][0]["evidence"]), 1)
        finally:
            streamer.stop()
            client.stop()
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
