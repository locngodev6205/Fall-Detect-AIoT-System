"""Dispatch fall notifications independently of camera inference and MQTT."""
from dataclasses import dataclass
import logging
from queue import Empty, Full, Queue
import threading
from uuid import uuid4

from edge.client.device_client import iso_now_local

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingFall:
    event_id: str
    observed_at: str
    confidence: float
    reason: str
    jpeg: bytes | None


class FallAlerts:
    def __init__(self, audio, client, stop, *, retry_delay=1.0):
        self.audio = audio
        self.client = client
        self.stop = stop
        self.retry_delay = retry_delay
        self.local = Queue(maxsize=16)
        self.remote = Queue(maxsize=16)
        self.lock = threading.Lock()
        self.pending = 0
        self.last_error = None

    def has_pending(self):
        with self.lock:
            return self.pending > 0

    def submit(self, confidence, reason, jpeg):
        event = PendingFall(f"fall-{uuid4().hex}", iso_now_local(), confidence, reason, jpeg)
        with self.lock:
            try:
                self.local.put_nowait(event)
            except Full:
                if self.last_error != "local_full":
                    logger.error("[FallAlerts] Local queue full; a fall alert could not be queued")
                self.last_error = "local_full"
                return
            self.pending += 1

    def _complete(self):
        with self.lock:
            self.pending -= 1

    def start(self):
        workers = [
            threading.Thread(target=self._local_loop, name="annha-fall-audio", daemon=True),
            threading.Thread(target=self._remote_loop, name="annha-fall-delivery", daemon=True),
        ]
        for worker in workers:
            worker.start()
        return workers

    def _local_loop(self):
        while not self.stop.is_set():
            try:
                event = self.local.get(timeout=0.2)
            except Empty:
                continue
            try:
                self.audio.trigger_emergency_siren("fall", "Cảnh báo! Phát hiện người thân có dấu hiệu té ngã!")
            except Exception:
                logger.error("[FallAlerts] Local siren failed")
            if not self.client.device_token:
                self._complete()
                continue
            try:
                self.remote.put_nowait(event)
            except Full:
                if self.last_error != "remote_full":
                    logger.error("[FallAlerts] Remote queue full; the local siren has already been attempted")
                self.last_error = "remote_full"
                self._complete()

    def _remote_loop(self):
        while not self.stop.is_set():
            try:
                event = self.remote.get(timeout=0.2)
            except Empty:
                continue
            delay = self.retry_delay
            while not self.stop.is_set():
                try:
                    delivered = self.client.send_event(
                        kind="fall", severity="critical", observation="abnormal",
                        reason=event.reason, confidence=event.confidence,
                        event_id=event.event_id, observed_at=event.observed_at,
                        queue_on_failure=False,
                    )
                except Exception:
                    delivered = None
                if delivered and delivered.get("id"):
                    if event.jpeg:
                        try:
                            self.client.upload_evidence(
                                event.jpeg, mime_type="image/jpeg", filename="fall_evidence.jpg",
                                internal_event_id=str(delivered["id"]),
                            )
                        except Exception:
                            logger.warning("[FallAlerts] Evidence upload failed")
                    self._complete()
                    break
                if delay == self.retry_delay:
                    logger.warning("[FallAlerts] Fall event pending; retrying with the same event ID")
                self.stop.wait(delay)
                delay = min(delay * 2, 30)
