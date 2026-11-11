"""Truyền hình trực tiếp JPEG (`/ws/device/frames`) và nhận đàm thoại Push-to-Talk (`/ws/device/audio`)."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable

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


async def _ws_connect(uri: str, token: str) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        return await websockets.connect(uri, additional_headers=headers, max_size=2 * 1024 * 1024)
    except TypeError:
        return await websockets.connect(uri, extra_headers=headers, max_size=2 * 1024 * 1024)


class LiveStreamer:
    """Quản lý 2 luồng WebSocket thời gian thực từ Pi 4 lên Backend AnNhà."""

    def __init__(
        self,
        base_url: str,
        device_token: str,
        *,
        fps_limit: float = 5.0,
        on_ptt_audio_file: Callable[[Path, str], None] | None = None,
    ) -> None:
        self.base_url = base_url
        self.device_token = device_token.strip()
        self.min_frame_interval = 1.0 / max(1.0, min(5.5, float(fps_limit)))
        self.on_ptt_audio_file = on_ptt_audio_file

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
                async with await _ws_connect(uri, self.device_token) as ws:
                    logger.info("[LiveStreamer] Đã kết nối WebSocket nhận đàm thoại Push-to-Talk (%s).", uri)
                    active_mime = "audio/webm"
                    chunks: list[bytes] = []
                    total_bytes = 0
                    max_ptt_bytes = 8 * 1024 * 1024
                    receiving = False

                    while self._running:
                        msg = await ws.recv()
                        if isinstance(msg, str):
                            data = json.loads(msg)
                            mtype = data.get("type")
                            if mtype == "start":
                                active_mime = str(data.get("mime") or "audio/webm")
                                chunks.clear()
                                total_bytes = 0
                                receiving = True
                                logger.info("[LiveStreamer] Bắt đầu nhận luồng giọng nói trực tiếp (%s)...", active_mime)
                            elif mtype == "stop":
                                if receiving and chunks:
                                    self._dispatch_ptt_buffer(b"".join(chunks), active_mime)
                                chunks.clear()
                                total_bytes = 0
                                receiving = False
                        elif isinstance(msg, (bytes, bytearray)) and receiving:
                            if total_bytes + len(msg) <= max_ptt_bytes:
                                chunks.append(bytes(msg))
                                total_bytes += len(msg)
                            else:
                                logger.warning("[LiveStreamer] Gói đàm thoại vượt giới hạn 8 MB -> phát phần đã nhận.")
                                self._dispatch_ptt_buffer(b"".join(chunks), active_mime)
                                chunks.clear()
                                total_bytes = 0
                                receiving = False
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._running:
                    logger.debug("[LiveStreamer] Kết nối lại /ws/device/audio sau 3s (%s)", exc)
                    await asyncio.sleep(3.0)

    def _dispatch_ptt_buffer(self, raw_audio: bytes, mime: str) -> None:
        if not raw_audio or self.on_ptt_audio_file is None:
            return
        import os
        ext = ".ogg" if "ogg" in mime.lower() else ".webm"
        fd: int | None = None
        path: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix="annha_ptt_", suffix=ext)
            path = Path(tmp_name)
            with os.fdopen(fd, "wb") as fh:
                fd = None
                fh.write(raw_audio)
            self.on_ptt_audio_file(path, mime)
        except Exception as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if path is not None:
                path.unlink(missing_ok=True)
            logger.warning("[LiveStreamer] Lỗi lưu đệm đàm thoại Push-to-Talk: %s", exc)
