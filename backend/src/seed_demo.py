"""Idempotent, explicitly invoked demo seed; preserves all non-demo rows and passwords.
Run after migrations with DATABASE_BACKEND=postgres. No external notifications.
Credentials are written to a private file, never printed. Fixture identity is internal; presentation names use ordinary labels.
"""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import uuid
import wave
import math
from . import pgdb as db,pgservices as svc,models
from .pgsecurity import password_hash,digest

def ident(key): return str(uuid.uuid5(uuid.NAMESPACE_URL,'annha/demo/v1/'+key))
def save_credentials(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream: json.dump(data,stream,ensure_ascii=False,indent=2)
    temp.replace(path);path.chmod(0o600)

def seed(output):
    path=Path(output);credentials=json.loads(path.read_text()) if path.exists() else {'accounts':[],'devices':[]}
    users={};homes={};cameras=[]
    for role,name in [('owner','Chủ nhà'),('caregiver','Người chăm sóc'),('viewer','Người xem'),('outsider','Chủ nhà B')]:
        email=role+'@demo.annha.test';uid=ident('user/'+role)
        prior=next((a for a in credentials['accounts'] if a['email']==email),None)
        password=prior['password'] if prior else secrets.token_urlsafe(15)
        with db.connect('auth') as conn:
            old=conn.execute('SELECT id FROM annha_private.users WHERE email=%s',(email,)).fetchone()
            if old and not prior: raise RuntimeError('Existing demo account requires its original private credential file; refusing to invent a password.')
            if old and str(old['id'])!=uid: raise RuntimeError('Demo email belongs to another account; seed stopped.')
            if not prior:
                credentials['accounts'].append({'email':email,'password':password,'role':role,'name':name});save_credentials(path,credentials)
            conn.execute('INSERT INTO annha_private.users(id,email,name,password_hash,email_verified_at) VALUES(%s,%s,%s,%s,now()) ON CONFLICT(id) DO NOTHING',(uid,email,name,password_hash(password)))
        users[role]=uid
    for key,title,owner in [('a','Nhà AnNhà','owner'),('b','Nhà Bình An','outsider')]:
        home=ident('home/'+key);homes[key]=home
        with db.connect('auth',home,users[owner]) as conn:
            conn.execute('INSERT INTO annha.homes(id,name,created_by) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(home,title,users[owner]))
            conn.execute("INSERT INTO annha_private.home_memberships(home_id,user_id,role,granted_by) VALUES(%s,%s,'owner',%s) ON CONFLICT DO NOTHING",(home,users[owner],users[owner]))
            conn.execute('INSERT INTO annha.home_settings(home_id) VALUES(%s) ON CONFLICT DO NOTHING',(home,))
            conn.execute('INSERT INTO annha.home_storage(home_id) VALUES(%s) ON CONFLICT DO NOTHING',(home,))
            for suffix,room_name in [('living','Phòng khách'),('bedroom','Phòng ngủ'),('entrance','Cửa chính'),('yard','Sân sau')]:
                room=ident('room/'+key+'/'+suffix);cam=ident('camera/'+key+'/'+suffix);device=ident('device/'+key+'/'+suffix)
                conn.execute('INSERT INTO annha.rooms(id,home_id,name) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(room,home,room_name))
                conn.execute('INSERT INTO annha_private.device_registry(id,model) VALUES(%s,%s) ON CONFLICT DO NOTHING',(device,'DEMO simulated camera'))
                conn.execute('INSERT INTO annha.cameras(id,home_id,room_id,device_id,name,capabilities) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(cam,home,room,device,room_name,db.J({'camera':True,'speaker':True,'sensors':True})))
                if not conn.execute('SELECT 1 FROM annha_private.device_credentials WHERE device_id=%s',(device,)).fetchone():
                    existing=next((d for d in credentials['devices'] if d['camera_id']==cam),None)
                    token=existing['device_token'] if existing else secrets.token_urlsafe(40)
                    if not existing:
                        credentials['devices'].append({'camera_id':cam,'device_token':token,'name':room_name});save_credentials(path,credentials)
                    conn.execute('INSERT INTO annha_private.device_credentials(device_id,camera_id,token_hash) VALUES(%s,%s,%s)',(device,cam,digest(token)))
                cameras.append({'id':cam,'home_id':home,'owner':users[owner],'name':room_name})
    with db.connect('auth',homes['a'],users['owner']) as conn:
        for role in ('caregiver','viewer'):
            conn.execute('INSERT INTO annha_private.home_memberships(home_id,user_id,role,granted_by) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(homes['a'],users[role],role,users['owner']))
            for camera in [c for c in cameras if c['home_id']==homes['a']] if role=='caregiver' else cameras[:1]:
                conn.execute('INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_view,can_handle_events,can_play_audio,can_edit_reminders) VALUES(%s,%s,%s,true,%s,%s,%s) ON CONFLICT DO NOTHING',(homes['a'],camera['id'],users[role],role=='caregiver',role=='caregiver',role=='caregiver'))
    for camera in cameras:
        home=camera['home_id'];cam=camera['id'];svc.compile_config(home,cam)
        for kind in ('audio',):
            asset=ident('asset/'+cam+'/'+kind);file=db.MEDIA_ROOT/(asset+('.png' if kind=='snapshot' else '.wav'))
            with db.connect('worker',home) as conn:
                if conn.execute('SELECT id FROM annha.media_assets WHERE id=%s',(asset,)).fetchone(): continue
                with wave.open(str(file),'wb') as audio:
                    audio.setparams((1,2,16000,0,'NONE','not compressed'))
                    audio.writeframes(b''.join(struct.pack('<h',int(7000*math.sin(i*2*math.pi*523.25/16000)*(1-i/16000))) for i in range(16000)))
                size=file.stat().st_size
                conn.execute('UPDATE annha.home_storage SET used_bytes=used_bytes+%s WHERE home_id=%s',(size,home))
                conn.execute("INSERT INTO annha.media_assets(id,home_id,camera_id,kind,name,mime_type,size_bytes,status,provider,local_object_key,upload_key,ready_at,created_by,sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,'ready','local',%s,%s,now(),%s,%s)",(asset,home,cam,kind,('Minh hoạ phòng' if kind=='snapshot' else 'Chuông thử loa'),'image/png' if kind=='snapshot' else 'audio/wav',size,file.name,'demo:'+kind,camera['owner'],hashlib.sha256(file.read_bytes()).digest()))
        for i,(kind,severity,observation) in enumerate([('fall','critical','suspected'),('immobility','warning','recovered'),('environment','warning','recovered')]):
            event,_=svc.ingest_event(camera,models.EventInput(event_id='demo:'+kind,kind=kind,severity=severity,observation=observation,observed_at=(db.now()-timedelta(hours=i+2)).isoformat(),reason={'fall':'Cần kiểm tra tư thế và tình trạng người trong phòng.','immobility':'Đã ghi nhận vận động trở lại trong khu vực theo dõi.','environment':'Các chỉ số môi trường đã trở lại ngưỡng cấu hình.'}[kind],confidence=.89 if kind=='fall' else None))
            if i:
                with db.connect('worker',home) as conn: conn.execute("UPDATE annha.events SET status='RESOLVED' WHERE id=%s AND status='OPEN'",(event['id'],))
        with db.connect('worker',home) as conn:
            for i in range(48):
                stamp=db.now()-timedelta(minutes=15*i)
                batch=conn.execute('INSERT INTO annha.telemetry_batches(id,home_id,camera_id,message_id,observed_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id',(ident('telemetry/'+cam+'/'+str(i)),home,cam,'demo-reading-'+str(i),stamp)).fetchone()
                if not batch: continue
                for metric,value,unit in [('temperature',27+2*math.sin(i/5),'C'),('humidity',65+8*math.sin(i/7),'%'),('gas',180+i%30,'ADC'),('light',200+i%60,'lux')]:
                    conn.execute("INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality) VALUES(%s,%s,%s,%s,%s,%s,'valid')",(home,cam,batch['id'],metric,round(value,1),unit))
            reminder=ident('reminder/'+cam)
            if not conn.execute('SELECT id FROM annha.reminders WHERE id=%s',(reminder,)).fetchone():
                conn.execute("INSERT INTO annha.reminders(id,home_id,camera_id,name,current_version,created_by) VALUES(%s,%s,%s,'Nhắc uống nước',1,%s)",(reminder,home,cam,camera['owner']))
                conn.execute("INSERT INTO annha.reminder_revisions(home_id,camera_id,reminder_id,version,local_time,source,asset_id) VALUES(%s,%s,%s,1,'09:00','audio',%s)",(home,cam,reminder,ident('asset/'+cam+'/audio')))
                conn.execute("INSERT INTO annha.reminder_executions(home_id,camera_id,reminder_id,reminder_version,occurrence_key,scheduled_at,executed_at,status,detail) VALUES(%s,%s,%s,1,'demo-occurrence',now()-interval '1 day',now()-interval '1 day','played','Đã ghi nhận phát theo lịch.')",(home,cam,reminder))
            if not conn.execute("SELECT id FROM annha.audit_logs WHERE action='demo.seed'").fetchone(): db.audit(conn,home,camera['owner'],'demo.seed',home)
        svc.compile_config(home,cam)
    save_credentials(path,credentials)
    print('Demo seed complete: 4 verified accounts, 2 homes, 4 rooms/cameras per home, 24 events, 384 telemetry batches, 8 reminders, local WAV media; UI uses original room artwork as labelled placeholders. Credentials saved privately.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='/app/data/demo-credentials.json');args=parser.parse_args()
    db.open_pools()
    try: seed(args.output)
    finally: db.close_pools()
