#!/usr/bin/env python3
"""Save a direct Neon URI as ignored libpq secrets without printing credentials."""
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def service_files(uri):
    try:
        value = urlsplit(uri.strip())
        host, port = value.hostname or '', value.port or 5432
        user, password = unquote(value.username or ''), unquote(value.password or '')
        database = unquote(value.path.removeprefix('/'))
    except ValueError:
        raise ValueError('Invalid PostgreSQL connection URI.') from None
    if value.scheme not in ('postgres','postgresql') or value.fragment:
        raise ValueError('Use a PostgreSQL URI from Neon Connect.')
    if not host.endswith('.neon.tech') or not re.fullmatch(r'[a-z0-9.-]+',host):
        raise ValueError('Expected a public Neon hostname ending in .neon.tech.')
    if '-pooler' in host:
        raise ValueError('Disable connection pooling and copy the DIRECT migration URI.')
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',part) for part in (user,database)):
        raise ValueError('Database/user names must use letters, numbers, dot, underscore or hyphen.')
    if not password or any(char in password for char in ('\n','\r','\x00')):
        raise ValueError('A nonempty single-line password is required.')
    if not 1 <= port <= 65535:
        raise ValueError('Invalid database port.')
    # Only explicitly parsed identity fields are used. URI options cannot weaken TLS.
    service = f'[annha_neon_migration]\nhost={host}\nport={port}\ndbname={database}\nuser={user}\nsslmode=verify-full\nsslrootcert=/etc/ssl/certs/ca-certificates.crt\nconnect_timeout=10\n'
    escaped = password.replace('\\','\\\\').replace(':','\\:')
    return service, f'{host}:{port}:{database}:{user}:{escaped}\n'


def save_files(uri, root=ROOT):
    service, password = service_files(uri)
    target = root / '.secrets'
    target.mkdir(mode=0o700, exist_ok=True)
    files = [('pg_service.conf',service),('pgpass',password)]
    for filename,_ in files:
        path = target / filename
        template = root / 'docker/database' / (filename + '.example')
        if path.exists() and path.read_text().strip() not in ('',template.read_text().strip()):
            raise ValueError('Neon secret files are already customized; no file was overwritten. Edit them locally if needed.')
    for filename,content in files:
        descriptor, temporary = tempfile.mkstemp(prefix='neon-',dir=target)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                stream.write(content)
            os.chmod(temporary,0o600)
            os.replace(temporary,target/filename)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)


def main():
    if not sys.stdin.isatty():
        print('Run this command in your local terminal; the URI prompt must be hidden.',file=sys.stderr)
        return 1
    try:
        uri = getpass.getpass('Paste DIRECT Neon connection URI (hidden): ')
        save_files(uri)
    except (EOFError,KeyboardInterrupt):
        print('Cancelled; no credential was printed.',file=sys.stderr)
        return 130
    except (ValueError,OSError) as error:
        # ValueError messages are controlled above; never print a URI or OS file contents.
        print(str(error) if isinstance(error,ValueError) else 'Could not write ignored Neon secret files.',file=sys.stderr)
        return 1
    print('Saved .secrets/pg_service.conf and .secrets/pgpass. No cloud connection or migration was performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
