"""Authenticated business API; physical execution is acknowledged only by device APIs."""
from datetime import datetime, timezone
import json
import os
import secrets
import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from . import db, models as m, services as svc
from .security import COOKIE, SESSION_SECONDS, active_rights, camera_access, device, digest, membership, password_hash, password_matches, public_user, throttle, user

router=APIRouter(prefix='/api')
Current=Annotated[dict,Depends(user)]
Device=Annotated[dict,Depends(device)]


def client_key(request):
    return request.client.host if request.client else 'unknown'


def check_scopes(conn,home_id,scopes):
    available={r[0] for r in conn.execute('SELECT id FROM cameras WHERE home_id=? AND claimed=1',(home_id,))}
    if not set(scopes)<=available: raise HTTPException(422,'Phạm vi chứa camera không thuộc nhà.')


def close_sockets(home_id):
    # Any membership/permission change terminates current sessions on this home.
    return [(socket,token) for socket,(token,home) in tuple(svc.connections.items()) if home==home_id]


@router.post('/auth/register',status_code=201)
def register(payload:m.Register,request:Request):
    throttle('register:'+client_key(request),5,3600)
    user_id=db.uid()
    hashed=password_hash(payload.password)
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM users WHERE email=?',(payload.email,)).fetchone(): raise HTTPException(409,'Email đã được đăng ký.')
        conn.execute('INSERT INTO users VALUES(?,?,?,?,0,?)',(user_id,payload.email,payload.name.strip(),hashed,db.now()))
        svc.queue_email(conn,{'id':user_id,'email':payload.email},'verify')
    return {'message':'Đã tạo tài khoản. Vui lòng mở email để xác minh.'}


@router.post('/auth/verify')
def verify(payload:m.Token):
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose='verify' AND expires>?",(digest(payload.token),time.time())).fetchone()
        if not row: raise HTTPException(400,'Liên kết không hợp lệ hoặc đã hết hạn.')
        conn.execute('UPDATE users SET verified=1 WHERE id=?',(row['user_id'],))
        conn.execute('DELETE FROM email_tokens WHERE token_hash=?',(digest(payload.token),))
    return {'message':'Email đã được xác minh. Bạn có thể đăng nhập.'}


@router.post('/auth/resend')
def resend(payload:m.Email,request:Request):
    throttle('resend:'+client_key(request),5,3600)
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM users WHERE email=? AND verified=0',(payload.email,)).fetchone()
        if row: svc.queue_email(conn,row,'verify')
    return {'message':'Nếu tài khoản cần xác minh, hệ thống sẽ gửi hướng dẫn qua email.'}


@router.post('/auth/login')
def login(payload:m.Login,request:Request,response:Response):
    throttle('login-ip:'+client_key(request),50,900)
    throttle('login-user:'+payload.email,10,900)
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM users WHERE email=?',(payload.email,)).fetchone()
        stored=row['password'] if row else password_hash('dummy-password-do-not-use')
        if not password_matches(payload.password,stored) or not row: raise HTTPException(401,'Email hoặc mật khẩu không đúng.')
        if not row['verified']: raise HTTPException(403,'Vui lòng xác minh email trước khi đăng nhập.')
        token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),row['id'],csrf,time.time()+SESSION_SECONDS))
        conn.execute('DELETE FROM rate_limits WHERE key=?',(digest('login-user:'+payload.email),))
    response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,secure=os.getenv('COOKIE_SECURE','false')=='true',samesite='lax',path='/')
    return {'user':public_user(row),'csrf':csrf}


@router.get('/auth/me')
def me(current:Current):
    return {'user':public_user(current),'csrf':current['csrf']}


@router.post('/auth/logout')
async def logout(current:Current,response:Response):
    with db.connect() as conn: conn.execute('DELETE FROM sessions WHERE token_hash=?',(current['token_hash'],))
    response.delete_cookie(COOKIE,path='/')
    await svc.revalidate_connections()
    return {'message':'Đã đăng xuất.'}


@router.post('/auth/forgot')
def forgot(payload:m.Email,request:Request):
    throttle('forgot:'+client_key(request),5,3600)
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM users WHERE email=?',(payload.email,)).fetchone()
        if row: svc.queue_email(conn,row,'reset')
    return {'message':'Nếu email đã đăng ký, hệ thống sẽ gửi liên kết khôi phục.'}


@router.post('/auth/reset')
async def reset(payload:m.Reset,request:Request):
    throttle('reset:'+client_key(request),10,900)
    hashed=password_hash(payload.password)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT * FROM email_tokens WHERE token_hash=? AND purpose='reset' AND expires>?",(digest(payload.token),time.time())).fetchone()
        if not row: raise HTTPException(400,'Liên kết không hợp lệ hoặc đã hết hạn.')
        conn.execute('UPDATE users SET password=? WHERE id=?',(hashed,row['user_id']))
        conn.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
        conn.execute("DELETE FROM email_tokens WHERE user_id=? AND purpose='reset'",(row['user_id'],))
    await svc.revalidate_connections()
    return {'message':'Đã đổi mật khẩu và kết thúc các phiên cũ.'}


@router.patch('/account')
def profile(payload:m.Name,current:Current):
    with db.connect() as conn: conn.execute('UPDATE users SET name=? WHERE id=?',(payload.name,current['id']))
    return {'name':payload.name}


@router.get('/homes')
def homes(current:Current):
    with db.connect() as conn:
        rows=conn.execute('SELECT h.*,m.role,m.scopes,m.rights FROM homes h JOIN memberships m ON m.home_id=h.id WHERE m.user_id=? ORDER BY h.name',(current['id'],)).fetchall()
    return [{**dict(r),'settings':json.loads(r['settings']) if r['role']=='owner' else {},'scopes':json.loads(r['scopes']),'rights':active_rights(r['rights'])} for r in rows]


@router.post('/homes',status_code=201)
def create_home(payload:m.Home,current:Current):
    home_id=db.uid()
    with db.connect() as conn:
        conn.execute('INSERT INTO homes(id,name,timezone) VALUES(?,?,?)',(home_id,payload.name,payload.timezone))
        conn.execute('INSERT INTO memberships(home_id,user_id,role) VALUES(?,?,?)',(home_id,current['id'],'owner'))
        db.audit(conn,home_id,current['id'],'home.create',home_id)
    return {'id':home_id,**payload.model_dump()}


@router.patch('/homes/{home_id}')
def update_home(home_id:str,payload:m.Home,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        conn.execute('UPDATE homes SET name=?,timezone=? WHERE id=?',(payload.name,payload.timezone,home_id))
        db.audit(conn,home_id,current['id'],'home.update',home_id)
    return {'id':home_id,**payload.model_dump()}


@router.get('/homes/{home_id}/rooms')
def rooms(home_id:str,current:Current):
    with db.connect() as conn:
        member=membership(conn,home_id,current['id'])
        rows=[dict(r) for r in conn.execute('SELECT * FROM rooms WHERE home_id=? ORDER BY name',(home_id,))]
        if member['role']!='owner':
            allowed={c['room_id'] for c in svc.visible_cameras(conn,home_id,current['id'])}
            rows=[r for r in rows if r['id'] in allowed]
    return rows


@router.post('/homes/{home_id}/rooms',status_code=201)
def create_room(home_id:str,payload:m.Name,current:Current):
    room_id=db.uid()
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        conn.execute('INSERT INTO rooms VALUES(?,?,?)',(room_id,home_id,payload.name))
        db.audit(conn,home_id,current['id'],'room.create',room_id)
    return {'id':room_id,'home_id':home_id,'name':payload.name}


@router.patch('/homes/{home_id}/rooms/{room_id}')
def update_room(home_id:str,room_id:str,payload:m.Name,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        result=conn.execute('UPDATE rooms SET name=? WHERE id=? AND home_id=?',(payload.name,room_id,home_id))
        if result.rowcount!=1: raise HTTPException(404,'Không tìm thấy phòng.')
        db.audit(conn,home_id,current['id'],'room.update',room_id)
    return {'id':room_id,'name':payload.name}


@router.get('/homes/{home_id}/cameras')
def cameras(home_id:str,current:Current):
    with db.connect() as conn: return svc.visible_cameras(conn,home_id,current['id'])


@router.post('/homes/{home_id}/cameras/claim',status_code=201)
def claim(home_id:str,payload:m.Claim,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        throttle('claim:'+current['id'],10,900)
        # Single transaction prevents two accounts from claiming the same code.
        conn.execute('BEGIN IMMEDIATE')
        camera=conn.execute('SELECT * FROM cameras WHERE pair_hash=? AND pair_expires>? AND claimed=0',(digest(payload.code),time.time())).fetchone()
        if not camera: raise HTTPException(400,'Mã ghép nối sai, hết hạn hoặc đã được sử dụng.')
        if not conn.execute('SELECT 1 FROM rooms WHERE id=? AND home_id=?',(payload.room_id,home_id)).fetchone(): raise HTTPException(422,'Phòng không thuộc nhà.')
        conn.execute('UPDATE cameras SET home_id=?,room_id=?,name=?,claimed=1,pair_hash=NULL,pair_expires=NULL WHERE id=?',(home_id,payload.room_id,payload.name,camera['id']))
        svc.revision(conn,camera['id'])
        db.audit(conn,home_id,current['id'],'camera.claim',camera['id'])
        return svc.camera_public(conn.execute('SELECT * FROM cameras WHERE id=?',(camera['id'],)).fetchone())


@router.delete('/cameras/{camera_id}')
async def remove_camera(camera_id:str,current:Current):
    with db.connect() as conn:
        camera=camera_access(conn,camera_id,current['id'],'manage')
        # Rotate credential and mark unclaimed; retain history under original home.
        conn.execute('UPDATE cameras SET claimed=0,token_hash=?,pair_hash=NULL,last_seen=NULL WHERE id=?',(digest(secrets.token_urlsafe(40)),camera_id))
        conn.execute("UPDATE commands SET status='expired' WHERE camera_id=? AND status IN ('pending','accepted')",(camera_id,))
        db.audit(conn,camera['home_id'],current['id'],'camera.remove',camera_id)
    for socket,_ in close_sockets(camera['home_id']):
        svc.connections.pop(socket,None)
        await socket.close(code=1008)
    await svc.revalidate_connections()
    return {'message':'Đã gỡ thiết bị và vô hiệu thông tin xác thực cũ.'}


@router.get('/homes/{home_id}/members')
def members(home_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        return [{**dict(r),'scopes':json.loads(r['scopes']),'rights':active_rights(r['rights'])} for r in conn.execute('SELECT u.id,u.name,u.email,m.role,m.scopes,m.rights FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.home_id=?',(home_id,))]


@router.patch('/homes/{home_id}/members/{user_id}')
async def update_member(home_id:str,user_id:str,payload:m.Access,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        old=membership(conn,home_id,user_id)
        if old['role']=='owner': raise HTTPException(409,'Không thay đổi chủ nhà bằng thao tác này.')
        check_scopes(conn,home_id,payload.scopes)
        conn.execute('UPDATE memberships SET role=?,scopes=?,rights=? WHERE home_id=? AND user_id=?',(payload.role,db.dumps(payload.scopes),db.dumps(payload.rights),home_id,user_id))
        db.audit(conn,home_id,current['id'],'member.update',user_id)
    for socket,_ in close_sockets(home_id):
        svc.connections.pop(socket,None);await socket.close(code=1008)
    await svc.revalidate_connections()
    return {'message':'Đã cập nhật quyền.'}


@router.delete('/homes/{home_id}/members/{user_id}')
async def remove_member(home_id:str,user_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        target=membership(conn,home_id,user_id)
        if target['role']=='owner': raise HTTPException(409,'Không thể thu hồi chủ nhà.')
        conn.execute('DELETE FROM memberships WHERE home_id=? AND user_id=?',(home_id,user_id))
        conn.execute("UPDATE invitations SET status='revoked' WHERE home_id=? AND email=(SELECT email FROM users WHERE id=?) AND status='pending'",(home_id,user_id))
        db.audit(conn,home_id,current['id'],'member.revoke',user_id)
    await svc.revalidate_connections()
    return {'message':'Đã thu hồi quyền.'}


@router.get('/homes/{home_id}/invitations')
def invitations(home_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        return [{k:r[k] for k in ('id','email','role','expires','status')} for r in conn.execute('SELECT * FROM invitations WHERE home_id=? ORDER BY created_at DESC',(home_id,))]


@router.post('/homes/{home_id}/invitations',status_code=201)
def invite(home_id:str,payload:m.Invite,current:Current):
    token=secrets.token_urlsafe(32);inv_id=db.uid()
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        throttle('invite:'+current['id'],20,3600)
        check_scopes(conn,home_id,payload.scopes)
        conn.execute('INSERT INTO invitations VALUES(?,?,?,?,?,?,?,?,?,?)',(inv_id,home_id,payload.email,payload.role,db.dumps(payload.scopes),db.dumps(payload.rights),digest(token),time.time()+7*86400,'pending',db.now()))
        base=os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')
        conn.execute('INSERT INTO mail_jobs(id,recipient,subject,body,created_at) VALUES(?,?,?,?,?)',(db.uid(),payload.email,'Lời mời tham gia AnNhà',f"Mở lời mời: {base}/#/invitation?token={token}",db.now()))
        db.audit(conn,home_id,current['id'],'invitation.create',inv_id)
    return {'id':inv_id,'message':'Đã tạo lời mời và xếp hàng gửi email.'}


@router.get('/invitations/{token}')
def invitation(token:str,current:Current):
    with db.connect() as conn:
        row=conn.execute('SELECT i.*,h.name AS home_name FROM invitations i JOIN homes h ON h.id=i.home_id WHERE token_hash=?',(digest(token),)).fetchone()
        if not row or row['email']!=current['email']: raise HTTPException(404,'Không tìm thấy lời mời cho tài khoản này.')
        return {**{k:row[k] for k in ('id','home_id','home_name','role','scopes','expires','status')},'rights':db.dumps(active_rights(row['rights']))}


@router.post('/invitations/{token}/accept')
def accept_invite(token:str,current:Current):
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute("SELECT * FROM invitations WHERE token_hash=? AND status='pending' AND expires>?",(digest(token),time.time())).fetchone()
        if not row or row['email']!=current['email']: raise HTTPException(400,'Lời mời hết hạn hoặc không thuộc tài khoản này.')
        check_scopes(conn,row['home_id'],json.loads(row['scopes']))
        existing=conn.execute('SELECT 1 FROM memberships WHERE home_id=? AND user_id=?',(row['home_id'],current['id'])).fetchone()
        if existing: raise HTTPException(409,'Bạn đã là thành viên. Chủ nhà có thể sửa quyền trong trang thành viên.')
        conn.execute('INSERT INTO memberships VALUES(?,?,?,?,?)',(row['home_id'],current['id'],row['role'],row['scopes'],row['rights']))
        conn.execute("UPDATE invitations SET status='revoked' WHERE home_id=? AND email=? AND status='pending'",(row['home_id'],row['email']))
        conn.execute("UPDATE invitations SET status='accepted' WHERE id=?",(row['id'],))
        db.audit(conn,row['home_id'],current['id'],'invitation.accept',row['id'])
    return {'home_id':row['home_id']}


@router.post('/invitations/{token}/decline')
def decline_invite(token:str,current:Current):
    with db.connect() as conn:
        result=conn.execute("UPDATE invitations SET status='declined' WHERE token_hash=? AND email=? AND status='pending' AND expires>?",(digest(token),current['email'],time.time()))
        if result.rowcount!=1: raise HTTPException(404,'Không có lời mời hợp lệ cho tài khoản này.')
    return {'message':'Đã từ chối lời mời.'}


@router.delete('/homes/{home_id}/invitations/{invitation_id}')
def revoke_invite(home_id:str,invitation_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        result=conn.execute("UPDATE invitations SET status='revoked' WHERE id=? AND home_id=? AND status='pending'",(invitation_id,home_id))
        if result.rowcount!=1: raise HTTPException(404,'Không có lời mời đang chờ.')
        db.audit(conn,home_id,current['id'],'invitation.revoke',invitation_id)
    return {'message':'Đã thu hồi lời mời.'}


@router.get('/cameras/{camera_id}/config')
def config(camera_id:str,current:Current):
    with db.connect() as conn:
        camera=camera_access(conn,camera_id,current['id'])
        row=conn.execute('SELECT * FROM configurations WHERE camera_id=? ORDER BY version DESC LIMIT 1',(camera_id,)).fetchone()
        return {'desired_version':camera['desired_version'],'applied_version':camera['applied_version'],'error':camera['config_error'],'payload':svc.config_without_zones(json.loads(row['payload']) if row else {})}


@router.get('/homes/{home_id}/events')
def events(home_id:str,current:Current,limit:int=100,status:str|None=None):
    if not 1<=limit<=500: raise HTTPException(422,'Giới hạn phải từ 1 đến 500.')
    with db.connect() as conn:
        member=membership(conn,home_id,current['id'])
        visible=[c['id'] for c in conn.execute('SELECT id FROM cameras WHERE home_id=?',(home_id,)) if member['role']=='owner' or c['id'] in member['scopes']]
        if not visible: return []
        sql='SELECT * FROM events WHERE home_id=? AND camera_id IN ('+','.join('?' for _ in visible)+')'
        params=[home_id,*visible]
        if status: sql+=' AND status=?';params.append(status)
        rows=conn.execute(sql+' ORDER BY received_at DESC LIMIT ?',params+[limit]).fetchall()
        return [svc.event_public(conn,r) for r in rows]


@router.get('/events/{event_id}')
def get_event(event_id:str,current:Current):
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy sự kiện.')
        camera_access(conn,row['camera_id'],current['id'],historical=True)
        return svc.event_public(conn,row)


@router.post('/events/{event_id}/actions')
async def event_action(event_id:str,payload:m.Action,current:Current):
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy sự kiện.')
        camera_access(conn,row['camera_id'],current['id'],'events',historical=True)
        closing=payload.action in ('resolve','safe','false_alarm')
        if closing and row['observation'] in ('abnormal','suspected') and (not payload.confirm_abnormal or not payload.note):
            raise HTTPException(409,'Còn dấu hiệu bất thường. Cần xác nhận và ghi chú trước khi kết thúc.')
        if row['status'] in ('RESOLVED','FALSE_ALARM') and payload.action!='note': raise HTTPException(409,'Sự kiện đã kết thúc.')
        if payload.action=='acknowledge': conn.execute("UPDATE events SET status='ACKNOWLEDGED' WHERE id=?",(event_id,))
        if closing: conn.execute('UPDATE events SET status=? WHERE id=?',('FALSE_ALARM' if payload.action=='false_alarm' else 'RESOLVED',event_id))
        if payload.action=='silence':
            if row['kind']=='environment' and row['observation']=='abnormal': raise HTTPException(409,'Không tắt cảnh báo môi trường đang bất thường từ thao tác này.')
            conn.execute('INSERT INTO commands(id,camera_id,home_id,user_id,kind,payload,expires,created_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)',
                         (db.uid(),row['camera_id'],row['home_id'],current['id'],'silence',db.dumps({'seconds':60,'event_id':event_id}),time.time()+60,db.now(),db.uid()))
        conn.execute('INSERT INTO actions VALUES(?,?,?,?,?,?)',(db.uid(),event_id,current['id'],payload.action,payload.note,db.now()))
        db.audit(conn,row['home_id'],current['id'],'event.'+payload.action,event_id)
        result=svc.event_public(conn,conn.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone())
    await svc.broadcast(result)
    return result


@router.get('/cameras/{camera_id}/telemetry')
def telemetry(camera_id:str,current:Current,limit:int=100):
    if not 1<=limit<=1000: raise HTTPException(422,'Giới hạn không hợp lệ.')
    with db.connect() as conn:
        camera_access(conn,camera_id,current['id'])
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in conn.execute('SELECT * FROM telemetry WHERE camera_id=? ORDER BY id DESC LIMIT ?',(camera_id,limit))]


@router.get('/homes/{home_id}/settings')
def settings(home_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        return m.Settings(**json.loads(conn.execute('SELECT settings FROM homes WHERE id=?',(home_id,)).fetchone()[0])).model_dump()


@router.put('/homes/{home_id}/settings')
def save_settings(home_id:str,payload:m.Settings,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        conn.execute('UPDATE homes SET settings=? WHERE id=?',(db.dumps(payload.model_dump()),home_id))
        for camera in conn.execute('SELECT id FROM cameras WHERE home_id=? AND claimed=1',(home_id,)).fetchall(): svc.revision(conn,camera['id'])
        db.audit(conn,home_id,current['id'],'settings.update',home_id)
    return payload.model_dump()


@router.get('/homes/{home_id}/assets')
def assets(home_id:str,current:Current):
    with db.connect() as conn:
        cameras=svc.visible_cameras(conn,home_id,current['id'])
        allowed={c['id'] for c in cameras}
        return [{k:r[k] for k in ('id','camera_id','event_id','name','mime','size','status','error','created_at')} for r in conn.execute('SELECT * FROM assets WHERE home_id=? ORDER BY created_at DESC',(home_id,)) if r['camera_id'] in allowed]


async def write_asset(request,home_id,camera_id,event_id=None):
    mime=request.headers.get('content-type','').split(';')[0]
    extensions={'image/jpeg':'.jpg','image/png':'.png','video/mp4':'.mp4','video/webm':'.webm','audio/webm':'.webm','audio/mpeg':'.mp3','audio/wav':'.wav','audio/ogg':'.ogg'}
    if mime not in extensions: raise HTTPException(415,'Định dạng file chưa được hỗ trợ.')
    asset_id=db.uid();filename=asset_id+extensions[mime];path=db.MEDIA_ROOT/filename
    size=0;prefix=b''
    quota=int(os.getenv('MAX_HOME_MEDIA_BYTES',str(512*1024*1024)))
    with db.connect() as conn:
        used=conn.execute("SELECT COALESCE(SUM(size),0) FROM assets WHERE home_id=? AND status='ready'",(home_id,)).fetchone()[0]
    try:
        with path.open('wb') as output:
            async for chunk in request.stream():
                size+=len(chunk)
                if size>25*1024*1024: raise HTTPException(413,'File vượt quá 25 MB.')
                if used+size>quota: raise HTTPException(413,'Nhà đã đạt giới hạn lưu trữ media.')
                if len(prefix)<16: prefix=(prefix+chunk)[:16]
                output.write(chunk)
        signatures={'image/jpeg':prefix.startswith(b'\xff\xd8\xff'),'image/png':prefix.startswith(b'\x89PNG\r\n\x1a\n'),
                    'audio/wav':prefix.startswith(b'RIFF') and prefix[8:12]==b'WAVE','audio/ogg':prefix.startswith(b'OggS'),
                    'audio/mpeg':prefix.startswith(b'ID3') or prefix[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2'),
                    'audio/webm':prefix.startswith(b'\x1aE\xdf\xa3'),'video/webm':prefix.startswith(b'\x1aE\xdf\xa3'),'video/mp4':prefix[4:8]==b'ftyp'}
        if not signatures.get(mime): raise HTTPException(415,'Nội dung file không khớp định dạng khai báo.')
        from urllib.parse import unquote
        name=unquote(request.headers.get('x-file-name','Tài nguyên'))[:160]
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current_used=conn.execute("SELECT COALESCE(SUM(size),0) FROM assets WHERE home_id=? AND status='ready'",(home_id,)).fetchone()[0]
            if current_used+size>quota: raise HTTPException(413,'Nhà đã đạt giới hạn lưu trữ media.')
            conn.execute('INSERT INTO assets(id,home_id,camera_id,event_id,name,mime,size,path,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         (asset_id,home_id,camera_id,event_id,name,mime,size,filename,db.now()))
            if event_id is None and mime.startswith('image/'):
                old_snapshots=conn.execute("SELECT id,path FROM assets WHERE camera_id=? AND event_id IS NULL AND mime LIKE 'image/%' AND status='ready' ORDER BY created_at DESC LIMIT -1 OFFSET 5",(camera_id,)).fetchall()
                for snapshot in old_snapshots:
                    (db.MEDIA_ROOT/snapshot['path']).unlink(missing_ok=True)
                    conn.execute("UPDATE assets SET status='expired' WHERE id=?",(snapshot['id'],))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {'id':asset_id,'name':name,'mime':mime,'size':size,'status':'ready'}


@router.post('/cameras/{camera_id}/assets',status_code=201)
async def upload_audio(camera_id:str,request:Request,current:Current):
    with db.connect() as conn: camera=camera_access(conn,camera_id,current['id'],'audio')
    if not request.headers.get('content-type','').startswith('audio/'): raise HTTPException(415,'Chỉ tải âm thanh ở màn hình này.')
    return await write_asset(request,camera['home_id'],camera_id)


@router.get('/assets/{asset_id}')
def asset_file(asset_id:str,current:Current):
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy tài nguyên.')
        camera_access(conn,row['camera_id'],current['id'],historical=True)
        return FileResponse(svc.asset_path(row),media_type=row['mime'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.delete('/assets/{asset_id}')
def delete_asset(asset_id:str,current:Current):
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy tài nguyên.')
        camera_access(conn,row['camera_id'],current['id'],'audio')
        if row['event_id']: raise HTTPException(409,'Bằng chứng được quản lý theo chính sách lưu trữ.')
        if conn.execute('SELECT 1 FROM reminders WHERE asset_id=?',(asset_id,)).fetchone(): raise HTTPException(409,'Âm thanh đang được lịch nhắc sử dụng.')
        (db.MEDIA_ROOT/row['path']).unlink(missing_ok=True)
        conn.execute("UPDATE assets SET status='expired' WHERE id=?",(asset_id,))
        db.audit(conn,row['home_id'],current['id'],'asset.delete',asset_id)
    return {'message':'Đã xóa file âm thanh.'}


@router.get('/homes/{home_id}/reminders')
def reminders(home_id:str,current:Current):
    with db.connect() as conn:
        allowed={c['id'] for c in svc.visible_cameras(conn,home_id,current['id'])}
        return [{**svc.reminder_public(r),'asset_status':r['asset_status'],'asset_error':r['asset_error']} for r in conn.execute('SELECT r.*,a.status AS asset_status,a.error AS asset_error FROM reminders r LEFT JOIN assets a ON a.id=r.asset_id WHERE r.home_id=? ORDER BY r.time',(home_id,)) if r['camera_id'] in allowed]


def save_reminder(home_id,payload,current,reminder_id=None):
    values=payload.model_dump(mode='json');reminder_id=reminder_id or db.uid()
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        camera=camera_access(conn,payload.camera_id,current['id'],'schedules')
        if camera['home_id']!=home_id: raise HTTPException(422,'Camera không thuộc nhà.')
        old=conn.execute('SELECT * FROM reminders WHERE id=?',(reminder_id,)).fetchone()
        if old: camera_access(conn,old['camera_id'],current['id'],'schedules')
        asset_id=payload.asset_id
        if payload.source=='audio':
            asset=conn.execute("SELECT * FROM assets WHERE id=? AND camera_id=? AND status='ready' AND mime LIKE 'audio/%'",(asset_id,payload.camera_id)).fetchone()
            if not asset: raise HTTPException(422,'File âm thanh không sẵn sàng hoặc thuộc camera khác.')
        else:
            if old and old['source']=='tts' and old['text']==payload.text and old['camera_id']==payload.camera_id:
                asset_id=old['asset_id']
            else:
                asset_id=db.uid()
                conn.execute("INSERT INTO assets(id,home_id,camera_id,name,mime,size,path,status,created_at) VALUES(?,?,?,?,?,0,?,'pending',?)",(asset_id,home_id,payload.camera_id,payload.name+'.wav','audio/wav',asset_id+'.wav',db.now()))
        version=old['version']+1 if old else 1
        conn.execute('''INSERT INTO reminders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET camera_id=excluded.camera_id,name=excluded.name,time=excluded.time,weekdays=excluded.weekdays,once_date=excluded.once_date,timezone=excluded.timezone,enabled=excluded.enabled,source=excluded.source,text=excluded.text,asset_id=excluded.asset_id,volume=excluded.volume,version=excluded.version,late_seconds=excluded.late_seconds''',
        (reminder_id,home_id,payload.camera_id,payload.name,payload.time,db.dumps(payload.weekdays),values['once_date'],payload.timezone,int(payload.enabled),payload.source,payload.text,asset_id,payload.volume,version,payload.late_seconds,old['created_at'] if old else db.now()))
        svc.revision(conn,payload.camera_id)
        if old and old['camera_id']!=payload.camera_id: svc.revision(conn,old['camera_id'])
        db.audit(conn,home_id,current['id'],'reminder.save',reminder_id)
    return {'id':reminder_id,'status':'pending','asset_id':asset_id}


@router.post('/homes/{home_id}/reminders',status_code=201)
def create_reminder(home_id:str,payload:m.Reminder,current:Current):
    return save_reminder(home_id,payload,current)


@router.put('/reminders/{reminder_id}')
def update_reminder(reminder_id:str,payload:m.Reminder,current:Current):
    with db.connect() as conn:
        old=conn.execute('SELECT * FROM reminders WHERE id=?',(reminder_id,)).fetchone()
        if not old: raise HTTPException(404,'Không tìm thấy lịch nhắc.')
        camera_access(conn,old['camera_id'],current['id'],'schedules')
    return save_reminder(old['home_id'],payload,current,reminder_id)


@router.delete('/reminders/{reminder_id}')
def remove_reminder(reminder_id:str,current:Current):
    with db.connect() as conn:
        old=conn.execute('SELECT * FROM reminders WHERE id=?',(reminder_id,)).fetchone()
        if not old: raise HTTPException(404,'Không tìm thấy lịch nhắc.')
        camera_access(conn,old['camera_id'],current['id'],'schedules')
        conn.execute('DELETE FROM reminders WHERE id=?',(reminder_id,))
        svc.revision(conn,old['camera_id'])
        db.audit(conn,old['home_id'],current['id'],'reminder.delete',reminder_id)
    return {'message':'Đã xóa lịch. Đang chờ thiết bị nhận cấu hình mới.'}


@router.get('/homes/{home_id}/executions')
def executions(home_id:str,current:Current):
    with db.connect() as conn:
        allowed={c['id'] for c in svc.visible_cameras(conn,home_id,current['id'])}
        return [dict(r) for r in conn.execute('SELECT e.* FROM executions e JOIN cameras c ON c.id=e.camera_id WHERE c.home_id=? ORDER BY e.created_at DESC LIMIT 200',(home_id,)) if r['camera_id'] in allowed]


@router.post('/cameras/{camera_id}/commands',status_code=201)
def command(camera_id:str,payload:m.Command,current:Current):
    with db.connect() as conn:
        camera=camera_access(conn,camera_id,current['id'],'audio')
        if payload.kind=='silence': raise HTTPException(422,'Hãy tắt âm từ đúng sự kiện để kiểm tra chính sách cảnh báo.')
        if payload.asset_id:
            asset=conn.execute("SELECT * FROM assets WHERE id=? AND camera_id=? AND mime LIKE 'audio/%' AND status='ready'",(payload.asset_id,camera_id)).fetchone()
            if not asset: raise HTTPException(422,'Âm thanh không thuộc camera hoặc chưa sẵn sàng.')
        old=conn.execute('SELECT * FROM commands WHERE user_id=? AND idempotency_key=?',(current['id'],payload.idempotency_key)).fetchone()
        command_payload={'asset_id':payload.asset_id,'volume':payload.volume}
        if old:
            if old['camera_id']!=camera_id or old['kind']!=payload.kind or json.loads(old['payload'])!=command_payload: raise HTTPException(409,'Mã lệnh đã được dùng cho nội dung khác.')
            return {'id':old['id'],'status':old['status']}
        command_id=db.uid()
        conn.execute('INSERT INTO commands(id,camera_id,home_id,user_id,kind,payload,expires,created_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)',
                     (command_id,camera_id,camera['home_id'],current['id'],payload.kind,db.dumps(command_payload),time.time()+payload.ttl_seconds,db.now(),payload.idempotency_key))
        db.audit(conn,camera['home_id'],current['id'],'command.create',command_id)
    return {'id':command_id,'status':'pending'}


@router.get('/cameras/{camera_id}/commands')
def commands(camera_id:str,current:Current):
    with db.connect() as conn:
        camera_access(conn,camera_id,current['id'],'audio')
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in conn.execute('SELECT * FROM commands WHERE camera_id=? ORDER BY created_at DESC LIMIT 50',(camera_id,))]


@router.get('/homes/{home_id}/audit')
def audit(home_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        return [dict(r) for r in conn.execute('SELECT a.*,u.name AS user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE home_id=? ORDER BY created_at DESC LIMIT 200',(home_id,))]


@router.get('/homes/{home_id}/delivery-status')
def deliveries(home_id:str,current:Current):
    with db.connect() as conn:
        membership(conn,home_id,current['id'],owner=True)
        return [dict(r) for r in conn.execute('SELECT id,event_id,status,attempts,sent_count,error FROM deliveries WHERE home_id=?',(home_id,))]


# Device APIs authenticate a separate device credential, never a browser session.
@router.post('/device/heartbeat')
def heartbeat(payload:m.Heartbeat,current:Device):
    with db.connect() as conn:
        conn.execute('UPDATE cameras SET last_seen=?,observation=?,capabilities=? WHERE id=?',(db.now(),payload.observation,db.dumps(payload.capabilities),current['id']))
    return {'server_time':db.now(),'desired_version':current['desired_version']}


@router.get('/device/config')
def device_config(current:Device):
    with db.connect() as conn:
        row=conn.execute('SELECT payload FROM configurations WHERE camera_id=? ORDER BY version DESC LIMIT 1',(current['id'],)).fetchone()
    return svc.config_without_zones(json.loads(row[0]) if row else {'version':0,'reminders':[]})


@router.post('/device/config/ack')
def config_ack(payload:m.ConfigAck,current:Device):
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        camera=conn.execute('SELECT * FROM cameras WHERE id=?',(current['id'],)).fetchone()
        if not conn.execute('SELECT 1 FROM configurations WHERE camera_id=? AND version=?',(current['id'],payload.version)).fetchone(): raise HTTPException(422,'Không có phiên bản cấu hình này.')
        if payload.version<camera['applied_version']: raise HTTPException(409,'Phản hồi cấu hình cũ.')
        if payload.success: conn.execute('UPDATE cameras SET applied_version=?,config_error=NULL WHERE id=?',(payload.version,current['id']))
        else: conn.execute('UPDATE cameras SET config_error=? WHERE id=?',(payload.error or 'Thiết bị từ chối cấu hình',current['id']))
    return {'message':'Đã ghi nhận phản hồi.'}


@router.post('/device/events')
async def device_event(payload:m.EventInput,current:Device):
    event,changed=svc.ingest_event(current,payload)
    if changed: await svc.broadcast(event)
    return {'id':event['id'],'event_id':payload.event_id,'sequence':event['sequence'],'stored':True}


@router.post('/device/telemetry')
async def device_telemetry(payload:m.Telemetry,current:Device):
    with db.connect() as conn:
        inserted=conn.execute('INSERT OR IGNORE INTO telemetry(camera_id,message_id,payload,observed_at,received_at) VALUES(?,?,?,?,?)',
                     (current['id'],payload.message_id,db.dumps(payload.model_dump()),payload.observed_at,db.now())).rowcount
    for event in (svc.evaluate_environment(current,payload) if inserted else []):
        await svc.broadcast(event)
    return {'stored':True,'message_id':payload.message_id}


@router.get('/device/commands')
def device_commands(current:Device):
    with db.connect() as conn:
        conn.execute("UPDATE commands SET status='expired' WHERE camera_id=? AND expires<? AND status IN ('pending','accepted')",(current['id'],time.time()))
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in conn.execute("SELECT * FROM commands WHERE camera_id=? AND status IN ('pending','accepted') AND expires>? ORDER BY created_at",(current['id'],time.time()))]


@router.post('/device/commands/{command_id}/ack')
def command_ack(command_id:str,payload:m.CommandAck,current:Device):
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM commands WHERE id=? AND camera_id=?',(command_id,current['id'])).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy lệnh cho thiết bị.')
        if row['status'] in ('executed','failed','expired'):
            if row['status']==payload.status: return {'status':row['status']}
            raise HTTPException(409,'Lệnh đã kết thúc.')
        if row['expires']<time.time() and row['status']!='executing': raise HTTPException(409,'Lệnh đã hết hạn.')
        stages={'pending':0,'accepted':1,'executing':2,'executed':3,'failed':3}
        if stages.get(row['status'],0)>stages[payload.status]: raise HTTPException(409,'Không được lùi trạng thái lệnh.')
        conn.execute('UPDATE commands SET status=?,result=? WHERE id=?',(payload.status,payload.detail,command_id))
    return {'status':payload.status}


@router.post('/device/executions')
def execution(payload:m.Execution,current:Device):
    with db.connect() as conn:
        reminder=conn.execute('SELECT * FROM reminders WHERE id=? AND camera_id=?',(payload.reminder_id,current['id'])).fetchone()
        if not reminder: raise HTTPException(404,'Lịch không thuộc thiết bị.')
        conn.execute('INSERT OR IGNORE INTO executions VALUES(?,?,?,?,?,?,?)',(db.uid(),current['id'],payload.reminder_id,payload.occurrence,payload.status,payload.detail,db.now()))
    return {'stored':True}


@router.get('/device/assets/{asset_id}')
def device_asset(asset_id:str,current:Device):
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM assets WHERE id=? AND camera_id=?',(asset_id,current['id'])).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy file cho thiết bị.')
        return FileResponse(svc.asset_path(row),media_type=row['mime'],headers={'Cache-Control':'no-store'})


@router.post('/device/evidence',status_code=201)
async def evidence(request:Request,current:Device,event_id:str|None=None):
    if event_id:
        with db.connect() as conn:
            if not conn.execute('SELECT 1 FROM events WHERE id=? AND camera_id=?',(event_id,current['id'])).fetchone(): raise HTTPException(404,'Sự kiện không thuộc thiết bị.')
    elif not request.headers.get('content-type','').startswith('image/'):
        raise HTTPException(422,'Cần sự kiện đích cho clip bằng chứng.')
    return await write_asset(request,current['home_id'],current['id'],event_id)


@router.get('/cameras/{camera_id}/snapshot')
def snapshot(camera_id:str,current:Current):
    with db.connect() as conn:
        camera_access(conn,camera_id,current['id'])
        row=conn.execute("SELECT * FROM assets WHERE camera_id=? AND mime LIKE 'image/%' AND status='ready' ORDER BY created_at DESC LIMIT 1",(camera_id,)).fetchone()
        if not row: raise HTTPException(404,'Thiết bị chưa gửi hình ảnh.')
        return FileResponse(svc.asset_path(row),media_type=row['mime'],headers={'Cache-Control':'no-store','X-Captured-At':row['created_at']})
