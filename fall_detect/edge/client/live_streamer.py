"""Truyền hình trực tiếp JPEG (`/ws/device/frames`) và nhận đàm thoại Push-to-Talk (`/ws/device/audio`)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable

from ..audio.live_input import MAX_CHUNK, MAX_SESSION_BYTES, SESSION_SECONDS, LiveInput

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

logger = logging.getLogger("annha.edge.streamer")

JPEG_SOI = b"\xff\xd8\xff"
MAX_FRAME_BYTES = 1_000_000  # Dưới ngưỡng 1 MB của media.py


def _ws_url(http_base_url: str, path: str) -> str:
    base = http_base_url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + path
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + path
    return f"ws://{base}{path}"


async def _ws_connect(uri: str, token: str, *, max_size=2 * 1024 * 1024, max_queue=4) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        return await websockets.connect(uri, additional_headers=headers, max_size=max_size, max_queue=max_queue)
    except TypeError:
        return await websockets.connect(uri, extra_headers=headers, max_size=max_size, max_queue=max_queue)


class LiveStreamer:
    """Quản lý 2 luồng WebSocket thời gian thực từ Pi 4 lên Backend AnNhà."""

    def __init__(
        self,
        base_url: str,
        device_token: str,
        *,
        fps_limit: float = 5.0,
        start_ptt: Callable[[str], LiveInput | None] | None = None,
        finish_ptt: Callable[[LiveInput], None] | None = None,
    ) -> None:
        self.base_url = base_url
        self.device_token = device_token.strip()
        self.min_frame_interval = 1.0 / max(1.0, min(5.5, float(fps_limit)))
        self.start_ptt = start_ptt
        self.finish_ptt = finish_ptt

        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._latest_seq: int = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def update_frame_jpeg(self, jpeg_bytes: bytes) -> None:
        """Cập nhật khung hình JPEG mới nhất từ luồng Camera AI (không nghẽn luồng AI)."""
        if not jpeg_bytes or not jpeg_bytes.startswith(JPEG_SOI) or len(jpeg_bytes) > MAX_FRAME_BYTES:
            return
        with self._lock:
            self._latest_jpeg = jpeg_bytes
            self._latest_seq += 1

    def clear_frame(self) -> None:
        """Stop reusing an old frame when a physical camera is disconnected."""
        with self._lock:
            self._latest_jpeg = None
            self._latest_seq += 1

    def get_latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def start(self) -> "LiveStreamer":
        if self._running or not self.device_token or websockets is None:
            if websockets is None:
                logger.warning("[LiveStreamer] Thiếu thư viện 'websockets', bỏ qua Live Stream.")
            return self
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, name="annha-ws-streamer", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.5)

    def _run_event_loop(self) -> None:
        asyncio.run(self._supervisor())

    async def _supervisor(self) -> None:
        tasks = [
            asyncio.create_task(self._frames_loop()),
            asyncio.create_task(self._audio_loop()),
        ]
        try:
            while self._running:
                await asyncio.sleep(0.3)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _frames_loop(self) -> None:
        uri = _ws_url(self.base_url, "/ws/device/frames")
        sent_seq = 0
        while self._running:
            try:
                async with await _ws_connect(uri, self.device_token) as ws:
                    logger.info("[LiveStreamer] Đã kết nối WebSocket truyền hình trực tiếp (%s).", uri)
                    while self._running:
                        with self._lock:
                            seq = self._latest_seq
                            frame = self._latest_jpeg
                        if frame is not None and seq != sent_seq:
                            await ws.send(frame)
                            sent_seq = seq
                            await asyncio.sleep(self.min_frame_interval)
                        else:
                            await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    logger.debug("[LiveStreamer] Kết nối lại /ws/device/frames sau 3s (%s)", exc)
                    await asyncio.sleep(3.0)

    async def _audio_loop(self) -> None:
        uri = _ws_url(self.base_url, "/ws/device/audio")
        while self._running:
            try:
                async with await _ws_connect(uri, self.device_token, max_size=MAX_CHUNK, max_queue=2) as ws:
                    logger.info("[LiveStreamer] Đã kết nối WebSocket nhận đàm thoại Push-to-Talk (%s).", uri)
                    await self._receive_audio(ws)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    logger.debug("[LiveStreamer] Kết nối lại /ws/device/audio sau 3s (%s)", exc)
                    await asyncio.sleep(3)

    async def _receive_audio(self, ws):
        loop = asyncio.get_running_loop()
        stream = None
        session = None
        deadline = 0
        total = 0

        def finish():
            nonlocal stream
            if stream is not None:
                (self.finish_ptt or LiveInput.close)(stream)
                stream = None

        async def reply(kind):
            await asyncio.wait_for(ws.send(json.dumps({"type": kind, "session": session})), 0.5)

        try:
            while self._running:
                try:
                    timeout = max(0, min(3, deadline - loop.time())) if stream else None
                    msg = await asyncio.wait_for(ws.recv(), timeout)
                except asyncio.TimeoutError:
                    finish()
                    await reply("unavailable")
                    continue
                if isinstance(msg, str):
                    data = json.loads(msg)
                    if data.get("type") == "start":
                        finish()
                        session = data.get("session")
                        if not session:
                            continue
                        total = 0
                        deadline = loop.time() + SESSION_SECONDS
                        try:
                            if self.start_ptt is not None:
                                starting = asyncio.create_task(asyncio.to_thread(self.start_ptt, data.get("mime")))
                                try:
                                    stream = await asyncio.shield(starting)
                                except asyncio.CancelledError:
                                    stream = await starting
                                    raise
                        except (OSError, ValueError):
                            logger.exception("[LiveStreamer] Không mở được đầu ra Push-to-Talk.")
                        await reply("ready" if stream else "unavailable")
                    elif data.get("type") == "stop" and data.get("session") == session:
                        finish()
                elif stream:
                    total += len(msg)
                    try:
                        if not msg or len(msg) > MAX_CHUNK or total > MAX_SESSION_BYTES:
                            raise ValueError("Push-to-Talk vượt giới hạn kích thước.")
                        await stream.write(msg)
                    except (OSError, ValueError):
                        finish()
                        await reply("unavailable")
                    else:
                        await reply("received")
                elif session:
                    await reply("unavailable")
        finally:
            finish()
