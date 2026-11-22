"""One bounded worker for ordinary file playback and reminder preparation."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock


class AudioWorker:
    def __init__(self, capacity: int = 16) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="annha-audio")
        self._capacity = capacity
        self._pending = 0
        self._lock = Lock()

    def is_busy(self) -> bool:
        with self._lock:
            return self._pending != 0

    def submit(self, action, *args) -> Future | None:
        with self._lock:
            if self._pending >= self._capacity:
                return None
            self._pending += 1
        try:
            future = self._executor.submit(action, *args)
        except RuntimeError:
            self._release()
            return None
        future.add_done_callback(self._release)
        return future

    def _release(self, _future=None) -> None:
        with self._lock:
            self._pending -= 1

    def stop(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def join(self) -> None:
        self._executor.shutdown(wait=True)
