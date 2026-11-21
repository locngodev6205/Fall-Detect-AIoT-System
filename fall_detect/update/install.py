#!/usr/bin/env python3
"""One-time bootstrap on the Pi. Run using the existing Edge virtualenv."""
import argparse
import getpass
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import sys


def install(args):
    if os.getuid() == 0:
        raise SystemExit('Chạy bằng tài khoản đang chạy Edge, dùng Python trong virtualenv. Script dùng sudo khi cài service.')
    if platform.machine() not in ('aarch64', 'arm64'):
        raise SystemExit('Bản đầu hỗ trợ Linux ARM64 trên Pi.')
    source = args.source.resolve()
    env_file = args.env.resolve()
    public = args.public_key.resolve()
    root = args.root.resolve()
    if root.exists() and (root / 'current').exists():
        raise SystemExit('Đã có cài đặt OTA. Kiểm tra bản hiện tại trước khi chạy lại bootstrap.')
    # Enforce dependencies before assigning the baseline compatibility fingerprint.
    from pip._vendor.packaging.requirements import Requirement
    for line in (source / 'requirements.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        version = importlib.metadata.version(requirement.name)
        if version not in requirement.specifier:
            raise SystemExit('Dependency chưa tương thích: ' + requirement.name)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    subprocess.run(['openssl', 'pkey', '-pubin', '-in', str(public), '-noout'], check=True, capture_output=True)
    settings = {}
    for line in env_file.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            settings[key.strip()] = value.strip().strip('\"\'')
    backend = settings.get('ANNHA_BASE_URL') or settings.get('BACKEND_URL')
    token = settings.get('DEVICE_TOKEN')
    pairing = env_file.with_name('.env.edge.pairing.json' if env_file.name == '.env.edge' else f'.env.edge.pairing-{env_file.name}.json')
    if pairing.exists():
        paired = json.loads(pairing.read_text())
        # Preserve the pairing file unchanged; runner resolves its own credentials.
        token = token or paired.get('token')
        backend = backend or paired.get('base_url')
    if not backend or not token:
        raise SystemExit('Cần ANNHA_BASE_URL/BACKEND_URL và DEVICE_TOKEN của thiết bị đã ghép đôi.')
    from updater import validate_backend_url
    backend = validate_backend_url(backend)
    user = getpass.getuser()
    subprocess.run(['sudo', 'install', '-d', '-o', user, '-m', '700', str(root)], check=True)
    shared = root / 'shared'
    baseline = root / 'releases/0.0.0'
    for path in (shared, baseline, root / 'staging', root / 'updater'):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    from package_release import build
    build('0.0.0', '0' * 40, root / 'staging', source)
    from updater import extract_bundle
    extract_bundle(root / 'staging/annha-pi.tar.gz', baseline)
    shutil.copytree(source / 'models', shared / 'models', dirs_exist_ok=True)
    if (source / 'edge_cache').exists():
        shutil.copytree(source / 'edge_cache', shared / 'edge_cache', dirs_exist_ok=True)
    else:
        (shared / 'edge_cache').mkdir()
    shutil.copy2(env_file, shared / 'app.env')
    (shared / 'app.env').chmod(0o600)
    # Keep pairing credentials and cache alongside the original env basename expected by the runner.
    if pairing.exists():
        shutil.copy2(pairing, shared / '.env.edge.pairing-app.env.json')
    if (source / '.env').exists():
        shutil.copy2(source / '.env', shared / 'legacy.env')
        (shared / 'legacy.env').chmod(0o600)
        (baseline / '.env').symlink_to(shared / 'legacy.env')
    shutil.copy2(public, shared / 'release.pub')
    updater_config = shared / 'updater.json'
    updater_config.write_text(json.dumps({'backend_url': backend, 'device_token': token}))
    updater_config.chmod(0o600)
    for name, target in (('models', shared / 'models'), ('edge_cache', shared / 'edge_cache'), ('.env.edge', shared / 'app.env')):
        (baseline / name).symlink_to(target)
    shutil.copy2(source / 'update/updater.py', root / 'updater/updater.py')
    (root / 'current').symlink_to(baseline, target_is_directory=True)
    uid = pwd.getpwnam(user).pw_uid
    python = Path(sys.executable).absolute()
    for value in (str(root), str(python), user):
        if any(c in value for c in '\n\r%"'):
            raise SystemExit('Đường dẫn service chứa ký tự không hỗ trợ.')
    edge = f'''[Unit]
Description=AnNha Edge application
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User={user}
WorkingDirectory={root}/current
ExecStart="{python}" -u -m edge.main_edge --env-file "{shared}/app.env"
Environment=ANNHA_UPDATE_SOCKET={shared}/update.sock
Environment=XDG_RUNTIME_DIR=/run/user/{uid}
Environment=PULSE_SERVER=unix:/run/user/{uid}/pulse/native
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
'''
    updater = f'''[Unit]
Description=AnNha signed application updater
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User={user}
WorkingDirectory={root}
ExecStart="{python}" -u "{root}/updater/updater.py" --root "{root}"
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
'''
    for name, content in (('annha-edge.service', edge), ('annha-updater.service', updater)):
        path = root / name
        path.write_text(content)
        subprocess.run(['sudo', 'install', '-m', '644', str(path), '/etc/systemd/system/' + name], check=True)
    policy = root / 'annha-updater.sudoers'
    policy.write_text(f'{user} ALL=(root) NOPASSWD: /usr/bin/systemctl stop annha-edge.service, /usr/bin/systemctl start annha-edge.service\n')
    subprocess.run(['sudo', 'visudo', '-cf', str(policy)], check=True)
    subprocess.run(['sudo', 'install', '-m', '440', str(policy), '/etc/sudoers.d/annha-updater'], check=True)
    subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
    print('Đã chuẩn bị OTA. Dừng tiến trình Edge cũ để giải phóng camera/serial, rồi chạy:')
    print('sudo systemctl enable --now annha-edge.service annha-updater.service')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path('/opt/annha'))
    install(parser.parse_args())
