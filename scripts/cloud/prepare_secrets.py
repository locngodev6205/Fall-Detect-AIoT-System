#!/usr/bin/env python3
"""Create ignored local secrets/templates once; never overwrite or print a secret."""
from pathlib import Path
import os
import secrets

ROOT = Path(__file__).resolve().parents[2]

def create_once(path, content):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f'Kept existing {path.relative_to(ROOT)}')
        return
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(content)
    print(f'Created {path.relative_to(ROOT)}')

def main():
    create_once(ROOT / '.env', (ROOT / '.env.example').read_text())
    target = ROOT / '.secrets'
    target.mkdir(mode=0o700, exist_ok=True)
    create_once(target / 'postgres_password', secrets.token_urlsafe(48) + '\n')
    for source, filename in [
        ('docker/database/pg_service.conf.example', 'pg_service.conf'),
        ('docker/database/pgpass.example', 'pgpass'),
        ('docker/cloudinary/cloudinary.env.example', 'cloudinary.env'),
    ]:
        create_once(target / filename, (ROOT / source).read_text())

if __name__ == '__main__':
    main()
