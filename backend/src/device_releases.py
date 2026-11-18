"""Signed application releases. Credentials remain on the backend."""
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import urllib.request
import urllib.error

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

VERSION = re.compile(r'^\d{1,6}\.\d{1,6}\.\d{1,6}$')
MAX_BYTES = 64 * 1024 * 1024
logger = logging.getLogger(__name__)


def download(url, limit, token=None, binary=True):
    headers = {'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json', 'User-Agent': 'AnNha-Updater'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    # urllib removes Authorization on cross-host redirects only with a custom handler.
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            redirected = super().redirect_request(req, fp, code, msg, response_headers, newurl)
            if redirected and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
                redirected.remove_header('Authorization')
            return redirected
    opener = urllib.request.build_opener(Redirect())
    with opener.open(urllib.request.Request(url, headers=headers), timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Asset vượt kích thước cho phép')
    return data


class ReleaseCatalog:
    def __init__(self):
        self.releases = {}
        self.error = None
        self.checked_at = None
        self.lock = threading.Lock()
        self.cache = Path(os.getenv('DEVICE_RELEASE_CACHE_DIR', str(Path(__file__).resolve().parents[1] / 'data/device-releases')))

    def bundle(self, release):
        manifest = release['manifest']
        path = self.cache / (manifest['sha256'] + '.tar.gz')
        if path.exists():
            data = path.read_bytes()
            if len(data) == manifest['bytes'] and hashlib.sha256(data).hexdigest() == manifest['sha256']:
                return path
        raise ValueError('Gói chưa được xác minh trong cache')

    def sync(self, pinned=()):
        if not self.lock.acquire(blocking=False):
            return
        try:
            repo = os.getenv('DEVICE_RELEASE_REPO', '')
            key = os.getenv('DEVICE_RELEASE_PUBLIC_KEY', '').replace('\\n', '\n')
            if not repo or not key:
                raise ValueError('Chưa cấu hình DEVICE_RELEASE_REPO và DEVICE_RELEASE_PUBLIC_KEY')
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
                raise ValueError('DEVICE_RELEASE_REPO không hợp lệ')
            public = load_pem_public_key(key.encode())
            if not isinstance(public, Ed25519PublicKey):
                raise ValueError('Public key phải là Ed25519')
            api = 'https://api.github.com/repos/' + repo + '/'
            token = os.getenv('DEVICE_RELEASE_GITHUB_TOKEN') or None
            listing = json.loads(download(api + 'releases?per_page=25', 2 * 1024 * 1024, token, binary=False))
            accepted = {}
            invalid = []
            self.cache.mkdir(parents=True, exist_ok=True)
            for item in listing:
                tag = item.get('tag_name', '')
                if item.get('draft') or item.get('prerelease') or not tag.startswith('annha-pi-v'):
                    continue
                version = tag[len('annha-pi-v'):]
                if not VERSION.fullmatch(version):
                    continue
                try:
                    assets = {a['name']: a['id'] for a in item['assets']}
                    def asset(name, limit):
                        return download(api + 'releases/assets/' + str(assets[name]), limit, token)
                    raw = asset('manifest.json', 8192)
                    signature = asset('manifest.sig', 256)
                    public.verify(signature, raw)
                    manifest = json.loads(raw)
                    validate_manifest(manifest)
                    if manifest['version'] != version:
                        raise ValueError('Tag và manifest khác phiên bản')
                    path = self.cache / (manifest['sha256'] + '.tar.gz')
                    if not path.exists() or path.stat().st_size != manifest['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != manifest['sha256']:
                        data = asset('annha-pi.tar.gz', manifest['bytes'])
                        if len(data) != manifest['bytes'] or hashlib.sha256(data).hexdigest() != manifest['sha256']:
                            raise ValueError('Checksum không hợp lệ')
                        temporary = path.with_suffix('.tmp')
                        temporary.write_bytes(data)
                        temporary.chmod(0o600)
                        temporary.replace(path)
                    accepted[version] = {'manifest': manifest, 'manifest64': base64.b64encode(raw).decode(),
                        'signature': base64.b64encode(signature).decode(), 'notes': (item.get('body') or '')[:4000]}
                except Exception:
                    invalid.append(tag)
            self.releases = accepted
            self.error = ('Bản phát hành thiếu asset hoặc xác minh thất bại: ' + ', '.join(invalid)) if invalid else None
            keep = {r['manifest']['sha256'] + '.tar.gz' for r in accepted.values()} | {digest + '.tar.gz' for digest in pinned}
            for path in self.cache.glob('*.tar.gz'):
                if path.name not in keep:
                    path.unlink(missing_ok=True)
        except urllib.error.HTTPError as exc:
            self.error = f'GitHub HTTP {exc.code}. Kiểm tra token, quyền đọc repo và hạn mức API.'
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, ValueError) else 'Không kết nối được GitHub để đồng bộ phiên bản.'
        finally:
            self.checked_at = time.time()
            self.lock.release()

    def public(self):
        return [dict(r['manifest'], notes=r['notes']) for _, r in sorted(self.releases.items(), key=lambda item: tuple(map(int, item[0].split('.'))), reverse=True)]


def validate_manifest(m):
    if not isinstance(m, dict) or not isinstance(m.get('version'), str) or not VERSION.fullmatch(m['version']):
        raise ValueError('Phiên bản không hợp lệ')
    if m.get('target') != 'linux-arm64' or not re.fullmatch(r'[a-f0-9]{40}', m.get('commit', '')):
        raise ValueError('Target hoặc commit không hợp lệ')
    if type(m.get('bytes')) is not int or not 0 < m['bytes'] <= MAX_BYTES:
        raise ValueError('Kích thước không hợp lệ')
    for field in ('sha256', 'model_sha256', 'runtime_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', m.get(field, '')):
            raise ValueError('Thiếu checksum ' + field)


catalog = ReleaseCatalog()
