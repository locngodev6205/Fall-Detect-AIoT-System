import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import smtplib
import subprocess
import time
import urllib.request

from fastapi import HTTPException
from . import db, models
from .security import digest, membership, camera_access, session_user

logger = logging.getLogger(__name__)
connections = {}  # WebSocket -> (session token, home id)


def camera_public(row):
    result = {k:row[k] for k in ('id','home_id','room_id','name','last_seen','observation','desired_version','applied_version','config_error')}
    result['capabilities'] = json.loads(row['capabilities'])
    result['online'] = bool(row['last_seen'] and (datetime.now(timezone.utc)-datetime.fromisoformat(row['last_seen'])).total_seconds()<45)
    result['sync_status'] = 'applied' if row['desired_version']>0 and row['applied_version']==row['desired_version'] else 'pending'
    return result


def visible_cameras(conn, home_id, user_id):
    member = membership(conn,home_id,user_id)
    rows = conn.execute('SELECT * FROM cameras WHERE home_id=? AND claimed=1 ORDER BY name',(home_id,)).fetchall()
    return [camera_public(row) for row in rows if member['role']=='owner' or row['id'] in member['scopes']]


def event_public(conn, row):
    result=dict(row)
    result['payload']=json.loads(result['payload'])
    result['actions']=[dict(x) for x in conn.execute('SELECT a.*,u.name AS user_name FROM actions a JOIN users u ON u.id=a.user_id WHERE event_id=? ORDER BY created_at',(row['id'],))]
    result['evidence']=[{k:a[k] for k in ('id','name','mime','status','error','created_at')} for a in conn.execute('SELECT * FROM assets WHERE event_id=?',(row['id'],))]
    return result


def reminder_public(row):
    result=dict(row)
    result['enabled']=bool(result['enabled'])
    result['weekdays']=json.loads(result['weekdays'])
    return result


def config_without_zones(payload):
    # Empty compatibility fields explicitly clear old device-side regions.
    return {**payload,'zones':[],'reference':{}}


def retire_zone_configs():
    # Append a revision once; preserve old configurations and applied_version.
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        cameras=conn.execute('SELECT * FROM cameras WHERE claimed=1').fetchall()
        for camera in cameras:
            row=conn.execute('SELECT payload FROM configurations WHERE camera_id=? ORDER BY version DESC LIMIT 1',(camera['id'],)).fetchone()
            payload=json.loads(row['payload']) if row else {}
            if payload.get('zones') or payload.get('reference'):
                revision(conn,camera['id'])
                db.audit(conn,camera['home_id'],'system','zones.retire',camera['id'])


def revision(conn, camera_id):
    camera=conn.execute('SELECT * FROM cameras WHERE id=?',(camera_id,)).fetchone()
    previous=conn.execute('SELECT payload FROM configurations WHERE camera_id=? ORDER BY version DESC LIMIT 1',(camera_id,)).fetchone()
    payload=config_without_zones(json.loads(previous['payload']) if previous else {})
    version=camera['desired_version']+1
    payload.update(version=version,camera_id=camera_id)
    payload['reminders']=[reminder_public(r) for r in conn.execute('SELECT * FROM reminders WHERE camera_id=?',(camera_id,))]
    settings=conn.execute('SELECT settings FROM homes WHERE id=?',(camera['home_id'],)).fetchone()
    payload['environment']=models.Settings(**json.loads(settings['settings'])).model_dump()
    conn.execute('INSERT INTO configurations VALUES(?,?,?,?)',(camera_id,version,db.dumps(payload),db.now()))
    conn.execute('UPDATE cameras SET desired_version=?,config_error=NULL WHERE id=?',(version,camera_id))
    return payload


def queue_email(conn, user, purpose):
    token=secrets.token_urlsafe(32)
    conn.execute('DELETE FROM email_tokens WHERE user_id=? AND purpose=?',(user['id'],purpose))
    conn.execute('INSERT INTO email_tokens VALUES(?,?,?,?)',(digest(token),user['id'],purpose,time.time()+(3600 if purpose=='reset' else 86400)))
    base=os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')
    route='reset' if purpose=='reset' else 'verify'
    link=f'{base}/#/{route}?token={token}'
    subject='Đặt lại mật khẩu AnNhà' if purpose=='reset' else 'Xác minh tài khoản AnNhà'
    conn.execute('INSERT INTO mail_jobs(id,recipient,subject,body,created_at) VALUES(?,?,?,?,?)',
                 (db.uid(),user['email'],subject,f'{subject}\n\nMở liên kết sau để tiếp tục:\n{link}\n\nNếu bạn không yêu cầu, hãy bỏ qua thư này.',db.now()))


def provision_device(name):
    token=secrets.token_urlsafe(40)
    code=secrets.token_urlsafe(12)
    device_id=db.uid()
    with db.connect() as conn:
        conn.execute('INSERT INTO cameras(id,name,token_hash,pair_hash,pair_expires) VALUES(?,?,?,?,?)',
                     (device_id,name,digest(token),digest(code),time.time()+1800))
    return {'device_id':device_id,'device_token':token,'pairing_code':code,'expires_in_seconds':1800}


def ingest_event(camera, payload):
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old=conn.execute('SELECT * FROM events WHERE camera_id=? AND source_id=?',(camera['id'],payload.event_id)).fetchone()
        if old and old['kind']!=payload.kind: raise HTTPException(409,'Không đổi loại của cùng một sự kiện nguồn.')
        if old and old['sequence']>=payload.sequence:
            return event_public(conn,old),False
        if payload.config_version and not conn.execute('SELECT 1 FROM configurations WHERE camera_id=? AND version=?',(camera['id'],payload.config_version)).fetchone():
            raise HTTPException(422,'Phiên bản cấu hình không thuộc camera.')
        values=payload.model_dump()
        event_id=old['id'] if old else db.uid()
        if old:
            status='OPEN' if old['status'] in ('RESOLVED','FALSE_ALARM') and payload.observation=='abnormal' else old['status']
            if status=='OPEN' and old['status'] in ('RESOLVED','FALSE_ALARM'):
                conn.execute("UPDATE deliveries SET status='pending',sent_count=0,attempts=0,next_attempt=0,error=NULL WHERE event_id=?",(event_id,))
            conn.execute('UPDATE events SET sequence=?,observation=?,payload=?,received_at=?,severity=?,status=? WHERE id=?',
                         (payload.sequence,payload.observation,db.dumps(values),db.now(),payload.severity,status,event_id))
        else:
            conn.execute('INSERT INTO events(id,camera_id,home_id,source_id,sequence,kind,severity,observed_at,received_at,observation,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (event_id,camera['id'],camera['home_id'],payload.event_id,payload.sequence,payload.kind,payload.severity,payload.observed_at,db.now(),payload.observation,db.dumps(values)))
        settings=models.Settings(**json.loads(conn.execute('SELECT settings FROM homes WHERE id=?',(camera['home_id'],)).fetchone()[0]))
        if settings.telegram_enabled and payload.severity!='info':
            conn.execute('INSERT OR IGNORE INTO deliveries(id,home_id,event_id) VALUES(?,?,?)',(db.uid(),camera['home_id'],event_id))
        return event_public(conn,conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()),True


async def broadcast(event):
    for socket,(token,home_id) in tuple(connections.items()):
        try:
            current=session_user(token)
            with db.connect() as conn:
                membership(conn,home_id,current['id'])
                if event['home_id']!=home_id: continue
                camera_access(conn,event['camera_id'],current['id'])
            await asyncio.wait_for(socket.send_json(event),timeout=2)
        except Exception:
            connections.pop(socket,None)
            try: await socket.close(code=1008)
            except Exception: pass


async def revalidate_connections():
    from .media import revalidate
    await revalidate()
    for socket,(token,home_id) in tuple(connections.items()):
        try:
            current=session_user(token)
            with db.connect() as conn: membership(conn,home_id,current['id'])
        except Exception:
            connections.pop(socket,None)
            try: await socket.close(code=1008)
            except Exception: pass


def asset_path(asset):
    path=db.MEDIA_ROOT / asset['path']
    if asset['status']!='ready' or not path.is_file(): raise HTTPException(404,'File chưa sẵn sàng hoặc đã hết hạn.')
    return path


def process_tts():
    with db.connect() as conn:
        rows=conn.execute("SELECT a.*,r.text FROM assets a JOIN reminders r ON r.asset_id=a.id WHERE a.status='pending' LIMIT 2").fetchall()
    for asset in rows:
        path=db.MEDIA_ROOT/asset['path']
        try:
            binary=shutil.which('espeak-ng')
            if not binary: raise RuntimeError('Chưa cài espeak-ng; file TTS chưa được tạo.')
            subprocess.run([binary,'-v','vi','-s','150','-w',str(path),'--stdin'],input=asset['text'].encode(),check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            with db.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                used=conn.execute("SELECT COALESCE(SUM(size),0) FROM assets WHERE home_id=? AND status='ready'",(asset['home_id'],)).fetchone()[0]
                if used+path.stat().st_size>int(os.getenv('MAX_HOME_MEDIA_BYTES',str(512*1024*1024))): raise RuntimeError('Nhà đã đạt giới hạn lưu trữ media.')
                conn.execute("UPDATE assets SET status='ready',size=?,error=NULL WHERE id=?",(path.stat().st_size,asset['id']))
                revision(conn,asset['camera_id'])
        except Exception as exc:
            path.unlink(missing_ok=True)
            with db.connect() as conn: conn.execute("UPDATE assets SET status='failed',error=? WHERE id=?",(str(exc)[:300],asset['id']))


def deliver_mail():
    with db.connect() as conn:
        rows=conn.execute("SELECT * FROM mail_jobs WHERE status='pending' AND next_attempt<=? LIMIT 5",(time.time(),)).fetchall()
    for job in rows:
        try:
            msg=EmailMessage()
            msg['From']=os.getenv('SMTP_FROM','AnNhà <noreply@annha.local>')
            msg['To']=job['recipient'];msg['Subject']=job['subject'];msg.set_content(job['body'])
            with smtplib.SMTP(os.getenv('SMTP_HOST','localhost'),int(os.getenv('SMTP_PORT','1025')),timeout=5) as smtp:
                if os.getenv('SMTP_STARTTLS','false')=='true': smtp.starttls()
                if os.getenv('SMTP_USER'): smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
                smtp.send_message(msg)
            with db.connect() as conn: conn.execute("UPDATE mail_jobs SET status='sent',error=NULL,body='' WHERE id=?",(job['id'],))
        except Exception as exc:
            attempt=job['attempts']+1
            with db.connect() as conn: conn.execute('UPDATE mail_jobs SET attempts=?,status=?,next_attempt=?,error=? WHERE id=?',
                (attempt,'failed' if attempt>=5 else 'pending',time.time()+min(300,10*2**attempt),type(exc).__name__,job['id']))


def deliver_telegram():
    token=os.getenv('TELEGRAM_BOT_TOKEN')
    with db.connect() as conn:
        jobs=conn.execute("SELECT d.*,h.settings,e.kind,e.observed_at,e.status AS event_status,c.name FROM deliveries d JOIN homes h ON h.id=d.home_id JOIN events e ON e.id=d.event_id JOIN cameras c ON c.id=e.camera_id WHERE d.status='pending' AND d.next_attempt<=? LIMIT 3",(time.time(),)).fetchall()
    for job in jobs:
        settings=models.Settings(**json.loads(job['settings']))
        try:
            if not settings.telegram_enabled or job['event_status'] in ('RESOLVED','FALSE_ALARM') or (job['event_status']!='OPEN' and job['sent_count']>0):
                with db.connect() as conn: conn.execute("UPDATE deliveries SET status='cancelled' WHERE id=?",(job['id'],))
                continue
            if not token or not settings.telegram_chat_id: raise RuntimeError('Chưa cấu hình bot hoặc người nhận Telegram')
            text=f"AnNhà: {job['kind']} tại {job['name']}\nThời điểm: {job['observed_at']}\nVui lòng mở ứng dụng để kiểm tra."
            photo=None
            if settings.telegram_photos:
                with db.connect() as conn:
                    photo=conn.execute("SELECT * FROM assets WHERE event_id=? AND mime IN ('image/jpeg','image/png') AND status='ready' ORDER BY created_at DESC LIMIT 1",(job['event_id'],)).fetchone()
            if photo:
                boundary='AnNha'+secrets.token_hex(16)
                chunks=[]
                for key,value in [('chat_id',settings.telegram_chat_id),('caption',text)]:
                    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="event{Path(photo["path"]).suffix}"\r\nContent-Type: {photo["mime"]}\r\n\r\n'.encode())
                chunks.append(asset_path(photo).read_bytes());chunks.append(f'\r\n--{boundary}--\r\n'.encode())
                data=b''.join(chunks);headers={'Content-Type':f'multipart/form-data; boundary={boundary}'};method='sendPhoto'
            else:
                data=db.dumps({'chat_id':settings.telegram_chat_id,'text':text}).encode();headers={'Content-Type':'application/json'};method='sendMessage'
            request=urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',data=data,headers=headers)
            with urllib.request.urlopen(request,timeout=8) as response:
                if not json.load(response).get('ok'): raise RuntimeError('Telegram từ chối yêu cầu')
            sent=job['sent_count']+1
            with db.connect() as conn: conn.execute('UPDATE deliveries SET status=?,sent_count=?,attempts=0,next_attempt=?,error=NULL WHERE id=?',
                ('sent' if sent>=5 or job['event_status']!='OPEN' else 'pending',sent,time.time()+120,job['id']))
        except Exception as exc:
            attempt=job['attempts']+1
            # Never persist exception URLs: a Telegram token is part of its URL.
            with db.connect() as conn: conn.execute('UPDATE deliveries SET attempts=?,status=?,next_attempt=?,error=? WHERE id=?',
                (attempt,'failed' if attempt>=5 else 'pending',time.time()+min(300,10*2**attempt),type(exc).__name__,job['id']))


def maintenance():
    with db.connect() as conn:
        conn.execute("UPDATE commands SET status='expired' WHERE expires<? AND status IN ('pending','accepted')",(time.time(),))
        conn.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        conn.execute('DELETE FROM email_tokens WHERE expires<?',(time.time(),))
        for home in conn.execute('SELECT id,settings FROM homes'):
            days=models.Settings(**json.loads(home['settings'])).retention_days
            cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
            # Audio referenced by reminders is retained; only event evidence expires.
            for asset in conn.execute("SELECT * FROM assets WHERE home_id=? AND event_id IS NOT NULL AND created_at<? AND status='ready'",(home['id'],cutoff)).fetchall():
                (db.MEDIA_ROOT/asset['path']).unlink(missing_ok=True)
                conn.execute("UPDATE assets SET status='expired' WHERE id=?",(asset['id'],))
            conn.execute('DELETE FROM telemetry WHERE camera_id IN (SELECT id FROM cameras WHERE home_id=?) AND received_at<?',(home['id'],cutoff))


async def worker():
    ticks=0
    while True:
        try:
            await revalidate_connections()
            for event in await asyncio.to_thread(check_device_health): await broadcast(event)
            await asyncio.to_thread(process_tts)
            await asyncio.to_thread(deliver_mail)
            await asyncio.to_thread(deliver_telegram)
            if ticks%12==0: await asyncio.to_thread(maintenance)
        except asyncio.CancelledError: raise
        except Exception: logger.exception('Background worker failed')
        ticks+=1
        await asyncio.sleep(5)


def evaluate_environment(camera,telemetry):
    """Evaluate fresh readings with persisted hold timers and hysteresis; never use invalid samples."""
    stamp=datetime.fromisoformat(telemetry.observed_at).timestamp()
    if abs(time.time()-stamp)>120: return []
    emissions=[]
    with db.connect() as conn:
        settings=models.Settings(**json.loads(conn.execute('SELECT settings FROM homes WHERE id=?',(camera['home_id'],)).fetchone()[0]))
        policies=[('temperature_high','temperature','C',settings.temperature_high,1),('temperature_low','temperature','C',settings.temperature_low,-1),
                  ('humidity_high','humidity','%',settings.humidity_high,1),('gas_high','gas',settings.gas_unit,settings.gas_high,1)]
        for metric,key,unit,threshold,direction in policies:
            reading=telemetry.readings.get(key)
            state=conn.execute('SELECT * FROM environment_states WHERE camera_id=? AND metric=?',(camera['id'],metric)).fetchone()
            if not reading or reading.quality!='valid' or reading.unit!=unit:
                if state and not state['active']: conn.execute('UPDATE environment_states SET since=NULL WHERE camera_id=? AND metric=?',(camera['id'],metric))
                continue
            if state and state['since'] and stamp<state['since']: continue
            active=bool(state and state['active']);since=state['since'] if state else None;source_id=state['source_id'] if state else None
            exceeds=(reading.value-threshold)*direction>0
            recovered=(reading.value-threshold)*direction<=-settings.hysteresis
            if active and recovered:
                emissions.append(models.EventInput(event_id=source_id,sequence=2,kind='environment',severity='critical' if key=='gas' else 'warning',observation='recovered',observed_at=telemetry.observed_at,reason=f'{key} đã trở về ngưỡng cấu hình'))
                active=False;since=None;source_id=None
            elif exceeds:
                if since is None: since=stamp
                if stamp-since>=settings.environment_hold_seconds:
                    active=True;source_id=source_id or f'environment:{metric}:{db.uid()}'
                    emissions.append(models.EventInput(event_id=source_id,kind='environment',severity='critical' if key=='gas' else 'warning',observation='abnormal',observed_at=telemetry.observed_at,reason=f'{key}: {reading.value} {reading.unit}, vượt ngưỡng {threshold}',duration_s=max(0,stamp-since)))
            elif not active: since=None
            conn.execute('INSERT INTO environment_states VALUES(?,?,?,?,?) ON CONFLICT(camera_id,metric) DO UPDATE SET since=excluded.since,source_id=excluded.source_id,active=excluded.active',(camera['id'],metric,since,source_id,int(active)))
        conn.execute('DELETE FROM telemetry WHERE camera_id=? AND id NOT IN (SELECT id FROM telemetry WHERE camera_id=? ORDER BY id DESC LIMIT 100000)',(camera['id'],camera['id']))
    return [ingest_event(camera,item)[0] for item in emissions]


def check_device_health():
    emissions=[]
    with db.connect() as conn:
        for camera in conn.execute('SELECT * FROM cameras WHERE claimed=1 AND last_seen IS NOT NULL').fetchall():
            state=conn.execute('SELECT * FROM device_health WHERE camera_id=?',(camera['id'],)).fetchone()
            offline=(datetime.now(timezone.utc)-datetime.fromisoformat(camera['last_seen'])).total_seconds()>45
            if offline:
                source=state['source_id'] if state and state['active'] else 'offline:'+db.uid()
                conn.execute('INSERT INTO device_health VALUES(?,?,1) ON CONFLICT(camera_id) DO UPDATE SET source_id=excluded.source_id,active=1',(camera['id'],source))
                emissions.append((dict(camera),models.EventInput(event_id=source,kind='device',severity='warning',observation='abnormal',observed_at=db.now(),reason='Quá hạn heartbeat; chưa xác định thiết bị mất mạng hay mất nguồn')))
            elif state and state['active']:
                emissions.append((dict(camera),models.EventInput(event_id=state['source_id'],sequence=2,kind='device',severity='warning',observation='recovered',observed_at=db.now(),reason='Thiết bị đã gửi heartbeat trở lại')))
                conn.execute('UPDATE device_health SET active=0 WHERE camera_id=?',(camera['id'],))
    return [event for camera,payload in emissions for event,changed in [ingest_event(camera,payload)] if changed]
