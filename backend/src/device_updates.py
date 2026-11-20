"""Camera-scoped OTA API shared by SQLite and PostgreSQL deployments."""
import asyncio
from contextlib import contextmanager
import json
import os
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from .device_releases import catalog, VERSION

PG = os.getenv('DATABASE_BACKEND', 'sqlite') == 'postgres'
if PG:
    from . import pgdb as db, pgsecurity as security
else:
    from . import db, security

router = APIRouter(prefix='/api')
TERMINAL = {'succeeded', 'failed', 'rolled_back', 'cancelled', 'expired'}
INSTALLING = {'installing', 'health_check', 'rolling_back'}


class Connection:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        if PG:
            sql = sql.replace('update_states', 'annha_private.update_states').replace('update_jobs', 'annha_private.update_jobs').replace('?', '%s')
        return self.conn.execute(sql, params)


@contextmanager
def transaction(camera=None):
    with (db.connect('auth') if PG else db.connect()) as raw:
        if PG and camera:
            raw.execute('SELECT id FROM annha.cameras WHERE id=%s FOR UPDATE', (camera,))
        elif not PG:
            raw.execute('BEGIN IMMEDIATE')
        yield Connection(raw)


def initialize():
    if PG:
        with db.connect('auth') as conn:
            conn.execute('SELECT 1 FROM annha_private.update_jobs LIMIT 0')
        return
    with db.connect() as conn:
        conn.executescript('''CREATE TABLE IF NOT EXISTS update_states(camera_id TEXT PRIMARY KEY REFERENCES cameras(id),payload TEXT NOT NULL,last_seen REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS update_jobs(id TEXT PRIMARY KEY,camera_id TEXT NOT NULL REFERENCES cameras(id),payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS update_jobs_camera ON update_jobs(camera_id);''')


async def release_worker():
    while True:
        def sync_pinned():
            with transaction() as conn:
                rows = conn.execute('SELECT payload FROM update_jobs').fetchall()
            pinned = {j['release']['manifest']['sha256'] for row in rows
                if (j := json.loads(row['payload'])).get('release') and j['status'] not in TERMINAL}
            # Release the database lease before making GitHub requests.
            catalog.sync(pinned)
        try:
            await asyncio.to_thread(sync_pinned)
        except Exception:
            catalog.error = 'Không đọc được dữ liệu cập nhật. Kiểm tra migration và kết nối database.'
        await asyncio.sleep(120)


def authorize(camera, user):
    if PG:
        security.camera_access(camera, user['id'], 'manage')
    else:
        with db.connect() as conn:
            security.camera_access(conn, camera, user['id'], 'manage')


def jobs(conn, camera):
    result = [json.loads(row['payload']) for row in conn.execute('SELECT payload FROM update_jobs WHERE camera_id=?', (camera,)).fetchall()]
    for job in result:
        if job['status'] not in TERMINAL | INSTALLING and time.time() > job['expires_at']:
            job.update(status='expired', message='Đã quá thời hạn cập nhật', updated_at=time.time())
            save(conn, job)
    return sorted(result, key=lambda j: j['created_at'], reverse=True)


def save(conn, job):
    conn.execute('UPDATE update_jobs SET payload=? WHERE id=? AND camera_id=?', (json.dumps(job), job['id'], job['camera_id']))


def state(conn, camera):
    row = conn.execute('SELECT * FROM update_states WHERE camera_id=?', (camera,)).fetchone()
    return dict(json.loads(row['payload']), last_seen=row['last_seen']) if row else None


def blocked(camera, connection=None, *, home=None):
    if PG:
        if home is None:
            with db.connect('auth') as conn:
                home = conn.execute('SELECT home_id FROM annha.cameras WHERE id=%s', (camera,)).fetchone()['home_id']
        with db.connect('device', home=home, camera=camera) as conn:
            return bool(conn.execute("SELECT 1 FROM annha.events WHERE camera_id=%s AND status IN ('OPEN','ACKNOWLEDGED') LIMIT 1", (camera,)).fetchone())
    if connection is not None:
        return bool(connection.execute("SELECT 1 FROM events WHERE camera_id=? AND status IN ('OPEN','ACKNOWLEDGED') LIMIT 1", (camera,)).fetchone())
    with db.connect() as conn:
        return bool(conn.execute("SELECT 1 FROM events WHERE camera_id=? AND status IN ('OPEN','ACKNOWLEDGED') LIMIT 1", (camera,)).fetchone())


class CreateJob(BaseModel):
    version: str | None = None
    rollback: bool = False
    scheduled_at: float | None = Field(default=None, allow_inf_nan=False)


class AgentState(BaseModel):
    current_version: str = Field(default='unmanaged', max_length=64)
    previous_version: str | None = Field(default=None, max_length=64)
    updater_version: str = Field(default='1', max_length=32)
    model_sha256: str = Field(default='', max_length=64)
    runtime_sha256: str = Field(default='', max_length=64)
    target: str = Field(default='', max_length=32)
    ready: bool = False
    reason: str = Field(default='', max_length=500)


class Progress(BaseModel):
    status: Literal['downloading', 'ready', 'deferred', 'installing', 'health_check', 'rolling_back', 'succeeded', 'failed', 'rolled_back']
    message: str = Field(default='', max_length=500)
    progress: int = Field(default=0, ge=0, le=100)


@router.get('/cameras/{camera}/updates')
def overview(camera: str, current=Depends(security.user)):
    authorize(camera, current)
    with transaction(camera) as conn:
        device = state(conn, camera)
        history = jobs(conn, camera)
    return {'state': device, 'online': bool(device and time.time() - device['last_seen'] < 45),
        'jobs': [{k: v for k, v in j.items() if k != 'release'} for j in history[:20]], 'releases': catalog.public(), 'release_error': catalog.error,
        'checked_at': catalog.checked_at}


@router.post('/cameras/{camera}/updates')
def create(camera: str, body: CreateJob, current=Depends(security.user)):
    authorize(camera, current)
    now = time.time()
    scheduled = body.scheduled_at if body.scheduled_at is not None else now
    if scheduled < now - 5 or scheduled > now + 30 * 86400:
        raise HTTPException(422, 'Lịch phải nằm trong 30 ngày tới.')
    with transaction(camera) as conn:
        if any(j['status'] not in TERMINAL for j in jobs(conn, camera)):
            raise HTTPException(409, 'Thiết bị đang có một lệnh cập nhật. Hãy hủy lịch trước.')
        device = state(conn, camera)
        if not device or now - device['last_seen'] >= 45:
            raise HTTPException(409, 'Bộ cập nhật thiết bị đang ngoại tuyến.')
        version = device.get('previous_version') if body.rollback else body.version
        release = catalog.releases.get(version)
        if not version or not VERSION.fullmatch(version) or version == device.get('current_version'):
            raise HTTPException(422, 'Phiên bản đích không hợp lệ.')
        if not body.rollback:
            if not release:
                raise HTTPException(422, 'Bản phát hành chưa được xác minh.')
            if any(release['manifest'][k] != device.get(k) for k in ('model_sha256', 'runtime_sha256', 'target')):
                raise HTTPException(409, 'Bản phát hành không tương thích model hoặc môi trường Python của thiết bị.')
        job = {'id': str(uuid.uuid4()), 'camera_id': camera, 'requested_by': str(current['id']), 'version': version,
            'rollback': body.rollback, 'scheduled_at': scheduled, 'expires_at': scheduled + 1800,
            'created_at': now, 'updated_at': now, 'status': 'pending', 'progress': 0, 'message': '',
            'release': release if not body.rollback else None}
        conn.execute('INSERT INTO update_jobs(id,camera_id,payload) VALUES(?,?,?)', (job['id'], camera, json.dumps(job)))
    return {k: v for k, v in job.items() if k != 'release'}


@router.post('/cameras/{camera}/updates/{job_id}/cancel')
def cancel(camera: str, job_id: str, current=Depends(security.user)):
    authorize(camera, current)
    with transaction(camera) as conn:
        job = next((j for j in jobs(conn, camera) if j['id'] == job_id), None)
        if not job:
            raise HTTPException(404, 'Không tìm thấy lệnh.')
        if job['status'] in INSTALLING:
            raise HTTPException(409, 'Đang cài hoặc phục hồi. Hãy chờ kết quả.')
        if job['status'] not in TERMINAL:
            job.update(status='cancelled', updated_at=time.time())
            save(conn, job)
    return {'status': job['status']}


@router.post('/device/updates/heartbeat')
def heartbeat(body: AgentState, camera=Depends(security.device)):
    with transaction(camera['id']) as conn:
        conn.execute('INSERT INTO update_states(camera_id,payload,last_seen) VALUES(?,?,?) ON CONFLICT(camera_id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen',
            (camera['id'], body.model_dump_json(), time.time()))
    return {'ok': True}


@router.get('/device/updates/job')
def offer(camera=Depends(security.device)):
    with transaction(camera['id']) as conn:
        pending = next((j for j in jobs(conn, camera['id']) if j['status'] not in TERMINAL), None)
    return {'job': pending, 'blocked': blocked(camera['id'], home=camera.get('home_id'))}


@router.post('/device/updates/{job_id}/progress')
def progress(job_id: str, body: Progress, camera=Depends(security.device)):
    with transaction(camera['id']) as conn:
        job = next((j for j in jobs(conn, camera['id']) if j['id'] == job_id), None)
        if not job:
            raise HTTPException(404, 'Không tìm thấy lệnh.')
        if job['status'] == body.status and body.status in {'installing', 'health_check'}:
            return {'status': job['status']}
        if job['status'] in TERMINAL:
            if body.status == job['status'] or (job['status'], body.status) in {('rolled_back', 'rolling_back'), ('succeeded', 'health_check')}:
                return {'status': job['status']}
            raise HTTPException(409, 'Lệnh đã kết thúc.')
        allowed = {
            'pending': {'downloading', 'ready', 'failed'},
            'downloading': {'downloading', 'ready', 'failed'},
            'ready': {'ready', 'deferred', 'installing', 'failed'},
            'deferred': {'deferred', 'installing', 'failed'},
            'installing': {'health_check', 'rolling_back', 'failed'},
            'health_check': {'succeeded', 'rolling_back', 'failed'},
            'rolling_back': {'rolling_back', 'rolled_back', 'failed'},
        }
        if body.status not in allowed.get(job['status'], set()):
            raise HTTPException(409, 'Chuyển trạng thái không hợp lệ.')
        if body.status == 'installing':
            device = state(conn, camera['id'])
            if time.time() < job['scheduled_at'] or not device or time.time() - device['last_seen'] > 45 or not device['ready']:
                raise HTTPException(409, 'Chưa đủ điều kiện an toàn để cài đặt.')
            # The device pool is separate. Never reacquire the held auth pool.
            if blocked(camera['id'], conn, home=camera['home_id'] if PG else None):
                raise HTTPException(409, 'Còn cảnh báo đang xử lý.')
        job.update(status=body.status, message=body.message, progress=body.progress, updated_at=time.time())
        save(conn, job)
    return {'status': job['status']}


@router.get('/device/updates/{job_id}/bundle')
def bundle(job_id: str, camera=Depends(security.device)):
    with transaction(camera['id']) as conn:
        job = next((j for j in jobs(conn, camera['id']) if j['id'] == job_id), None)
    if not job or job['status'] in TERMINAL or not job.get('release'):
        raise HTTPException(404, 'Gói không khả dụng.')
    return FileResponse(catalog.bundle(job['release']), media_type='application/gzip', filename='annha-pi.tar.gz')
