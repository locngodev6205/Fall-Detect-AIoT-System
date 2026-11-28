import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, WebSocketDisconnect
from psycopg import OperationalError

from backend.src import pgmedia


class VideoLeaseTests(IsolatedAsyncioTestCase):
    def setUp(self):
        for store in (pgmedia.viewers, pgmedia.video_devices, pgmedia.media_sessions):
            store.clear()
            self.addCleanup(store.clear)

    async def test_device_authenticates_once_and_expired_viewer_gets_no_frame(self):
        device = AsyncMock()
        device.receive_bytes.side_effect = [b'\xff\xd8\xffjpg', WebSocketDisconnect()]
        valid, expired = AsyncMock(), AsyncMock()
        pgmedia.viewers['benchmark'] = {valid: time.monotonic() + 10, expired: 0}
        with patch.object(pgmedia, 'device_identity', return_value=({'id': 'benchmark'}, 'fixture')) as auth:
            await pgmedia.device_frames(device)
        auth.assert_called_once_with(device)
        valid.send_bytes.assert_awaited_once()
        expired.send_bytes.assert_not_awaited()

    async def test_revocation_closes_both_video_roles_and_removes_their_access(self):
        device, viewer = AsyncMock(), AsyncMock()
        pgmedia.video_devices[device] = 'benchmark'
        pgmedia.viewers['benchmark'] = {viewer: time.monotonic() + 10}
        pgmedia.media_sessions[viewer] = ('fixture', 'benchmark', 'view')
        with (
            patch.object(pgmedia, 'session_user', side_effect=HTTPException(401)),
            patch.object(pgmedia, 'device_identity', side_effect=HTTPException(401)),
        ):
            await pgmedia.revalidate()
        self.assertFalse(pgmedia.video_devices or pgmedia.viewers or pgmedia.media_sessions)
        device.close.assert_awaited_once()
        viewer.close.assert_awaited_once()

    async def test_viewer_is_revalidated_and_removed_on_permission_failure(self):
        viewer = AsyncMock()

        async def receive():
            await asyncio.Future()

        viewer.receive_text.side_effect = receive
        with (
            patch.object(pgmedia, 'VIEW_RECHECK_SECONDS', .01),
            patch.object(pgmedia, 'viewer_authorization', side_effect=[('fixture', None), HTTPException(403)]) as auth,
        ):
            await asyncio.wait_for(pgmedia.browser_frames(viewer, 'benchmark'), 1)
        self.assertEqual(auth.call_count, 2)
        self.assertFalse(pgmedia.viewers or pgmedia.media_sessions)

    async def test_device_is_revalidated_after_lease_and_revoked_connection_closes(self):
        device = AsyncMock()
        async def receive():
            await asyncio.Future()
        device.receive_bytes.side_effect = receive
        with (
            patch.object(pgmedia, 'AUTH_LEASE_SECONDS', .03),
            patch.object(pgmedia, 'device_identity', side_effect=[({'id': 'benchmark'}, 'fixture'), HTTPException(401)]) as auth,
        ):
            await asyncio.wait_for(pgmedia.device_frames(device), 1)
        self.assertEqual(auth.call_count, 2)
        self.assertFalse(pgmedia.video_devices)
        device.close.assert_awaited_once()

    async def test_viewer_session_expiry_caps_lease_even_if_database_fails(self):
        viewer = AsyncMock()

        async def receive():
            await asyncio.Future()

        viewer.receive_text.side_effect = receive
        expires_at = datetime.now(timezone.utc) + timedelta(milliseconds=100)
        with patch.object(pgmedia, 'viewer_authorization', side_effect=[('fixture', expires_at), OperationalError('offline')]) as auth:
            await asyncio.wait_for(pgmedia.browser_frames(viewer, 'benchmark'), 1)
        self.assertEqual(auth.call_count, 2)
        self.assertFalse(pgmedia.viewers or pgmedia.media_sessions)
        viewer.close.assert_awaited_once()

    async def test_expired_device_credential_is_rejected_before_accept(self):
        device = AsyncMock()
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        with patch.object(pgmedia, 'device_identity', return_value=({'id': 'benchmark', 'credential_expires_at': expired}, 'fixture')):
            await pgmedia.device_frames(device)
        device.accept.assert_not_awaited()
        device.close.assert_awaited_once()
