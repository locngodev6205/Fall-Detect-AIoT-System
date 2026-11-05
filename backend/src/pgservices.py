"""Business operations on normalized PostgreSQL tables; cloud side effects use durable jobs."""
import asyncio
from contextlib import suppress
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import smtplib
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from . import pgdb as db, models, media_storage
from .email_templates import render_email
from .demo_metadata import demo_camera
from .pgsecurity import digest,verification_code_digest,reset_code_digest,membership,session_user,camera_access,device_identity

connections={}
logger=logging.getLogger(__name__)
telegram_webhook_ready=False

def telegram_update_mode():
    mode=os.getenv('TELEGRAM_UPDATE_MODE','polling').strip().lower()
    return mode if mode in ('polling','webhook') else 'invalid'

class MediaQuotaExceeded(RuntimeError):
    pass

class TTSAssetUnavailable(RuntimeError):
    pass

def encrypt(value): return Fernet(os.environ['DATA_ENCRYPTION_KEY'].encode()).encrypt(json.dumps(value,ensure_ascii=False).encode())
def decrypt(value): return json.loads(Fernet(os.environ['DATA_ENCRYPTION_KEY'].encode()).decrypt(bytes(value)))

def mail(conn,recipient,subject,body,purpose='message',html_body=None):
    conn.execute("INSERT INTO annha_private.job_queue(kind,payload,secret_ciphertext,key_id,idempotency_key) VALUES('email',%s,%s,%s,%s)",
        (db.J({'purpose':purpose}),encrypt({'recipient':recipient,'subject':subject,'body':body,'html_body':html_body}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary'),db.uid()))

def queue_email(conn,account,purpose):
    is_verification=purpose=='verify_email'
    token=f'{secrets.randbelow(100_000_000):08d}'
    if not is_verification:
        # Same lock order as reset: account first, then credential rows.
        conn.execute('SELECT id FROM annha_private.users WHERE id=%s FOR UPDATE',(account['id'],))
    conn.execute('UPDATE annha_private.email_tokens SET consumed_at=now() WHERE user_id=%s AND purpose=%s AND consumed_at IS NULL',(account['id'],purpose))
    conn.execute('INSERT INTO annha_private.email_tokens(token_hash,user_id,purpose,expires_at,email_version) VALUES(%s,%s,%s,%s,%s)',
        (verification_code_digest(token) if is_verification else reset_code_digest(account['email'],token),account['id'],purpose,db.now()+timedelta(minutes=15 if not is_verification else 1440),account['email_version']))
    kind='password_reset' if purpose=='reset_password' else 'verification'
    rendered=render_email(kind,public_url=os.getenv('PUBLIC_URL','http://localhost:8188'),
        recipient_name=account.get('name'),code=token)
    mail(conn,account['email'],rendered.subject,rendered.text,purpose,rendered.html)

def provision_device(name):
    device=db.uid();token=secrets.token_urlsafe(40);code=secrets.token_urlsafe(16)
    with db.connect('auth') as conn:
        conn.execute('INSERT INTO annha_private.device_registry(id,model) VALUES(%s,%s)',(device,name))
        conn.execute('INSERT INTO annha_private.device_credentials(device_id,token_hash) VALUES(%s,%s)',(device,digest(token)))
        conn.execute('INSERT INTO annha_private.pairing_codes(code_hash,device_id,expires_at) VALUES(%s,%s,%s)',(digest(code),device,db.now()+timedelta(minutes=30)))
    return {'device_id':device,'device_token':token,'pairing_code':code,'expires_in_seconds':1800}

def cameras_public(conn,rows,permissions=None):
    rows=list(rows)
    if not rows: return []
    permissions=permissions or {}
    states={str(state['camera_id']):state for state in conn.execute("""SELECT c.id AS camera_id,s.desired_version,s.applied_version,s.error,
      EXISTS(SELECT 1 FROM annha.media_assets a WHERE a.camera_id=c.id AND a.kind='snapshot' AND a.mime_type LIKE 'image/%%' AND a.status='ready'
        AND a.upload_key<>'demo:snapshot' AND (a.expires_at IS NULL OR a.expires_at>now())) AS snapshot_available
      FROM annha.cameras c LEFT JOIN annha.camera_config_state s ON s.camera_id=c.id WHERE c.id=ANY(%s::uuid[])""",([str(row['id']) for row in rows],))}
    result=[];stamp=db.now()
    for row in rows:
        state=states.get(str(row['id']),{});desired=state.get('desired_version') or 0;applied=state.get('applied_version') or 0
        result.append({**{key:row[key] for key in ('id','home_id','room_id','name','observation','capabilities')},
            'is_demo':demo_camera(row['id']),'snapshot_available':bool(state.get('snapshot_available')),'last_seen':row['last_seen_at'],
            'online':bool(row['last_seen_at'] and (stamp-row['last_seen_at']).total_seconds()<45),'permissions':permissions.get(str(row['id']),{}),
            'desired_version':desired,'applied_version':applied,'config_error':state.get('error'),'sync_status':'applied' if desired and desired==applied else 'pending'})
    return result

def camera_public(conn,row,permissions=None): return cameras_public(conn,[row],permissions)[0]

def current_config_payload(payload):
    return {key:value for key,value in payload.items() if key not in ('zones','reference')}

def device_config_payload(payload):
    # Empty legacy tombstones tell older edge clients to clear cached zone fields.
    return {**current_config_payload(payload),'zones':[],'reference':{}}

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
        body=jsonable_encoder({'camera_id':camera,'environment':settings,'reminders':reminders})
        if previous and {key:value for key,value in previous['payload'].items() if key!='version'}==body: return previous['payload']
        version=previous['version']+1 if previous else 1;body['version']=version
        conn.execute('INSERT INTO annha.camera_configurations(home_id,camera_id,version,payload) VALUES(%s,%s,%s,%s)',(home,camera,version,db.J(body)))
        conn.execute('''INSERT INTO annha.camera_config_state(home_id,camera_id,desired_version) VALUES(%s,%s,%s)
            ON CONFLICT(home_id,camera_id) DO UPDATE SET desired_version=excluded.desired_version,error=NULL''',(home,camera,version))
        return body

def retire_zone_configs():
    """Append one current-schema revision for legacy configs without deleting history."""
    with db.connect('auth') as conn:
        cameras=[(str(row['home_id']),str(row['id'])) for row in conn.execute('SELECT id,home_id FROM annha.cameras WHERE retired_at IS NULL')]
    for home,camera in cameras:
        with db.connect('worker',home,camera=camera) as conn:
            row=conn.execute('SELECT payload FROM annha.camera_configurations WHERE camera_id=%s ORDER BY version DESC LIMIT 1',(camera,)).fetchone()
        if row and ('zones' in row['payload'] or 'reference' in row['payload']):
            compile_config(home,camera)
            with db.connect('worker',home,camera=camera) as conn:
                db.audit(conn,home,None,'zones.retire',camera,camera)

def events_public(conn,rows):
    rows=list(rows)
    if not rows: return []
    ids=[str(row['id']) for row in rows]
    # Queue independent reads before fetching; the enclosing transaction pipelines them.
    updates_cursor=conn.execute("SELECT DISTINCT ON(event_id) event_id,payload FROM annha.event_updates WHERE event_id=ANY(%s::uuid[]) ORDER BY event_id,sequence DESC",(ids,))
    actions_cursor=conn.execute('SELECT * FROM annha.event_actions WHERE event_id=ANY(%s::uuid[]) ORDER BY created_at,id',(ids,))
    assets_cursor=conn.execute('SELECT id,home_id,camera_id,event_id,kind,name,status,created_at,mime_type,size_bytes,error_code,expires_at FROM annha.media_assets WHERE event_id=ANY(%s::uuid[]) ORDER BY created_at',(ids,))
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
    status=row['status']
    expires_at=row.get('expires_at') if hasattr(row,'get') else None
    if status=='ready' and expires_at and expires_at<=db.now(): status='expired'
    return {**{key:row[key] for key in ('id','home_id','camera_id','event_id','kind','name','created_at')},'status':status,
            'mime':row['mime_type'],'size':row['size_bytes'] or 0,'error':row['error_code']}

def asset_path(row):
    if row['status']!='ready' or (row['expires_at'] and row['expires_at']<=db.now()):
        raise HTTPException(404,'File chưa sẵn sàng hoặc đã hết hạn.')
    try:
        return media_storage.LocalStorage(db.MEDIA_ROOT).path_for(row)
    except media_storage.MediaStorageError:
        raise HTTPException(404,'File không khả dụng.') from None

def asset_response(row,range_header=None,extra_headers=None):
    """Resolve a private asset only after the caller's existing RLS/camera check."""
    if row['status']!='ready' or (row['expires_at'] and row['expires_at']<=db.now()):
        raise HTTPException(404,'File chưa sẵn sàng hoặc đã hết hạn.')
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    if extra_headers: headers.update(extra_headers)
    if row['provider']=='local':
        return FileResponse(asset_path(row),media_type=row['mime_type'],headers=headers)
    if row['provider']!='cloudinary':
        raise HTTPException(503,'Nguồn lưu trữ media chưa được hỗ trợ.')
    try:
        provider=media_storage.provider_for_asset(row,db.MEDIA_ROOT)
        response=provider.open_read(row,range_header)
    except media_storage.MediaNotFound:
        raise HTTPException(404,'Bằng chứng không còn khả dụng.') from None
    except media_storage.MediaUnavailable:
        # Retained originals remain a recoverable fallback only for a provider outage.
        try:
            local=media_storage.LocalStorage(db.MEDIA_ROOT).path_for(row)
        except media_storage.MediaStorageError:
            raise HTTPException(503,'Không thể tải media lúc này.') from None
        return FileResponse(local,media_type=row['mime_type'],headers={**headers,'X-Media-Source':'local-fallback'})
    for key in ('Content-Length','Content-Range','Accept-Ranges'):
        value=response.headers.get(key)
        if value: headers[key]=value
    status=getattr(response,'status',getattr(response,'code',200))
    def chunks():
        while True:
            block=response.read(64*1024)
            if not block: break
            yield block
    return StreamingResponse(chunks(),status_code=status,media_type=row['mime_type'],
        headers=headers,background=BackgroundTask(response.close))

def _staged_path(key):
    if not key or Path(key).name!=key:
        raise media_storage.MediaNotFound('Staged media is unavailable.')
    path=db.MEDIA_ROOT/'.staging'/key
    if not path.is_file():
        raise media_storage.MediaNotFound('Staged media is unavailable.')
    return path

def _upload_cloud_asset(home,asset_id,path):
    with db.connect('worker',home) as conn:
        row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
    if not row or row['status']!='uploading':
        return
    provider=media_storage.CloudinaryStorage()
    metadata=provider.upload(path,asset_id,row['mime_type'])
    if metadata.size_bytes!=row['size_bytes'] or metadata.sha256!=bytes(row['sha256']):
        raise media_storage.MediaUnavailable('Uploaded bytes did not match reserved metadata.')
    with db.connect('worker',home,camera=row['camera_id']) as conn:
        current=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
        if not current:
            raise media_storage.MediaUnavailable('Media upload row disappeared.')
        if current['status']!='uploading':
            # A concurrent delete wins; persist the provider ID so its durable delete job
            # can clean up the object created while the upload request was in flight.
            conn.execute('''UPDATE annha.media_assets SET status='deleting',provider='cloudinary',
                provider_environment=%s,provider_asset_id=%s,public_id=%s,resource_type=%s,
                delivery_type=%s,provider_version=%s,local_object_key=%s,size_bytes=%s,
                width=%s,height=%s,duration_s=%s,sha256=%s,deletion_requested_at=COALESCE(deletion_requested_at,now())
                WHERE id=%s''',(metadata.provider_environment,metadata.provider_asset_id,metadata.public_id,
                metadata.resource_type,metadata.delivery_type,metadata.provider_version,path.name,
                metadata.size_bytes,metadata.width,metadata.height,metadata.duration_s,metadata.sha256,asset_id))
            conn.execute('''INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,idempotency_key)
                VALUES(%s,'delete_media',%s,%s,%s) ON CONFLICT(idempotency_key) DO UPDATE
                SET status='pending',available_at=now(),lease_until=NULL,last_error_code=NULL''',
                (home,asset_id,db.J({'target_status':'deleted'}),'media-delete:'+asset_id))
            return
        reserved=conn.execute('''UPDATE annha.home_storage SET reserved_bytes=reserved_bytes-%s,
             used_bytes=used_bytes+%s WHERE home_id=%s AND reserved_bytes>=%s RETURNING home_id''',
             (current['reserved_bytes'],metadata.size_bytes,home,current['reserved_bytes'])).fetchone()
        if not reserved:
            raise media_storage.MediaUnavailable('Media quota reservation is inconsistent.')
        conn.execute('''UPDATE annha.media_assets SET status='ready',provider='cloudinary',
             provider_environment=%s,provider_asset_id=%s,public_id=%s,resource_type=%s,
             delivery_type=%s,provider_version=%s,local_object_key=NULL,size_bytes=%s,
             width=%s,height=%s,duration_s=%s,sha256=%s,ready_at=now(),reserved_bytes=0,error_code=NULL
             WHERE id=%s''',(metadata.provider_environment,metadata.provider_asset_id,metadata.public_id,
             metadata.resource_type,metadata.delivery_type,metadata.provider_version,metadata.size_bytes,
             metadata.width,metadata.height,metadata.duration_s,metadata.sha256,asset_id))

def _finalize_media_delete(home,asset_id,target_status):
    with db.connect('worker',home) as conn:
        row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(asset_id,)).fetchone()
        if not row: return
        if row['status'] not in ('deleting','expired','deleted'):
            return
    if row['provider']=='cloudinary' and row['public_id']:
        media_storage.CloudinaryStorage().delete(row)
    # Cloudinary assets migrated from local storage retain the original until explicit
    # user deletion or retention expiry; deletion of the media removes that copy too.
    media_storage.LocalStorage(db.MEDIA_ROOT).delete(row)
    if row['local_object_key'] and Path(row['local_object_key']).name==row['local_object_key']:
        (db.MEDIA_ROOT/'.staging'/row['local_object_key']).unlink(missing_ok=True)
    with db.connect('worker',home) as conn:
        row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
        if not row or row['status'] not in ('deleting','expired','deleted'):
            return
        if row['status'] not in ('expired','deleted'):
            # ready_at is the durable marker that bytes were counted as used.
            # Failed uploads keep their expected size for retry but were never
            # committed to used_bytes; subtracting them would steal quota from
            # unrelated assets in the same home.
            used_bytes=(row['size_bytes'] or 0) if row['ready_at'] else 0
            conn.execute('UPDATE annha.home_storage SET used_bytes=GREATEST(0,used_bytes-%s),reserved_bytes=GREATEST(0,reserved_bytes-%s) WHERE home_id=%s',
                (used_bytes,row['reserved_bytes'] or 0,home))
        final=target_status if target_status in ('expired','deleted') else 'deleted'
        conn.execute('UPDATE annha.media_assets SET status=%s,deleted_at=now(),reserved_bytes=0,error_code=NULL WHERE id=%s',(final,asset_id))

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
            for channel in conn.execute('''SELECT * FROM annha.notification_channels
                WHERE home_id=%s AND enabled AND revoked_at IS NULL AND suppressed_at IS NULL
                  AND %s=ANY(event_kinds)
                  AND CASE %s WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END >=
                      CASE minimum_severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END
                  AND (camera_scope_all OR EXISTS (SELECT 1 FROM annha.notification_channel_cameras scope
                    WHERE scope.home_id=%s AND scope.channel_id=notification_channels.id AND scope.camera_id=%s))''',
                (home,payload.kind,payload.severity,home,cam)).fetchall():
                generation=conn.execute('SELECT COALESCE(MAX(generation),0)+1 AS n FROM annha.notification_deliveries WHERE event_id=%s AND channel_id=%s',(event,channel['id'])).fetchone()['n']
                conn.execute('''INSERT INTO annha.notification_deliveries(home_id,camera_id,event_id,channel_id,generation,dispatch_kind,reminder_number)
                  VALUES(%s,%s,%s,%s,%s,'initial',0) ON CONFLICT DO NOTHING''',(home,cam,event,channel['id'],generation))
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

def send_mail(recipient,subject,body,html_body=None):
    message=EmailMessage();message['From']=os.getenv('SMTP_FROM','AnNhà <noreply@annha.local>');message['To']=recipient;message['Subject']=subject;message.set_content(body)
    if html_body:
        message.add_alternative(html_body,subtype='html')
    host=os.getenv('SMTP_HOST','localhost').strip()
    port=int(os.getenv('SMTP_PORT','1025'))
    starttls=os.getenv('SMTP_STARTTLS','false').lower()=='true'
    username=os.getenv('SMTP_USER','').strip()
    password=os.getenv('SMTP_PASSWORD','')
    if bool(username)!=bool(password): raise RuntimeError('SMTPAuthenticationConfigurationIncomplete')
    if host.lower()=='smtp-relay.brevo.com' and (port!=587 or not starttls or not username or not password):
        raise RuntimeError('BrevoSMTPRequiresAuthenticatedStartTLS')
    with smtplib.SMTP(host,port,timeout=10) as smtp:
        if starttls:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if username: smtp.login(username,password)
        smtp.send_message(message)

def process_job(job_id=None,kinds=None):
    lease=db.uid()
    with db.connect('worker') as conn:
        job=conn.execute('''WITH picked AS (SELECT id FROM annha_private.job_queue WHERE
          ((status='pending' AND available_at<=now()) OR (status='running' AND lease_until<now()))
          AND (%s::uuid IS NULL OR id=%s::uuid) AND (%s::text[] IS NULL OR kind=ANY(%s::text[]))
          ORDER BY available_at FOR UPDATE SKIP LOCKED LIMIT 1)
          UPDATE annha_private.job_queue j SET status='running',lease_owner=%s,lease_until=now()+interval '2 minutes',attempts=attempts+1
          FROM picked WHERE j.id=picked.id RETURNING j.*''',(job_id,job_id,kinds,kinds,lease)).fetchone()
    if not job: return
    try:
        if job['kind']=='email':
            data=decrypt(job['secret_ciphertext']);send_mail(data['recipient'],data['subject'],data['body'],data.get('html_body'))
        elif job['kind']=='compile_config': compile_config(str(job['home_id']),job['payload']['camera_id'])
        elif job['kind']=='upload':
            home=str(job['home_id']);asset=str(job['asset_id'])
            with db.connect('worker',home) as conn:
                stored=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
            if stored and stored['status']=='uploading':
                path=_staged_path(stored['local_object_key'])
                _upload_cloud_asset(home,asset,path)
                path.unlink(missing_ok=True)
        elif job['kind']=='delete_media':
            home=str(job['home_id']);asset=str(job['asset_id'])
            target=job['payload'].get('target_status','deleted')
            _finalize_media_delete(home,asset,target)
        elif job['kind']=='tts':
            home=str(job['home_id']);asset=str(job['asset_id']);data=decrypt(job['secret_ciphertext'])
            with db.connect('worker',home) as conn:
                initial=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
            if not initial or initial['status'] in ('failed','deleted','expired','deleting'):
                raise TTSAssetUnavailable('TTSAssetUnavailable')
            if initial['status']=='ready':
                with db.connect('worker') as conn:
                    conn.execute("""INSERT INTO annha_private.job_queue(home_id,kind,payload,idempotency_key)
                        VALUES(%s,'compile_config',%s,%s) ON CONFLICT(idempotency_key) DO NOTHING""",
                        (job['home_id'],db.J({'camera_id':job['payload']['camera_id']}),'compile-tts:'+str(job['asset_id'])))
                    conn.execute("UPDATE annha_private.job_queue SET status='done',completed_at=now(),secret_ciphertext=NULL,key_id=NULL,lease_until=NULL,last_error_code=NULL WHERE id=%s AND lease_owner=%s",(job['id'],lease))
                return
            cloud=media_storage.preferred_provider(db.MEDIA_ROOT).name=='cloudinary'
            provider=media_storage.CloudinaryStorage() if cloud else None
            path=(db.MEDIA_ROOT/'.staging'/(asset+'.wav')) if cloud else db.MEDIA_ROOT/(asset+'.wav')
            path.parent.mkdir(parents=True,exist_ok=True)
            binary=shutil.which('espeak-ng')
            if not binary: raise RuntimeError('TTSUnavailable')
            subprocess.run([binary,'-v','vi','-s','150','-w',str(path),'--stdin'],input=data['text'].encode(),timeout=30,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            size=path.stat().st_size;digest=hashlib.sha256(path.read_bytes()).digest()
            if cloud:
                quota_exceeded=False;asset_unavailable=False;already_ready=False
                with db.connect('worker',home,camera=initial['camera_id']) as conn:
                    stored=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset,)).fetchone()
                    if not stored or stored['status'] not in ('processing','uploading','ready'):
                        asset_unavailable=True
                    elif stored['status']=='processing':
                        reserved=conn.execute('''UPDATE annha.home_storage SET reserved_bytes=reserved_bytes+%s
                            WHERE home_id=%s AND used_bytes+reserved_bytes+%s<=quota_bytes RETURNING home_id''',(size,home,size)).fetchone()
                        if not reserved:
                            conn.execute("UPDATE annha.media_assets SET status='failed',error_code='QuotaExceeded' WHERE id=%s",(asset,))
                            quota_exceeded=True
                        else:
                            conn.execute("""UPDATE annha.media_assets SET status='uploading',provider='cloudinary',
                                provider_environment=%s,public_id=%s,resource_type=%s,delivery_type=%s,
                                size_bytes=%s,reserved_bytes=%s,local_object_key=%s,sha256=%s WHERE id=%s""",
                                (provider.environment,provider.public_id(asset),provider.resource_type('audio/wav'),provider.delivery_type,
                                 size,size,path.name,digest,asset))
                    elif stored['status']=='uploading' and (stored['size_bytes']!=size or not stored['sha256'] or bytes(stored['sha256'])!=digest):
                        raise RuntimeError('TTSRetryBytesChanged')
                    else:
                        already_ready=stored['status']=='ready'
                if quota_exceeded:
                    path.unlink(missing_ok=True)
                    raise MediaQuotaExceeded('QuotaExceeded')
                if asset_unavailable:
                    path.unlink(missing_ok=True)
                    raise TTSAssetUnavailable('TTSAssetUnavailable')
                if not already_ready: _upload_cloud_asset(home,asset,path)
                path.unlink(missing_ok=True)
            else:
                quota_exceeded=False;asset_unavailable=False
                with db.connect('worker',home,camera=initial['camera_id']) as conn:
                    stored=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset,)).fetchone()
                    if not stored or stored['status'] not in ('processing','ready'):
                        asset_unavailable=True
                    elif stored['status']=='processing':
                        reserved=conn.execute('''UPDATE annha.home_storage SET used_bytes=used_bytes+%s
                            WHERE home_id=%s AND used_bytes+reserved_bytes+%s<=quota_bytes RETURNING home_id''',(size,home,size)).fetchone()
                        if not reserved:
                            conn.execute("UPDATE annha.media_assets SET status='failed',error_code='QuotaExceeded' WHERE id=%s",(asset,))
                            quota_exceeded=True
                        else:
                            conn.execute("UPDATE annha.media_assets SET status='ready',size_bytes=%s,local_object_key=%s,provider='local',ready_at=now(),reserved_bytes=0,sha256=%s,error_code=NULL WHERE id=%s",(size,path.name,digest,asset))
                if quota_exceeded:
                    path.unlink(missing_ok=True)
                    raise MediaQuotaExceeded('QuotaExceeded')
                if asset_unavailable:
                    path.unlink(missing_ok=True)
                    raise TTSAssetUnavailable('TTSAssetUnavailable')
        else: raise RuntimeError('UnsupportedJob')
        with db.connect('worker') as conn:
            if job['kind']=='tts':
                conn.execute("""INSERT INTO annha_private.job_queue(home_id,kind,payload,idempotency_key)
                    VALUES(%s,'compile_config',%s,%s) ON CONFLICT(idempotency_key) DO NOTHING""",
                    (job['home_id'],db.J({'camera_id':job['payload']['camera_id']}),'compile-tts:'+str(job['asset_id'])))
            conn.execute("UPDATE annha_private.job_queue SET status='done',completed_at=now(),secret_ciphertext=NULL,key_id=NULL,lease_until=NULL,last_error_code=NULL WHERE id=%s AND lease_owner=%s",(job['id'],lease))
    except Exception as error:
        if isinstance(error,MediaQuotaExceeded):
            with db.connect('worker') as conn:
                conn.execute("UPDATE annha_private.job_queue SET status='failed',lease_until=NULL,last_error_code='QuotaExceeded' WHERE id=%s AND lease_owner=%s",(job['id'],lease))
            return
        if isinstance(error,TTSAssetUnavailable):
            with db.connect('worker') as conn:
                conn.execute("UPDATE annha_private.job_queue SET status='cancelled',completed_at=now(),secret_ciphertext=NULL,key_id=NULL,lease_until=NULL,last_error_code='TTSAssetUnavailable' WHERE id=%s AND lease_owner=%s",(job['id'],lease))
            return
        retry_delay=min(3600,10*2**min(job['attempts'],8))
        terminal=job['kind'] in ('upload','tts') and job['attempts']>=5
        with db.connect('worker') as conn:
            if job['kind']=='delete_media':
                conn.execute("UPDATE annha_private.job_queue SET status='pending',available_at=now()+%s,lease_until=NULL,last_error_code=%s WHERE id=%s AND lease_owner=%s",
                    (timedelta(seconds=retry_delay),type(error).__name__,job['id'],lease))
            else:
                conn.execute("UPDATE annha_private.job_queue SET status=%s,available_at=now()+%s,lease_until=NULL,last_error_code=%s WHERE id=%s AND lease_owner=%s",
                    ('failed' if terminal else 'pending',timedelta(seconds=min(300,retry_delay)),type(error).__name__,job['id'],lease))
        if terminal and job['home_id'] and job['asset_id']:
            with db.connect('worker',job['home_id']) as conn:
                asset=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(job['asset_id'],)).fetchone()
                if asset and asset['status'] in ('processing','uploading'):
                    if asset['reserved_bytes']:
                        conn.execute('UPDATE annha.home_storage SET reserved_bytes=GREATEST(0,reserved_bytes-%s) WHERE home_id=%s',(asset['reserved_bytes'],job['home_id']))
                    conn.execute("UPDATE annha.media_assets SET status='failed',reserved_bytes=0,error_code=%s WHERE id=%s",
                        ('TTSFailed' if job['kind']=='tts' else 'UploadFailed',job['asset_id']))
                    if job['kind']=='tts' and asset['provider']=='cloudinary':
                        staged=db.MEDIA_ROOT/'.staging'/Path(asset['local_object_key'] or '').name
                        staged.unlink(missing_ok=True)

def telegram_bot_username():
    return os.getenv('TELEGRAM_BOT_USERNAME','AnNhaSafetyAlertBot').strip().lstrip('@')

def telegram_bot_ref():
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    return hashlib.sha256(token.encode()).digest() if token else None

def telegram_pairing_ready():
    mode=telegram_update_mode()
    if mode=='webhook': return telegram_webhook_ready
    if mode!='polling' or not telegram_bot_ref(): return False
    try:
        with db.connect('worker') as conn:
            row=conn.execute('''SELECT last_poll_at >= now()-interval '2 minutes' AS ready
              FROM annha_private.telegram_polling_state WHERE bot_ref=%s''',(telegram_bot_ref(),)).fetchone()
        return bool(row and row['ready'])
    except Exception:
        # Missing migration or an unavailable poller must not expose a broken link action.
        return False

def telegram_webhook_secret():
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    return hmac.new(token.encode(),b'annha.telegram.webhook.v1',hashlib.sha256).hexdigest() if token else ''

def parse_telegram_pairing_update(update,username=None):
    """Accept only a private-chat /start deep link addressed to this bot."""
    if not isinstance(update,dict): return None
    update_id=update.get('update_id')
    if isinstance(update_id,bool) or not isinstance(update_id,int) or update_id<0 or update_id>9223372036854775807:
        return None
    message=update.get('message')
    if not isinstance(message,dict): return None
    chat=message.get('chat') or {};sender=message.get('from') or {}
    chat_id=chat.get('id');sender_id=sender.get('id')
    if chat.get('type')!='private' or isinstance(chat_id,bool) or not isinstance(chat_id,int) or chat_id<=0:
        return None
    if isinstance(sender_id,bool) or not isinstance(sender_id,int) or sender_id!=chat_id:
        return None
    text=str(message.get('text') or '').strip()
    if len(text)>256: return None
    parts=text.split()
    if len(parts)!=2: return None
    command=parts[0]
    expected=(username or telegram_bot_username()).lower()
    if command!='/start' and command.lower()!='/start@'+expected: return None
    token=parts[1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',token): return None
    return {'update_id':update_id,'chat_id':str(chat_id),'token':token}

def _telegram_api_json(method,payload=None,timeout=5):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise RuntimeError('not_configured')
    data=json.dumps(payload).encode() if payload is not None else None
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,data=data,
        headers={'Content-Type':'application/json'} if data is not None else {})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        result=json.load(response)
    if not isinstance(result,dict) or not result.get('ok'):
        raise RuntimeError('provider_rejected')
    return result.get('result')

def configure_telegram_webhook():
    """Configure one shared public webhook only after explicit deployment opt-in."""
    global telegram_webhook_ready
    telegram_webhook_ready=False
    if telegram_update_mode()!='webhook': return False
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip();username=telegram_bot_username()
    if not token or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',username):
        logger.warning('Telegram webhook setup skipped: bot configuration is incomplete')
        return False
    public_url=os.getenv('PUBLIC_URL','').strip()
    parsed=urlsplit(public_url)
    host=(parsed.hostname or '').lower()
    local_hosts={'localhost','localhost.localdomain'}
    if parsed.scheme!='https' or not host or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or host in local_hosts or host.endswith('.localhost'):
        logger.warning('Telegram webhook setup skipped: PUBLIC_URL must be a public HTTPS origin')
        return False
    try:
        import ipaddress
        address=ipaddress.ip_address(host)
        if not address.is_global:
            logger.warning('Telegram webhook setup skipped: PUBLIC_URL must be publicly reachable')
            return False
    except ValueError:
        pass
    try:
        with db.connect('worker') as conn:
            bot_ref=telegram_bot_ref()
            if not bot_ref:
                logger.warning('Telegram webhook setup skipped: bot configuration is incomplete')
                return False
            permissions=conn.execute('''SELECT to_regclass('annha_private.telegram_pairings') AS pairings,
              to_regclass('annha_private.telegram_polling_state') AS polling_state,
              has_table_privilege(current_user,'annha_private.telegram_pairings','SELECT,INSERT,UPDATE,DELETE') AS pairing_access,
              has_table_privilege(current_user,'annha_private.notification_secrets','INSERT,UPDATE') AS destination_access''').fetchone()
            if not permissions['pairings'] or not permissions['polling_state'] or not permissions['pairing_access'] or not permissions['destination_access']:
                logger.warning('Telegram webhook setup skipped: pairing migration or worker permissions are incomplete')
                return False
            # Share the poller's transaction lock so a deployment mode switch
            # cannot call setWebhook while a long-poll request is in flight.
            conn.execute("SELECT set_config('statement_timeout','60000',true)")
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(bot_ref.hex(),))
            target=public_url.rstrip('/')+'/api/integrations/telegram/webhook'
            current=_telegram_api_json('getWebhookInfo') or {}
            current_url=current.get('url') or ''
            if current_url and current_url!=target and os.getenv('TELEGRAM_WEBHOOK_REPLACE_EXISTING','false').lower()!='true':
                logger.warning('Telegram webhook setup skipped: this bot already points to another webhook')
                return False
            _telegram_api_json('setWebhook',{'url':target,'secret_token':telegram_webhook_secret(),
                'allowed_updates':['message'],'max_connections':40,'drop_pending_updates':False})
        telegram_webhook_ready=True
        return True
    except Exception as error:
        logger.warning('Telegram webhook setup failed (%s); pairing remains unavailable',type(error).__name__)
        return False

def _process_telegram_pairing_update(conn,update):
    """Consume a one-time token inside the current worker transaction."""
    parsed=parse_telegram_pairing_update(update)
    if not parsed: return 'ignored'
    token_hash=digest(parsed['token'])
    found=conn.execute('SELECT home_id FROM annha_private.telegram_pairings WHERE token_hash=%s',(token_hash,)).fetchone()
    if not found: return 'ignored'
    home=str(found['home_id'])
    conn.execute("SELECT set_config('app.home_id',%s,true)",(home,))
    pair=conn.execute('SELECT * FROM annha_private.telegram_pairings WHERE token_hash=%s AND home_id=%s FOR UPDATE',(token_hash,home)).fetchone()
    if not pair: return 'ignored'
    if pair['completed_at'] is not None: return 'duplicate'
    if pair['revoked_at'] is not None or pair['expires_at']<=db.now(): return 'expired'
    duplicate=conn.execute('SELECT 1 FROM annha_private.telegram_pairings WHERE provider_update_id=%s',(parsed['update_id'],)).fetchone()
    if duplicate: return 'duplicate'
    recipient=conn.execute('''SELECT m.role,u.disabled_at,u.deleted_at FROM annha_private.home_memberships m
      JOIN annha_private.users u ON u.id=m.user_id WHERE m.home_id=%s AND m.user_id=%s AND m.revoked_at IS NULL''',
      (home,pair['recipient_user_id'])).fetchone()
    channel=conn.execute('''SELECT c.id FROM annha.notification_channels c JOIN annha.homes h ON h.id=c.home_id
      WHERE c.id=%s AND c.home_id=%s AND c.recipient_user_id=%s AND c.kind='telegram'
        AND c.revoked_at IS NULL AND h.archived_at IS NULL''',
      (pair['channel_id'],home,pair['recipient_user_id'])).fetchone()
    if not recipient or recipient['role'] not in ('owner','caregiver') or recipient['disabled_at'] or recipient['deleted_at'] or not channel:
        conn.execute('UPDATE annha_private.telegram_pairings SET revoked_at=now() WHERE id=%s',(pair['id'],))
        return 'revoked'
    conn.execute('''INSERT INTO annha_private.notification_secrets(home_id,channel_id,destination_ciphertext,key_id)
      VALUES(%s,%s,%s,%s) ON CONFLICT(channel_id) DO UPDATE SET destination_ciphertext=excluded.destination_ciphertext,key_id=excluded.key_id''',
      (home,pair['channel_id'],encrypt({'chat_id':parsed['chat_id']}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary')))
    changed=conn.execute('''UPDATE annha_private.telegram_pairings SET completed_at=now(),provider_update_id=%s
      WHERE id=%s AND completed_at IS NULL AND revoked_at IS NULL AND expires_at>now() RETURNING id''',
      (parsed['update_id'],pair['id']))
    if not changed.fetchone(): raise RuntimeError('pairing_state_changed')
    db.audit(conn,home,None,'notification.telegram_pairing.complete',pair['recipient_user_id'])
    return 'linked'

def process_telegram_pairing_update(update,conn=None):
    """Atomically consume a one-time token and store the recipient's encrypted chat ID."""
    if conn is not None: return _process_telegram_pairing_update(conn,update)
    with db.connect('worker') as worker_conn:
        return _process_telegram_pairing_update(worker_conn,update)

class TelegramPollingError(RuntimeError):
    def __init__(self,code,retry_after=None):
        self.code=code;self.retry_after=retry_after
        super().__init__(code)

def telegram_poll_api(method,payload=None,timeout=5):
    """Telegram API call for polling; never includes the token in errors or logs."""
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise TelegramPollingError('not_configured')
    data=json.dumps(payload).encode() if payload is not None else None
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,data=data,
        headers={'Content-Type':'application/json'} if data is not None else {})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            result=json.load(response)
    except urllib.error.HTTPError as error:
        retry_after=None
        try:
            body=json.loads(error.read())
            retry_after=(body.get('parameters') or {}).get('retry_after')
        except (ValueError,AttributeError):
            pass
        if error.code==429:
            try: retry_after=max(1,int(retry_after or error.headers.get('Retry-After','1')))
            except (TypeError,ValueError,AttributeError): retry_after=1
            raise TelegramPollingError('rate_limited',retry_after) from None
        if error.code==409: raise TelegramPollingError('another_consumer') from None
        raise TelegramPollingError('provider_unavailable') from None
    except (TimeoutError,urllib.error.URLError,ConnectionError,OSError):
        raise TelegramPollingError('network_unavailable') from None
    except Exception:
        raise TelegramPollingError('invalid_provider_response') from None
    if not isinstance(result,dict) or not result.get('ok'):
        code=result.get('error_code') if isinstance(result,dict) else None
        retry_after=(result.get('parameters') or {}).get('retry_after') if isinstance(result,dict) else None
        if code==429:
            try: retry_after=max(1,int(retry_after or 1))
            except (TypeError,ValueError): retry_after=1
            raise TelegramPollingError('rate_limited',retry_after)
        if code==409: raise TelegramPollingError('another_consumer')
        raise TelegramPollingError('provider_rejected')
    return result.get('result')

class TelegramDeliveryError(RuntimeError):
    def __init__(self,code,retry_after=None,ambiguous=False):
        self.code=code;self.retry_after=retry_after;self.ambiguous=ambiguous
        super().__init__(code)

def telegram_error_message(code):
    return {'TelegramNotConfigured':'Bot Telegram chưa được cấu hình trên máy chủ.',
      'TelegramRateLimited':'Telegram đang giới hạn yêu cầu. Hệ thống sẽ thử lại sau.',
      'TelegramTimedOut':'Chưa rõ Telegram đã nhận tin hay chưa. Kiểm tra lịch sử trước khi thử gửi lại.',
      'TelegramRejected':'Telegram từ chối yêu cầu. Kiểm tra bot, người nhận và định dạng ảnh.',
      'TelegramPhotoRejected':'Ảnh không được Telegram chấp nhận; hệ thống đã chuyển sang gửi nội dung chữ.',
      'TelegramProviderUnavailable':'Telegram tạm thời không phản hồi.'}.get(code,'Không thể gửi thông báo Telegram.')

def _telegram_response(payload):
    if not payload.get('ok'):
        code=int(payload.get('error_code') or 0);parameters=payload.get('parameters') or {}
        if code==429:
            raise TelegramDeliveryError('TelegramRateLimited',max(1,int(parameters.get('retry_after',60))))
        if code>=500: raise TelegramDeliveryError('TelegramProviderUnavailable',ambiguous=True)
        raise TelegramDeliveryError('TelegramRejected')
    result=payload.get('result') or {}
    return str(result.get('message_id','')) or None

def send_telegram_text(chat_id,text):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise TelegramDeliveryError('TelegramNotConfigured')
    data=json.dumps({'chat_id':str(chat_id),'text':text},ensure_ascii=False).encode('utf-8')
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=data,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=10) as response: return _telegram_response(json.load(response))
    except urllib.error.HTTPError as error:
        try:
            payload=json.loads(error.read())
            _telegram_response(payload)
        except TelegramDeliveryError: raise
        except Exception: pass
        if error.code==429:
            try: wait=max(1,int(error.headers.get('Retry-After','60')))
            except (TypeError,ValueError): wait=60
            raise TelegramDeliveryError('TelegramRateLimited',wait) from None
        if error.code>=500: raise TelegramDeliveryError('TelegramProviderUnavailable',ambiguous=True) from None
        raise TelegramDeliveryError('TelegramRejected') from None
    except (TimeoutError,urllib.error.URLError,ConnectionError,OSError):
        raise TelegramDeliveryError('TelegramTimedOut',ambiguous=True) from None
    except TelegramDeliveryError: raise
    except Exception:
        raise TelegramDeliveryError('TelegramProviderUnavailable',ambiguous=True) from None

def send_telegram_photo(chat_id,caption,mime_type,photo):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise TelegramDeliveryError('TelegramNotConfigured')
    if mime_type not in ('image/jpeg','image/png') or not photo or len(photo)>10*1024*1024:
        raise TelegramDeliveryError('TelegramPhotoRejected')
    boundary='AnNha'+secrets.token_hex(16)
    body=[]
    for key,value in (('chat_id',str(chat_id)),('caption',caption[:1024])):
        body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    ext='.jpg' if mime_type=='image/jpeg' else '.png'
    body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="evidence{ext}"\r\nContent-Type: {mime_type}\r\n\r\n'.encode())
    body.extend((photo,f'\r\n--{boundary}--\r\n'.encode()))
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendPhoto',data=b''.join(body),headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
    try:
        with urllib.request.urlopen(request,timeout=15) as response: return _telegram_response(json.load(response))
    except urllib.error.HTTPError as error:
        try:
            payload=json.loads(error.read());_telegram_response(payload)
        except TelegramDeliveryError as provider_error:
            if provider_error.code=='TelegramRejected':
                raise TelegramDeliveryError('TelegramPhotoRejected') from None
            raise
        except Exception: pass
        if error.code==429:
            try: wait=max(1,int(error.headers.get('Retry-After','60')))
            except (TypeError,ValueError): wait=60
            raise TelegramDeliveryError('TelegramRateLimited',wait) from None
        if error.code>=500: raise TelegramDeliveryError('TelegramProviderUnavailable',ambiguous=True) from None
        raise TelegramDeliveryError('TelegramPhotoRejected') from None
    except (TimeoutError,urllib.error.URLError,ConnectionError,OSError):
        raise TelegramDeliveryError('TelegramTimedOut',ambiguous=True) from None
    except TelegramDeliveryError: raise
    except Exception:
        raise TelegramDeliveryError('TelegramProviderUnavailable',ambiguous=True) from None

def telegram_destination_ref(chat_id):
    """Telegram message IDs are unique per chat, so keep a keyed, non-reversible chat scope."""
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: return 'telegram-chat:unconfigured'
    digest=hmac.new(token.encode(),str(chat_id).encode(),hashlib.sha256).hexdigest()
    return 'telegram-chat:'+digest

def _telegram_clean(value,limit=2000):
    text=''.join(ch for ch in str(value or '') if ch in '\n\t' or ord(ch)>=32).strip()
    return text[:limit]

def format_telegram_event(home,event):
    from zoneinfo import ZoneInfo
    kind_names={'fall':'Nghi ngờ té ngã','immobility':'Bất động kéo dài','environment':'Môi trường bất thường','device':'Lỗi giám sát'}
    severity_names={'critical':'Nghiêm trọng','warning':'Trung bình','info':'Thông tin'}
    try: stamp=event['first_observed_at'].astimezone(ZoneInfo(home['timezone']))
    except Exception: stamp=event['first_observed_at'].astimezone(timezone.utc)
    location=' · '.join(value for value in (event.get('room_name'),event.get('camera_name')) if value)
    reason=_telegram_clean(event.get('reason'),1500)
    url=os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')+'/#/event/'+str(event['id'])
    body='\n'.join(part for part in (
      '🚨 AnNhà · Cảnh báo trong gia đình',
      'Nhà: '+_telegram_clean(home['name'],120),
      'Vị trí: '+_telegram_clean(location or event.get('camera_name') or 'Camera',180),
      'Sự kiện: '+kind_names.get(event['kind'],'Cảnh báo')+' · '+severity_names.get(event['severity'],'Chưa rõ mức độ'),
      'Thời điểm: '+stamp.strftime('%d/%m/%Y %H:%M:%S'),
      ('Chi tiết: '+reason) if reason else '',
      'Mở sự kiện: '+url,
      'Yêu cầu gửi đã được tiếp nhận; đây không xác nhận người nhận đã đọc.'
    ) if part)
    return body[:4096]

def format_telegram_caption(home,event):
    """Short photo caption that retains the event link within Telegram's limit."""
    from zoneinfo import ZoneInfo
    kind_names={'fall':'Nghi ngờ té ngã','immobility':'Bất động kéo dài','environment':'Môi trường bất thường','device':'Lỗi giám sát'}
    severity_names={'critical':'Nghiêm trọng','warning':'Trung bình','info':'Thông tin'}
    try: stamp=event['first_observed_at'].astimezone(ZoneInfo(home['timezone']))
    except Exception: stamp=event['first_observed_at'].astimezone(timezone.utc)
    location=' · '.join(value for value in (event.get('room_name'),event.get('camera_name')) if value)
    url=os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')+'/#/event/'+str(event['id'])
    reason=_telegram_clean(event.get('reason'),180)
    parts=['🚨 AnNhà · '+_telegram_clean(home['name'],100),
      'Vị trí: '+_telegram_clean(location or event.get('camera_name') or 'Camera',120),
      kind_names.get(event['kind'],'Cảnh báo')+' · '+severity_names.get(event['severity'],'Chưa rõ mức độ'),
      stamp.strftime('%d/%m/%Y %H:%M:%S')]
    if reason: parts.append(reason)
    parts.append(url)
    caption='\n'.join(parts)
    if len(caption)>1024:
        parts[-2:]=[url]
        caption='\n'.join(parts)
    return caption[:1024]

def format_safety_email(event,recipient_name):
    from zoneinfo import ZoneInfo
    kind_names={'fall':'Nghi ngờ té ngã','immobility':'Bất động kéo dài','environment':'Môi trường bất thường','device':'Lỗi giám sát'}
    severity_names={'critical':'Nghiêm trọng','warning':'Trung bình','info':'Thông tin'}
    try: stamp=event['first_observed_at'].astimezone(ZoneInfo(event['timezone']))
    except Exception: stamp=event['first_observed_at'].astimezone(timezone.utc)
    return render_email('safety_alert',public_url=os.getenv('PUBLIC_URL','http://localhost:8188'),
        recipient_name=recipient_name,home_name=event.get('home_name'),room_name=event.get('room_name'),
        camera_name=event.get('camera_name'),severity_label=severity_names.get(event.get('severity'),'Chưa rõ mức độ'),
        event_label=kind_names.get(event.get('kind'),'Cảnh báo'),occurred_at=stamp.strftime('%d/%m/%Y %H:%M:%S'),
        event_id=event.get('id'))

def _read_notification_image(row):
    from .media_storage import MediaNotFound,MediaUnavailable
    if row['status']!='ready' or (row['expires_at'] and row['expires_at']<=db.now()): return None,'missing'
    if row['mime_type'] not in ('image/jpeg','image/png') or int(row['size_bytes'] or 0)>10*1024*1024: return None,'unavailable'
    width,height=row.get('width'),row.get('height')
    if width and height and (int(width)+int(height)>10000 or max(width,height)/max(1,min(width,height))>20): return None,'unavailable'
    try:
        if row['provider']=='local':
            data=media_storage.LocalStorage(db.MEDIA_ROOT).path_for(row).read_bytes()
        elif row['provider']=='cloudinary':
            try:
                response=media_storage.provider_for_asset(row,db.MEDIA_ROOT).open_read(row)
                try: data=response.read(10*1024*1024+1)
                finally: response.close()
            except MediaUnavailable:
                # Keep the private local original as an outage fallback; never create a public URL.
                data=media_storage.LocalStorage(db.MEDIA_ROOT).path_for(row).read_bytes()
        else: return None,'unavailable'
    except MediaNotFound: return None,'missing'
    except MediaUnavailable: return None,'unavailable'
    except Exception: return None,'unavailable'
    if len(data)>10*1024*1024: return None,'unavailable'
    expected=b'\xff\xd8\xff' if row['mime_type']=='image/jpeg' else b'\x89PNG\r\n\x1a\n'
    if not data.startswith(expected): return None,'unavailable'
    return data,'sent'

def schedule_notification_reminders(home):
    with db.connect('worker',home) as conn:
        due=conn.execute('''SELECT d.id,d.event_id,d.camera_id,d.channel_id,d.generation,d.reminder_number,d.email_version,
          COALESCE(d.last_dispatch_at,d.accepted_at) AS anchor_at
          FROM annha.notification_deliveries d
          JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id
          JOIN annha.notification_channels c ON c.id=d.channel_id AND c.home_id=d.home_id
          JOIN annha.home_settings s ON s.home_id=d.home_id
          WHERE d.home_id=%s AND d.dispatch_kind IN ('initial','reminder') AND d.status IN ('accepted','unknown')
           AND d.reminder_number<s.notification_max_reminders AND COALESCE(d.last_dispatch_at,d.accepted_at) IS NOT NULL
           AND COALESCE(d.last_dispatch_at,d.accepted_at)+s.notification_reminder_interval_seconds*interval '1 second'<=now()
           AND annha_private.can_schedule_notification_reminder(d.id)
           AND NOT EXISTS(SELECT 1 FROM annha.notification_deliveries newer WHERE newer.event_id=d.event_id
             AND newer.channel_id=d.channel_id AND newer.generation>d.generation)
          ORDER BY anchor_at LIMIT 100''',(home,)).fetchall()
        for row in due:
            conn.execute('''INSERT INTO annha.notification_deliveries(home_id,camera_id,event_id,channel_id,generation,
              dispatch_kind,reminder_number,email_version)
          VALUES(%s,%s,%s,%s,%s,'reminder',%s,%s) ON CONFLICT(event_id,channel_id,generation) DO NOTHING''',
              (home,row['camera_id'],row['event_id'],row['channel_id'],row['generation']+1,row['reminder_number']+1,row['email_version']))

def process_notifications(home_id=None,delivery_id=None):
    if delivery_id and not home_id: raise ValueError('Targeted delivery requires a home')
    if home_id: homes=[str(home_id)]
    else:
        with db.connect('auth') as conn: homes=[str(r['id']) for r in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
    for home in homes:
        if not delivery_id: schedule_notification_reminders(home)
        with db.connect('worker',home) as conn:
            job=conn.execute("SELECT * FROM annha.notification_deliveries WHERE status='pending' AND next_attempt_at<=now() AND (%s::uuid IS NULL OR id=%s::uuid) ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1",(delivery_id,delivery_id)).fetchone()
            if not job: continue
            allowed=conn.execute('SELECT annha_private.can_dispatch_notification(%s) AS ok',(job['id'],)).fetchone()['ok']
            if not allowed:
                conn.execute("UPDATE annha.notification_deliveries SET status='cancelled',last_error_code='NotEligible' WHERE id=%s",(job['id'],));continue
            channel=conn.execute('SELECT * FROM annha.notification_channels WHERE id=%s',(job['channel_id'],)).fetchone()
            event=conn.execute('''SELECT e.*,c.name AS camera_name,r.name AS room_name,h.name AS home_name,h.timezone
              FROM annha.events e JOIN annha.cameras c ON c.id=e.camera_id AND c.home_id=e.home_id
              LEFT JOIN annha.rooms r ON r.id=c.room_id AND r.home_id=e.home_id
              JOIN annha.homes h ON h.id=e.home_id WHERE e.id=%s AND e.home_id=%s''',(job['event_id'],home)).fetchone()
            destination=conn.execute('SELECT destination_ciphertext FROM annha_private.notification_secrets WHERE home_id=%s AND channel_id=%s',(home,channel['id'])).fetchone() if channel['kind']=='telegram' else None
            evidence=conn.execute('''SELECT * FROM annha.media_assets WHERE home_id=%s AND event_id=%s
              AND kind IN ('event_image','snapshot') AND mime_type IN ('image/jpeg','image/png') AND status='ready'
              AND upload_key<>'demo:snapshot' AND (expires_at IS NULL OR expires_at>now())
              ORDER BY created_at DESC,id DESC LIMIT 1''',(home,job['event_id'])).fetchone() if channel['kind']=='telegram' and channel['allow_media'] else None
            conn.execute("UPDATE annha.notification_deliveries SET status='sending',attempt_count=attempt_count+1,next_attempt_at=now()+interval '2 minutes',last_dispatch_at=now() WHERE id=%s",(job['id'],))
        message=format_telegram_event({'name':event['home_name'],'timezone':event['timezone']},event)
        state='accepted';error=None;provider_id=None;media_result='not_requested';retry_after=None;provider_account_ref='default'
        try:
            if channel['kind']=='email':
                if os.getenv('EMAIL_ALERTS_ENABLED','false').lower()!='true': raise RuntimeError('EmailProviderDisabled')
                with db.connect('auth') as conn: recipient=conn.execute('SELECT email,name,email_version FROM annha_private.users WHERE id=%s AND disabled_at IS NULL AND deleted_at IS NULL',(channel['recipient_user_id'],)).fetchone()
                if not recipient or recipient['email_version']!=job['email_version']: raise RuntimeError('StaleEmail')
                with db.connect('worker',home) as conn:
                    if not conn.execute('SELECT annha_private.can_dispatch_notification(%s) AS ok',(job['id'],)).fetchone()['ok']: raise RuntimeError('NotEligible')
                rendered=format_safety_email(event,recipient['name'])
                send_mail(recipient['email'],rendered.subject,rendered.text,rendered.html)
            else:
                if not destination or not os.getenv('TELEGRAM_BOT_TOKEN','').strip(): raise TelegramDeliveryError('TelegramNotConfigured')
                chat_id=decrypt(destination['destination_ciphertext'])['chat_id']
                photo=None
                if channel['allow_media']:
                    if not evidence: media_result='missing'
                    else: photo,media_result=_read_notification_image(evidence)
                else: media_result='consent_disabled'
                with db.connect('worker',home) as conn:
                    if not conn.execute('SELECT annha_private.can_dispatch_notification(%s) AS ok',(job['id'],)).fetchone()['ok']: raise RuntimeError('NotEligible')
                    latest=conn.execute('''SELECT c.allow_media,s.destination_ciphertext FROM annha.notification_channels c
                      LEFT JOIN annha_private.notification_secrets s ON s.home_id=c.home_id AND s.channel_id=c.id
                      WHERE c.home_id=%s AND c.id=%s AND c.enabled AND c.revoked_at IS NULL''',(home,channel['id'])).fetchone()
                    if not latest: raise RuntimeError('NotEligible')
                    if not latest['destination_ciphertext']: raise TelegramDeliveryError('TelegramNotConfigured')
                    chat_id=decrypt(latest['destination_ciphertext'])['chat_id']
                    provider_account_ref=telegram_destination_ref(chat_id)
                    if not latest['allow_media']:
                        photo=None;media_result='consent_disabled'
                if photo:
                    try: provider_id=send_telegram_photo(chat_id,format_telegram_caption({'name':event['home_name'],'timezone':event['timezone']},event),evidence['mime_type'],photo)
                    except TelegramDeliveryError as photo_error:
                        if photo_error.code!='TelegramPhotoRejected': raise
                        provider_id=send_telegram_text(chat_id,message);media_result='text_fallback'
                else:
                    provider_id=send_telegram_text(chat_id,message)
        except TelegramDeliveryError as exc:
            state='unknown' if exc.ambiguous else ('pending' if exc.retry_after is not None else 'failed');error=exc.code;retry_after=exc.retry_after
        except Exception as exc:
            error=type(exc).__name__ if type(exc).__name__ in ('TimeoutError','SMTPException','StaleEmail','EmailProviderDisabled','NotEligible') else 'ProviderError'
            if channel['kind']=='email' and error not in ('StaleEmail','EmailProviderDisabled','NotEligible'):
                state='pending'
                retry_after=min(300,10*2**min(5,job['attempt_count']+1))
            else: state='failed'
        with db.connect('worker',home) as conn:
            count=job['attempt_count']+1
            if error=='NotEligible': state='cancelled'
            if retry_after is not None and count>=5: state='failed';retry_after=None
            receipt_status=state if state in ('accepted','failed','unknown') else 'failed'
            conn.execute('INSERT INTO annha.delivery_attempts(home_id,delivery_id,attempt,status,provider,provider_account_ref,provider_message_id,error_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                (home,job['id'],count,receipt_status,'smtp' if channel['kind']=='email' else 'telegram',provider_account_ref,provider_id,error))
            due=timedelta(seconds=max(1,min(86400,int(retry_after)))) if retry_after is not None else timedelta(0)
            conn.execute('''UPDATE annha.notification_deliveries SET status=%s,last_error_code=%s,sent_count=sent_count+%s,
               accepted_at=CASE WHEN %s THEN now() ELSE accepted_at END,next_attempt_at=now()+%s,media_result=%s WHERE id=%s''',
                (state,error,1 if state=='accepted' else 0,state=='accepted',due,media_result,job['id']))

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
            for asset in conn.execute("""SELECT * FROM annha.media_assets a WHERE a.status='ready'
                AND a.expires_at IS NOT NULL AND a.expires_at<now()
                AND NOT EXISTS (SELECT 1 FROM annha.reminder_revisions v JOIN annha.reminders r
                    ON r.id=v.reminder_id AND r.current_version=v.version AND r.deleted_at IS NULL
                    WHERE v.asset_id=a.id)
                FOR UPDATE OF a""").fetchall():
                conn.execute("UPDATE annha.media_assets SET status='deleting',deletion_requested_at=now() WHERE id=%s",(asset['id'],))
                conn.execute('''INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,idempotency_key)
                    VALUES(%s,'delete_media',%s,%s,%s) ON CONFLICT(idempotency_key) DO UPDATE
                    SET status='pending',available_at=now(),lease_until=NULL,last_error_code=NULL''',
                    (home,asset['id'],db.J({'target_status':'expired'}),'media-expire:'+str(asset['id'])))
            for asset in conn.execute("""SELECT * FROM annha.media_assets a WHERE a.status='failed'
                AND a.error_code='UploadFailed' AND a.kind<>'tts'
                AND a.created_at<now()-interval '7 days'
                FOR UPDATE OF a""").fetchall():
                conn.execute("UPDATE annha.media_assets SET status='deleting',deletion_requested_at=now() WHERE id=%s",(asset['id'],))
                conn.execute('''INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,idempotency_key)
                    VALUES(%s,'delete_media',%s,%s,%s) ON CONFLICT(idempotency_key) DO UPDATE
                    SET status='pending',available_at=now(),lease_until=NULL,last_error_code=NULL''',
                    (home,asset['id'],db.J({'target_status':'expired'}),'media-failed-upload-expire:'+str(asset['id'])))
            conn.execute('DELETE FROM annha.telemetry_batches WHERE received_at<now()-(SELECT telemetry_retention_days FROM annha.home_settings WHERE home_id=%s)*interval \'1 day\'',(home,))
        for camera,payload in emissions:
            event,changed=ingest_event(camera,payload)
            if changed: pending_broadcasts.append(event)
    try:
        reconcile_media_if_due(homes)
    except Exception as error:
        import logging
        logging.getLogger(__name__).warning('Media reconciliation failed: %s',type(error).__name__)

def reconcile_media_if_due(homes=None,force=False):
    """Daily read-only reconciliation with its result saved per home for the owner UI."""
    from . import media_migration
    if not media_storage.cloudinary_configured(): return None
    if homes is None:
        with db.connect('auth') as conn:
            homes=[str(row['id']) for row in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
    if not homes: return None
    cutoff=db.now()-timedelta(hours=24)
    due=force
    for home in homes:
        with db.connect('worker',home) as conn:
            last=conn.execute("SELECT max(created_at) AS checked_at FROM annha.audit_logs WHERE action='media.reconcile'").fetchone()['checked_at']
        if not last or last<cutoff:
            due=True;break
    if not due: return None
    report=media_migration.inventory(db.MEDIA_ROOT)
    for home in homes:
        with db.connect('worker',home) as conn:
            conn.execute('''INSERT INTO annha.audit_logs(home_id,actor_type,action,target_type,target_id,details)
                VALUES(%s,'system','media.reconcile','home',%s,%s)''',(home,home,db.J(report)))
    return report

async def close_home_connections(home):
    for socket,(_,tenant) in tuple(connections.items()):
        if str(tenant)==str(home):
            connections.pop(socket,None)
            with suppress(Exception): await socket.close(code=1008)
    await revalidate_connections()

async def _worker_loop(name,operation,interval,kinds=None):
    import logging
    while True:
        try:
            if kinds is not None:
                await asyncio.to_thread(process_job,None,kinds)
            else:
                await asyncio.to_thread(operation)
        except Exception as error:
            logging.getLogger(__name__).warning('PostgreSQL %s worker operation failed: %s',name,type(error).__name__)
        await asyncio.sleep(interval)

async def _maintenance_loop():
    import logging
    last=0
    while True:
        try:
            if time.monotonic()-last>=15:
                await asyncio.to_thread(maintenance);last=time.monotonic()
            while pending_broadcasts: await broadcast(pending_broadcasts.pop(0))
            await revalidate_connections()
        except Exception as error:
            logging.getLogger(__name__).warning('PostgreSQL maintenance worker operation failed: %s',type(error).__name__)
        await asyncio.sleep(2)

async def worker():
    tasks=[asyncio.create_task(_worker_loop('TTS',process_job,0.5,['tts'])),
           asyncio.create_task(_worker_loop('jobs',process_job,1,['email','compile_config','upload','delete_media'])),
           asyncio.create_task(_worker_loop('notifications',process_notifications,2)),
           asyncio.create_task(_maintenance_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
