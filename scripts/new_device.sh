#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 - "$@" <<'PY'
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

parser = argparse.ArgumentParser(prog='new_device.sh', description='Đăng ký và quản lý thông tin ghép nối Pi trên máy backend.')
operation = parser.add_mutually_exclusive_group()
operation.add_argument('name', nargs='?', help='Tên thiết bị mới')
operation.add_argument('--reissue-code', type=UUID, metavar='DEVICE_ID')
operation.add_argument('--rotate-token', type=UUID, metavar='DEVICE_ID')
parser.add_argument('--save-env', action='store_true', help='Lưu token vào fall_detect/.env.edge trên máy này')
parser.add_argument('--base-url', help='URL backend mà Pi truy cập được')
args = parser.parse_args()

if args.save_env and args.reissue_code:
    parser.error('--reissue-code chỉ cấp lại mã ghép nối, không đổi token.')
if args.save_env != bool(args.base_url):
    parser.error('Dùng --save-env cùng --base-url trỏ tới backend mà Pi truy cập được.')
if args.base_url:
    url = urlsplit(args.base_url)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username
            or url.password or url.query or url.fragment or url.path.rstrip('/')
            or any(ch.isspace() for ch in args.base_url)):
        parser.error('--base-url phải là URL gốc HTTP(S) của backend.')

env_path = Path('fall_detect/.env.edge')
lines = []
if args.save_env and env_path.exists():
    replaced = {'ANNHA_BASE_URL', 'ANNHA_DEVICE_ID', 'DEVICE_TOKEN'}
    lines = [
        line for line in env_path.read_text(encoding='utf-8').splitlines()
        if line.split('=', 1)[0].strip() not in replaced
    ]

command = ['docker', 'compose', 'exec', '-T', 'backend', 'python', '-m', 'src.provision']
if args.reissue_code:
    command.extend(['--reissue-code', str(args.reissue_code)])
elif args.rotate_token:
    command.extend(['--rotate-token', str(args.rotate_token)])
else:
    command.extend(['--name', args.name or 'Camera Pi 4'])

result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
if result.returncode:
    raise SystemExit(result.returncode)
data = json.loads(result.stdout)
print(f"DEVICE_ID: {data['device_id']}")
if 'pairing_code' in data:
    print(f"Mã ghép nối trên web (30 phút): {data['pairing_code']}")
if args.save_env:
    lines.extend([
        f"ANNHA_BASE_URL={args.base_url.rstrip('/')}",
        f"ANNHA_DEVICE_ID={data['device_id']}",
        f"DEVICE_TOKEN={data['device_token']}",
    ])
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=env_path.parent, prefix='.env.edge.', delete=False
        ) as temp:
            temp_path = Path(temp.name)
            temp.write('\n'.join(lines) + '\n')
        os.replace(temp_path, env_path)
    except OSError as error:
        print(f"DEVICE_TOKEN: {data['device_token']}")
        parser.exit(1, f'Không lưu được cấu hình: {error}\n')
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
    print(f'Đã lưu token vào {env_path} trên máy này. Chuyển cấu hình sang Pi nếu Pi chạy ở máy khác.')
elif 'device_token' in data:
    print(f"DEVICE_TOKEN (lưu vào .env.edge trên Pi): {data['device_token']}")
PY
