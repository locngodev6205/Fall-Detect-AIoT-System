"""Display the Edge JPEG stream on the Pi desktop without opening the camera again."""
import logging
import os
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


def show_preview(streamer, stop):
    player = shutil.which("ffplay")
    if not player:
        logger.warning("[Preview] Thiếu ffplay. Cài gói ffmpeg để xem camera trên desktop.")
        return

    env = os.environ.copy()
    if not env.get("WAYLAND_DISPLAY") and not env.get("DISPLAY"):
        runtime_dir = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        socket = runtime_dir / "wayland-0"
        if socket.is_socket():
            env.update(XDG_RUNTIME_DIR=str(runtime_dir), WAYLAND_DISPLAY=socket.name,
                       SDL_VIDEODRIVER="wayland")
        elif Path("/tmp/.X11-unix/X0").is_socket():
            env["DISPLAY"] = ":0"
        else:
            logger.warning("[Preview] Chưa tìm thấy phiên desktop trên Pi.")
            return

    while not stop.is_set() and streamer.get_preview_jpeg() is None:
        stop.wait(0.1)
    if stop.is_set():
        return

    try:
        with subprocess.Popen(
            [player, "-hide_banner", "-loglevel", "error", "-probesize", "32",
             "-analyzeduration", "0", "-f", "mjpeg", "-framerate",
             str(1 / streamer.min_frame_interval), "-an", "-sync", "ext",
             "-framedrop", "-window_title", "AnNhà - Camera Pi", "-i", "pipe:0"],
            env=env, stdin=subprocess.PIPE,
        ) as process:
            try:
                last = None
                while not stop.is_set() and process.poll() is None:
                    jpeg = streamer.get_preview_jpeg()
                    if jpeg is None or jpeg is last:
                        stop.wait(0.02)
                        continue
                    process.stdin.write(jpeg)
                    process.stdin.flush()
                    last = jpeg
            except BrokenPipeError:
                pass
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
    except OSError:
        logger.warning("[Preview] Không mở được cửa sổ camera trên desktop.", exc_info=True)
