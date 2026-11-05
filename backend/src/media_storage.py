"""Private media storage adapters for local files and authenticated Cloudinary assets."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import os
from pathlib import Path
import re
import urllib.error
import urllib.request


class MediaStorageError(RuntimeError):
    """A provider operation failed without exposing credentials or signed URLs."""


class MediaNotFound(MediaStorageError):
    pass


class MediaUnavailable(MediaStorageError):
    pass


@dataclass(frozen=True)
class ProviderAsset:
    provider: str
    provider_environment: str | None = None
    provider_asset_id: str | None = None
    public_id: str | None = None
    resource_type: str | None = None
    delivery_type: str | None = None
    provider_version: int | None = None
    local_object_key: str | None = None
    size_bytes: int | None = None
    sha256: bytes | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None


def parse_config(path: str | Path | None = None, environ: dict | None = None) -> dict[str, str]:
    """Read a KEY=value secret file (or injected env) without logging its contents."""
    environ = os.environ if environ is None else environ
    config: dict[str, str] = {}
    selected = path or environ.get('CLOUDINARY_CONFIG_FILE') or '/run/secrets/cloudinary.env'
    file_path = Path(selected)
    if file_path.is_file():
        for raw in file_path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                raise ValueError('Cloudinary secret file must contain KEY=value lines.')
            key, value = line.split('=', 1)
            key = key.strip()
            if key in config:
                raise ValueError('Cloudinary secret file has duplicate keys.')
            config[key] = value.strip()
    for key in ('CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET',
                'CLOUDINARY_ASSET_FOLDER', 'CLOUDINARY_ENVIRONMENT'):
        if environ.get(key):
            config[key] = environ[key].strip()
    # Local developer runs may keep the secret outside /run/secrets.
    if not file_path.exists() and selected == '/run/secrets/cloudinary.env':
        fallback = Path('.secrets/cloudinary.env')
        if fallback.is_file():
            return parse_config(fallback, environ)
    return config


def cloudinary_configured(path: str | Path | None = None, environ: dict | None = None) -> bool:
    try:
        config = parse_config(path, environ)
        return all(config.get(key) and 'REPLACE_' not in config[key]
                   for key in ('CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET'))
    except (OSError, ValueError):
        return False


class LocalStorage:
    """Local adapter retained for SQLite, offline development and legacy media."""
    name = 'local'

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, row) -> Path:
        key = row.get('local_object_key') if hasattr(row, 'get') else row['local_object_key']
        if not key or Path(key).name != key:
            raise MediaNotFound('Local media is unavailable.')
        path = self.root / key
        if not path.is_file():
            raise MediaNotFound('Local media is unavailable.')
        return path

    def delete(self, row) -> None:
        key = row.get('local_object_key') if hasattr(row, 'get') else row['local_object_key']
        if key and Path(key).name == key:
            (self.root / key).unlink(missing_ok=True)

    @staticmethod
    def metadata(path: Path, mime_type: str) -> ProviderAsset:
        return ProviderAsset(provider='local', local_object_key=path.name,
                             size_bytes=path.stat().st_size,
                             sha256=hashlib.sha256(path.read_bytes()).digest())


class CloudinaryStorage:
    """Server-side signed uploads and authenticated media delivery/deletion."""
    name = 'cloudinary'
    delivery_type = 'authenticated'
    _mime_to_resource = {'image/jpeg': 'image', 'image/png': 'image',
                         'video/mp4': 'video', 'video/webm': 'video',
                         'audio/webm': 'video', 'audio/mpeg': 'video',
                         'audio/wav': 'video', 'audio/ogg': 'video'}
    _mime_to_format = {'image/jpeg': 'jpg', 'image/png': 'png',
                       'video/mp4': 'mp4', 'video/webm': 'webm',
                       'audio/webm': 'webm', 'audio/mpeg': 'mp3',
                       'audio/wav': 'wav', 'audio/ogg': 'ogg'}

    def __init__(self, config: dict[str, str] | None = None, sdk=None,
                 opener=None, environment: str | None = None):
        self.config = config or parse_config()
        for key in ('CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET'):
            if not self.config.get(key) or 'REPLACE_' in self.config[key]:
                raise MediaUnavailable('Cloud media storage is not configured.')
        self.cloud_name = self.config['CLOUDINARY_CLOUD_NAME']
        self.asset_folder = self.config.get('CLOUDINARY_ASSET_FOLDER', 'Fall Detection')
        self.environment = (environment or self.config.get('CLOUDINARY_ENVIRONMENT')
                            or os.getenv('APP_ENV', 'development')).strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', self.environment):
            raise ValueError('CLOUDINARY_ENVIRONMENT must be a short lowercase identifier.')
        self._sdk_value = sdk
        self.opener = opener or urllib.request.urlopen

    def _sdk(self):
        if self._sdk_value is not None:
            if isinstance(self._sdk_value, tuple) and len(self._sdk_value)==3:
                return self._sdk_value
            # A single fake object may implement config/uploader/utils for tests.
            return self._sdk_value, self._sdk_value, self._sdk_value
        else:
            try:
                root = importlib.import_module('cloudinary')
                self._sdk_value = (root, importlib.import_module('cloudinary.uploader'),
                                   importlib.import_module('cloudinary.utils'))
            except ImportError:
                raise MediaUnavailable('Cloudinary SDK is unavailable.') from None
        return self._sdk_value

    def _configure(self):
        root, uploader, utils = self._sdk()
        root.config(cloud_name=self.cloud_name,
                    api_key=self.config['CLOUDINARY_API_KEY'],
                    api_secret=self.config['CLOUDINARY_API_SECRET'], secure=True)
        return uploader, utils

    @staticmethod
    def resource_type(mime_type: str) -> str:
        try:
            return CloudinaryStorage._mime_to_resource[mime_type]
        except KeyError:
            raise ValueError('Unsupported media type for Cloudinary.') from None

    def public_id(self, media_id: str) -> str:
        # The media ID is generated by the backend; caller-provided names never enter this path.
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', str(media_id)):
            raise ValueError('Invalid internal media ID.')
        return f'annha/{self.environment}/{media_id.lower()}'

    def upload(self, path: str | Path, media_id: str, mime_type: str) -> ProviderAsset:
        uploader, _ = self._configure()
        resource = self.resource_type(mime_type)
        path = Path(path)
        try:
            result = uploader.upload(str(path), resource_type=resource,
                type=self.delivery_type, public_id=self.public_id(media_id),
                asset_folder=self.asset_folder, overwrite=True,
                unique_filename=False, use_filename=False, timeout=30)
            size = path.stat().st_size
            if (result.get('type') != self.delivery_type
                    or result.get('public_id') != self.public_id(media_id)
                    or result.get('resource_type') != resource
                    or result.get('bytes') != size
                    or not result.get('asset_id') or not result.get('version')):
                raise MediaUnavailable('Cloudinary returned incomplete upload metadata.')
            digest = hashlib.sha256(path.read_bytes()).digest()
            width = result.get('width')
            height = result.get('height')
            return ProviderAsset(provider=self.name, provider_environment=self.environment,
                provider_asset_id=result['asset_id'], public_id=result['public_id'],
                resource_type=resource, delivery_type=self.delivery_type,
                provider_version=int(result['version']), size_bytes=size, sha256=digest,
                # Cloudinary returns zero dimensions for audio stored as a video
                # resource; PostgreSQL intentionally stores absent dimensions as NULL.
                width=int(width) if width and int(width)>0 else None,
                height=int(height) if height and int(height)>0 else None,
                duration_s=result.get('duration'))
        except MediaStorageError:
            raise
        except Exception:
            # SDK errors can contain provider request details; keep them out of logs/API.
            raise MediaUnavailable('Cloudinary upload failed.') from None

    def signed_url(self, row) -> str:
        _, utils = self._configure()
        mime = row['mime_type']
        resource = row['resource_type']
        expected = self.resource_type(mime)
        if resource != expected or row['delivery_type'] != self.delivery_type:
            raise MediaUnavailable('Cloudinary metadata is invalid.')
        fmt = self._mime_to_format.get(mime)
        if not fmt:
            raise MediaUnavailable('Cloudinary metadata is invalid.')
        try:
            result = utils.cloudinary_url(row['public_id'], resource_type=resource,
                type=self.delivery_type, version=int(row['provider_version']),
                format=fmt, secure=True, sign_url=True)
            return result[0] if isinstance(result, tuple) else result
        except Exception:
            raise MediaUnavailable('Could not prepare authorized media delivery.') from None

    def open_read(self, row, range_header: str | None = None):
        request = urllib.request.Request(self.signed_url(row), method='GET')
        if range_header:
            request.add_header('Range', range_header)
        try:
            response = self.opener(request, timeout=30)
            return response
        except urllib.error.HTTPError as error:
            if error.code == 404:
                error.close()
                raise MediaNotFound('Cloud media is unavailable.') from None
            if error.code in (401, 403):
                error.close()
                raise MediaUnavailable('Cloud media access is unavailable.') from None
            if error.code == 416:
                return error
            error.close()
            raise MediaUnavailable('Cloud media request failed.') from None
        except Exception:
            raise MediaUnavailable('Cloud media request failed.') from None

    def verify(self, row, expected_size: int, expected_sha256: bytes | None = None) -> bool:
        response = self.open_read(row)
        try:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 26214400:
                    return False
                digest.update(chunk)
            return size == expected_size and (
                expected_sha256 is None or digest.digest() == bytes(expected_sha256))
        finally:
            response.close()

    def delete(self, row) -> None:
        uploader, _ = self._configure()
        try:
            result = uploader.destroy(row['public_id'], resource_type=row['resource_type'],
                type=self.delivery_type, invalidate=True)
            if result.get('result') not in ('ok', 'not found'):
                raise MediaUnavailable('Cloudinary deletion was not confirmed.')
        except MediaStorageError:
            raise
        except Exception:
            raise MediaUnavailable('Cloudinary deletion failed.') from None


def preferred_provider(local_root: str | Path, mode: str | None = None):
    """Select Cloudinary when configured; otherwise preserve local-only operation."""
    selected = (mode or os.getenv('MEDIA_STORAGE_PROVIDER', 'auto')).strip().lower()
    if selected not in ('auto', 'local', 'cloudinary'):
        raise ValueError('MEDIA_STORAGE_PROVIDER must be auto, local, or cloudinary.')
    if selected == 'local':
        return LocalStorage(local_root)
    if selected == 'cloudinary':
        return CloudinaryStorage()
    if cloudinary_configured():
        return CloudinaryStorage()
    return LocalStorage(local_root)


def provider_for_asset(row, local_root: str | Path):
    provider = row['provider']
    if provider == 'local':
        return LocalStorage(local_root)
    if provider == 'cloudinary':
        return CloudinaryStorage()
    raise MediaUnavailable('Media provider is unsupported.')
