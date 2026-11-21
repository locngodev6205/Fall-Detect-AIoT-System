#!/usr/bin/env python3
"""Independent Pi updater with signed staging and durable rollback journal."""
import argparse
import base64
import fcntl
import hashlib
import http.client
import ipaddress
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import subprocess
import tarfile
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit

LOG = logging.getLogger('annha-updater')
VERSION = re.compile(r'^\d{1,6}\.\d{1,6}\.\d{1,6}$')
TERMINAL = {'succeeded', 'failed', 'rolled_back', 'cancelled', 'expired'}


LOCAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8',
    '::1/128', 'fc00::/7', '100.64.0.0/10',
))


def validate_backend_url(value):
    url = urlsplit(value)
    if (url.scheme not in ('http', 'https') or not url.hostname or
            url.username is not None or url.password is not None or
            url.query or url.fragment or value != value.strip()):
        raise ValueError('Backend URL không hợp lệ')
    _ = url.port
    if url.scheme == 'http' and url.hostname != 'localhost':
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            raise ValueError('Backend từ xa yêu cầu HTTPS') from None
        if not any(address in network for network in LOCAL_NETWORKS):
            raise ValueError('Backend từ xa yêu cầu HTTPS')
    return value.rstrip('/')


class TemporaryNetworkError(RuntimeError):
    pass


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def extract_bundle(bundle, directory):
    with tarfile.open(bundle, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) > 5000 or sum(m.size for m in members) > 128 * 1024 * 1024:
            raise ValueError('Gói giải nén quá lớn')
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Đường dẫn hoặc loại tệp trong gói không hợp lệ')
        for member in members:
            if member.isdir():
                (directory / member.name).mkdir(parents=True, exist_ok=True)
                continue
            target = directory / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
            target.chmod(0o644)


class Updater:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.shared = self.root / 'shared'
        self.releases = self.root / 'releases'
        self.staging = self.root / 'staging'
        self.staging.mkdir(parents=True, exist_ok=True)
        self.releases.mkdir(parents=True, exist_ok=True)
        self.config = json.loads((self.shared / 'updater.json').read_text())
        self.base = validate_backend_url(self.config['backend_url'])
        self.token = self.config['device_token']
        self.journal = self.shared / 'update-journal.json'
        self.previous_file = self.shared / 'previous.json'
        self.socket = str(self.shared / 'update.sock')
        self.lock = (self.shared / 'updater.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def request(self, path, body=None):
        for attempt in range(3):
            try:
                return self.request_once(path, body)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise
            except urllib.error.URLError as exc:
                if isinstance(exc.reason, ssl.SSLCertVerificationError):
                    raise ValueError('Không xác minh được chứng chỉ backend') from None
            except (OSError, http.client.IncompleteRead):
                pass
            if attempt < 2:
                time.sleep(2 ** attempt)
        raise TemporaryNetworkError('Backend tạm thời không phản hồi')

    def request_once(self, path, body=None):
        headers = {'Authorization': 'Bearer ' + self.token}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + '/api/device/updates/' + path, data=data, headers=headers)
        # Same-origin API calls must never forward device credentials to redirects.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
            if path.endswith('/bundle'):
                data = response.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise ValueError('Gói quá lớn')
                return data
            return json.loads(response.read(2 * 1024 * 1024))

    def local(self, action='status'):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(4)
            connection.connect(self.socket)
            connection.sendall(json.dumps({'action': action}).encode() + b'\n')
            with connection.makefile('rb') as stream:
                return json.loads(stream.readline(8192))

    def heartbeat(self):
        try:
            local = self.local()
        except (OSError, ValueError):
            local = {'current_version': self.current(), 'ready': False, 'reason': 'Ứng dụng chưa phản hồi'}
        previous = json.loads(self.previous_file.read_text()).get('version') if self.previous_file.exists() else None
        payload = {k: local[k] for k in ('current_version', 'ready', 'reason', 'model_sha256', 'runtime_sha256', 'target') if k in local}
        payload.update(previous_version=previous, updater_version='1')
        self.request('heartbeat', payload)
        return local

    def current(self):
        path = (self.root / 'current').resolve()
        return path.name if path.parent == self.releases and VERSION.fullmatch(path.name) else 'unmanaged'

    def target(self, version):
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise ValueError('Phiên bản không hợp lệ')
        return self.releases / version

    def report(self, job, status, message='', progress=0):
        return self.request(job['id'] + '/progress', {'status': status, 'message': message, 'progress': progress})

    def switch(self, version):
        target = self.target(version)
        if not (target / 'release.json').is_file():
            raise ValueError('Bản đích không tồn tại')
        temporary = self.root / 'current.next'
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target, target_is_directory=True)
        temporary.replace(self.root / 'current')
        fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def service(self, action):
        subprocess.run(['sudo', '-n', '/usr/bin/systemctl', action, 'annha-edge.service'], check=True, timeout=25, capture_output=True)

    def prepare(self, job, local):
        version = job['version']
        destination = self.target(version)
        if job['rollback']:
            if not (destination / 'release.json').exists():
                raise ValueError('Bản rollback đã mất')
            return destination
        release = job['release']
        raw = base64.b64decode(release['manifest64'], validate=True)
        signature = base64.b64decode(release['signature'], validate=True)
        manifest_file = self.staging / 'manifest.json'
        signature_file = self.staging / 'manifest.sig'
        manifest_file.write_bytes(raw)
        signature_file.write_bytes(signature)
        subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin', '-inkey', str(self.shared / 'release.pub'),
            '-in', str(manifest_file), '-sigfile', str(signature_file)], check=True, capture_output=True, timeout=10)
        manifest = json.loads(raw)
        if manifest.get('version') != version or not re.fullmatch(r'[a-f0-9]{64}', manifest.get('sha256', '')):
            raise ValueError('Manifest không hợp lệ')
        if platform.machine() not in ('aarch64', 'arm64') or manifest.get('target') != 'linux-arm64':
            raise ValueError('Bản này yêu cầu Pi chạy Linux ARM64')
        for key in ('model_sha256', 'runtime_sha256', 'target'):
            if not local.get(key) or manifest.get(key) != local[key]:
                raise ValueError('Model hoặc môi trường Python không tương thích')
        if type(manifest.get('bytes')) is not int or not 0 < manifest['bytes'] <= 64 * 1024 * 1024:
            raise ValueError('Kích thước manifest không hợp lệ')
        if shutil.disk_usage(self.root).free < 256 * 1024 * 1024 + manifest['bytes'] * 2:
            raise ValueError('Không đủ dung lượng trống để cập nhật')
        bundle = self.staging / (manifest['sha256'] + '.tar.gz')
        data = bundle.read_bytes() if bundle.is_file() and bundle.stat().st_size == manifest['bytes'] else b''
        if hashlib.sha256(data).hexdigest() != manifest['sha256']:
            data = self.request(job['id'] + '/bundle')
        if len(data) != manifest['bytes'] or hashlib.sha256(data).hexdigest() != manifest['sha256']:
            raise ValueError('Sai SHA-256 hoặc kích thước gói')
        temporary = bundle.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(bundle)
        directory = self.staging / ('release-' + job['id'])
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
        extract_bundle(bundle, directory)
        metadata = json.loads((directory / 'release.json').read_text())
        if any(metadata.get(k) != manifest.get(k) for k in ('version', 'commit', 'model_sha256', 'runtime_sha256', 'target')):
            raise ValueError('Thông tin gói khác manifest')
        (directory / 'models').symlink_to(self.shared / 'models', target_is_directory=True)
        (directory / 'edge_cache').symlink_to(self.shared / 'edge_cache', target_is_directory=True)
        (directory / '.env.edge').symlink_to(self.shared / 'app.env')
        if (self.shared / 'legacy.env').exists():
            (directory / '.env').symlink_to(self.shared / 'legacy.env')
        if destination.exists():
            if self.current() == version:
                raise ValueError('Đang chạy bản đích')
            previous = json.loads(self.previous_file.read_text()).get('version') if self.previous_file.exists() else None
            if previous == version:
                existing = json.loads((destination / 'release.json').read_text())
                if existing != metadata:
                    raise ValueError('Không thể ghi đè bản rollback')
                shutil.rmtree(directory)
                return destination
            shutil.rmtree(destination)
        directory.replace(destination)
        return destination

    def healthy(self, version, *, require_backend=True):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                local = self.heartbeat() if require_backend else self.local()
                if local.get('current_version') == version and local.get('healthy'):
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def recover(self):
        if not self.journal.exists():
            return
        journal = json.loads(self.journal.read_text())
        job = journal['job']
        if journal.get('outcome'):
            if journal.get('local_verified'):
                atomic_json(self.previous_file, {'version': journal['old']})
                self.report(job, 'health_check')
                self.heartbeat()
            if journal['outcome'] == 'rolled_back':
                self.report(job, 'rolling_back', 'Đã phục hồi bản trước')
            self.report(job, journal['outcome'], journal.get('message', ''), 100)
            self.journal.unlink()
            return
        offer = self.request('job') if not journal.get('claimed') else {}
        active = offer.get('job')
        if not journal.get('claimed') and (not active or active['id'] != job['id'] or active['status'] in ('pending', 'ready', 'deferred', 'downloading')):
            # Intent was written before the server claim, but the server did not claim it.
            self.journal.unlink()
            try:
                self.local('resume')
            except OSError:
                pass
            return
        if journal.get('phase') in ('claim_pending', 'claimed'):
            journal.update(phase='report_pending', outcome='failed',
                           message='Đã dừng cập nhật trước khi thay đổi ứng dụng')
            atomic_json(self.journal, journal)
            self.recover()
            return
        try:
            if journal.get('phase') != 'restored':
                self.service('stop')
                self.switch(journal['old'])
                self.service('start')
                journal['phase'] = 'restored'
                atomic_json(self.journal, journal)
            healthy = self.healthy(journal['old'], require_backend=False)
            outcome = 'rolled_back' if healthy else 'failed'
            message = 'Đã phục hồi bản trước' if healthy else 'Bản trước chưa vượt qua health check. Cần kiểm tra thiết bị.'
        except Exception:
            outcome, message = 'failed', 'Không phục hồi được service. Cần kiểm tra thiết bị.'
        journal.update(phase='report_pending', outcome=outcome, message=message)
        atomic_json(self.journal, journal)
        self.recover()

    def install(self, job):
        old = self.current()
        if old == 'unmanaged':
            raise ValueError('Cần cài nền cập nhật trước khi dùng OTA')
        journal = {'job': job, 'old': old, 'phase': 'claim_pending'}
        atomic_json(self.journal, journal)
        try:
            self.report(job, 'installing')
            journal.update(claimed=True, phase='claimed')
            atomic_json(self.journal, journal)
            final = self.local()
            if not final.get('ready') or not final.get('maintenance_active'):
                raise RuntimeError('Điều kiện cập nhật đã thay đổi')
            journal['phase'] = 'modifying'
            atomic_json(self.journal, journal)
            self.service('stop')
            self.switch(job['version'])
            journal['phase'] = 'switched'
            atomic_json(self.journal, journal)
            self.service('start')
            if not self.healthy(job['version'], require_backend=False):
                raise RuntimeError('Bản mới không đạt health check trong 120 giây')
            journal.update(phase='report_pending', outcome='succeeded', local_verified=True,
                           message='Ứng dụng mới đã sẵn sàng')
            atomic_json(self.journal, journal)
        except Exception:
            self.recover()
            raise
        self.recover()

    def cleanup(self):
        keep = {self.current()}
        if self.previous_file.exists():
            keep.add(json.loads(self.previous_file.read_text()).get('version'))
        for path in self.releases.iterdir():
            if path.is_dir() and not path.is_symlink() and VERSION.fullmatch(path.name) and path.name not in keep:
                shutil.rmtree(path)
        for path in self.staging.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)

    def tick(self):
        self.recover()
        local = self.heartbeat()
        offer = self.request('job')
        job = offer.get('job')
        if not job:
            self.cleanup()
            return
        if job['status'] in ('installing', 'health_check', 'rolling_back'):
            raise RuntimeError('Job đang cài nhưng thiếu journal. Cần kiểm tra thiết bị.')
        if job['status'] in ('pending', 'downloading'):
            try:
                self.report(job, 'downloading')
                self.prepare(job, local)
                self.report(job, 'ready', progress=100)
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    return
                raise
            except TemporaryNetworkError:
                return
            except Exception:
                self.report(job, 'failed', 'Chuẩn bị gói cập nhật thất bại')
                return
        if time.time() < job['scheduled_at']:
            return
        if offer['blocked'] or not local.get('ready'):
            self.report(job, 'deferred', 'Còn cảnh báo đang xử lý' if offer['blocked'] else local.get('reason', 'Thiết bị đang bận'))
            return
        prepared = self.local('prepare')
        if not prepared.get('prepared'):
            self.report(job, 'deferred', prepared.get('reason', 'Thiết bị đang bận'))
            return
        try:
            self.heartbeat()
            self.install(job)
        finally:
            try:
                self.local('resume')
            except OSError:
                pass

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as exc:
                LOG.warning('Update cycle failed (%s)', type(exc).__name__)
            time.sleep(10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/opt/annha')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    Updater(args.root).run()
