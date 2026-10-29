"""PostgreSQL persistence: separate runtime pools, transaction-local roles and RLS context."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import ssl
import uuid
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROLES={'app':'annha_app','auth':'annha_auth','device':'annha_device','worker':'annha_worker'}
POOLS={}
MEDIA_ROOT=Path(os.getenv('MEDIA_ROOT',str(Path(__file__).resolve().parents[1]/'data/media')))
J=Jsonb

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)

def open_pools():
    if POOLS: return
    try:
        for name in ROLES:
            url=os.getenv('DATABASE_URL_'+name.upper())
            if not url: raise RuntimeError('Missing least-privilege PostgreSQL runtime configuration.')
            POOLS[name]=ConnectionPool(url,min_size=0,max_size=int(os.getenv('DATABASE_POOL_MAX','3')),open=True,
                kwargs={'row_factory':dict_row,'prepare_threshold':None,'connect_timeout':15,
                        'sslmode':'verify-full','sslrootcert':ssl.get_default_verify_paths().cafile},timeout=20)
        with connect('auth') as conn:
            conn.execute('SELECT 1 FROM annha_private.users LIMIT 0')
        MEDIA_ROOT.mkdir(parents=True,exist_ok=True)
    except Exception:
        close_pools()
        raise RuntimeError('PostgreSQL startup failed; check runtime credentials, TLS and migrations.') from None

def close_pools():
    for pool in POOLS.values(): pool.close()
    POOLS.clear()

@contextmanager
def connect(role='app',home=None,user=None,camera=None):
    if role not in ROLES: raise ValueError('Unknown database role')
    with POOLS[role].connection() as conn:
        with conn.transaction():
            conn.execute('SET LOCAL ROLE '+ROLES[role])
            for key,value in [('app.home_id',home),('app.user_id',user),('app.camera_id',camera),
                              ('statement_timeout',os.getenv('DATABASE_STATEMENT_TIMEOUT_MS','10000'))]:
                conn.execute('SELECT set_config(%s,%s,true)',(key,str(value) if value is not None else ''))
            yield conn

def audit(conn,home,user,action,target, camera=None):
    conn.execute('INSERT INTO annha.audit_logs(home_id,actor_type,user_id,camera_id,action,target_type,target_id) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                 (home,'user' if user else 'system',user,camera,action,action.split('.')[0],target))
