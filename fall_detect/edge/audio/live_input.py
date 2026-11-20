"""A session-long decoder feeding a Bluetooth-targeted PCM player."""
import asyncio
import os
import subprocess
import time

from .bluetooth_manager import get_audio_env

FORMATS = {"audio/webm": "webm", "audio/ogg": "ogg"}
MAX_CHUNK = 32 * 1024
MAX_SESSION_BYTES = 1024 * 1024
SESSION_SECONDS = 60


class LiveInput:
    def __init__(self, mime, sink, backend):
        self.decoder = self.output = None
        self.interrupted = False
        if backend == "mock":
            return
        if backend == "wpctl":
            command = ["pw-cat", "--playback", "--target", sink, "--latency", "100ms",
                       "--properties", '{"node.dont-fallback":true,"node.dont-reconnect":true}', "-"]
            # AU carries a streamable PCM header on PipeWire versions without --raw.
            codec, container = "pcm_s16be", "au"
        elif backend == "pactl":
            command = ["paplay", "--device=" + sink, "--latency-msec=100", "--raw",
                       "--rate=48000", "--channels=1", "--format=s16le"]
            codec, container = "pcm_s16le", "s16le"
        else:
            raise ValueError("Không có đầu ra Bluetooth phù hợp.")
        try:
            self.decoder = subprocess.Popen(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-probesize", "4096",
                 "-analyzeduration", "1", "-f", FORMATS[mime], "-i", "pipe:0", "-vn",
                 "-af", "volume=-6dB", "-c:a", codec, "-ar", "48000", "-ac", "1",
                 "-flush_packets", "1", "-f", container, "pipe:1"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            self.output = subprocess.Popen(
                command, stdin=self.decoder.stdout, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=get_audio_env(),
            )
            self.decoder.stdout.close()
            os.set_blocking(self.decoder.stdin.fileno(), False)
        except (OSError, ValueError):
            self.close()
            raise

    async def write(self, chunk):
        if self.interrupted:
            raise ConnectionError("Đàm thoại đã bị ngắt.")
        if self.decoder is None:  # Mock speaker
            return
        if self.output.poll() is not None or self.decoder.poll() is not None:
            raise ConnectionError("Trình phát Push-to-Talk đã dừng.")
        pending = memoryview(chunk)
        deadline = time.monotonic() + 0.35
        while pending:
            try:
                pending = pending[os.write(self.decoder.stdin.fileno(), pending):]
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Đầu ra Bluetooth xử lý không kịp.")
                await asyncio.sleep(0.01)

    def interrupt(self):
        self.interrupted = True
        for proc in (self.output, self.decoder):
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    def close(self):
        self.interrupt()
        for proc in (self.output, self.decoder):
            if proc is not None:
                proc.wait()
                for stream in (proc.stdin, proc.stdout):
                    if stream is not None:
                        stream.close()
