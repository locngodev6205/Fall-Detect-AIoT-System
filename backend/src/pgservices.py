"""Business operations on normalized PostgreSQL tables; cloud side effects use durable jobs."""
import asyncio
from contextlib import suppress
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
import json
import os
from pathlib import Path
import secrets
import shutil
import smtplib
import subprocess
import time
import urllib.request
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from . import pgdb as db, models
from .demo_metadata import demo_camera
from .pgsecurity import digest,membership,session_user,camera_access,device_identity

connections={}

def encrypt(value): return Fernet(os.environ['DATA_ENCRYPTION_KEY'].encode()).encrypt(json.dumps(value,ensure_ascii=False).encode())
def decrypt(value): return json.loads(Fernet(os.environ['DATA_ENCRYPTION_KEY'].encode()).decrypt(bytes(value)))

def mail(conn,recipient,subject,body,purpose='message'):
    conn.execute("INSERT INTO annha_private.job_queue(kind,payload,secret_ciphertext,key_id,idempotency_key) VALUES('email',%s,%s,%s,%s)",
        (db.J({'purpose':purpose}),encrypt({'recipient':recipient,'subject':subject,'body':body}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary'),db.uid()))

def queue_email(conn,account,purpose):
    token=secrets.token_urlsafe(32)
    conn.execute('UPDATE annha_private.email_tokens SET consumed_at=now() WHERE user_id=%s AND purpose=%s AND consumed_at IS NULL',(account['id'],purpose))
    conn.execute('INSERT INTO annha_private.email_tokens(token_hash,user_id,purpose,expires_at,email_version) VALUES(%s,%s,%s,%s,%s)',
        (digest(token),account['id'],purpose,db.now()+timedelta(hours=1 if purpose=='reset_password' else 24),account['email_version']))
    page='reset' if purpose=='reset_password' else 'verify'
    subject='Đặt lại mật khẩu AnNhà' if page=='reset' else 'Xác minh tài khoản AnNhà'
    mail(conn,account['email'],subject,f"{subject}\n\n{os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')}/#/{page}?token={token}",purpose)

def provision_device(name):
    device=db.uid();token=secrets.token_urlsafe(40);code=secrets.token_urlsafe(16)
    with db.connect('auth') as conn:
        conn.execute('INSERT INTO annha_private.device_registry(id,model) VALUES(%s,%s)',(device,name))
        conn.execute('INSERT INTO annha_private.device_credentials(device_id,token_hash) VALUES(%s,%s)',(device,digest(token)))
        conn.execute('INSERT INTO annha_private.pairing_codes(code_hash,device_id,expires_at) VALUES(%s,%s,%s)',(digest(code),device,db.now()+timedelta(minutes=30)))
    return {'device_id':device,'device_token':token,'pairing_code':code,'expires_in_seconds':1800}

def cameras_public(conn,rows):
    rows=list(rows)
    if not rows: return []
    states={str(state['camera_id']):state for state in conn.execute("""SELECT c.id AS camera_id,s.desired_version,s.applied_version,s.error,
      EXISTS(SELECT 1 FROM annha.media_assets a WHERE a.camera_id=c.id AND a.mime_type LIKE 'image/%%' AND a.status='ready'
        AND a.upload_key<>'demo:snapshot' AND (a.expires_at IS NULL OR a.expires_at>now())) AS snapshot_available
      FROM annha.cameras c LEFT JOIN annha.camera_config_state s ON s.camera_id=c.id WHERE c.id=ANY(%s::uuid[])""",([str(row['id']) for row in rows],))}
    result=[];stamp=db.now()
    for row in rows:
        state=states.get(str(row['id']),{});desired=state.get('desired_version') or 0;applied=state.get('applied_version') or 0
        result.append({**{key:row[key] for key in ('id','home_id','room_id','name','observation','capabilities')},
            'is_demo':demo_camera(row['id']),'snapshot_available':bool(state.get('snapshot_available')),'last_seen':row['last_seen_at'],
            'online':bool(row['last_seen_at'] and (stamp-row['last_seen_at']).total_seconds()<45),
            'desired_version':desired,'applied_version':applied,'config_error':state.get('error'),'sync_status':'applied' if desired and desired==applied else 'pending'})
    return result

def camera_public(conn,row): return cameras_public(conn,[row])[0]

def reminder_rows(conn,home,camera=None,include_deleted=False):
    sql='''SELECT r.*,v.local_time,v.timezone,v.weekdays,v.once_date,v.source,v.text_content,v.asset_id,v.volume,v.late_seconds,
        a.status AS asset_status,a.error_code AS asset_error FROM annha.reminders r
        JOIN annha.reminder_revisions v ON v.home_id=r.home_id AND v.camera_id=r.camera_id AND v.reminder_id=r.id AND v.version=r.current_version
        LEFT JOIN annha.media_assets a ON a.id=v.asset_id WHERE r.home_id=%s'''
    args=[home]
    if not include_deleted: sql+=' AND r.deleted_at IS NULL'
    if camera: sql+=' AND r.camera_id=%s';args.append(camera)
    result=[]
    for row in conn.execute(sql+' ORDER BY v.local_time,r.id',args):
        item=dict(row);item.update(time=row['local_time'].strftime('%H:%M'),version=row['current_version'],text=row['text_content'] or '')
        result.append(item)
    return result

def compile_config(home,camera):
    with db.connect('worker',home,camera=camera) as conn:
        found=conn.execute('SELECT id FROM annha.cameras WHERE id=%s AND retired_at IS NULL FOR UPDATE',(camera,)).fetchone()
        if not found: return None
        settings=dict(conn.execute('SELECT * FROM annha.home_settings WHERE home_id=%s',(home,)).fetchone())
        settings.pop('home_id',None);settings.pop('updated_at',None)
        reminders=reminder_rows(conn,home,camera)
        previous=conn.execute('SELECT * FROM annha.camera_configurations WHERE camera_id=%s ORDER BY version DESC LIMIT 1',(camera,)).fetchone()
        body=jsonable_encoder({'camera_id':camera,'zones':[],'reference':{},'environment':settings,'reminders':reminders})
        if previous and {key:value for key,value in previous['payload'].items() if key!='version'}==body: return previous['payload']
        version=previous['version']+1 if previous else 1;body['version']=version
        conn.execute('INSERT INTO annha.camera_configurations(home_id,camera_id,version,payload) VALUES(%s,%s,%s,%s)',(home,camera,version,db.J(body)))
        conn.execute('''INSERT INTO annha.camera_config_state(home_id,camera_id,desired_version) VALUES(%s,%s,%s)
            ON CONFLICT(home_id,camera_id) DO UPDATE SET desired_version=excluded.desired_version,error=NULL''',(home,camera,version))
        return body

def events_public(conn,rows):
    rows=list(rows)
    if not rows: return []
    ids=[str(row['id']) for row in rows]
    # Queue independent reads before fetching; the enclosing transaction pipelines them.
    updates_cursor=conn.execute("SELECT DISTINCT ON(event_id) event_id,payload FROM annha.event_updates WHERE event_id=ANY(%s::uuid[]) ORDER BY event_id,sequence DESC",(ids,))
    actions_cursor=conn.execute('SELECT * FROM annha.event_actions WHERE event_id=ANY(%s::uuid[]) ORDER BY created_at,id',(ids,))
    assets_cursor=conn.execute('SELECT id,home_id,camera_id,event_id,name,status,created_at,mime_type,size_bytes,error_code FROM annha.media_assets WHERE event_id=ANY(%s::uuid[]) ORDER BY created_at',(ids,))
    updates={str(row['event_id']):row['payload'] for row in updates_cursor.fetchall()}
    actions=actions_cursor.fetchall();assets=assets_cursor.fetchall()
    names={}
    if actions:
        with db.connect('auth') as auth:
            names={str(item['id']):item['name'] for item in auth.execute('SELECT id,name FROM annha_private.users WHERE id=ANY(%s::uuid[])',(list({str(a['user_id']) for a in actions}),))}
    grouped_actions={};grouped_assets={}
    for action in actions:
        action=dict(action);action['user_name']=names.get(str(action['user_id']),'Tài khoản đã ngừng sử dụng')
        grouped_actions.setdefault(str(action['event_id']),[]).append(action)
    for asset in assets: grouped_assets.setdefault(str(asset['event_id']),[]).append(asset_public(asset))
    return jsonable_encoder([{**dict(row),'is_demo':demo_camera(row['camera_id']),'sequence':row['latest_sequence'],
        'observed_at':row['first_observed_at'],'payload':updates.get(str(row['id']),{}),
        'actions':grouped_actions.get(str(row['id']),[]),'evidence':grouped_assets.get(str(row['id']),[])} for row in rows])

def event_public(conn,row): return events_public(conn,[row])[0]

def asset_public(row):
    return {**{key:row[key] for key in ('id','home_id','camera_id','event_id','name','status','created_at')},
            'mime':row['mime_type'],'size':row['size_bytes'] or 0,'error':row['error_code']}

def asset_path(row):
    key=row['local_object_key']
    if not key or Path(key).name!=key: raise HTTPException(404,'File không khả dụng.')
    path=db.MEDIA_ROOT/key
    if row['status']!='ready' or (row['expires_at'] and row['expires_at']<=db.now()) or not path.is_file():
        raise HTTPException(404,'File chưa sẵn sàng hoặc đã hết hạn.')
    return path

def ingest_event(camera,payload):
    home=camera['home_id'];cam=camera['id']
    with db.connect('worker',home,camera=cam) as conn:
        if not conn.execute('SELECT id FROM annha.cameras WHERE id=%s AND retired_at IS NULL FOR UPDATE',(cam,)).fetchone(): raise HTTPException(401,'Thiết bị đã ngừng hoạt động.')
        old=conn.execute('SELECT * FROM annha.events WHERE camera_id=%s AND source_id=%s FOR UPDATE',(cam,payload.event_id)).fetchone()
        if old and old['kind']!=payload.kind: raise HTTPException(409,'Không đổi loại của cùng sự kiện.')
        if old and old['latest_sequence']>=payload.sequence: return event_public(conn,old),False
        if payload.config_version and not conn.execute('SELECT 1 FROM annha.camera_configurations WHERE camera_id=%s AND version=%s',(cam,payload.config_version)).fetchone():
            raise HTTPException(422,'Phiên bản cấu hình không thuộc thiết bị.')
        event=str(old['id']) if old else db.uid();stamp=datetime.fromisoformat(payload.observed_at)
        reopened=bool(old and old['status'] in ('RESOLVED','FALSE_ALARM') and payload.observation=='abnormal')
        if old:
            conn.execute('''UPDATE annha.events SET latest_sequence=%s,severity=%s,observation=%s,last_observed_at=%s,received_at=now(),updated_at=now(),
              reason=%s,duration_s=%s,model_score=%s,config_version=%s,status=%s WHERE id=%s''',
                (payload.sequence,payload.severity,payload.observation,stamp,payload.reason,payload.duration_s,payload.confidence,payload.config_version or None,'OPEN' if reopened else old['status'],event))
        else:
            conn.execute('''INSERT INTO annha.events(id,home_id,camera_id,source_id,latest_sequence,kind,severity,observation,first_observed_at,last_observed_at,reason,duration_s,model_score,config_version,expires_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (event,home,cam,payload.event_id,payload.sequence,payload.kind,payload.severity,payload.observation,stamp,stamp,payload.reason,payload.duration_s,payload.confidence,payload.config_version or None,db.now()+timedelta(days=365)))
        conn.execute('INSERT INTO annha.event_updates(home_id,camera_id,event_id,sequence,observed_at,observation,severity,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (home,cam,event,payload.sequence,stamp,payload.observation,payload.severity,db.J(payload.model_dump())))
        if not old or reopened:
            for channel in conn.execute('SELECT * FROM annha.notification_channels WHERE enabled AND revoked_at IS NULL').fetchall():
                generation=conn.execute('SELECT COALESCE(MAX(generation),0)+1 AS n FROM annha.notification_deliveries WHERE event_id=%s AND channel_id=%s',(event,channel['id'])).fetchone()['n']
                conn.execute('INSERT INTO annha.notification_deliveries(home_id,camera_id,event_id,channel_id,generation) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(home,cam,event,channel['id'],generation))
        return event_public(conn,conn.execute('SELECT * FROM annha.events WHERE id=%s',(event,)).fetchone()),True

async def broadcast(event):
    for socket,(token,home) in tuple(connections.items()):
        if str(home)!=str(event['home_id']): continue
        try:
            current=await asyncio.to_thread(session_user,token)
            await asyncio.to_thread(camera_access,event['camera_id'],current['id'],'view',True)
            await asyncio.wait_for(socket.send_json(jsonable_encoder(event)),timeout=1)
        except Exception:
            connections.pop(socket,None)
            with suppress(Exception): await socket.close(code=1008)

async def revalidate_connections():
    for socket,(token,home) in tuple(connections.items()):
        try:
            current=await asyncio.to_thread(session_user,token)
            await asyncio.to_thread(membership,home,current['id'])
        except HTTPException:
            connections.pop(socket,None)
            with suppress(Exception): await socket.close(code=1008)
    from . import pgmedia
    await pgmedia.revalidate()

def send_mail(recipient,subject,body):
    message=EmailMessage();message['From']=os.getenv('SMTP_FROM','AnNhà <noreply@annha.local>');message['To']=recipient;message['Subject']=subject;message.set_content(body)
    with smtplib.SMTP(os.getenv('SMTP_HOST','localhost'),int(os.getenv('SMTP_PORT','1025')),timeout=10) as smtp:
        if os.getenv('SMTP_STARTTLS','false').lower()=='true': smtp.starttls()
        if os.getenv('SMTP_USER'): smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
        smtp.send_message(message)

def process_job():
    lease=db.uid()
    with db.connect('worker') as conn:
        job=conn.execute('''WITH picked AS (SELECT id FROM annha_private.job_queue WHERE (status='pending' AND available_at<=now()) OR
          (status='running' AND lease_until<now()) ORDER BY available_at FOR UPDATE SKIP LOCKED LIMIT 1)
          UPDATE annha_private.job_queue j SET status='running',lease_owner=%s,lease_until=now()+interval '2 minutes',attempts=attempts+1
          FROM picked WHERE j.id=picked.id RETURNING j.*''',(lease,)).fetchone()
    if not job: return
    try:
        if job['kind']=='email':
            data=decrypt(job['secret_ciphertext']);send_mail(data['recipient'],data['subject'],data['body'])
        elif job['kind']=='compile_config': compile_config(str(job['home_id']),job['payload']['camera_id'])
        elif job['kind']=='tts':
            home=str(job['home_id']);asset=str(job['asset_id']);data=decrypt(job['secret_ciphertext']);path=db.MEDIA_ROOT/(asset+'.wav')
            binary=shutil.which('espeak-ng')
            if not binary: raise RuntimeError('TTSUnavailable')
            subprocess.run([binary,'-v','vi','-s','150','-w',str(path),'--stdin'],input=data['text'].encode(),timeout=30,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            with db.connect('worker',home) as conn:
                stored=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset,)).fetchone()
                if stored['status']!='ready':
                    conn.execute('UPDATE annha.home_storage SET reserved_bytes=reserved_bytes-%s,used_bytes=used_bytes+%s WHERE home_id=%s',(stored['reserved_bytes'],path.stat().st_size,home))
                    conn.execute("UPDATE annha.media_assets SET status='ready',size_bytes=%s,local_object_key=%s,provider='local',ready_at=now(),reserved_bytes=0,error_code=NULL WHERE id=%s",(path.stat().st_size,path.name,asset))
            compile_config(home,str(stored['camera_id']))
        else: raise RuntimeError('UnsupportedJob')
        with db.connect('worker') as conn:
            conn.execute("UPDATE annha_private.job_queue SET status='done',completed_at=now(),secret_ciphertext=NULL,key_id=NULL,lease_until=NULL,last_error_code=NULL WHERE id=%s AND lease_owner=%s",(job['id'],lease))
    except Exception as error:
        with db.connect('worker') as conn:
            conn.execute("UPDATE annha_private.job_queue SET status=%s,available_at=now()+%s,lease_until=NULL,last_error_code=%s WHERE id=%s AND lease_owner=%s",
                ('failed' if job['attempts']>=5 else 'pending',timedelta(seconds=min(300,10*2**job['attempts'])),type(error).__name__,job['id'],lease))
        if job['kind']=='tts' and job['attempts']>=5:
            with db.connect('worker',job['home_id']) as conn:
                conn.execute("UPDATE annha.media_assets SET status='failed',error_code='TTSFailed' WHERE id=%s",(job['asset_id'],))

def process_notifications():
    with db.connect('auth') as conn: homes=[str(r['id']) for r in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
    for home in homes:
        with db.connect('worker',home) as conn:
            job=conn.execute("SELECT * FROM annha.notification_deliveries WHERE status='pending' AND next_attempt_at<=now() ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if not job: continue
            allowed=conn.execute('SELECT annha_private.can_dispatch_notification(%s) AS ok',(job['id'],)).fetchone()['ok']
            if not allowed:
                conn.execute("UPDATE annha.notification_deliveries SET status='cancelled' WHERE id=%s",(job['id'],));continue
            channel=conn.execute('SELECT * FROM annha.notification_channels WHERE id=%s',(job['channel_id'],)).fetchone()
            if channel['kind']=='email' and os.getenv('EMAIL_ALERTS_ENABLED','false').lower()!='true': continue
            event=conn.execute('SELECT e.*,c.name FROM annha.events e JOIN annha.cameras c ON c.id=e.camera_id WHERE e.id=%s',(job['event_id'],)).fetchone()
            destination=conn.execute('SELECT destination_ciphertext FROM annha_private.notification_secrets WHERE channel_id=%s',(channel['id'],)).fetchone() if channel['kind']=='telegram' else None
            conn.execute("UPDATE annha.notification_deliveries SET status='sending',attempt_count=attempt_count+1,next_attempt_at=now()+interval '2 minutes' WHERE id=%s",(job['id'],))
        text=f"AnNhà: {event['kind']} tại {event['name']}\nThời điểm: {event['first_observed_at'].isoformat()}\nMã sự kiện: {event['id']}\nVui lòng mở ứng dụng để kiểm tra."
        state='accepted';error=None;provider_id=None
        try:
            if channel['kind']=='email':
                with db.connect('auth') as conn: recipient=conn.execute('SELECT email,email_version FROM annha_private.users WHERE id=%s',(channel['recipient_user_id'],)).fetchone()
                if recipient['email_version']!=job['email_version']: raise RuntimeError('StaleEmail')
                send_mail(recipient['email'],'AnNhà: cảnh báo cần kiểm tra',text)
            else:
                if not destination or not os.getenv('TELEGRAM_BOT_TOKEN'): raise RuntimeError('TelegramNotConfigured')
                chat=decrypt(destination['destination_ciphertext'])['chat_id']
                request=urllib.request.Request('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/sendMessage',data=json.dumps({'chat_id':chat,'text':text}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=10) as response:
                    data=json.load(response)
                    if not data.get('ok'): raise RuntimeError('TelegramRejected')
                    provider_id=str(data['result']['message_id'])
        except Exception as exc: state='failed';error=type(exc).__name__
        with db.connect('worker',home) as conn:
            count=job['attempt_count']+1
            conn.execute('INSERT INTO annha.delivery_attempts(home_id,delivery_id,attempt,status,provider,provider_message_id,error_code) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (home,job['id'],count,state,'smtp' if channel['kind']=='email' else 'telegram',provider_id,error))
            conn.execute('''UPDATE annha.notification_deliveries SET status=%s,last_error_code=%s,sent_count=sent_count+%s,
               accepted_at=CASE WHEN %s THEN now() ELSE accepted_at END,next_attempt_at=now()+interval '2 minutes' WHERE id=%s''',
                ('pending' if count<5 else ('accepted' if state=='accepted' else 'failed'),error,1 if state=='accepted' else 0,state=='accepted',job['id']))

# These monitors persist their state so a restart cannot reset the hold timer.
def evaluate_environment(camera,telemetry):
    stamp=datetime.fromisoformat(telemetry.observed_at)
    if abs((db.now()-stamp).total_seconds())>120: return []
    emissions=[]
    with db.connect('worker',camera['home_id'],camera=camera['id']) as conn:
        conn.execute('SELECT id FROM annha.cameras WHERE id=%s FOR UPDATE',(camera['id'],))
        settings=conn.execute('SELECT * FROM annha.home_settings WHERE home_id=%s',(camera['home_id'],)).fetchone()
        policies=[('temperature_high','temperature','C',1),('temperature_low','temperature','C',-1),('humidity_high','humidity','%',1),('gas_high','gas',settings['gas_unit'],1)]
        for key,metric,unit,direction in policies:
            old=conn.execute('SELECT * FROM annha.monitor_states WHERE camera_id=%s AND monitor_key=%s',(camera['id'],key)).fetchone()
            state=old['state'] if old else {};since=old['since_at'] if old else None;active=bool(old and old['active']);source=state.get('source_id')
            if state.get('last_observed') and stamp<=datetime.fromisoformat(state['last_observed']): continue
            reading=telemetry.readings.get(metric)
            if not reading or reading.quality!='valid' or reading.unit!=unit:
                if not active: since=None
            else:
                delta=(reading.value-settings[key])*direction
                if active and delta<=-settings['hysteresis']:
                    emissions.append(models.EventInput(event_id=source,sequence=2,kind='environment',severity='critical' if metric=='gas' else 'warning',observation='recovered',observed_at=stamp.isoformat(),reason=f'{metric} đã trở về ngưỡng cấu hình'))
                    active=False;since=None;source=None
                elif delta>0:
                    since=since or stamp
                    if not active and (stamp-since).total_seconds()>=settings['environment_hold_seconds']:
                        active=True;source='environment:'+key+':'+db.uid()
                        emissions.append(models.EventInput(event_id=source,kind='environment',severity='critical' if metric=='gas' else 'warning',observation='abnormal',observed_at=stamp.isoformat(),reason=f'{metric}: {reading.value} {unit}; ngưỡng {settings[key]}',duration_s=(stamp-since).total_seconds()))
                elif not active: since=None
            conn.execute('''INSERT INTO annha.monitor_states(home_id,camera_id,monitor_key,active,since_at,state) VALUES(%s,%s,%s,%s,%s,%s)
              ON CONFLICT(camera_id,monitor_key) DO UPDATE SET active=excluded.active,since_at=excluded.since_at,state=excluded.state,updated_at=now()''',(camera['home_id'],camera['id'],key,active,since,db.J({'source_id':source,'last_observed':stamp.isoformat()})))
    events=[ingest_event(camera,payload)[0] for payload in emissions]
    for event in events: pending_broadcasts.append(event)
    return events

pending_broadcasts=[]

def maintenance():
    with db.connect('auth') as conn:
        homes=[str(r['id']) for r in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
        conn.execute('DELETE FROM annha_private.sessions WHERE expires_at<now()-interval \'7 days\'')
        conn.execute('DELETE FROM annha_private.email_tokens WHERE expires_at<now()-interval \'7 days\'')
        conn.execute('DELETE FROM annha_private.rate_limits WHERE window_end<now()')
    for home in homes:
        emissions=[]
        with db.connect('worker',home) as conn:
            conn.execute("UPDATE annha.commands SET status='expired' WHERE expires_at<now() AND status IN ('pending','accepted')")
            # A crash after a provider accepted a send is ambiguous; do not blindly resend.
            conn.execute("UPDATE annha.notification_deliveries SET status='unknown',last_error_code='LeaseExpired' WHERE status='sending' AND next_attempt_at<now()")
            for camera in conn.execute('SELECT * FROM annha.cameras WHERE retired_at IS NULL AND last_seen_at IS NOT NULL').fetchall():
                camera={**dict(camera),'id':str(camera['id']),'home_id':home}
                old=conn.execute("SELECT * FROM annha.monitor_states WHERE camera_id=%s AND monitor_key='offline' FOR UPDATE",(camera['id'],)).fetchone()
                offline=(db.now()-camera['last_seen_at']).total_seconds()>45;active=bool(old and old['active'])
                if offline==active: continue
                source=old['state']['source_id'] if active else 'offline:'+db.uid()
                conn.execute("INSERT INTO annha.monitor_states(home_id,camera_id,monitor_key,active,state) VALUES(%s,%s,'offline',%s,%s) ON CONFLICT(camera_id,monitor_key) DO UPDATE SET active=excluded.active,state=excluded.state,updated_at=now()",(home,camera['id'],offline,db.J({'source_id':source})))
                emissions.append((camera,models.EventInput(event_id=source,sequence=1 if offline else 2,kind='device',severity='warning',observation='abnormal' if offline else 'recovered',observed_at=db.now().isoformat(),reason='Quá hạn heartbeat; chưa rõ mất mạng hay mất nguồn' if offline else 'Đã nhận heartbeat trở lại')))
            for asset in conn.execute("SELECT * FROM annha.media_assets WHERE status='ready' AND (expires_at<now() OR (kind IN ('snapshot','event_image','event_clip') AND created_at<now()-(SELECT retention_days FROM annha.home_settings WHERE home_id=current_setting('app.home_id')::uuid)*interval '1 day')) FOR UPDATE").fetchall():
                if asset['provider']!='local': continue
                if asset['local_object_key'] and Path(asset['local_object_key']).name==asset['local_object_key']: (db.MEDIA_ROOT/asset['local_object_key']).unlink(missing_ok=True)
                conn.execute('UPDATE annha.home_storage SET used_bytes=used_bytes-%s WHERE home_id=%s',(asset['size_bytes'],home))
                conn.execute("UPDATE annha.media_assets SET status='expired',deleted_at=now() WHERE id=%s",(asset['id'],))
            conn.execute('DELETE FROM annha.telemetry_batches WHERE received_at<now()-(SELECT telemetry_retention_days FROM annha.home_settings WHERE home_id=%s)*interval \'1 day\'',(home,))
        for camera,payload in emissions:
            event,changed=ingest_event(camera,payload)
            if changed: pending_broadcasts.append(event)

async def close_home_connections(home):
    for socket,(_,tenant) in tuple(connections.items()):
        if str(tenant)==str(home):
            connections.pop(socket,None)
            with suppress(Exception): await socket.close(code=1008)
    await revalidate_connections()

async def worker():
    import logging
    last=0
    while True:
        try:
            await asyncio.to_thread(process_job)
            await asyncio.to_thread(process_notifications)
            if time.monotonic()-last>=15:
                await asyncio.to_thread(maintenance);last=time.monotonic()
            while pending_broadcasts: await broadcast(pending_broadcasts.pop(0))
            await revalidate_connections()
        except Exception as error:
            logging.getLogger(__name__).warning('PostgreSQL worker operation failed: %s',type(error).__name__)
        await asyncio.sleep(2)
