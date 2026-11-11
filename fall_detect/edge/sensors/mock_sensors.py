"""Bộ giả lập phần cứng Arduino (DHT11 + MQ-2 + 2 Servo Pan-Tilt) mượt mà khi chạy trên PC."""
from __future__ import annotations

import math
import random
import threading
import time
from typing import Any


PAN_MIN, PAN_CENTER, PAN_MAX = 30, 90, 150
TILT_MIN, TILT_CENTER, TILT_MAX = 45, 90, 135


class MockArduinoDevice:
    """Mô phỏng đầy đủ cảm biến DHT11, MQ-2 (ADC) và góc quay 2 trục Servo."""

    def __init__(self, seed: int | None = None) -> None:
        self._lock = threading.Lock()
        self._rng = random.Random(seed)
        self._start_mono = time.monotonic()
        self._pan = PAN_CENTER
        self._tilt = TILT_CENTER
        self._enabled = False
        self._override: dict[str, Any] | None = None
        self._override_until = 0.0

    def inject_override(
        self,
        *,
        temp: float | None = None,
        hum: float | None = None,
        gas: float | None = None,
        duration_s: float = 30.0,
    ) -> None:
        """Cho phép kịch bản kiểm thử bơm giá trị giả định (ví dụ rò rỉ gas = 650 ADC)."""
        with self._lock:
            self._override = {"temp": temp, "hum": hum, "gas": gas}
            self._override_until = time.monotonic() + max(0.1, duration_s)

    def clear_override(self) -> None:
        with self._lock:
            self._override = None
            self._override_until = 0.0

    def read_raw(self) -> dict[str, Any]:
        elapsed = time.monotonic() - self._start_mono
        with self._lock:
            temp = round(28.2 + 1.4 * math.sin(elapsed / 45.0) + self._rng.uniform(-0.15, 0.15), 1)
            hum = round(64.0 + 4.5 * math.cos(elapsed / 60.0) + self._rng.uniform(-0.4, 0.4), 1)
            gas = int(round(165 + 18 * math.sin(elapsed / 30.0) + self._rng.uniform(-4, 4)))

            if self._override and time.monotonic() < self._override_until:
                if self._override.get("temp") is not None:
                    temp = float(self._override["temp"])
                if self._override.get("hum") is not None:
                    hum = float(self._override["hum"])
                if self._override.get("gas") is not None:
                    gas = int(round(float(self._override["gas"])))
            elif self._override:
                self._override = None

            return {
                "temp": temp,
                "hum": hum,
                "gas": gas,
                "gas_warmup": 0,
                "pan": self._pan,
                "tilt": self._tilt,
                "enabled": self._enabled,
            }

    def set_angles(self, pan: int, tilt: int) -> tuple[int, int]:
        if not (PAN_MIN <= pan <= PAN_MAX and TILT_MIN <= tilt <= TILT_MAX):
            raise ValueError(f"Góc ngoài giới hạn an toàn: pan={pan}, tilt={tilt}")
        with self._lock:
            self._pan = int(pan)
            self._tilt = int(tilt)
            self._enabled = True
            return self._pan, self._tilt

    def move_relative(self, delta_pan: int, delta_tilt: int) -> tuple[int, int]:
        with self._lock:
            new_pan = max(PAN_MIN, min(PAN_MAX, self._pan + int(delta_pan)))
            new_tilt = max(TILT_MIN, min(TILT_MAX, self._tilt + int(delta_tilt)))
            self._pan = new_pan
            self._tilt = new_tilt
            self._enabled = True
            return self._pan, self._tilt

    def center(self) -> tuple[int, int]:
        return self.set_angles(PAN_CENTER, TILT_CENTER)

    def detach(self) -> None:
        with self._lock:
            self._enabled = False

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pan": self._pan,
                "tilt": self._tilt,
                "target_pan": self._pan,
                "target_tilt": self._tilt,
                "enabled": self._enabled,
                "moving": 0,
                "is_mock": True,
            }
