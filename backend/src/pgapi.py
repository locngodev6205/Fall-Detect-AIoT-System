"""AnNhà HTTP API backed by the normalized Neon/PostgreSQL schema."""
from datetime import datetime,timedelta
import hashlib
import os
from pathlib import Path
import secrets
from typing import Annotated
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from fastapi.responses import FileResponse
from fastapi.encoders import jsonable_encoder
from . import models as m, pgdb as db, pgservices as svc
from .pgsecurity import COOKIE,SESSION_SECONDS,camera_access,csrf_for,device,digest,membership,password_hash,password_matches,public_user,session_user,throttle,user

router=APIRouter(prefix='/api')
Current=Annotated[dict,Depends(user)];Device=Annotated[dict,Depends(device)]

def fail_if_missing(row,message='Không tìm thấy tài nguyên.'):
    if not row: raise HTTPException(404,message)
    return row

def scopes(conn,home,items):
    available={str(r['id']) for r in conn.execute('SELECT id FROM annha.cameras WHERE home_id=%s AND retired_at IS NULL',(home,))}
    if not set(items)<=available: raise HTTPException(422,'Camera không thuộc nhà.')

def grant_rows(conn,home,account,payload):
    scopes(conn,home,payload.scopes)
    conn.execute('DELETE FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s',(home,account))
    for camera in payload.scopes:
        conn.execute('''INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_view,can_handle_events,can_play_audio,can_edit_reminders)
          VALUES(%s,%s,%s,true,%s,%s,%s)''',(home,camera,account,payload.role=='caregiver',payload.role=='caregiver' and payload.rights.get('audio',False),payload.role=='caregiver' and payload.rights.get('schedules',False)))

@router.post('/auth/register',status_code=201)
def register(payload:m.Register,request:Request):
    throttle('register:'+str(request.client.host),5,3600)
    with db.connect('auth') as conn:
        row=conn.execute('INSERT INTO annha_private.users(email,name,password_hash) VALUES(%s,%s,%s) RETURNING *',(payload.email,payload.name,password_hash(payload.password))).fetchone()
        svc.queue_email(conn,row,'verify_email')
    return {'message':'Đã tạo tài khoản. Vui lòng mở email để xác minh.'}

@router.post('/auth/verify')
def verify(payload:m.Token):
    with db.connect('auth') as conn:
        token=conn.execute("SELECT * FROM annha_private.email_tokens WHERE token_hash=%s AND purpose='verify_email' AND consumed_at IS NULL AND expires_at>now() FOR UPDATE",(digest(payload.token),)).fetchone()
        if not token: raise HTTPException(400,'Liên kết không hợp lệ hoặc đã hết hạn.')
        updated=conn.execute('UPDATE annha_private.users SET email_verified_at=now() WHERE id=%s AND email_version=%s RETURNING id',(token['user_id'],token['email_version'])).fetchone()
        if not updated: raise HTTPException(400,'Địa chỉ email đã thay đổi.')
        conn.execute('UPDATE annha_private.email_tokens SET consumed_at=now() WHERE token_hash=%s',(digest(payload.token),))
    return {'message':'Email đã được xác minh. Bạn có thể đăng nhập.'}

@router.post('/auth/resend')
def resend(payload:m.Email,request:Request):
    throttle('resend:'+str(request.client.host),5,3600)
    with db.connect('auth') as conn:
        account=conn.execute('SELECT * FROM annha_private.users WHERE email=%s AND email_verified_at IS NULL AND deleted_at IS NULL',(payload.email,)).fetchone()
        if account: svc.queue_email(conn,account,'verify_email')
    return {'message':'Nếu tài khoản cần xác minh, hệ thống sẽ gửi hướng dẫn qua email.'}

@router.post('/auth/login')
def login(payload:m.Login,request:Request,response:Response):
    throttle('login-ip:'+str(request.client.host),50,900);throttle('login-user:'+payload.email,10,900)
    with db.connect('auth') as conn:
        account=conn.execute('SELECT * FROM annha_private.users WHERE email=%s AND disabled_at IS NULL AND deleted_at IS NULL',(payload.email,)).fetchone()
        if not password_matches(payload.password,account['password_hash'] if account else password_hash('dummy-not-a-user')) or not account: raise HTTPException(401,'Email hoặc mật khẩu không đúng.')
        if not account['email_verified_at']: raise HTTPException(403,'Vui lòng xác minh email trước khi đăng nhập.')
        token=secrets.token_urlsafe(40);csrf=csrf_for(token)
        conn.execute('INSERT INTO annha_private.sessions(token_hash,user_id,csrf_hash,auth_version,expires_at) VALUES(%s,%s,%s,%s,%s)',(digest(token),account['id'],digest(csrf),account['auth_version'],db.now()+timedelta(seconds=SESSION_SECONDS)))
        conn.execute('DELETE FROM annha_private.rate_limits WHERE key_hash=%s',(digest('login-user:'+payload.email),))
    response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,secure=os.getenv('COOKIE_SECURE','false').lower()=='true',samesite='lax',path='/')
    return {'user':public_user(account),'csrf':csrf}

@router.get('/auth/me')
def me(current:Current): return {'user':public_user(current),'csrf':current['csrf']}

@router.post('/auth/logout')
async def logout(current:Current,response:Response):
    with db.connect('auth') as conn: conn.execute('UPDATE annha_private.sessions SET revoked_at=now() WHERE token_hash=%s',(current['token_hash'],))
    response.delete_cookie(COOKIE,path='/');await svc.revalidate_connections()
    return {'message':'Đã đăng xuất.'}

@router.post('/auth/forgot')
def forgot(payload:m.Email,request:Request):
    throttle('forgot:'+str(request.client.host),5,3600)
    with db.connect('auth') as conn:
        account=conn.execute('SELECT * FROM annha_private.users WHERE email=%s AND deleted_at IS NULL',(payload.email,)).fetchone()
        if account: svc.queue_email(conn,account,'reset_password')
    return {'message':'Nếu email đã đăng ký, hệ thống sẽ gửi liên kết khôi phục.'}

@router.post('/auth/reset')
async def reset(payload:m.Reset,request:Request):
    throttle('reset:'+str(request.client.host),10,900)
    with db.connect('auth') as conn:
        token=conn.execute("SELECT * FROM annha_private.email_tokens WHERE token_hash=%s AND purpose='reset_password' AND consumed_at IS NULL AND expires_at>now() FOR UPDATE",(digest(payload.token),)).fetchone()
        if not token: raise HTTPException(400,'Liên kết không hợp lệ hoặc đã hết hạn.')
        changed=conn.execute('UPDATE annha_private.users SET password_hash=%s,auth_version=auth_version+1 WHERE id=%s AND email_version=%s RETURNING id',(password_hash(payload.password),token['user_id'],token['email_version'])).fetchone()
        if not changed: raise HTTPException(400,'Địa chỉ email đã thay đổi.')
        conn.execute('UPDATE annha_private.sessions SET revoked_at=now() WHERE user_id=%s',(token['user_id'],))
        conn.execute('UPDATE annha_private.email_tokens SET consumed_at=now() WHERE user_id=%s',(token['user_id'],))
    await svc.revalidate_connections();return {'message':'Đã đổi mật khẩu và kết thúc các phiên cũ.'}

@router.patch('/account')
def profile(payload:m.Name,current:Current):
    with db.connect('auth') as conn: conn.execute('UPDATE annha_private.users SET name=%s,updated_at=now() WHERE id=%s',(payload.name,current['id']))
    return {'name':payload.name}

@router.get('/homes')
def homes(current:Current):
    with db.connect('auth') as conn:
        rows=conn.execute('SELECT h.* FROM annha.homes h JOIN annha_private.home_memberships m ON m.home_id=h.id WHERE m.user_id=%s AND m.revoked_at IS NULL AND h.archived_at IS NULL ORDER BY h.name',(current['id'],)).fetchall()
    return [{**dict(row),**membership(str(row['id']),current['id']),'id':row['id'],'name':row['name'],'settings':{},'email_notifications_supported':True} for row in rows]

@router.post('/homes',status_code=201)
def create_home(payload:m.Home,current:Current):
    home=db.uid()
    with db.connect('auth',home,current['id']) as conn:
        conn.execute('INSERT INTO annha.homes(id,name,timezone,created_by) VALUES(%s,%s,%s,%s)',(home,payload.name,payload.timezone,current['id']))
        conn.execute("INSERT INTO annha_private.home_memberships(home_id,user_id,role,granted_by) VALUES(%s,%s,'owner',%s)",(home,current['id'],current['id']))
        conn.execute('INSERT INTO annha.home_settings(home_id) VALUES(%s)',(home,))
        conn.execute('INSERT INTO annha.home_storage(home_id,quota_bytes) VALUES(%s,%s)',(home,int(os.getenv('MAX_HOME_MEDIA_BYTES','536870912'))))
        db.audit(conn,home,current['id'],'home.create',home)
    return {'id':home,**payload.model_dump()}

@router.patch('/homes/{home_id}')
def update_home(home_id:str,payload:m.Home,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn:
        conn.execute('UPDATE annha.homes SET name=%s,timezone=%s WHERE id=%s',(payload.name,payload.timezone,home_id));db.audit(conn,home_id,current['id'],'home.update',home_id)
    return {'id':home_id,**payload.model_dump()}

@router.get('/homes/{home_id}/rooms')
def rooms(home_id:str,current:Current):
    membership(home_id,current['id'])
    with db.connect('app',home_id,current['id']) as conn: return conn.execute('SELECT * FROM annha.rooms WHERE archived_at IS NULL ORDER BY name').fetchall()

@router.post('/homes/{home_id}/rooms',status_code=201)
def create_room(home_id:str,payload:m.Name,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn:
        row=conn.execute('INSERT INTO annha.rooms(home_id,name) VALUES(%s,%s) RETURNING *',(home_id,payload.name)).fetchone();db.audit(conn,home_id,current['id'],'room.create',row['id'])
    return row

@router.patch('/homes/{home_id}/rooms/{room_id}')
def update_room(home_id:str,room_id:str,payload:m.Name,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn:
        row=fail_if_missing(conn.execute('UPDATE annha.rooms SET name=%s WHERE id=%s RETURNING *',(payload.name,room_id)).fetchone());db.audit(conn,home_id,current['id'],'room.update',room_id)
    return row

@router.get('/homes/{home_id}/cameras')
def cameras(home_id:str,current:Current):
    membership(home_id,current['id'])
    with db.connect('app',home_id,current['id']) as conn: return [svc.camera_public(conn,row) for row in conn.execute('SELECT * FROM annha.cameras WHERE retired_at IS NULL ORDER BY name').fetchall()]

@router.post('/homes/{home_id}/cameras/claim',status_code=201)
def claim(home_id:str,payload:m.Claim,current:Current):
    membership(home_id,current['id'],True);throttle('claim:'+current['id'],10,900);camera=db.uid()
    with db.connect('auth',home_id,current['id']) as conn:
        code=conn.execute('SELECT * FROM annha_private.pairing_codes WHERE code_hash=%s AND consumed_at IS NULL AND expires_at>now() FOR UPDATE',(digest(payload.code),)).fetchone()
        if not code: raise HTTPException(400,'Mã ghép nối sai, hết hạn hoặc đã dùng.')
        fail_if_missing(conn.execute('SELECT id FROM annha.rooms WHERE home_id=%s AND id=%s',(home_id,payload.room_id)).fetchone(),'Phòng không thuộc nhà.')
        conn.execute('INSERT INTO annha.cameras(id,home_id,room_id,device_id,name) VALUES(%s,%s,%s,%s,%s)',(camera,home_id,payload.room_id,code['device_id'],payload.name))
        conn.execute('UPDATE annha_private.device_credentials SET camera_id=%s WHERE device_id=%s AND camera_id IS NULL AND revoked_at IS NULL',(camera,code['device_id']))
        conn.execute('UPDATE annha_private.pairing_codes SET consumed_at=now(),claimed_camera_id=%s WHERE code_hash=%s',(camera,digest(payload.code)))
        db.audit(conn,home_id,current['id'],'camera.claim',camera)
    svc.compile_config(home_id,camera)
    with db.connect('app',home_id,current['id']) as conn: return svc.camera_public(conn,conn.execute('SELECT * FROM annha.cameras WHERE id=%s',(camera,)).fetchone())

@router.delete('/cameras/{camera_id}')
async def remove_camera(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'],'manage');home=camera['home_id']
    with db.connect('auth',home,current['id']) as conn:
        conn.execute('UPDATE annha.cameras SET retired_at=now() WHERE id=%s',(camera_id,))
        conn.execute('UPDATE annha_private.device_credentials SET revoked_at=now() WHERE camera_id=%s',(camera_id,));db.audit(conn,home,current['id'],'camera.remove',camera_id)
    with db.connect('worker',home) as conn:
        conn.execute("UPDATE annha.commands SET status='expired' WHERE camera_id=%s AND status IN ('pending','accepted')",(camera_id,))
    await svc.close_home_connections(camera['home_id']);return {'message':'Đã gỡ thiết bị, giữ lịch sử và thu hồi credential.'}

@router.get('/homes/{home_id}/members')
def members(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('auth') as conn:
        rows=conn.execute('SELECT u.id,u.name,u.email FROM annha_private.users u JOIN annha_private.home_memberships m ON m.user_id=u.id WHERE m.home_id=%s AND m.revoked_at IS NULL',(home_id,)).fetchall()
    return [{**dict(row),**membership(home_id,str(row['id'])),'id':row['id']} for row in rows]

@router.patch('/homes/{home_id}/members/{user_id}')
async def update_member(home_id:str,user_id:str,payload:m.Access,current:Current):
    membership(home_id,current['id'],True)
    if membership(home_id,user_id)['role']=='owner': raise HTTPException(409,'Không thay đổi chủ nhà bằng thao tác này.')
    with db.connect('auth',home_id,current['id']) as conn:
        grant_rows(conn,home_id,user_id,payload)
        conn.execute('UPDATE annha_private.home_memberships SET role=%s,version=version+1 WHERE home_id=%s AND user_id=%s',(payload.role,home_id,user_id));db.audit(conn,home_id,current['id'],'member.update',user_id)
    await svc.close_home_connections(home_id);return {'message':'Đã cập nhật quyền.'}

@router.delete('/homes/{home_id}/members/{user_id}')
async def remove_member(home_id:str,user_id:str,current:Current):
    membership(home_id,current['id'],True)
    if membership(home_id,user_id)['role']=='owner': raise HTTPException(409,'Không thể thu hồi chủ nhà.')
    with db.connect('auth',home_id,current['id']) as conn:
        conn.execute('UPDATE annha_private.home_memberships SET revoked_at=now(),version=version+1 WHERE home_id=%s AND user_id=%s',(home_id,user_id))
        conn.execute("UPDATE annha_private.invitations SET status='revoked' WHERE home_id=%s AND email=(SELECT email FROM annha_private.users WHERE id=%s) AND status='pending'",(home_id,user_id));db.audit(conn,home_id,current['id'],'member.revoke',user_id)
    await svc.close_home_connections(home_id);return {'message':'Đã thu hồi quyền.'}

@router.get('/homes/{home_id}/invitations')
def invitations(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('auth') as conn: return [{**dict(row),'expires':row['expires_at'].timestamp()} for row in conn.execute('SELECT id,email,role,expires_at,status FROM annha_private.invitations WHERE home_id=%s ORDER BY created_at DESC',(home_id,))]

@router.post('/homes/{home_id}/invitations',status_code=201)
def invite(home_id:str,payload:m.Invite,current:Current):
    membership(home_id,current['id'],True);throttle('invite:'+current['id'],20,3600);token=secrets.token_urlsafe(32)
    with db.connect('auth',home_id,current['id']) as conn:
        scopes(conn,home_id,payload.scopes)
        conn.execute("UPDATE annha_private.invitations SET status='expired' WHERE home_id=%s AND email=%s AND status='pending' AND expires_at<=now()",(home_id,payload.email))
        row=conn.execute('INSERT INTO annha_private.invitations(home_id,email,role,token_hash,invited_by,expires_at) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',(home_id,payload.email,payload.role,digest(token),current['id'],db.now()+timedelta(days=7))).fetchone()
        for camera in payload.scopes:
            conn.execute('INSERT INTO annha_private.invitation_camera_grants(home_id,invitation_id,camera_id,can_handle_events,can_play_audio,can_edit_reminders) VALUES(%s,%s,%s,%s,%s,%s)',
                (home_id,row['id'],camera,payload.role=='caregiver',payload.role=='caregiver' and payload.rights.get('audio',False),payload.role=='caregiver' and payload.rights.get('schedules',False)))
        svc.mail(conn,payload.email,'Lời mời tham gia AnNhà',os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')+'/#/invitation?token='+token,'invitation');db.audit(conn,home_id,current['id'],'invitation.create',row['id'])
    return {'id':row['id'],'message':'Đã tạo lời mời và xếp hàng gửi email.'}

def invitation_data(token,current,conn,lock=False):
    row=conn.execute('SELECT * FROM annha_private.invitations WHERE token_hash=%s'+(' FOR UPDATE' if lock else ''),(digest(token),)).fetchone()
    if not row or row['email']!=current['email']: raise HTTPException(404,'Không tìm thấy lời mời cho tài khoản này.')
    return row

@router.get('/invitations/{token}')
def invitation(token:str,current:Current):
    with db.connect('auth') as conn:
        row=invitation_data(token,current,conn);grants=conn.execute('SELECT * FROM annha_private.invitation_camera_grants WHERE invitation_id=%s',(row['id'],)).fetchall()
        name=conn.execute('SELECT name FROM annha.homes WHERE id=%s',(row['home_id'],)).fetchone()['name']
    return {**{key:row[key] for key in ('id','home_id','role','status')},'home_name':name,'expires':row['expires_at'].timestamp(),
        'scopes':__import__('json').dumps([str(g['camera_id']) for g in grants]),'rights':__import__('json').dumps({'audio':any(g['can_play_audio'] for g in grants),'schedules':any(g['can_edit_reminders'] for g in grants)})}

@router.post('/invitations/{token}/{action}')
def invitation_action(token:str,action:str,current:Current):
    if action not in ('accept','decline'): raise HTTPException(404,'Không tìm thấy thao tác.')
    with db.connect('auth',user=current['id']) as conn:
        row=invitation_data(token,current,conn,True)
        if row['status']!='pending' or row['expires_at']<=db.now(): raise HTTPException(400,'Lời mời hết hạn hoặc đã được sử dụng.')
        home=str(row['home_id']);conn.execute("SELECT set_config('app.home_id',%s,true)",(home,))
        if action=='accept':
            existing=conn.execute('SELECT * FROM annha_private.home_memberships WHERE home_id=%s AND user_id=%s',(home,current['id'])).fetchone()
            if existing and not existing['revoked_at']: raise HTTPException(409,'Bạn đã là thành viên.')
            conn.execute('''INSERT INTO annha_private.home_memberships(home_id,user_id,role,granted_by) VALUES(%s,%s,%s,%s)
              ON CONFLICT(home_id,user_id) DO UPDATE SET revoked_at=NULL,role=excluded.role,version=annha_private.home_memberships.version+1''',(home,current['id'],row['role'],row['invited_by']))
            conn.execute('DELETE FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s',(home,current['id']))
            conn.execute('''INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_view,can_handle_events,can_play_audio,can_edit_reminders)
              SELECT home_id,camera_id,%s,can_view,can_handle_events,can_play_audio,can_edit_reminders FROM annha_private.invitation_camera_grants WHERE invitation_id=%s''',(current['id'],row['id']))
        conn.execute('UPDATE annha_private.invitations SET status=%s,accepted_by=%s,accepted_at=%s WHERE id=%s',('accepted' if action=='accept' else 'declined',current['id'] if action=='accept' else None,db.now() if action=='accept' else None,row['id']))
        db.audit(conn,home,current['id'],'invitation.'+action,row['id'])
    return {'home_id':home,'message':'Đã xử lý lời mời.'}

@router.delete('/homes/{home_id}/invitations/{invitation_id}')
def revoke_invitation(home_id:str,invitation_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('auth',home_id,current['id']) as conn:
        row=conn.execute("UPDATE annha_private.invitations SET status='revoked' WHERE id=%s AND home_id=%s AND status='pending' RETURNING id",(invitation_id,home_id)).fetchone();fail_if_missing(row)
        db.audit(conn,home_id,current['id'],'invitation.revoke',invitation_id)
    return {'message':'Đã thu hồi lời mời.'}

@router.get('/cameras/{camera_id}/config')
def config(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'])
    with db.connect('app',camera['home_id'],current['id']) as conn:
        state=conn.execute('SELECT * FROM annha.camera_config_state WHERE camera_id=%s',(camera_id,)).fetchone() or {}
        row=conn.execute('SELECT payload FROM annha.camera_configurations WHERE camera_id=%s ORDER BY version DESC LIMIT 1',(camera_id,)).fetchone()
    return {'desired_version':state.get('desired_version',0),'applied_version':state.get('applied_version') or 0,'error':state.get('error'),'payload':row['payload'] if row else {'zones':[],'reference':{}}}

@router.get('/homes/{home_id}/events')
def events(home_id:str,current:Current,limit:int=100,status:str|None=None):
    membership(home_id,current['id'])
    if not 1<=limit<=500: raise HTTPException(422,'Giới hạn không hợp lệ.')
    with db.connect('app',home_id,current['id']) as conn:
        rows=conn.execute('SELECT * FROM annha.events WHERE (%s::text IS NULL OR status=%s) ORDER BY received_at DESC,id DESC LIMIT %s',(status,status,limit)).fetchall()
        return [svc.event_public(conn,row) for row in rows]

def event_scope(event_id,current,action='view'):
    # Resolve the tenant from trusted records, then enforce RLS and camera permission.
    with db.connect('auth') as auth:
        homes=[str(row['home_id']) for row in auth.execute('SELECT home_id FROM annha_private.home_memberships WHERE user_id=%s AND revoked_at IS NULL',(current['id'],))]
    for home in homes:
        with db.connect('app',home,current['id']) as conn:
            row=conn.execute('SELECT * FROM annha.events WHERE id=%s',(event_id,)).fetchone()
            if row:
                camera_access(str(row['camera_id']),current['id'],action,True)
                return home
    raise HTTPException(404,'Không tìm thấy sự kiện.')

@router.get('/events/{event_id}')
def get_event(event_id:str,current:Current):
    home=event_scope(event_id,current)
    with db.connect('app',home,current['id']) as conn: return svc.event_public(conn,conn.execute('SELECT * FROM annha.events WHERE id=%s',(event_id,)).fetchone())

@router.post('/events/{event_id}/actions')
async def event_action(event_id:str,payload:m.Action,current:Current):
    home=event_scope(event_id,current,'events');command=None
    with db.connect('app',home,current['id']) as conn:
        row=conn.execute('SELECT * FROM annha.events WHERE id=%s FOR UPDATE',(event_id,)).fetchone()
        closing=payload.action in ('resolve','safe','false_alarm')
        if closing and row['observation'] in ('abnormal','suspected') and (not payload.confirm_abnormal or not payload.note): raise HTTPException(409,'Còn bất thường; cần xác nhận và ghi chú.')
        if row['status'] in ('RESOLVED','FALSE_ALARM') and payload.action!='note': raise HTTPException(409,'Sự kiện đã kết thúc.')
        if payload.action=='acknowledge': conn.execute("UPDATE annha.events SET status='ACKNOWLEDGED',updated_at=now() WHERE id=%s",(event_id,))
        if closing: conn.execute('UPDATE annha.events SET status=%s,updated_at=now() WHERE id=%s',('FALSE_ALARM' if payload.action=='false_alarm' else 'RESOLVED',event_id))
        if payload.action=='silence':
            if row['kind']=='environment' and row['observation']=='abnormal': raise HTTPException(409,'Không tắt cảnh báo môi trường còn bất thường.')
            command=db.uid();conn.execute("INSERT INTO annha.commands(id,home_id,camera_id,requested_by,idempotency_key,kind,payload,expires_at) VALUES(%s,%s,%s,%s,%s,'silence',%s,%s)",(command,home,row['camera_id'],current['id'],db.uid(),db.J({'seconds':60,'event_id':event_id}),db.now()+timedelta(seconds=60)))
        conn.execute('INSERT INTO annha.event_actions(home_id,camera_id,event_id,user_id,action,note,confirmed_abnormal,silence_until,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (home,row['camera_id'],event_id,current['id'],payload.action,payload.note,payload.confirm_abnormal,db.now()+timedelta(seconds=60) if command else None,db.uid()))
        db.audit(conn,home,current['id'],'event.'+payload.action,event_id)
        result=svc.event_public(conn,conn.execute('SELECT * FROM annha.events WHERE id=%s',(event_id,)).fetchone())
    await svc.broadcast(result);return result

@router.get('/cameras/{camera_id}/telemetry')
def telemetry(camera_id:str,current:Current,limit:int=100):
    camera=camera_access(camera_id,current['id'])
    if not 1<=limit<=1000: raise HTTPException(422,'Giới hạn không hợp lệ.')
    with db.connect('app',camera['home_id'],current['id']) as conn:
        rows=conn.execute('SELECT * FROM annha.telemetry_batches WHERE camera_id=%s ORDER BY received_at DESC,id DESC LIMIT %s',(camera_id,limit)).fetchall()
        result=[]
        for row in rows:
            readings={r['metric']:{key:r[key] for key in ('value','unit','quality')} for r in conn.execute('SELECT * FROM annha.sensor_readings WHERE batch_id=%s',(row['id'],))}
            result.append({**dict(row),'payload':{'observed_at':row['observed_at'],'readings':readings}})
        return result

class Settings(m.Settings):
    email_enabled: bool=False

@router.get('/homes/{home_id}/settings')
def settings(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('worker',home_id) as conn:
        base=dict(conn.execute('SELECT * FROM annha.home_settings WHERE home_id=%s',(home_id,)).fetchone())
        base.pop('home_id');base.pop('updated_at');base.pop('telemetry_retention_days');base.pop('event_retention_days')
        channels=conn.execute('SELECT * FROM annha.notification_channels WHERE revoked_at IS NULL AND recipient_user_id=%s',(current['id'],)).fetchall()
        base.update(telegram_enabled=False,telegram_chat_id='',telegram_photos=False,email_enabled=False)
        for channel in channels:
            if channel['kind']=='email': base['email_enabled']=channel['enabled'] and not channel['suppressed_at']
            else:
                secret=conn.execute('SELECT destination_ciphertext FROM annha_private.notification_secrets WHERE channel_id=%s',(channel['id'],)).fetchone()
                base.update(telegram_enabled=channel['enabled'],telegram_photos=channel['allow_media'],telegram_chat_id=svc.decrypt(secret['destination_ciphertext'])['chat_id'] if secret else '')
    return base

@router.put('/homes/{home_id}/settings')
def save_settings(home_id:str,payload:Settings,current:Current):
    membership(home_id,current['id'],True);values=payload.model_dump()
    columns=['retention_days','temperature_high','temperature_low','humidity_high','gas_high','gas_unit','environment_hold_seconds','hysteresis']
    with db.connect('app',home_id,current['id']) as conn:
        conn.execute('UPDATE annha.home_settings SET '+','.join(key+'=%s' for key in columns)+',telemetry_retention_days=%s,updated_at=now() WHERE home_id=%s',[values[key] for key in columns]+[payload.retention_days,home_id])
        for kind,enabled in [('email',payload.email_enabled),('telegram',payload.telegram_enabled)]:
            row=conn.execute('SELECT * FROM annha.notification_channels WHERE recipient_user_id=%s AND kind=%s AND revoked_at IS NULL FOR UPDATE',(current['id'],kind)).fetchone()
            version=current['email_version'] if kind=='email' else None
            channel=str(row['id']) if row else db.uid()
            media=payload.telegram_photos if kind=='telegram' else False
            if row: conn.execute('UPDATE annha.notification_channels SET enabled=%s,email_version=%s,allow_media=%s,media_consent_at=%s,consent_by=%s WHERE id=%s',(enabled,version,media,db.now() if media else None,current['id'] if media else None,channel))
            else: conn.execute('''INSERT INTO annha.notification_channels(id,home_id,recipient_user_id,kind,label,enabled,email_version,allow_media,media_consent_at,consent_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(channel,home_id,current['id'],kind,kind,enabled,version,media,db.now() if media else None,current['id'] if media else None))
        db.audit(conn,home_id,current['id'],'settings.update',home_id)
    with db.connect('worker',home_id) as conn:
        for channel in conn.execute("SELECT id FROM annha.notification_channels WHERE recipient_user_id=%s AND kind='telegram' AND revoked_at IS NULL",(current['id'],)):
            conn.execute('''INSERT INTO annha_private.notification_secrets(home_id,channel_id,destination_ciphertext,key_id) VALUES(%s,%s,%s,%s)
                ON CONFLICT(channel_id) DO UPDATE SET destination_ciphertext=excluded.destination_ciphertext,key_id=excluded.key_id''',(home_id,channel['id'],svc.encrypt({'chat_id':payload.telegram_chat_id}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary')))
        cameras=[str(r['id']) for r in conn.execute('SELECT id FROM annha.cameras WHERE retired_at IS NULL')]
    for camera in cameras: svc.compile_config(home_id,camera)
    return values

@router.get('/homes/{home_id}/assets')
def assets(home_id:str,current:Current):
    membership(home_id,current['id'])
    with db.connect('app',home_id,current['id']) as conn: return [svc.asset_public(row) for row in conn.execute('SELECT * FROM annha.media_assets ORDER BY created_at DESC')]

def asset_scope(asset_id,current,action='view'):
    with db.connect('auth') as auth: homes=[str(r['home_id']) for r in auth.execute('SELECT home_id FROM annha_private.home_memberships WHERE user_id=%s AND revoked_at IS NULL',(current['id'],))]
    for home in homes:
        with db.connect('app',home,current['id']) as conn:
            row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(asset_id,)).fetchone()
            if row:
                camera_access(str(row['camera_id']),current['id'],action,True);return home,row
    raise HTTPException(404,'Không tìm thấy file.')

async def write_asset(request,home,camera,event=None,current=None):
    mime=request.headers.get('content-type','').split(';')[0]
    extensions={'image/jpeg':'.jpg','image/png':'.png','video/mp4':'.mp4','video/webm':'.webm','audio/webm':'.webm','audio/mpeg':'.mp3','audio/wav':'.wav','audio/ogg':'.ogg'}
    if mime not in extensions: raise HTTPException(415,'Định dạng chưa hỗ trợ.')
    asset=db.uid();path=db.MEDIA_ROOT/(asset+extensions[mime]);size=0;prefix=b''
    from urllib.parse import unquote
    name=unquote(request.headers.get('x-file-name','Tài nguyên'))[:160] or 'Tài nguyên'
    try:
        with path.open('wb') as output:
            async for chunk in request.stream():
                size+=len(chunk)
                if size>26214400: raise HTTPException(413,'File vượt quá 25 MiB.')
                output.write(chunk)
                if len(prefix)<16: prefix=(prefix+chunk)[:16]
        valid={'image/jpeg':prefix.startswith(b'\xff\xd8\xff'),'image/png':prefix.startswith(b'\x89PNG\r\n\x1a\n'),
            'video/mp4':prefix[4:8]==b'ftyp','video/webm':prefix.startswith(b'\x1aE\xdf\xa3'),'audio/webm':prefix.startswith(b'\x1aE\xdf\xa3'),
            'audio/wav':prefix.startswith(b'RIFF') and prefix[8:12]==b'WAVE','audio/ogg':prefix.startswith(b'OggS'),'audio/mpeg':prefix.startswith(b'ID3') or prefix[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2')}
        if not valid.get(mime): raise HTTPException(415,'Nội dung không khớp định dạng.')
        kind='audio' if mime.startswith('audio/') else ('event_clip' if mime.startswith('video/') else ('event_image' if event else 'snapshot'))
        with db.connect('worker',home,camera=camera) as conn:
            if not conn.execute('UPDATE annha.home_storage SET used_bytes=used_bytes+%s WHERE home_id=%s AND used_bytes+reserved_bytes+%s<=quota_bytes RETURNING home_id',(size,home,size)).fetchone(): raise HTTPException(413,'Dung lượng lưu trữ của nhà đã hết.')
            retention=conn.execute('SELECT retention_days FROM annha.home_settings WHERE home_id=%s',(home,)).fetchone()['retention_days']
            conn.execute('''INSERT INTO annha.media_assets(id,home_id,camera_id,event_id,kind,name,mime_type,size_bytes,status,provider,local_object_key,ready_at,expires_at,upload_key,created_by,sha256)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'ready','local',%s,now(),%s,%s,%s,%s)''',
                (asset,home,camera,event,kind,name,mime,size,path.name,db.now()+timedelta(days=retention) if event or kind=='snapshot' else None,db.uid(),current['id'] if current else None,hashlib.sha256(path.read_bytes()).digest()))
        return {'id':asset,'mime':mime,'size':size,'name':name,'status':'ready'}
    except Exception:
        path.unlink(missing_ok=True);raise

@router.post('/cameras/{camera_id}/assets',status_code=201)
async def upload_audio(camera_id:str,request:Request,current:Current):
    camera=camera_access(camera_id,current['id'],'audio')
    if not request.headers.get('content-type','').startswith('audio/'): raise HTTPException(415,'Chỉ tải file âm thanh.')
    return await write_asset(request,camera['home_id'],camera_id,current=current)

@router.get('/assets/{asset_id}')
def asset_file(asset_id:str,current:Current):
    _,asset=asset_scope(asset_id,current)
    return FileResponse(svc.asset_path(asset),media_type=asset['mime_type'],headers={'Cache-Control':'private, no-store'})

@router.delete('/assets/{asset_id}')
def delete_asset(asset_id:str,current:Current):
    home,asset=asset_scope(asset_id,current,'manage')
    with db.connect('worker',home) as conn:
        row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
        if conn.execute('''SELECT 1 FROM annha.reminder_revisions v JOIN annha.reminders r ON r.id=v.reminder_id AND r.current_version=v.version
             WHERE v.asset_id=%s AND r.deleted_at IS NULL''',(asset_id,)).fetchone(): raise HTTPException(409,'File còn được dùng trong lịch nhắc.')
        if row['status'] in ('deleted','expired'): return {'message':'File đã ngừng sử dụng.'}
        if row['local_object_key']: (db.MEDIA_ROOT/Path(row['local_object_key']).name).unlink(missing_ok=True)
        conn.execute('UPDATE annha.home_storage SET used_bytes=used_bytes-%s,reserved_bytes=reserved_bytes-%s WHERE home_id=%s',(row['size_bytes'] or 0 if row['status']=='ready' else 0,row['reserved_bytes'],home))
        conn.execute("UPDATE annha.media_assets SET status='deleted',deleted_at=now(),reserved_bytes=0 WHERE id=%s",(asset_id,));db.audit(conn,home,current['id'],'asset.delete',asset_id)
    return {'message':'Đã xoá file, giữ metadata lịch sử.'}

@router.get('/homes/{home_id}/reminders')
def reminders(home_id:str,current:Current):
    membership(home_id,current['id'])
    with db.connect('app',home_id,current['id']) as conn: return svc.reminder_rows(conn,home_id)

def save_reminder(home,payload,current,reminder_id=None):
    camera=camera_access(payload.camera_id,current['id'],'schedules')
    if camera['home_id']!=home: raise HTTPException(422,'Camera không thuộc nhà.')
    reminder=reminder_id or db.uid();asset=payload.asset_id;new_tts=False
    with db.connect('app',home,current['id']) as conn:
        old=conn.execute('SELECT * FROM annha.reminders WHERE id=%s FOR UPDATE',(reminder,)).fetchone()
        if reminder_id and not old: raise HTTPException(404,'Không tìm thấy lịch.')
        if old and str(old['camera_id'])!=payload.camera_id: raise HTTPException(422,'Để đổi camera, hãy tạo lịch mới; giữ lịch sử lịch cũ.')
        if payload.source=='audio':
            fail_if_missing(conn.execute("SELECT id FROM annha.media_assets WHERE id=%s AND camera_id=%s AND status='ready' AND kind IN ('audio','tts')",(asset,payload.camera_id)).fetchone(),'Âm thanh chưa sẵn sàng hoặc thuộc camera khác.')
        else:
            previous=conn.execute('SELECT * FROM annha.reminder_revisions WHERE reminder_id=%s AND version=%s',(reminder,old['current_version'])).fetchone() if old else None
            if previous and previous['source']=='tts' and previous['text_content']==payload.text: asset=str(previous['asset_id'])
            else:
                new_tts=True;asset=db.uid()
                conn.execute("INSERT INTO annha.media_assets(id,home_id,camera_id,kind,name,mime_type,status,provider,upload_key,created_by) VALUES(%s,%s,%s,'tts',%s,'audio/wav','processing','local',%s,%s)",(asset,home,payload.camera_id,payload.name+'.wav',db.uid(),current['id']))
        version=old['current_version']+1 if old else 1
        if old: conn.execute('UPDATE annha.reminders SET name=%s,enabled=%s,current_version=%s,updated_at=now(),deleted_at=NULL WHERE id=%s',(payload.name,payload.enabled,version,reminder))
        else: conn.execute('INSERT INTO annha.reminders(id,home_id,camera_id,name,enabled,current_version,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s)',(reminder,home,payload.camera_id,payload.name,payload.enabled,version,current['id']))
        conn.execute('''INSERT INTO annha.reminder_revisions(home_id,camera_id,reminder_id,version,local_time,timezone,weekdays,once_date,source,text_content,asset_id,volume,late_seconds)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(home,payload.camera_id,reminder,version,payload.time,payload.timezone,payload.weekdays if not payload.once_date else [],payload.once_date,payload.source,payload.text or None,asset,payload.volume,payload.late_seconds))
        db.audit(conn,home,current['id'],'reminder.save',reminder)
    if new_tts:
        with db.connect('worker',home) as conn:
            conn.execute("INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,secret_ciphertext,key_id,idempotency_key) VALUES(%s,'tts',%s,%s,%s,%s,%s)",(home,asset,db.J({'camera_id':payload.camera_id}),svc.encrypt({'text':payload.text}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary'),'tts:'+asset))
    svc.compile_config(home,payload.camera_id)
    return {'id':reminder,'status':'pending','asset_id':asset}

@router.post('/homes/{home_id}/reminders',status_code=201)
def create_reminder(home_id:str,payload:m.Reminder,current:Current): return save_reminder(home_id,payload,current)

@router.put('/reminders/{reminder_id}')
def update_reminder(reminder_id:str,payload:m.Reminder,current:Current):
    camera=camera_access(payload.camera_id,current['id'],'schedules')
    return save_reminder(camera['home_id'],payload,current,reminder_id)

@router.delete('/reminders/{reminder_id}')
def remove_reminder(reminder_id:str,current:Current):
    with db.connect('auth') as auth: homes=[str(r['home_id']) for r in auth.execute('SELECT home_id FROM annha_private.home_memberships WHERE user_id=%s AND revoked_at IS NULL',(current['id'],))]
    for home in homes:
        with db.connect('app',home,current['id']) as conn:
            row=conn.execute('SELECT * FROM annha.reminders WHERE id=%s',(reminder_id,)).fetchone()
            if not row: continue
            camera_access(str(row['camera_id']),current['id'],'schedules')
            conn.execute('UPDATE annha.reminders SET deleted_at=now(),enabled=false,updated_at=now() WHERE id=%s',(reminder_id,));db.audit(conn,home,current['id'],'reminder.delete',reminder_id)
        svc.compile_config(home,str(row['camera_id']));return {'message':'Đã xoá lịch, giữ lịch sử thực thi.'}
    raise HTTPException(404,'Không tìm thấy lịch nhắc.')

@router.get('/homes/{home_id}/executions')
def executions(home_id:str,current:Current):
    membership(home_id,current['id'])
    with db.connect('app',home_id,current['id']) as conn: return conn.execute('SELECT *,received_at AS created_at,occurrence_key AS occurrence FROM annha.reminder_executions ORDER BY received_at DESC LIMIT 200').fetchall()

@router.post('/cameras/{camera_id}/commands',status_code=201)
def command(camera_id:str,payload:m.Command,current:Current):
    camera=camera_access(camera_id,current['id'],'audio');home=camera['home_id']
    if payload.kind=='silence': raise HTTPException(422,'Hãy tắt âm từ đúng sự kiện.')
    body={'asset_id':payload.asset_id,'volume':payload.volume}
    with db.connect('app',home,current['id']) as conn:
        if payload.asset_id: fail_if_missing(conn.execute("SELECT id FROM annha.media_assets WHERE id=%s AND camera_id=%s AND status='ready' AND kind IN ('audio','tts')",(payload.asset_id,camera_id)).fetchone(),'File chưa sẵn sàng hoặc thuộc camera khác.')
        old=conn.execute('SELECT * FROM annha.commands WHERE requested_by=%s AND idempotency_key=%s',(current['id'],payload.idempotency_key)).fetchone()
        if old:
            if str(old['camera_id'])!=camera_id or old['kind']!=payload.kind or old['payload']!=body: raise HTTPException(409,'Mã lệnh đã dùng cho nội dung khác.')
            return {'id':old['id'],'status':old['status']}
        row=conn.execute('INSERT INTO annha.commands(home_id,camera_id,requested_by,idempotency_key,kind,asset_id,payload,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,status',(home,camera_id,current['id'],payload.idempotency_key,payload.kind,payload.asset_id,db.J(body),db.now()+timedelta(seconds=payload.ttl_seconds))).fetchone()
        db.audit(conn,home,current['id'],'command.create',row['id'])
    return row

@router.get('/cameras/{camera_id}/commands')
def commands(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'],'audio')
    with db.connect('app',camera['home_id'],current['id']) as conn:
        return [{**dict(row),'expires':row['expires_at'].timestamp()} for row in conn.execute('SELECT * FROM annha.commands WHERE camera_id=%s ORDER BY created_at DESC LIMIT 50',(camera_id,))]

@router.get('/homes/{home_id}/audit')
def audit(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn: return conn.execute('SELECT * FROM annha.audit_logs ORDER BY created_at DESC LIMIT 200').fetchall()

@router.get('/homes/{home_id}/delivery-status')
def deliveries(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn: return conn.execute('SELECT *,attempt_count AS attempts,last_error_code AS error FROM annha.notification_deliveries ORDER BY created_at DESC LIMIT 200').fetchall()

# Device identity comes from the registered token, never from a supplied tenant ID.
@router.post('/device/heartbeat')
def heartbeat(payload:m.Heartbeat,current:Device):
    with db.connect('worker',current['home_id'],camera=current['id']) as conn:
        conn.execute('UPDATE annha.cameras SET last_seen_at=now(),observation=%s,capabilities=%s WHERE id=%s',(payload.observation,db.J(payload.capabilities),current['id']))
        state=conn.execute('SELECT desired_version FROM annha.camera_config_state WHERE camera_id=%s',(current['id'],)).fetchone()
    return {'server_time':db.now(),'desired_version':state['desired_version'] if state else 0}

@router.get('/device/config')
def device_config(current:Device):
    with db.connect('device',current['home_id'],camera=current['id']) as conn:
        row=conn.execute('SELECT payload FROM annha.camera_configurations WHERE camera_id=%s ORDER BY version DESC LIMIT 1',(current['id'],)).fetchone()
    return row['payload'] if row else {'version':0,'reminders':[],'zones':[],'reference':{}}

@router.post('/device/config/ack')
def config_ack(payload:m.ConfigAck,current:Device):
    with db.connect('worker',current['home_id'],camera=current['id']) as conn:
        state=conn.execute('SELECT * FROM annha.camera_config_state WHERE camera_id=%s FOR UPDATE',(current['id'],)).fetchone()
        if not state or not conn.execute('SELECT 1 FROM annha.camera_configurations WHERE camera_id=%s AND version=%s',(current['id'],payload.version)).fetchone(): raise HTTPException(422,'Không có phiên bản cấu hình này.')
        if payload.version<(state['applied_version'] or 0): raise HTTPException(409,'Phản hồi cấu hình cũ.')
        conn.execute('INSERT INTO annha.config_acknowledgements(home_id,camera_id,message_id,version,success,error) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(current['home_id'],current['id'],f'{payload.version}:{payload.success}:{hashlib.sha256(payload.error.encode()).hexdigest()}',payload.version,payload.success,payload.error))
        if payload.success: conn.execute('UPDATE annha.camera_config_state SET applied_version=%s,applied_at=now(),error=NULL WHERE camera_id=%s',(payload.version,current['id']))
        else: conn.execute('UPDATE annha.camera_config_state SET error=%s WHERE camera_id=%s',(payload.error or 'Thiết bị từ chối cấu hình',current['id']))
    return {'message':'Đã ghi nhận phản hồi.'}

@router.post('/device/events')
async def device_event(payload:m.EventInput,current:Device):
    import asyncio
    event,changed=await asyncio.to_thread(svc.ingest_event,current,payload)
    if changed: await svc.broadcast(event)
    return {'id':event['id'],'event_id':payload.event_id,'sequence':event['sequence'],'stored':True}

@router.post('/device/telemetry')
def device_telemetry(payload:m.Telemetry,current:Device):
    with db.connect('worker',current['home_id'],camera=current['id']) as conn:
        batch=conn.execute('INSERT INTO annha.telemetry_batches(home_id,camera_id,message_id,observed_at) VALUES(%s,%s,%s,%s) ON CONFLICT(camera_id,message_id) DO NOTHING RETURNING id',(current['home_id'],current['id'],payload.message_id,datetime.fromisoformat(payload.observed_at))).fetchone()
        if batch:
            for metric,value in payload.readings.items():
                conn.execute('INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality) VALUES(%s,%s,%s,%s,%s,%s,%s)',(current['home_id'],current['id'],batch['id'],metric,value.value,value.unit,value.quality))
    if batch: svc.evaluate_environment(current,payload)
    return {'stored':True,'message_id':payload.message_id}

@router.get('/device/commands')
def device_commands(current:Device):
    with db.connect('worker',current['home_id'],camera=current['id']) as conn:
        conn.execute("UPDATE annha.commands SET status='expired' WHERE camera_id=%s AND expires_at<now() AND status IN ('pending','accepted')",(current['id'],))
        return [{**dict(row),'expires':row['expires_at'].timestamp()} for row in conn.execute("SELECT * FROM annha.commands WHERE camera_id=%s AND status IN ('pending','accepted') AND expires_at>now() ORDER BY created_at",(current['id'],))]

@router.post('/device/commands/{command_id}/ack')
def command_ack(command_id:str,payload:m.CommandAck,current:Device):
    with db.connect('device',current['home_id'],camera=current['id']) as conn:
        row=fail_if_missing(conn.execute('SELECT * FROM annha.commands WHERE id=%s AND camera_id=%s FOR UPDATE',(command_id,current['id'])).fetchone())
        if row['status'] in ('executed','failed','expired'):
            if row['status']==payload.status: return {'status':row['status']}
            raise HTTPException(409,'Lệnh đã kết thúc.')
        if row['expires_at']<db.now() and row['status']!='executing': raise HTTPException(409,'Lệnh đã hết hạn.')
        stages={'pending':0,'accepted':1,'executing':2,'executed':3,'failed':3}
        if stages.get(row['status'],0)>stages[payload.status]: raise HTTPException(409,'Không được lùi trạng thái lệnh.')
        conn.execute('UPDATE annha.commands SET status=%s,result=%s,accepted_at=COALESCE(accepted_at,now()),completed_at=CASE WHEN %s THEN now() ELSE completed_at END WHERE id=%s',(payload.status,db.J({'detail':payload.detail}),payload.status in ('executed','failed'),command_id))
    return {'status':payload.status}

@router.post('/device/executions')
def execution(payload:m.Execution,current:Device):
    with db.connect('device',current['home_id'],camera=current['id']) as conn:
        reminder=fail_if_missing(conn.execute('SELECT * FROM annha.reminders WHERE id=%s AND camera_id=%s',(payload.reminder_id,current['id'])).fetchone())
        conn.execute('''INSERT INTO annha.reminder_executions(home_id,camera_id,reminder_id,reminder_version,occurrence_key,scheduled_at,executed_at,status,detail)
            VALUES(%s,%s,%s,%s,%s,now(),now(),%s,%s) ON CONFLICT(camera_id,reminder_id,occurrence_key) DO NOTHING''',(current['home_id'],current['id'],payload.reminder_id,reminder['current_version'],payload.occurrence,payload.status,payload.detail))
    return {'stored':True}

@router.get('/device/assets/{asset_id}')
def device_asset(asset_id:str,current:Device):
    with db.connect('device',current['home_id'],camera=current['id']) as conn:
        row=fail_if_missing(conn.execute('SELECT * FROM annha.media_assets WHERE id=%s AND camera_id=%s',(asset_id,current['id'])).fetchone())
        return FileResponse(svc.asset_path(row),media_type=row['mime_type'],headers={'Cache-Control':'no-store'})

@router.post('/device/evidence',status_code=201)
async def evidence(request:Request,current:Device,event_id:str|None=None):
    if event_id:
        with db.connect('worker',current['home_id'],camera=current['id']) as conn:
            fail_if_missing(conn.execute('SELECT id FROM annha.events WHERE id=%s AND camera_id=%s',(event_id,current['id'])).fetchone())
    elif not request.headers.get('content-type','').startswith('image/'): raise HTTPException(422,'Cần sự kiện đích cho clip bằng chứng.')
    return await write_asset(request,current['home_id'],current['id'],event_id)

@router.get('/cameras/{camera_id}/snapshot')
def snapshot(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'])
    with db.connect('app',camera['home_id'],current['id']) as conn:
        row=fail_if_missing(conn.execute("SELECT * FROM annha.media_assets WHERE camera_id=%s AND mime_type LIKE 'image/%%' AND status='ready' ORDER BY created_at DESC LIMIT 1",(camera_id,)).fetchone(),'Thiết bị chưa gửi hình ảnh.')
        return FileResponse(svc.asset_path(row),media_type=row['mime_type'],headers={'Cache-Control':'no-store','X-Captured-At':row['created_at'].isoformat()})
