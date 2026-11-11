"""Pair a Pi without copying a credential from the backend."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.parse import urlsplit

import requests


def _check_url(base_url: str) -> None:
    url = urlsplit(base_url)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username
            or url.password or url.query or url.fragment or url.path.rstrip('/')):
        raise ValueError('ANNHA_BASE_URL phải là địa chỉ gốc của backend.')
    if url.scheme == 'http':
        try:
            address = ipaddress.ip_address(url.hostname)
            local = address.is_loopback or any(
                address in ipaddress.ip_network(subnet)
                for subnet in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7')
            )
        except ValueError:
            local = url.hostname == 'localhost' or url.hostname.endswith('.local')
        if not local:
            raise ValueError('Dùng HTTPS để ghép nối qua Internet.')


def _save(path: Path, data: dict) -> None:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            json.dump(data, temp)
        os.replace(temp_path, path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def pair_device(base_url: str, state_path: Path, *, start_pairing: bool) -> str:
    """Resume a previously started enrollment or start it with local consent."""
    if not state_path.exists() and not start_pairing:
        return ''
    base_url = base_url.rstrip('/')
    _check_url(base_url)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['base_url'] != base_url:
            raise ValueError(f'Cấu hình ghép nối tại {state_path} thuộc backend khác.')
    else:
        state = {'base_url': base_url, 'token': secrets.token_urlsafe(40), 'paired': False}
        _save(state_path, state)
    if state['paired']:
        return state['token']

    token = state['token']
    headers = {'Authorization': f'Bearer {token}'}
    print('Đang chờ chủ nhà ghép nối Pi trên AnNhà.', flush=True)
    displayed_code = None
    with requests.Session() as session:
        while True:
            try:
                config = session.get(
                    f'{base_url}/api/device/config', headers=headers, timeout=5, allow_redirects=False,
                )
                if config.status_code == 200:
                    if config.json().get('version', 0) > 0:
                        state['paired'] = True
                        state.pop('code', None)
                        state.pop('expires_at', None)
                        _save(state_path, state)
                        print('Đã ghép nối Pi. Đang khởi động thiết bị.', flush=True)
                        return token
                elif config.status_code >= 500 or config.status_code == 429:
                    time.sleep(4)
                    continue
                elif config.status_code != 401:
                    raise ValueError(f'Không kiểm tra được ghép nối (HTTP {config.status_code}).')

                if state.get('expires_at', 0) <= time.time():
                    response = session.post(
                        f'{base_url}/api/device/pairing-ticket',
                        headers=headers,
                        timeout=5, allow_redirects=False,
                    )
                    if response.status_code >= 500 or response.status_code == 429:
                        time.sleep(4)
                        continue
                    if response.status_code != 200:
                        raise ValueError(f'Không lấy được mã ghép nối (HTTP {response.status_code}).')
                    ticket = response.json()
                    state['code'] = ticket['pairing_code']
                    state['expires_at'] = time.time() + ticket['expires_in_seconds']
                    _save(state_path, state)
                if state['code'] != displayed_code:
                    print(f"Mã ghép nối (Thiết bị → Thêm thiết bị): {state['code']}", flush=True)
                    displayed_code = state['code']
            except (requests.ConnectionError, requests.Timeout):
                print('Chưa kết nối được backend. Đang thử lại.', flush=True)
            time.sleep(4)
