"""Issue stateless pairing tickets for Pi-generated credentials."""
import base64
import binascii
import hashlib
import hmac
import os
import re
import time
from uuid import UUID

from fastapi import HTTPException

PREFIX = 'PI1.'
TTL_SECONDS = 1800


def _signature(payload: bytes) -> bytes:
    key = os.getenv('SESSION_CSRF_KEY', '').encode()
    if len(key) < 32:
        raise HTTPException(503, 'Backend chưa cấu hình khóa ghép nối.')
    return hmac.digest(key, b'annha:pi-pairing:v1:' + payload, 'sha256')[:16]


def issue_ticket(authorization: str) -> dict:
    if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{54}', authorization):
        raise HTTPException(401, 'Thông tin ghép nối thiết bị không hợp lệ.')
    token_hash = hashlib.sha256(authorization[7:].encode()).digest()
    expiry = int(time.time()) + TTL_SECONDS
    payload = token_hash + expiry.to_bytes(4, 'big')
    encoded = base64.urlsafe_b64encode(payload + _signature(payload)).decode().rstrip('=')
    return {'pairing_code': PREFIX + encoded, 'expires_in_seconds': TTL_SECONDS}


def read_ticket(code: str) -> tuple[str, bytes] | None:
    if not code.startswith(PREFIX):
        return None
    encoded = code[len(PREFIX):]
    try:
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
    except (ValueError, binascii.Error):
        raw = b''
    if (
        len(raw) != 52
        or base64.urlsafe_b64encode(raw).decode().rstrip('=') != encoded
        or not hmac.compare_digest(raw[36:], _signature(raw[:36]))
        or int.from_bytes(raw[32:36], 'big') <= time.time()
    ):
        raise HTTPException(400, 'Mã ghép nối sai hoặc đã hết hạn.')
    token_hash = raw[:32]
    # The identity remains reserved even after its camera or credential is revoked.
    return str(UUID(bytes=token_hash[:16])), token_hash
