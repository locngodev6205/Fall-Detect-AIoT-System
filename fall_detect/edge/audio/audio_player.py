"""Bộ phát âm thanh ưu tiên trên Loa Bluetooth (Còi khẩn cấp tại chỗ, Lịch nhắc, Lệnh Web & Đàm thoại).

Đặc tả an toàn:
  1. Còi báo động tại chỗ (`trigger_emergency_siren`):
     - Phát ngay lập tức tại phòng khi phát hiện Té ngã (`fall`) hoặc Khí gas vượt ngưỡng (`gas`),
       kể cả khi đứt cáp quang / mất kết nối Backend hay đang ở Chế độ ban đêm (`22:00 - 06:00`).
     - Có quyền ưu tiên cao nhất: tự ngắt lời nhắc thường đang phát và đẩy âm lượng lên 100%.
  2. Lệnh `silence` từ Web (`DEVICE_API.md`):
     - Tạm ngắt còi tại chỗ trong thời gian cấu hình đối với sự kiện té ngã / thử loa,
       NHƯNG KHÔNG BAO GIỜ tắt hoặc ngắt tiến trình còi đang phát khi rò rỉ khí gas (`is_gas=True`).
  3. Chốt chặn Loa Bluetooth chuyên dụng:
     - Nếu không phải chế độ Mock mà Loa Bluetooth đang mất kết nối (`sink is None`), ghi log cảnh báo
       rõ ràng và TUYỆT ĐỐI KHÔNG phát qua cổng 3.5mm / HDMI nội bộ.
"""

from __future__ import annotations

from collections import deque
import hashlib
import logging
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable
import wave

from .bluetooth_manager import BluetoothSpeakerManager, get_audio_env
from .live_input import FORMATS, LiveInput

logger = logging.getLogger(__name__)


def ensure_chime_wav(dest: Path) -> Path:
    """Sinh file chuông 2 nốt C5-E5 (523Hz -> 659Hz) chuẩn PCM 16-bit 24kHz nếu chưa có."""
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 24000
    duration_s = 0.65
    total = int(sample_rate * duration_s)
    frames = bytearray()
    for i in range(total):
        t = i / sample_rate
        freq = 523.25 if t < 0.30 else 659.25
        local_t = t if t < 0.30 else (t - 0.30)
        env = math.exp(-5.0 * local_t) * min(1.0, local_t / 0.015)
        sample = int(max(-32767, min(32767, 22000 * env * math.sin(2.0 * math.pi * freq * t))))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(dest), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return dest


def ensure_siren_wav(dest: Path) -> Path:
    """Sinh file còi báo động khẩn cấp 2 tần số xen kẽ (880Hz <-> 1320Hz) rõ nét trong phòng."""
    if dest.exists() and dest.stat().st_size > 2000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 24000
    duration_s = 2.0
    total = int(sample_rate * duration_s)
    frames = bytearray()
    for i in range(total):
        t = i / sample_rate
        cycle = int(t / 0.25) % 2
        freq = 1320.0 if cycle == 0 else 880.0
        sample = int(max(-32767, min(32767, 28500 * math.sin(2.0 * math.pi * freq * t))))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(dest), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return dest


def _terminate_and_reap(proc: subprocess.Popen[bytes] | None, *, immediate: bool = False) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            if immediate:
                proc.kill()
                proc.wait(timeout=0.2)
                return
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
        else:
            proc.wait(timeout=0.2)
    except Exception:
        pass


class AudioPlayer:
    """Trình phát âm thanh đa mức ưu tiên qua Loa Bluetooth chuyên dụng."""

    def __init__(
        self,
        bt_manager: BluetoothSpeakerManager,
        cache_dir: str | Path | None = None,
        *,
        siren_cooldown_s: float = 5.0,
    ) -> None:
        self.bt = bt_manager
        self.cache_dir = Path(cache_dir or (Path(__file__).resolve().parents[2] / "edge_cache" / "audio"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.siren_cooldown_s = max(0.5, float(siren_cooldown_s))

        self.chime_path = ensure_chime_wav(self.cache_dir / "chime.wav")
        self.siren_path = ensure_siren_wav(self.cache_dir / "emergency_siren.wav")

        self._has_pw_play = shutil.which("pw-play") is not None
        self._has_paplay = shutil.which("paplay") is not None
        self._has_ffmpeg = shutil.which("ffmpeg") is not None
        self._has_espeak = shutil.which("espeak-ng") or shutil.which("espeak")

        self._lock = threading.Lock()
        self._closed = False
        self._live_input: LiveInput | None = None
        self._interrupted = set()
        self._current_proc: subprocess.Popen[bytes] | None = None
        self._current_priority: int = 0  # 0: idle, 1: normal/reminder, 2: emergency
        self._current_is_gas: bool = False
        self._silenced_until: float = 0.0
        self._siren_in_flight: set[str] = set()
        self._last_siren_ts: dict[str, float] = {}
        self._pending_voice = 0
        self.history: deque[dict[str, Any]] = deque(maxlen=100)

    def is_busy(self) -> bool:
        """Report playback until the child process has actually finished."""
        with self._lock:
            return self._live_input is not None or self._pending_voice > 0 or bool(self._current_proc is not None and self._current_proc.poll() is None)

    def stop(self) -> None:
        """Dừng và thu hồi tiến trình âm thanh đang chạy khi tắt Edge Runtime."""
        with self._lock:
            self._closed = True
            if self._live_input is not None:
                self._live_input.interrupt()
            proc = self._current_proc
            self._current_proc = None
            self._current_priority = 0
            self._current_is_gas = False
        _terminate_and_reap(proc)

    def silence(self, duration_s: float = 120.0) -> None:
        """Tạm ngắt âm thanh cảnh báo không phải khí gas trong `duration_s` giây.

        Nếu đang phát còi báo rò rỉ khí gas (`_current_is_gas == True`), tuyệt đối KHÔNG ngắt còi!
        """
        proc_to_stop: subprocess.Popen[bytes] | None = None
        with self._lock:
            if self._live_input is not None:
                self._live_input.interrupt()
            self._silenced_until = time.monotonic() + max(1.0, float(duration_s))
            if (
                self._current_proc is not None
                and self._current_proc.poll() is None
                and not self._current_is_gas
            ):
                proc_to_stop = self._current_proc
                self._interrupted.add(proc_to_stop)
                self._current_proc = None
                self._current_priority = 0
        _terminate_and_reap(proc_to_stop)
        self.history.append({"type": "silence", "duration_s": float(duration_s), "ts": time.time()})

    def is_silenced(self) -> bool:
        with self._lock:
            return time.monotonic() < self._silenced_until

    def synthesize_tts_wav(self, text: str) -> Path:
        """Tổng hợp giọng nói tiếng Việt offline qua `espeak-ng --stdin` (chống CLI option injection)."""
        clean = (text or "").strip()[:1500]
        digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:16]
        out_path = self.cache_dir / f"tts_{digest}.wav"
        if out_path.exists() and out_path.stat().st_size > 500:
            return out_path

        if self._has_espeak and clean:
            with tempfile.NamedTemporaryFile(dir=self.cache_dir, suffix=".wav", delete=False) as stream:
                temp_path = Path(stream.name)
            try:
                subprocess.run(
                    [self._has_espeak, "-v", "vi", "-s", "145", "-w", str(temp_path), "--stdin"],
                    input=clean.encode("utf-8"), check=True, capture_output=True, timeout=6.0,
                )
                with wave.open(str(temp_path), "rb") as wav:
                    if wav.getnframes() == 0:
                        return self.chime_path
                temp_path.replace(out_path)
                return out_path
            except (OSError, EOFError, wave.Error, subprocess.SubprocessError) as exc:
                logger.warning("[AudioPlayer] Lỗi gọi eSpeak TTS: %s", type(exc).__name__)
            finally:
                temp_path.unlink(missing_ok=True)

        return self.chime_path

    def _prepare_file(self, file_path: Path) -> Path | None:
        if file_path in (self.chime_path, self.siren_path):
            return file_path
        if not self._has_ffmpeg:
            return None
        with tempfile.NamedTemporaryFile(dir=self.cache_dir, suffix=".wav", delete=False) as temp:
            converted = Path(temp.name)
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(file_path),
                 "-vn", "-ar", "48000", "-ac", "2",
                 "-af", "volume=-6dB,adelay=250:all=1,apad=pad_dur=0.6",
                 "-c:a", "pcm_s16le", str(converted)],
                check=True, capture_output=True, timeout=10,
            )
            return converted
        except (OSError, subprocess.SubprocessError) as error:
            converted.unlink(missing_ok=True)
            logger.warning("[AudioPlayer] Lỗi giải mã: %s", type(error).__name__)
            return None

    def _spawn_bluetooth_player(self, file_path: Path, sink: str, backend: str):
        if backend == "wpctl" and self._has_pw_play:
            command = ["pw-play", "--target", str(sink), "--latency", "200ms",
                       "--properties", '{"node.dont-fallback":true,"node.dont-reconnect":true}']
        elif backend == "pactl" and self._has_paplay:
            command = ["paplay", f"--device={sink}"]
        else:
            raise OSError("Thiếu trình phát cho Bluetooth sink.")
        return subprocess.Popen(
            [*command, str(file_path)], env=get_audio_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def _watch_and_reap(
        self,
        proc: subprocess.Popen[bytes],
        cleanup_paths: tuple[Path | None, ...],
        label: str,
        on_finished: Callable[[bool], None] | None,
    ) -> None:
        success = False
        try:
            try:
                status = proc.wait(timeout=180)
            except subprocess.TimeoutExpired:
                _terminate_and_reap(proc)
                raise
            success = status == 0
            if success:
                logger.info("[AudioPlayer] Đã phát xong %r qua Bluetooth.", label)
            else:
                logger.warning("[AudioPlayer] Trình phát %r dừng với mã %d.", label, status)
        except subprocess.TimeoutExpired:
            logger.warning("[AudioPlayer] Phát %r quá thời gian.", label)
        finally:
            with self._lock:
                success = success and proc not in self._interrupted and not self._closed
                self._interrupted.discard(proc)
                if self._current_proc is proc:
                    self._current_proc = None
                    self._current_priority = 0
                    self._current_is_gas = False
            if on_finished is not None:
                on_finished(success)
            for path in cleanup_paths:
                if path is not None:
                    path.unlink(missing_ok=True)

    def play_file(
        self,
        file_path: str | Path,
        *,
        volume: int = 75,
        priority: int = 1,
        label: str = "audio",
        bypass_silence: bool = False,
        is_gas: bool = False,
        cleanup_after_play: bool = False,
        wait_for_completion: bool = False,
        start_guard: Callable[[], bool] | None = None,
        on_finished: Callable[[bool], None] | None = None,
    ) -> tuple[bool, str]:
        """Phát file âm thanh qua Loa Bluetooth chuyên dụng."""
        path = Path(file_path)
        if not path.exists():
            return False, f"Không tìm thấy file âm thanh: {path.name}"

        converted = None
        proc = None
        original_to_remove = path if cleanup_after_play else None
        try:
            if not self.bt.is_speaker_ready():
                return False, "Loa Bluetooth chưa kết nối."
            if not self.bt.mock_mode:
                prepared = self._prepare_file(path)
                if prepared is None:
                    return False, "Không thể giải mã file âm thanh."
                converted = prepared if prepared != path else None
            with self._lock:
                if self._closed:
                    return False, "Phát đã bị hủy vì thiết bị đang tắt."
                if start_guard is not None and not start_guard():
                    return False, "Phát đã bị hủy vì lịch đã thay đổi hoặc quá hạn."
                if not bypass_silence and not is_gas and time.monotonic() < self._silenced_until:
                    return False, "Thiết bị đang trong thời gian tạm tắt âm (silence)."
                current = self._current_proc
                if current is not None and current.poll() is None:
                    if (self._current_is_gas and not is_gas) or priority < self._current_priority or priority == self._current_priority < 2:
                        return False, "Loa đang bận phát âm thanh."
                    self._interrupted.add(current)
                    _terminate_and_reap(current, immediate=priority >= 2)
                if self._live_input is not None:
                    if priority < 2:
                        return False, "Loa đang phát đàm thoại."
                    self._live_input.interrupt()
                self.bt.apply_volume(volume, refresh=False)
                status = self.bt.get_status()
                sink = status["sink"]
                if not sink:
                    return False, "Loa Bluetooth đã ngắt kết nối."
                if not status["mock_mode"]:
                    proc = self._spawn_bluetooth_player(converted or path, sink, status["backend"])
                    self._current_proc = proc
                    self._current_priority = priority
                    self._current_is_gas = is_gas
                self.history.append(dict(type="play", label=label, file=path.name, volume=volume,
                                         priority=priority, is_gas=is_gas, mock=status["mock_mode"],
                                         ts=time.time()))

            if proc is None:
                if on_finished is not None:
                    on_finished(True)
                return True, "Đã phát qua loa Bluetooth mô phỏng."
            paths = (original_to_remove, converted)
            if not wait_for_completion:
                threading.Thread(target=self._watch_and_reap, args=(proc, paths, label, on_finished),
                                 name="audio-proc-reaper", daemon=True).start()
                return True, f"Đã khởi chạy trình phát '{label}'."
            try:
                exit_code = proc.wait(timeout=180)
                with self._lock:
                    interrupted = proc in self._interrupted or self._closed
                if interrupted:
                    return False, f"Phát '{label}' đã bị ngắt."
                if exit_code:
                    return False, f"Trình phát '{label}' lỗi (mã {exit_code})."
                status = self.bt.get_status()
                if not status["ready"] or status["sink"] != sink:
                    return False, f"Loa Bluetooth đã đổi hoặc ngắt khi phát '{label}'."
                return True, f"Trình phát '{label}' đã hoàn thành."
            except subprocess.TimeoutExpired:
                _terminate_and_reap(proc)
                return False, f"Phát '{label}' quá thời gian."
            finally:
                with self._lock:
                    self._interrupted.discard(proc)
                    if self._current_proc is proc:
                        self._current_proc = None
                        self._current_priority = 0
                        self._current_is_gas = False
        except OSError as exc:
            return False, f"Không mở được trình phát Bluetooth: {exc}"
        finally:
            if proc is None or wait_for_completion:
                for temporary in (original_to_remove, converted):
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)

    def start_live_stream(self, mime: str) -> LiveInput | None:
        if mime not in FORMATS or not self.bt.is_speaker_ready():
            return None
        status = self.bt.get_status()
        sink, backend = status["sink"], status["backend"]
        if not sink:
            return None
        try:
            target = self.bt.resolve_live_target(sink, backend)
            with self._lock:
                if (self._closed or self._live_input is not None or self._pending_voice
                        or time.monotonic() < self._silenced_until
                        or (self._current_proc is not None and self._current_proc.poll() is None)):
                    return None
                current = self.bt.get_status()
                if (current["sink"], current["backend"]) != (sink, backend):
                    return None
                if not self.bt.apply_volume(85, refresh=False):
                    return None
                self._live_input = LiveInput(mime, target, backend)
                return self._live_input
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            logger.warning("[AudioPlayer] Push-to-Talk chưa sẵn sàng: %s", exc)
            return None

    def finish_live_stream(self, stream: LiveInput):
        stream.close()
        with self._lock:
            if self._live_input is stream:
                self._live_input = None

    def trigger_emergency_siren(
        self,
        kind: str = "fall",
        reason: str = "",
        *,
        now_monotonic: float | None = None,
    ) -> tuple[bool, str]:
        """Kích hoạt Còi báo động khẩn cấp tại chỗ ở âm lượng 100% (vượt qua cả Chế độ ban đêm).

        Lưu ý an toàn: Sự kiện khí gas (`kind == "gas"`) KHÔNG BAO GIỜ bị chặn hay bị tắt bởi lệnh `silence`.
        """
        mono = time.monotonic() if now_monotonic is None else float(now_monotonic)
        kind = kind.lower()
        is_gas = kind == "gas"

        if not is_gas and self.is_silenced():
            return False, "Còi cảnh báo đang tạm tắt theo lệnh người dùng."

        with self._lock:
            last_ts = self._last_siren_ts.get(kind, -1e9)
            if kind in self._siren_in_flight or mono - last_ts < self.siren_cooldown_s:
                return False, "Còi khẩn cấp đang phát hoặc trong chu kỳ chống dội."
            self._siren_in_flight.add(kind)

        def finished(success: bool) -> None:
            with self._lock:
                self._siren_in_flight.discard(kind)
                if success:
                    self._last_siren_ts[kind] = mono

        ok = False
        try:
            ok, detail = self.play_file(
                self.siren_path, volume=100, priority=3 if is_gas else 2,
                label=f"emergency_{kind}", bypass_silence=is_gas, is_gas=is_gas,
                on_finished=finished,
            )
        finally:
            if not ok:
                finished(False)
        if ok and reason and not self.bt.mock_mode and self._has_espeak:
            tts_wav = self.synthesize_tts_wav(reason)
            if tts_wav != self.chime_path:
                with self._lock:
                    self._pending_voice += 1
                threading.Thread(
                    target=self._delayed_voice_warning,
                    args=(tts_wav, is_gas),
                    daemon=True,
                ).start()
        return ok, detail

    def _delayed_voice_warning(self, tts_wav: Path, is_gas: bool) -> None:
        try:
            time.sleep(2.1)
            self.play_file(
                tts_wav,
                volume=100,
                priority=3 if is_gas else 2,
                label="emergency_tts",
                bypass_silence=is_gas,
                is_gas=is_gas,
            )
        finally:
            with self._lock:
                self._pending_voice -= 1

    def execute_audio_command(
        self,
        command: dict[str, Any],
        asset_resolver: Callable[[str], Path | None] | None = None,
        *,
        start_guard: Callable[[], bool] | None = None,
    ) -> tuple[bool, str]:
        """Thực thi các lệnh âm thanh từ Web UI (`test_speaker`, `play_audio`, `silence`)."""
        kind = command.get("kind")
        payload = command.get("payload") or {}
        volume = int(payload.get("volume") if payload.get("volume") is not None else 75)

        if kind == "silence":
            seconds = float(payload.get("seconds") or 120.0)
            self.silence(duration_s=seconds)
            return True, f"Đã tạm ngắt còi báo tại chỗ trong {int(seconds)} giây (trừ cảnh báo rò khí gas)."

        if kind == "test_speaker":
            return self.play_file(
                self.chime_path, volume=volume, priority=0, label="test_speaker",
                wait_for_completion=True, start_guard=start_guard,
            )

        if kind == "play_audio":
            asset_id = str(payload.get("asset_id") or "").strip()
            if not asset_id:
                return False, "Thiếu mã file âm thanh (asset_id)."
            audio_path = asset_resolver(asset_id) if asset_resolver else None
            if audio_path is None or not audio_path.exists():
                return False, f"Không thể tải file âm thanh '{asset_id}' trên thiết bị."
            return self.play_file(
                audio_path, volume=volume, priority=1, label=f"asset:{asset_id}",
                wait_for_completion=True, start_guard=start_guard,
            )

        return False, f"Lệnh âm thanh không hỗ trợ: {kind!r}"
