"""SQLite persistence. Existing legacy alert data is preserved, never exposed unscoped."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import uuid

DB_PATH = Path(os.getenv('DATABASE_PATH', str(Path(__file__).resolve().parents[1] / 'data/annha.sqlite3')))
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', str(DB_PATH.parent / 'media')))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS email_tokens(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),purpose TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mail_jobs(id TEXT PRIMARY KEY,recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS homes(id TEXT PRIMARY KEY,name TEXT NOT NULL,timezone TEXT NOT NULL,settings TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS memberships(home_id TEXT NOT NULL REFERENCES homes(id),user_id TEXT NOT NULL REFERENCES users(id),role TEXT NOT NULL,scopes TEXT NOT NULL DEFAULT '[]',rights TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(home_id,user_id));
CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY,home_id TEXT NOT NULL REFERENCES homes(id),name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY,home_id TEXT REFERENCES homes(id),room_id TEXT REFERENCES rooms(id),name TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,pair_hash TEXT UNIQUE,pair_expires REAL,claimed INTEGER NOT NULL DEFAULT 0,last_seen TEXT,observation TEXT NOT NULL DEFAULT 'unknown',capabilities TEXT NOT NULL DEFAULT '{}',desired_version INTEGER NOT NULL DEFAULT 0,applied_version INTEGER NOT NULL DEFAULT 0,config_error TEXT);
CREATE TABLE IF NOT EXISTS invitations(id TEXT PRIMARY KEY,home_id TEXT NOT NULL REFERENCES homes(id),email TEXT NOT NULL,role TEXT NOT NULL,scopes TEXT NOT NULL,rights TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,expires REAL NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS configurations(camera_id TEXT NOT NULL REFERENCES cameras(id),version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(camera_id,version));
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,camera_id TEXT NOT NULL REFERENCES cameras(id),home_id TEXT NOT NULL REFERENCES homes(id),source_id TEXT NOT NULL,sequence INTEGER NOT NULL,kind TEXT NOT NULL,severity TEXT NOT NULL,observed_at TEXT NOT NULL,received_at TEXT NOT NULL,observation TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',payload TEXT NOT NULL,UNIQUE(camera_id,source_id));
CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),user_id TEXT NOT NULL REFERENCES users(id),action TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS telemetry(id INTEGER PRIMARY KEY,camera_id TEXT NOT NULL REFERENCES cameras(id),message_id TEXT NOT NULL,payload TEXT NOT NULL,observed_at TEXT NOT NULL,received_at TEXT NOT NULL,UNIQUE(camera_id,message_id));
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,home_id TEXT NOT NULL REFERENCES homes(id),camera_id TEXT NOT NULL REFERENCES cameras(id),event_id TEXT REFERENCES events(id),name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,path TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ready',error TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY,home_id TEXT NOT NULL REFERENCES homes(id),camera_id TEXT NOT NULL REFERENCES cameras(id),name TEXT NOT NULL,time TEXT NOT NULL,weekdays TEXT NOT NULL,once_date TEXT,timezone TEXT NOT NULL,enabled INTEGER NOT NULL,source TEXT NOT NULL,text TEXT NOT NULL,asset_id TEXT REFERENCES assets(id),volume INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,late_seconds INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY,camera_id TEXT NOT NULL REFERENCES cameras(id),reminder_id TEXT NOT NULL,occurrence TEXT NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(camera_id,reminder_id,occurrence));
CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,camera_id TEXT NOT NULL REFERENCES cameras(id),home_id TEXT NOT NULL REFERENCES homes(id),user_id TEXT NOT NULL REFERENCES users(id),kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',expires REAL NOT NULL,result TEXT,created_at TEXT NOT NULL,idempotency_key TEXT NOT NULL,UNIQUE(user_id,idempotency_key));
CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,home_id TEXT NOT NULL REFERENCES homes(id),event_id TEXT NOT NULL REFERENCES events(id),status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT,UNIQUE(event_id));
CREATE TABLE IF NOT EXISTS device_health(camera_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS environment_states(camera_id TEXT NOT NULL,metric TEXT NOT NULL,since REAL,source_id TEXT,active INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(camera_id,metric));
CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,home_id TEXT NOT NULL,user_id TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_events_home ON events(home_id,received_at);
CREATE INDEX IF NOT EXISTS idx_telemetry_camera ON telemetry(camera_id,id);
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        columns={row[1] for row in db.execute('PRAGMA table_info(deliveries)')}
        if 'sent_count' not in columns: db.execute('ALTER TABLE deliveries ADD COLUMN sent_count INTEGER NOT NULL DEFAULT 0')
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)


def audit(db, home_id, user_id, action, target):
    db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (uid(),home_id,user_id,action,target,now()))
