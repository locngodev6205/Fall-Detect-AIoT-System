"""Per-process, authenticated browser-to-device audio relay."""
import asyncio
from contextlib import suppress
import json
from uuid import uuid4

from fastapi import HTTPException, WebSocketDisconnect

MAX_CHUNK = 32 * 1024
MAX_SESSION_BYTES = 1024 * 1024


class AudioRelay:
    def __init__(self, authorize, identify, close, devices, senders, media_sessions):
        self.authorize = authorize
        self.identify = identify
        self.close = close
        self.devices = devices
        self.senders = senders
        self.media_sessions = media_sessions
        self.replies = {}

    async def device(self, socket):
        try:
            camera, _ = await asyncio.to_thread(self.identify, socket)
        except HTTPException:
            await self.close(socket)
            return
        camera_id = camera["id"]
        if camera_id in self.devices:
            await self.close(socket, 1013)
            return
        self.devices[camera_id] = socket
        try:
            await socket.accept()
            while True:
                try:
                    reply = await asyncio.wait_for(socket.receive_json(), 3)
                except asyncio.TimeoutError:
                    await asyncio.to_thread(self.identify, socket)
                    continue
                await asyncio.to_thread(self.identify, socket)
                pending = self.replies.get(camera_id)
                if pending and pending[0] is socket and isinstance(reply, dict):
                    _, session_id, future = pending
                    if not future.done() and reply.get("session") == session_id:
                        future.set_result(reply.get("type"))
        except (WebSocketDisconnect, RuntimeError, HTTPException, ValueError):
            pass
        finally:
            pending = self.replies.get(camera_id)
            if pending and pending[0] is socket and not pending[2].done():
                pending[2].set_result("unavailable")
            if self.devices.get(camera_id) is socket:
                self.devices.pop(camera_id)
                sender = self.senders.get(camera_id)
                if sender:
                    await self.close(sender, 1011)
            await self.close(socket)

    async def exchange(self, camera_id, peer, session_id, send, expected, timeout):
        if self.devices.get(camera_id) is not peer:
            return False
        reply = asyncio.get_running_loop().create_future()
        self.replies[camera_id] = (peer, session_id, reply)
        try:
            await asyncio.wait_for(send(), timeout)
            return await asyncio.wait_for(reply, timeout) == expected
        finally:
            self.replies.pop(camera_id, None)

    async def browser(self, socket, camera_id):
        try:
            token = await asyncio.to_thread(self.authorize, socket, camera_id, "audio")
        except HTTPException:
            await self.close(socket)
            return
        peer = self.devices.get(camera_id)
        if not peer or camera_id in self.senders:
            # Accept only authenticated browsers so the close code reaches the UI.
            await socket.accept()
            await self.close(socket, 1013)
            return
        self.senders[camera_id] = socket
        self.media_sessions[socket] = (token, camera_id, "audio")
        session_id = uuid4().hex
        started = False
        total = 0
        close_code = 1000
        try:
            await socket.accept()
            async with asyncio.timeout(60):
                metadata = await asyncio.wait_for(socket.receive_json(), 5)
                if not isinstance(metadata, dict) or metadata.get("mime") not in ("audio/webm", "audio/ogg"):
                    close_code = 1003
                    return
                started = True
                ready = await self.exchange(camera_id, peer, session_id, lambda: peer.send_json(
                    {"type": "start", "mime": metadata["mime"], "session": session_id}), "ready", 2)
                if not ready:
                    close_code = 1013
                    return
                await socket.send_json({"type": "ready", "protocol": 2})
                while True:
                    data = await asyncio.wait_for(socket.receive(), 3)
                    if data["type"] == "websocket.disconnect":
                        break
                    if data.get("text"):
                        if json.loads(data["text"]) == {"type": "stop"}:
                            break
                        close_code = 1003
                        break
                    chunk = data.get("bytes") or b""
                    total += len(chunk)
                    if not chunk or len(chunk) > MAX_CHUNK or total > MAX_SESSION_BYTES:
                        close_code = 1009
                        break
                    await asyncio.to_thread(self.authorize, socket, camera_id, "audio")
                    if not await self.exchange(camera_id, peer, session_id, lambda: peer.send_bytes(chunk),
                                               "received", 0.75):
                        close_code = 1013
                        break
        except HTTPException:
            close_code = 1008
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError, ValueError):
            close_code = 1011
        finally:
            try:
                if started:
                    with suppress(Exception):
                        await asyncio.wait_for(peer.send_json({"type": "stop", "session": session_id}), 0.5)
            finally:
                self.senders.pop(camera_id, None)
                self.media_sessions.pop(socket, None)
                await self.close(socket, close_code)
