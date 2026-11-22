"""Local maintenance handshake served on a restricted Unix socket."""
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import socketserver
import threading
import time


def maintenance_guard(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with self.update_lock:
            if function.__name__ == 'handle_fall_detected':
                self.maintenance_until = 0
            elif function.__name__ != '_evaluate_local_autonomous_safety' and time.monotonic() < self.maintenance_until:
                return False, 'Thiết bị đang chuẩn bị cập nhật'
            result = function(self, *args, **kwargs)
            if function.__name__ == '_evaluate_local_autonomous_safety':
                self.last_safety_check = time.monotonic()
            if self.local_danger:
                self.maintenance_until = 0
            return result
    return wrapped


class UpdateStatusServer:
    def __init__(self, runtime, root):
        self.runtime = runtime
        self.root = root
        self.server = None
        self.model_sha256 = ''
        self.runtime_sha256 = hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest()
        model = root / 'models/fall_detection_transformer.tflite'
        if model.exists():
            self.model_sha256 = hashlib.sha256(model.read_bytes()).hexdigest()
        release = root / 'release.json'
        self.version = json.loads(release.read_text())['version'] if release.exists() else 'unmanaged'

    def status(self):
        r = self.runtime
        now = time.monotonic()
        camera_stamp = r.last_camera_frame
        safety_stamp = getattr(r, 'last_safety_check', 0)
        fresh = camera_stamp > 0 and 0 <= now - camera_stamp < 5
        safety_fresh = safety_stamp > 0 and 0 <= now - safety_stamp < 5
        healthy = fresh and safety_fresh and r.model_inference_ok and not r.force_mock_hardware
        busy = r.audio_worker.is_busy() or r.audio.is_busy()
        ready = healthy and not r.local_danger and not r.unreported_alert and not busy
        reason = '' if ready else ('Nguy hiểm hoặc cảnh báo chưa gửi' if r.local_danger or r.unreported_alert else
            'Âm thanh đang phát' if busy else 'Camera, model hoặc giám sát an toàn chưa sẵn sàng')
        return {'current_version': self.version, 'model_sha256': self.model_sha256,
            'runtime_sha256': self.runtime_sha256, 'target': 'linux-arm64',
            'maintenance_active': time.monotonic() < r.maintenance_until,
            'healthy': healthy, 'ready': ready, 'reason': reason, 'pid': os.getpid()}

    def start(self):
        path = os.getenv('ANNHA_UPDATE_SOCKET')
        if not path:
            return
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        Path(path).unlink(missing_ok=True)
        owner = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(3)
                request = json.loads(self.rfile.readline(1024))
                with owner.runtime.update_lock:
                    result = owner.status()
                    if request.get('action') == 'prepare' and result['ready']:
                        owner.runtime.maintenance_until = time.monotonic() + 60
                        result['prepared'] = True
                    elif request.get('action') == 'resume':
                        owner.runtime.maintenance_until = 0
                    self.wfile.write(json.dumps(result).encode() + b'\n')
        self.server = socketserver.ThreadingUnixStreamServer(path, Handler)
        self.server.daemon_threads = True
        os.chmod(path, 0o600)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            Path(os.environ['ANNHA_UPDATE_SOCKET']).unlink(missing_ok=True)
