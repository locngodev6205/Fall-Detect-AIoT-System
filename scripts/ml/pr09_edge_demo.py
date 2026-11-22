"""Replay or run the real Edge vision loop with isolated event delivery."""
import argparse
from contextlib import nullcontext
import json
import logging
from pathlib import Path
import resource
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "fall_detect"), str(ROOT)]

import cv2
import config
from edge.main_edge import AnNhaEdgeRuntime
from ml.features import video_frame_timestamp
from research.benchmark import quantiles


class EndOfDemo(Exception):
    pass


class Capture:
    def __init__(self, source, live, seconds):
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError("Capture unavailable")
        self.live = live
        if live:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        self.started = time.monotonic()
        self.seconds = seconds
        self.stamp = None
        self.frames = 0
        self.frame_gaps = []
        self.size = None

    def read(self):
        if self.live and time.monotonic()-self.started >= self.seconds:
            raise EndOfDemo
        ok, frame = self.cap.read()
        if not ok and not self.live:
            raise EndOfDemo
        if ok:
            previous = self.stamp
            self.stamp = (time.monotonic() if self.live else video_frame_timestamp(
                self.cap.get(cv2.CAP_PROP_POS_MSEC), self.cap.get(cv2.CAP_PROP_FPS), previous))
            if previous is not None:
                self.frame_gaps.append(self.stamp-previous)
            self.frames += 1
            self.size = list(frame.shape[:2][::-1])
        return ok, frame

    def release(self):
        self.cap.release()


def thermal():
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text())/1000
    except (OSError, ValueError):
        return None


def run(args, device=None, alerts=None, frame_probe=None):
    config.FALL_MODEL_BACKEND = "gru_e4_42"
    config.FALL_GRU_CHECKPOINT = str(args.checkpoint)
    source = args.camera if args.camera is not None else str(args.video)
    with tempfile.TemporaryDirectory(prefix="annha-pr09-") as cache:
        runtime = AnNhaEdgeRuntime(base_url="http://127.0.0.1:1", device_token="demo-only",
                                   cache_dir=Path(cache), force_mock_hardware=True)
        capture = Capture(source, args.camera is not None, args.seconds)
        logged, sent = [], []
        metrics = dict(pose_ms=[], gru_ms=[], model_errors=0, timestamp_resets=0)
        jpeg_frames = 0
        real_submit = runtime.fall_alerts.submit
        real_jpeg = runtime.streamer.update_frame_jpeg

        def submit(confidence, reason, jpeg):
            logged.append(dict(timestamp=capture.stamp, confidence=confidence, jpeg=bool(jpeg)))
            real_submit(confidence, reason, jpeg)

        def send_event(**payload):
            payload.pop("queue_on_failure")
            if device is None:
                result = {"id": payload["event_id"]}
            else:
                response = device.post("/api/device/events", json=payload)
                response.raise_for_status()
                result = response.json()
                retry = device.post("/api/device/events", json=payload)
                retry.raise_for_status()
                assert retry.json()["id"] == result["id"]
            sent.append(result["id"])
            return result

        def publish(jpeg, **kwargs):
            nonlocal jpeg_frames
            jpeg_frames += 1
            if capture.live and jpeg_frames == 1 and runtime.model_inference_ok:
                print("CAMERA READY", flush=True)
            real_jpeg(jpeg, **kwargs)

        runtime.fall_alerts.submit = submit
        runtime.audio.trigger_emergency_siren = lambda *_: None
        runtime.client.send_event = send_event
        runtime.client.upload_evidence = lambda *a, **kw: None
        runtime.streamer.update_frame_jpeg = publish
        workers = runtime.fall_alerts.start()
        start, cpu = time.monotonic(), time.process_time()
        start_temp = thermal()
        try:
            runtime._run_opencv_mediapipe_loop(
                capture, frame_timestamp=lambda: capture.stamp, metrics=metrics)
        except EndOfDemo:
            pass
        finally:
            # Let the actual Edge delivery queue drain before ending the demo.
            deadline = time.monotonic() + 3
            while runtime.unreported_alert and time.monotonic() < deadline:
                time.sleep(.02)
            runtime._stop_event.set()
            for worker in workers:
                worker.join(1)
            capture.release()
        elapsed = time.monotonic()-start
        if not runtime.model_inference_ok or not capture.frames:
            raise RuntimeError("GRU or capture unavailable")
        if len(logged) != len(sent):
            raise RuntimeError("Fall delivery queue did not drain")
        if alerts is not None and sent:
            assert all(alerts.receive_json()["id"] == event_id for event_id in sent)
        if frame_probe is not None:
            frame_probe(runtime.streamer.get_latest_jpeg())
        return dict(events=logged, delivered=len(sent), jpeg_frames=jpeg_frames,
                    frames=capture.frames, size=capture.size, fps=capture.frames/elapsed,
                    timestamp_gaps_ms=quantiles([x*1000 for x in capture.frame_gaps]),
                    gaps_over_100ms=sum(x > .1001 for x in capture.frame_gaps),
                    cpu_percent=100*(time.process_time()-cpu)/elapsed,
                    peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                    temperature_start_c=start_temp, temperature_end_c=thermal(),
                    pose_fps=len(metrics["pose_ms"])/elapsed,
                    pose_ms=quantiles(metrics["pose_ms"]), gru_ms=quantiles(metrics["gru_ms"]),
                    scored_windows=len(metrics["gru_ms"]),
                    model_errors=metrics["model_errors"], timestamp_resets=metrics["timestamp_resets"])


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", type=Path)
    source.add_argument("--camera", type=int)
    parser.add_argument("--seconds", type=float, default=25.)
    parser.add_argument("--web-probe", action="store_true", help="Isolated SQLite + WebSocket")
    args = parser.parse_args()
    if args.output.exists() or args.seconds <= 0:
        parser.error("Use a fresh output and a positive duration")
    if args.web_probe:
        from backend.tests.test_business import BusinessTests
        fixture = BusinessTests()
        fixture.setUp()
        try:
            owner, _ = fixture.account("pr09-demo@example.test")
            home, _, camera, provision = fixture.home_camera(owner)
            device = fixture.device(provision)
            heartbeat = device.post("/api/device/heartbeat", json={
                "observation": "clear", "capabilities": {
                    "camera": True, "speaker": False, "sensors": False, "show_landmarks": False,
                },
            })
            heartbeat.raise_for_status()

            def frame_probe(frame):
                assert frame, "No frame from actual Edge renderer"
                with owner.websocket_connect(f'/ws/cameras/{camera["id"]}') as viewer:
                    with device.websocket_connect("/ws/device/frames") as sender:
                        sender.send_bytes(frame)
                        assert viewer.receive_bytes() == frame
            with owner.websocket_connect(f'/ws/alerts?home_id={home["id"]}') as alerts:
                result = run(args, device, alerts, frame_probe)
            history = owner.get(f'/api/homes/{home["id"]}/events')
            history.raise_for_status()
            assert len(history.json()) == result["delivered"]
            result["history_events"] = len(history.json())
            result["websocket_events"] = result["delivered"]
            result["websocket_jpeg"] = True
            result["heartbeat_http"] = heartbeat.status_code
        finally:
            fixture.tearDown()
    else:
        result = run(args)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)


if __name__ == "__main__":
    main()
