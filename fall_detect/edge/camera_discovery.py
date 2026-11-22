"""Discover a usable Linux camera by reading a real frame (not just opening a node).

No hardware is accessed while importing this module. Explicit integer indices stay
supported for debugging; `auto` prefers a stable V4L2 by-id path and then probes
/dev/videoN candidates, skipping metadata nodes that cannot deliver frames.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("annha.edge.camera")


def normalize_camera_id(value: str | int | None) -> int | str:
    """Accept CAMERA_ID=auto or a nonnegative OpenCV camera index."""
    raw = "auto" if value is None else str(value).strip()
    if not raw or raw.lower() == "auto":
        return "auto"
    if raw.isdecimal():
        return int(raw)
    raise ValueError("CAMERA_ID phải là 'auto' hoặc một số nguyên không âm.")


def camera_sources(camera_id: str | int, device_root: Path = Path("/dev")) -> list[str | int]:
    """Return candidate camera nodes, preferring stable USB camera symlinks."""
    selector = normalize_camera_id(camera_id)
    if selector != "auto":
        return [selector]

    preferred = sorted((device_root / "v4l" / "by-id").glob("*-video-index0"))
    numeric = sorted(
        (path for path in device_root.glob("video*") if path.name[5:].isdecimal()),
        key=lambda path: int(path.name[5:]),
    )
    result: list[str | int] = []
    seen: set[Path] = set()
    for path in [*preferred, *numeric]:
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(str(path))
    return result


def open_working_camera(
    cv2: Any,
    camera_id: str | int = "auto",
    *,
    device_root: Path = Path("/dev"),
    probe_reads: int = 3,
) -> tuple[Any | None, str | int | None]:
    """Open the first camera that can actually return a nonempty video frame.

    The caller owns the successful VideoCapture and must release it.
    All unsuccessful captures are released here.
    """
    for source in camera_sources(camera_id, device_root):
        capture = None
        try:
            backend = getattr(cv2, "CAP_V4L2", None)
            capture = cv2.VideoCapture(source, backend) if backend is not None else cv2.VideoCapture(source)
            if not capture.isOpened():
                continue
            for _ in range(max(1, probe_reads)):
                ok, frame = capture.read()
                if ok and frame is not None and getattr(frame, "size", 0) > 0:
                    logger.info("[Vision] Camera hoạt động: %s", source)
                    return capture, source
        except Exception as error:
            logger.warning("[Vision] Không đọc được %s: %s", source, error)
        finally:
            # On success the returned capture stays opened; ownership moves to caller.
            if capture is not None and (not capture.isOpened() or not (
                'ok' in locals() and ok and 'frame' in locals() and
                frame is not None and getattr(frame, "size", 0) > 0
            )):
                capture.release()
    return None, None
