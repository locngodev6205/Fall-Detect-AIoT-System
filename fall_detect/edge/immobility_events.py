"""Keep ordered immobility updates off the camera thread."""
from queue import Empty, SimpleQueue
from uuid import uuid4

from edge.client.device_client import iso_now_local
from modules.immobility import State


class ImmobilityEvents:
    def __init__(self):
        self.queue = SimpleQueue()
        self.event_id = None
        self.pending = None
        self.retry_at = 0.

    def submit(self, reading, *, jpeg_evidence=None, threshold_seconds=None):
        if reading.transition == State.INACTIVE:
            self.event_id = f"immobility-{uuid4().hex}"
            severity, observation, sequence = "warning", "abnormal", 1
            reason = "Không quan sát thấy chuyển động đáng kể trong khoảng theo dõi liên tục."
        elif reading.transition == State.RECOVERED and self.event_id:
            severity, observation, sequence = "info", "recovered", 2
            reason = "Quan sát thấy người chuyển động trở lại."
        else:
            return
        self.queue.put(dict(kind="immobility", event_id=self.event_id, sequence=sequence,
                            duration_s=reading.duration_s, severity=severity,
                            observation=observation, reason=reason, observed_at=iso_now_local(),
                            jpeg_evidence=jpeg_evidence if sequence == 1 else None,
                            **({"detection": {"threshold_value": threshold_seconds, "measured_value": reading.duration_s}}
                               if sequence == 1 and threshold_seconds is not None else {})))
        if sequence == 2:
            self.event_id = None

    def flush(self, client, stamp):
        if stamp < self.retry_at:
            return
        if self.pending is None:
            try:
                self.pending = self.queue.get_nowait()
            except Empty:
                return
        result = client.send_event(**self.pending, queue_on_failure=False)
        if result and result.get("id"):
            self.pending = None
        else:
            self.retry_at = stamp+5.
