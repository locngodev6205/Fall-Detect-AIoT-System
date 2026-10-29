"""Apply versioned schema and provision least-privilege logins. Never logs credentials.
Usage: python3 scripts/cloud/deploy_postgres.py --env .env --output .secrets/neon-runtime.env
Requires psycopg[binary], python-dotenv, cryptography. Use direct owner URL only here.
"""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import ssl
from urllib.parse import urlsplit,urlunsplit,quote
import psycopg
from psycopg import sql
from dotenv import dotenv_values
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[2]
MIGRATIONS=['001_schema.sql','002_security.sql','005_email_notifications.sql','007_home_archiving.sql','008_archived_home_notifications.sql']

def deploy(env_file,output):
    settings=dotenv_values(env_file)
    url=settings.get('DATABASE_URL_UNPOOLED') or settings.get('DATABASE_URL')
    if not url: raise SystemExit('Direct owner DATABASE_URL_UNPOOLED is required.')
    parsed=urlsplit(url)
    if '-pooler.' in parsed.hostname: raise SystemExit('Migration requires a direct URL, not the pooled endpoint.')
    output=Path(output); previous=dotenv_values(output) if output.exists() else {}
    with psycopg.connect(url,sslmode='verify-full',sslrootcert=ssl.get_default_verify_paths().cafile,connect_timeout=20) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(817398204)')
        exists=conn.execute("SELECT to_regclass('annha_private.schema_migrations')").fetchone()[0]
        if not exists and conn.execute("SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname='annha')").fetchone()[0]:
            raise SystemExit('Untracked existing schema; inspect before adoption. No data changed.')
        if exists:
            recorded=dict(conn.execute('SELECT name,checksum FROM annha_private.schema_migrations').fetchall())
        else: recorded={}
        for name in MIGRATIONS:
            raw=(ROOT/'backend/database/postgresql'/name).read_text();checksum=hashlib.sha256(raw.encode()).hexdigest()
            if name in recorded:
                if recorded[name]!=checksum: raise SystemExit('Applied migration checksum differs: '+name)
                continue
            body='\n'.join(line for line in raw.splitlines() if line.strip() not in ('BEGIN;','COMMIT;'))
            conn.execute(body)
            if not exists:
                conn.execute('CREATE TABLE annha_private.schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())')
                conn.execute('REVOKE ALL ON annha_private.schema_migrations FROM PUBLIC,annha_app,annha_auth,annha_device,annha_worker');exists=True
            conn.execute('INSERT INTO annha_private.schema_migrations(name,checksum) VALUES(%s,%s)',(name,checksum))
            print('Applied',name)
        # Baseline auth grants cover existing private tables; keep the deployment ledger owner-only.
        conn.execute('REVOKE ALL ON annha_private.schema_migrations FROM PUBLIC,annha_app,annha_auth,annha_device,annha_worker')
        owner=conn.execute('SELECT current_user').fetchone()[0]
        for group in ('app','auth','device','worker'):
            conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier('annha_'+group),sql.Identifier(owner)))
        generated={}
        for kind in ('app','auth','device','worker'):
            role='annha_runtime_'+kind;key='DATABASE_URL_'+kind.upper()
            old_url=previous.get(key);password=urlsplit(old_url).password if old_url else secrets.token_urlsafe(36)
            if old_url:
                from urllib.parse import unquote
                password=unquote(password)
            if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT').format(sql.Identifier(role),sql.Literal(password)))
            elif not old_url: raise SystemExit('Existing login without matching credential file: '+role)
            conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier('annha_'+kind),sql.Identifier(role)))
            host=parsed.hostname.replace('-pooler.','.')
            pooled=host.replace('.', '-pooler.',1)
            generated[key]=urlunsplit((parsed.scheme,role+':'+quote(password,safe='')+'@'+pooled,parsed.path,'sslmode=verify-full&channel_binding=require',''))
        count=conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname IN ('annha','annha_private')").fetchone()[0]
    generated.update(DATABASE_BACKEND='postgres',SESSION_CSRF_KEY=previous.get('SESSION_CSRF_KEY') or secrets.token_urlsafe(48),DATA_ENCRYPTION_KEY=previous.get('DATA_ENCRYPTION_KEY') or Fernet.generate_key().decode(),DATA_ENCRYPTION_KEY_ID=previous.get('DATA_ENCRYPTION_KEY_ID') or 'primary')
    output.parent.mkdir(parents=True,exist_ok=True)
    # Atomic private file; quoted values are compatible with Compose/python-dotenv.
    temp=output.with_suffix('.tmp');fd=os.open(temp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as stream:
        for key,value in generated.items(): stream.write(key+"='"+value+"'\n")
    temp.replace(output);output.chmod(0o600)
    print(f'PostgreSQL ready: {count} tables including migration ledger; 4 restricted logins. Runtime env saved privately.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--env',default='.env');parser.add_argument('--output',default='.secrets/neon-runtime.env');args=parser.parse_args()
    try: deploy(args.env,args.output)
    except psycopg.Error as error: raise SystemExit('Database setup failed: '+type(error).__name__+' (SQLSTATE '+str(error.sqlstate)+'). Credentials omitted.') from None
