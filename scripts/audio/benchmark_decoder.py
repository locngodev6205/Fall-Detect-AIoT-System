#!/usr/bin/env python3
"""Measure host-side first PCM, decoder RSS/CPU, and input pipe occupancy.

Run from the repository root on Linux. The sink is a temporary file fed by cat.
This benchmark does not use a Bluetooth device, browser, or audio daemon.
"""
import array
import asyncio
import fcntl
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import tempfile
import termios
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fall_detect.edge.audio.live_input import FORMATS, LiveInput  # noqa: E402


def fixture(container):
    packetization = (["-cluster_time_limit", "200"] if container == "webm"
                     else ["-page_duration", "200000"])
    return subprocess.check_output([
        "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "4", "-c:a", "libopus", "-b:a", "48k", "-vbr", "off",
        *packetization, "-f", container, "pipe:1",
    ])


def pipe_pending(fd):
    pending = array.array("i", [0])
    fcntl.ioctl(fd, termios.FIONREAD, pending, True)
    return pending[0]


def rss_kib(pid):
    lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    return next(int(line.split()[1]) for line in lines if line.startswith("VmRSS:"))


async def sample(mime, encoded, capture):
    popen = subprocess.Popen
    with capture.open("wb") as output:
        def start(command, **options):
            if Path(command[0]).name == "pw-cat":
                return popen(["cat"], stdin=options["stdin"], stdout=output)
            return popen(command, **options)

        with patch.object(subprocess, "Popen", side_effect=start), patch("shutil.which", side_effect=lambda name: name):
            stream = LiveInput(mime, "fixture", "wpctl")
        started = time.monotonic()
        first_pcm = None
        max_pending = max_rss = offset = 0
        # Approximately 200 ms of encoded data per chunk, with the stream left open.
        chunk_size = len(encoded) // 20
        try:
            for tick in range(220):
                if tick % 20 == 0 and offset < len(encoded) // 2:
                    await stream.write(encoded[offset:offset + chunk_size])
                    offset += chunk_size
                    max_rss = max(max_rss, rss_kib(stream.decoder.pid))
                max_pending = max(max_pending, pipe_pending(stream.decoder.stdin.fileno()))
                if first_pcm is None and capture.stat().st_size > 1024:
                    first_pcm = time.monotonic() - started
                await asyncio.sleep(0.01)
            if first_pcm is None:
                raise RuntimeError(f"{mime} produced no PCM before stop")
            return first_pcm * 1000, max_pending, max_rss
        finally:
            stream.close()


def children_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


async def main():
    with tempfile.TemporaryDirectory() as temp:
        for mime, container in FORMATS.items():
            encoded = fixture(container)
            started = time.monotonic()
            cpu_before = children_cpu()
            samples = [await sample(mime, encoded, Path(temp) / "pcm") for _ in range(5)]
            latency, pending, rss = zip(*samples)
            cpu = 100 * (children_cpu() - cpu_before) / (time.monotonic() - started)
            print(f"{container}: first PCM median {statistics.median(latency):.1f} ms, "
                  f"max {max(latency):.1f} ms, input pipe max {max(pending)} B, "
                  f"decoder RSS max {max(rss)} KiB, child CPU {cpu:.2f}% of one core",
                  flush=True)


if __name__ == "__main__":
    asyncio.run(main())
