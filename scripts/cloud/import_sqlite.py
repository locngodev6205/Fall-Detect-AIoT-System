"""One-time atomic import of the preserved SQLite snapshot into an empty Neon app.
The source is read-only. Sessions/tokens are intentionally reissued by login/resend.
Unsupported active queue data causes refusal, never silent loss. Media stays local.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import ssl
import uuid
from dotenv import dotenv_values
import psycopg
from psycopg.types.json import Jsonb as J


def run(source,env):
    old=sqlite3.connect('file:'+str(Path(source).resolve())+'?mode=ro',uri=True);old.row_factory=sqlite3.Row
    rows=lambda name:[dict(r) for r in old.execute('SELECT * FROM '+name)]
    # This migration supports the current snapshot; refuse a newer unsupported state.
    for table in ('executions','commands','deliveries','invitations'):
        if rows(table): raise SystemExit('Import needs review for non-empty '+table+'; source is untouched.')
    settings=dotenv_values(env);url=settings.get('DATABASE_URL_UNPOOLED') or settings.get('DATABASE_URL')
    key=hashlib.sha256(Path(source).read_bytes()).hexdigest();now=datetime.now(timezone.utc)
    homes={r['id']:r for r in rows('homes')};cameras={r['id']:r for r in rows('cameras') if r['claimed']}
    owners={r['home_id']:r['user_id'] for r in rows('memberships') if r['role']=='owner'}
    if set(homes)!=set(owners): raise SystemExit('Every home must have exactly one owner before import.')
    with psycopg.connect(url,sslmode='verify-full',sslrootcert=ssl.get_default_verify_paths().cafile) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(817398204)')
        if conn.execute('SELECT 1 FROM annha_private.schema_migrations WHERE name=%s',('sqlite-import:'+key,)).fetchone(): print('Snapshot already imported; no changes.');return
        if conn.execute('SELECT 1 FROM annha_private.users LIMIT 1').fetchone(): raise SystemExit('Import requires empty application tables; no data changed.')
        for r in rows('users'):
            conn.execute('INSERT INTO annha_private.users(id,email,name,password_hash,email_verified_at,created_at) VALUES(%s,%s,%s,%s,%s,%s)',(r['id'],r['email'],r['name'],r['password'],now if r['verified'] else None,r['created_at']))
        for r in homes.values():
            conn.execute('INSERT INTO annha.homes(id,name,timezone,created_by) VALUES(%s,%s,%s,%s)',(r['id'],r['name'],r['timezone'],owners[r['id']]))
        for r in rows('memberships'):
            conn.execute('INSERT INTO annha_private.home_memberships(home_id,user_id,role,granted_by) VALUES(%s,%s,%s,%s)',(r['home_id'],r['user_id'],r['role'],owners[r['home_id']]))
        for r in homes.values():
            s=json.loads(r['settings']);cols=['retention_days','temperature_low','temperature_high','humidity_high','gas_high','gas_unit','environment_hold_seconds','hysteresis'];defaults=[14,16,35,85,700,'ADC',10,2]
            conn.execute('INSERT INTO annha.home_settings(home_id,'+','.join(cols)+') VALUES('+','.join(['%s']*9)+')',[r['id']]+[s.get(k,v) for k,v in zip(cols,defaults)])
            conn.execute('INSERT INTO annha.home_storage(home_id) VALUES(%s)',(r['id'],))
        for r in rows('rooms'): conn.execute('INSERT INTO annha.rooms(id,home_id,name) VALUES(%s,%s,%s)',(r['id'],r['home_id'],r['name']))
        for r in rows('cameras'):
            device=str(uuid.uuid5(uuid.NAMESPACE_URL,'annha/import/device/'+r['id']))
            conn.execute('INSERT INTO annha_private.device_registry(id,model) VALUES(%s,%s)',(device,'Imported SQLite device'))
            if r['claimed']:
                conn.execute('INSERT INTO annha.cameras(id,home_id,room_id,device_id,name,capabilities,observation,last_seen_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(r['id'],r['home_id'],r['room_id'],device,r['name'],J(json.loads(r['capabilities'])),r['observation'],r['last_seen']))
            conn.execute('INSERT INTO annha_private.device_credentials(device_id,camera_id,token_hash) VALUES(%s,%s,%s)',(device,r['id'] if r['claimed'] else None,bytes.fromhex(r['token_hash'])))
            if not r['claimed'] and r['pair_hash'] and r['pair_expires']>now.timestamp():
                conn.execute('INSERT INTO annha_private.pairing_codes(code_hash,device_id,created_at,expires_at) VALUES(%s,%s,%s,%s)',(bytes.fromhex(r['pair_hash']),device,now,datetime.fromtimestamp(r['pair_expires'],timezone.utc)))
        for r in rows('memberships'):
            rights=json.loads(r['rights'])
            for camera in json.loads(r['scopes']):
                if camera in cameras: conn.execute('INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_handle_events,can_play_audio,can_edit_reminders) VALUES(%s,%s,%s,%s,%s,%s)',(r['home_id'],camera,r['user_id'],r['role']=='caregiver',r['role']=='caregiver' and rights.get('audio',False),r['role']=='caregiver' and rights.get('schedules',False)))
        for r in rows('configurations'):
            cam=cameras[r['camera_id']];body=json.loads(r['payload']);body['zones']=[];body['reference']={}
            conn.execute('INSERT INTO annha.camera_configurations(home_id,camera_id,version,payload,created_at) VALUES(%s,%s,%s,%s,%s)',(cam['home_id'],cam['id'],r['version'],J(body),r['created_at']))
        for r in cameras.values():
            if r['desired_version']: conn.execute('INSERT INTO annha.camera_config_state(home_id,camera_id,desired_version,applied_version,error) VALUES(%s,%s,%s,%s,%s)',(r['home_id'],r['id'],r['desired_version'],r['applied_version'] or None,r['config_error']))
        for r in rows('events'):
            p=json.loads(r['payload'])
            conn.execute('INSERT INTO annha.events(id,home_id,camera_id,source_id,latest_sequence,kind,severity,observation,status,first_observed_at,last_observed_at,received_at,reason,duration_s,model_score,config_version) VALUES('+','.join(['%s']*16)+')',(r['id'],r['home_id'],r['camera_id'],r['source_id'],r['sequence'],r['kind'],r['severity'],r['observation'],r['status'],r['observed_at'],r['observed_at'],r['received_at'],p.get('reason',''),p.get('duration_s'),p.get('confidence'),p.get('config_version') or None))
            conn.execute('INSERT INTO annha.event_updates(home_id,camera_id,event_id,sequence,observed_at,observation,severity,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(r['home_id'],r['camera_id'],r['id'],r['sequence'],r['observed_at'],r['observation'],r['severity'],J(p)))
        for r in rows('actions'):
            event=next(e for e in rows('events') if e['id']==r['event_id'])
            conn.execute('INSERT INTO annha.event_actions(id,home_id,camera_id,event_id,user_id,action,note,confirmed_abnormal,silence_until,request_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s)',(r['id'],event['home_id'],event['camera_id'],r['event_id'],r['user_id'],r['action'],r['note'],now if r['action']=='silence' else None,r['id'],r['created_at']))
        for r in rows('assets'):
            kind='event_clip' if r['event_id'] and r['mime'].startswith('video/') else 'event_image' if r['event_id'] else 'audio' if r['mime'].startswith('audio/') else 'snapshot'
            if Path(r['path']).name!=r['path']: raise SystemExit('Invalid local media key; import aborted.')
            conn.execute("INSERT INTO annha.media_assets(id,home_id,camera_id,event_id,kind,name,mime_type,size_bytes,status,provider,local_object_key,upload_key,created_by,created_at,ready_at,error_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'local',%s,%s,%s,%s,%s,%s)",(r['id'],r['home_id'],r['camera_id'],r['event_id'],kind,r['name'],r['mime'],r['size'],r['status'] if r['status']!='pending' else 'processing',r['path'],'import:'+r['id'],owners[r['home_id']],r['created_at'],r['created_at'] if r['status']=='ready' else None,r['error']))
            if r['status']=='ready': conn.execute('UPDATE annha.home_storage SET used_bytes=used_bytes+%s WHERE home_id=%s',(r['size'],r['home_id']))
        for r in rows('reminders'):
            conn.execute('INSERT INTO annha.reminders(id,home_id,camera_id,name,enabled,current_version,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(r['id'],r['home_id'],r['camera_id'],r['name'],bool(r['enabled']),r['version'],owners[r['home_id']],r['created_at']))
            conn.execute('INSERT INTO annha.reminder_revisions(home_id,camera_id,reminder_id,version,local_time,timezone,weekdays,once_date,source,text_content,asset_id,volume,late_seconds) VALUES('+','.join(['%s']*13)+')',(r['home_id'],r['camera_id'],r['id'],r['version'],r['time'],r['timezone'],[] if r['once_date'] else json.loads(r['weekdays']),r['once_date'],r['source'],r['text'] or None,r['asset_id'],r['volume'],r['late_seconds']))
        for r in rows('telemetry'):
            home=cameras[r['camera_id']]['home_id'];p=json.loads(r['payload'])
            batch=conn.execute('INSERT INTO annha.telemetry_batches(home_id,camera_id,message_id,observed_at,received_at) VALUES(%s,%s,%s,%s,%s) RETURNING id',(home,r['camera_id'],r['message_id'],r['observed_at'],r['received_at'])).fetchone()[0]
            for metric,v in p['readings'].items(): conn.execute('INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality) VALUES(%s,%s,%s,%s,%s,%s,%s)',(home,r['camera_id'],batch,metric,v['value'],v['unit'],v['quality']))
        for r in rows('audit'):
            try: target=str(uuid.UUID(r['target']))
            except ValueError: target=None
            conn.execute("INSERT INTO annha.audit_logs(id,home_id,actor_type,user_id,action,target_type,target_id,created_at) VALUES(%s,%s,%s,%s,%s,'legacy',%s,%s)",(r['id'],r['home_id'],'system' if r['user_id']=='system' else 'user',None if r['user_id']=='system' else r['user_id'],r['action'],target,r['created_at']))
        conn.execute('INSERT INTO annha_private.schema_migrations(name,checksum) VALUES(%s,%s)',('sqlite-import:'+key,key))
    print('SQLite import committed: existing accounts/password hashes, homes, permissions, cameras/device hashes, configs, events, media references, reminders, telemetry and audit preserved. Sign in again; SQLite source unchanged.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--env',default='.env');a=p.parse_args();run(a.source,a.env)
