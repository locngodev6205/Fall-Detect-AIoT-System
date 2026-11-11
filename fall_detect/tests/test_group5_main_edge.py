"""Kiểm thử tích hợp toàn hệ thống Nhóm 5: `AnNhaEdgeRuntime` đa luồng hợp nhất."""

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

from edge.main_edge import AnNhaEdgeRuntime, render_synthetic_hud_jpeg  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Group5UnifiedRuntimeTests(unittest.TestCase):
    def test_synthetic_hud_jpeg_generation(self) -> None:
        jpg = render_synthetic_hud_jpeg(person_cx=0.35, person_cy=0.60, servo_pan=96, servo_tilt=88)
        self.assertTrue(jpg.startswith(b"\xff\xd8\xff"))
        self.assertGreater(len(jpg), 3000)

    def test_unified_runtime_end_to_end_lifecycle(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        cname = f"annha-test-group5-{port}"
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
sess, csrf = "sess-group5-token-123456", "csrf-group5-token-123456"
with db.connect() as conn:
    conn.execute("INSERT INTO users(id,email,name,password,verified,created_at) VALUES(?,?,?,?,1,?)",
                 (uid, "owner5@test.local", "Chủ nhà", security.password_hash("Pass123!"), db.now()))
    conn.execute("INSERT INTO homes(id,name,timezone,settings) VALUES(?,?,?,?)",
                 (hid, "Nhà Kiểm Thử Nhóm 5", "Asia/Ho_Chi_Minh", "{}"))
    conn.execute("INSERT INTO memberships(home_id,user_id,role,scopes,rights) VALUES(?,?,'owner','[]','{}')",
                 (hid, uid))
    conn.execute("INSERT INTO rooms(id,home_id,name) VALUES(?,?,?)", (rid, hid, "Phòng khách"))
    conn.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)",
                 (security.digest(sess), uid, csrf, time.time() + 3600))
prov = services.provision_device("Pi 4 Hợp Nhất")
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
                    "name": "Pi 4 Hợp Nhất",
                    "room_id": meta["room_id"],
                },
                headers=headers,
                timeout=5,
            )
            self.assertIn(claim_res.status_code, (200, 201), claim_res.text)
            cam_id = claim_res.json()["id"]

            runtime = AnNhaEdgeRuntime(
                base_url=base_url,
                device_token=meta["prov"]["device_token"],
                heartbeat_interval_s=3.0,
                telemetry_interval_s=3.0,
                command_poll_interval_s=0.6,
                snapshot_interval_s=5.0,
                cache_dir=Path(tmp.name) / "edge_cache",
                force_mock_hardware=True,
            )
            runtime.start()
            try:
                time.sleep(2.8)
                # Kiểm tra thiết bị đã Online, đồng bộ applied_version=1 và gửi snapshot + telemetry
                cams = web.get(f"{base_url}/api/homes/{meta['home_id']}/cameras", timeout=5).json()
                cam = next(c for c in cams if c["id"] == cam_id)
                self.assertTrue(cam["online"])
                self.assertEqual(cam["applied_version"], 1)

                snap = web.get(f"{base_url}/api/cameras/{cam_id}/snapshot", timeout=5)
                self.assertEqual(snap.status_code, 200)
                self.assertTrue(snap.content.startswith(b"\xff\xd8\xff"))

                # Mô phỏng phát hiện té ngã -> Hú còi tại chỗ 100% + Gửi sự kiện & ảnh bằng chứng lên Backend
                evidence_jpg = runtime.streamer.get_latest_jpeg()
                runtime.handle_fall_detected(
                    confidence=0.95,
                    reason="Kiểm thử té ngã toàn trình E2E.",
                    jpeg_evidence=evidence_jpg,
                )

                events = web.get(f"{base_url}/api/homes/{meta['home_id']}/events", timeout=5).json()
                fall_events = [e for e in events if e["kind"] == "fall"]
                self.assertGreaterEqual(len(fall_events), 1)
                self.assertGreaterEqual(len(fall_events[0]["evidence"]), 1)
                self.assertTrue(any(h.get("label") == "emergency_fall" for h in runtime.audio.history))
            finally:
                runtime.stop()
        finally:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
