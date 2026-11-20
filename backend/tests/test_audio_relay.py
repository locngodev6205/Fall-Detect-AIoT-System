"""In-process WebSocket integration with isolated identity fixtures."""
from contextlib import suppress
import unittest

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from backend.src.audio_relay import AudioRelay, MAX_CHUNK


class AudioRelayTests(unittest.TestCase):
    def setUp(self):
        def authorize(socket, camera_id, permission):
            if (camera_id, permission, socket.cookies.get("session"), socket.headers.get("origin")) != (
                "cam", "audio", "operator", "https://testserver"
            ):
                raise HTTPException(403)
            return "operator"

        def identify(socket):
            if socket.headers.get("authorization") != "Bearer fixture":
                raise HTTPException(401)
            return {"id": "cam"}, "fixture"

        async def close(socket, code=1008):
            with suppress(RuntimeError):
                await socket.close(code)

        self.relay = AudioRelay(authorize, identify, close, {}, {}, {})
        app = FastAPI()

        @app.websocket("/device")
        async def device(socket: WebSocket):
            await self.relay.device(socket)

        @app.websocket("/browser/{camera}")
        async def browser(socket: WebSocket, camera: str):
            await self.relay.browser(socket, camera)

        self.client = self.enterContext(TestClient(app, cookies={"session": "operator"}))
        self.browser_headers = {"Origin": "https://testserver"}
        self.device_headers = {"Authorization": "Bearer fixture"}

    def start(self, browser, device):
        browser.send_json({"mime": "audio/webm"})
        start = device.receive_json()
        self.assertEqual(start["type"], "start")
        device.send_json({"type": "ready", "session": start["session"]})
        self.assertEqual(browser.receive_json(), {"type": "ready", "protocol": 2})
        return start["session"]

    def test_keeps_origin_device_auth_and_camera_scope(self):
        for path, headers in [
            ("/device", {}), ("/browser/cam", {"Origin": "https://untrusted.test"}),
            ("/browser/other", self.browser_headers),
        ]:
            with self.subTest(path=path), self.assertRaises(WebSocketDisconnect) as closed:
                with self.client.websocket_connect(path, headers=headers):
                    pass
            self.assertEqual(closed.exception.code, 1008)

    def test_missing_device_returns_service_unavailable(self):
        with self.assertRaises(WebSocketDisconnect) as closed:
            with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                browser.receive_json()
        self.assertEqual(closed.exception.code, 1013)

    def test_continuous_chunks_single_sender_stop_and_new_session(self):
        with self.client.websocket_connect("/device", headers=self.device_headers) as device:
            for _ in range(2):
                with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                    session = self.start(browser, device)
                    with self.assertRaises(WebSocketDisconnect) as closed:
                        with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as duplicate:
                            duplicate.receive_json()
                    self.assertEqual(closed.exception.code, 1013)
                    for chunk in (b"first", b"second"):
                        browser.send_bytes(chunk)
                        self.assertEqual(device.receive_bytes(), chunk)
                        device.send_json({"type": "received", "session": session})
                    browser.send_json({"type": "stop"})
                    self.assertEqual(device.receive_json(), {"type": "stop", "session": session})
                    self.assertEqual(browser.receive()["code"], 1000)

    def test_invalid_mime_and_oversize_close(self):
        with self.client.websocket_connect("/device", headers=self.device_headers) as device:
            with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                browser.send_json({"mime": "video/webm"})
                self.assertEqual(browser.receive()["code"], 1003)
            with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                session = self.start(browser, device)
                browser.send_bytes(b"x" * (MAX_CHUNK + 1))
                self.assertEqual(device.receive_json(), {"type": "stop", "session": session})
                self.assertEqual(browser.receive()["code"], 1009)

    def test_slow_consumer_closes_and_does_not_forward_next_chunk(self):
        with self.client.websocket_connect("/device", headers=self.device_headers) as device:
            with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                session = self.start(browser, device)
                browser.send_bytes(b"first")
                browser.send_bytes(b"second")
                self.assertEqual(device.receive_bytes(), b"first")
                self.assertEqual(device.receive_json(), {"type": "stop", "session": session})
                self.assertEqual(browser.receive()["code"], 1011)

    def test_browser_disconnect_and_device_disconnect_cleanup(self):
        with self.client.websocket_connect("/device", headers=self.device_headers) as device:
            with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                session = self.start(browser, device)
                browser.close()
                self.assertEqual(device.receive_json(), {"type": "stop", "session": session})
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/browser/cam", headers=self.browser_headers) as browser:
                browser.receive_json()
