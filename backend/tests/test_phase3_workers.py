"""Focused concurrency regression for independent TTS and notification loops."""
import asyncio
from contextlib import suppress
import threading
import unittest
from unittest.mock import AsyncMock, patch

from backend.src import pgservices


class WorkerIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_tts_does_not_block_notification_dispatch(self):
        tts_started=threading.Event();release_tts=threading.Event();tts_finished=threading.Event()
        notification_started=threading.Event();general_jobs_started=threading.Event()

        def process_job(job_id=None,kinds=None):
            if kinds==['tts']:
                tts_started.set();release_tts.wait(2);tts_finished.set()
            else:
                general_jobs_started.set()

        def process_notifications(): notification_started.set()

        with patch.object(pgservices,'process_job',side_effect=process_job), \
             patch.object(pgservices,'process_notifications',side_effect=process_notifications), \
             patch.object(pgservices,'maintenance'), \
             patch.object(pgservices,'revalidate_connections',new=AsyncMock()):
            worker=asyncio.create_task(pgservices.worker())
            try:
                self.assertTrue(await asyncio.to_thread(tts_started.wait,1))
                self.assertTrue(await asyncio.to_thread(general_jobs_started.wait,1))
                self.assertTrue(await asyncio.to_thread(notification_started.wait,1))
                self.assertFalse(tts_finished.is_set())
            finally:
                release_tts.set();worker.cancel()
                with suppress(asyncio.CancelledError): await worker


if __name__=='__main__': unittest.main()
