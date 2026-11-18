"""AnNhà HTTP API backed by the normalized Neon/PostgreSQL schema."""
from datetime import datetime,timedelta
import asyncio
import hashlib
import os
import psycopg
import secrets
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from fastapi.encoders import jsonable_encoder
from . import device_pairing
from . import models as m, pgdb as db, pgservices as svc, media_storage
from .pgsecurity import COOKIE,SESSION_SECONDS,camera_access,csrf_for,device,digest,effective_camera_permissions,membership,password_hash,password_matches,public_user,session_user,throttle,user,verification_code_digest,reset_code_digest

from .web_queries import page_result,select_page,time_range,asset_usage
from .demo_metadata import demo_home

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
        rights=payload.rights_for_camera(camera).model_dump() if payload.role=='caregiver' else {'audio':False,'schedules':False}
        conn.execute('''INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_view,can_handle_events,can_play_audio,can_edit_reminders)
          VALUES(%s,%s,%s,true,%s,%s,%s)''',(home,camera,account,payload.role=='caregiver',rights['audio'],rights['schedules']))

@router.post('/auth/register',status_code=201)
def register(payload:m.Register,request:Request):
    throttle('register:'+str(request.client.host),5,3600)
    with db.connect('auth') as conn:
        row=conn.execute('INSERT INTO annha_private.users(email,name,password_hash) VALUES(%s,%s,%s) RETURNING *',(payload.email,payload.name,password_hash(payload.password))).fetchone()
        svc.queue_email(conn,row,'verify_email')
    return {'message':'Đã tạo tài khoản. Vui lòng mở email để xác minh.'}

@router.post('/auth/verify')
def verify(payload:m.VerifyEmail,request:Request):
    if payload.code:
        client=request.client.host if request.client else 'unknown'
        throttle('verify-code:'+client,5,900)
    token_hash=verification_code_digest(payload.code) if payload.code else digest(payload.token)
    with db.connect('auth') as conn:
        token=conn.execute("SELECT * FROM annha_private.email_tokens WHERE token_hash=%s AND purpose='verify_email' AND consumed_at IS NULL AND expires_at>now() FOR UPDATE",(token_hash,)).fetchone()
        if not token: raise HTTPException(400,'Mã xác minh hoặc liên kết không hợp lệ, đã dùng hoặc hết hạn.')
        updated=conn.execute('UPDATE annha_private.users SET email_verified_at=now() WHERE id=%s AND email_version=%s RETURNING id',(token['user_id'],token['email_version'])).fetchone()
        if not updated: raise HTTPException(400,'Địa chỉ email đã thay đổi.')
        conn.execute('UPDATE annha_private.email_tokens SET consumed_at=now() WHERE token_hash=%s',(token_hash,))
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
    throttle('forgot-email:'+payload.email,3,900)
    with db.connect('auth') as conn:
        account=conn.execute('SELECT * FROM annha_private.users WHERE email=%s AND deleted_at IS NULL AND disabled_at IS NULL',(payload.email,)).fetchone()
        if account: svc.queue_email(conn,account,'reset_password')
    return {'message':'Nếu email đã đăng ký, hệ thống sẽ gửi mã đặt lại mật khẩu.'}

def reset_limits(payload,request):
    throttle('reset:'+str(request.client.host),20,900)
    if payload.email: throttle('reset-email:'+payload.email,10,900)

def reset_record(conn,payload,lock=False):
    hashed=reset_code_digest(payload.email,payload.code) if payload.code else digest(payload.token)
    hint=conn.execute("SELECT user_id FROM annha_private.email_tokens WHERE token_hash=%s AND purpose='reset_password'",(hashed,)).fetchone()
    if not hint: raise HTTPException(400,'Mã hoặc yêu cầu đặt lại mật khẩu không hợp lệ, đã dùng hoặc hết hạn.')
    account=conn.execute('SELECT id,email_version FROM annha_private.users WHERE id=%s AND disabled_at IS NULL AND deleted_at IS NULL'+(' FOR UPDATE' if lock else ''),(hint['user_id'],)).fetchone()
    if not account: raise HTTPException(400,'Mã hoặc yêu cầu đặt lại mật khẩu không hợp lệ, đã dùng hoặc hết hạn.')
    token=conn.execute("SELECT * FROM annha_private.email_tokens WHERE token_hash=%s AND purpose='reset_password' AND consumed_at IS NULL AND expires_at>now() AND email_version=%s"+(' FOR UPDATE' if lock else ''),(hashed,account['email_version'])).fetchone()
    if not token: raise HTTPException(400,'Mã hoặc yêu cầu đặt lại mật khẩu không hợp lệ, đã dùng hoặc hết hạn.')
    return token

@router.post('/auth/reset/check')
def check_reset(payload:m.ResetCredential,request:Request):
    reset_limits(payload,request)
    with db.connect('auth') as conn: reset_record(conn,payload)
    return {'message':'Mã hợp lệ. Hãy nhập mật khẩu mới.'}

@router.post('/auth/reset')
async def reset(payload:m.Reset,request:Request):
    reset_limits(payload,request)
    hashed_password=password_hash(payload.password)
    with db.connect('auth') as conn:
        token=reset_record(conn,payload,True)
        conn.execute('UPDATE annha_private.users SET password_hash=%s,auth_version=auth_version+1 WHERE id=%s',(hashed_password,token['user_id']))
        conn.execute('UPDATE annha_private.sessions SET revoked_at=now() WHERE user_id=%s',(token['user_id'],))
        conn.execute("UPDATE annha_private.email_tokens SET consumed_at=now() WHERE user_id=%s AND purpose='reset_password'",(token['user_id'],))
    await svc.revalidate_connections()
    return {'message':'Đã đổi mật khẩu và kết thúc các phiên cũ. Bạn có thể đăng nhập bằng mật khẩu mới.'}

@router.patch('/account')
def profile(payload:m.Name,current:Current):
    with db.connect('auth') as conn: conn.execute('UPDATE annha_private.users SET name=%s,updated_at=now() WHERE id=%s',(payload.name,current['id']))
    return {'name':payload.name}

@router.get('/homes')
def homes(current:Current):
    with db.connect('auth') as conn:
        rows=conn.execute("""SELECT h.*,m.home_id,m.user_id,m.role,m.granted_by,m.created_at AS membership_created_at,m.revoked_at,m.version,
          COALESCE(g.scopes,'[]'::jsonb) AS scopes,jsonb_build_object('audio',COALESCE(g.audio,false),'schedules',COALESCE(g.schedules,false)) AS rights,
          (SELECT count(*) FROM annha.rooms r WHERE r.home_id=h.id AND r.archived_at IS NULL) AS room_count,
          (SELECT count(*) FROM annha.cameras c WHERE c.home_id=h.id AND c.retired_at IS NULL AND (m.role='owner' OR c.id::text IN(SELECT jsonb_array_elements_text(COALESCE(g.scopes,'[]'::jsonb))))) AS camera_count
          FROM annha.homes h JOIN annha_private.home_memberships m ON m.home_id=h.id
          LEFT JOIN LATERAL (SELECT jsonb_agg(camera_id::text) FILTER(WHERE can_view) AS scopes,bool_or(can_play_audio) AS audio,bool_or(can_edit_reminders) AS schedules
            FROM annha_private.camera_grants WHERE home_id=m.home_id AND user_id=m.user_id) g ON true
          WHERE m.user_id=%s AND m.revoked_at IS NULL AND h.archived_at IS NULL ORDER BY h.name""",(current['id'],)).fetchall()
    result=[]
    for row in rows:
        item=dict(row);item['created_at']=item.pop('membership_created_at');item.update(settings={},email_notifications_supported=True,is_demo=demo_home(row['id']),archive_supported=True)
        result.append(item)
    return result

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

@router.delete('/homes/{home_id}')
async def delete_home(home_id:str,payload:m.DeleteHome,current:Current):
    membership(home_id,current['id'],True)
    stamp=db.now()
    # The trusted control plane locks the home before retirement; business history stays intact.
    with db.connect('auth',home_id,current['id']) as conn:
        row=conn.execute('SELECT name FROM annha.homes WHERE id=%s AND archived_at IS NULL FOR UPDATE',(home_id,)).fetchone()
        if not row: raise HTTPException(404,'Nhà không tồn tại.')
        if payload.confirmation!=row['name']: raise HTTPException(422,'Nhập đúng tên nhà để xác nhận xoá.')
        conn.execute('UPDATE annha.cameras SET retired_at=%s WHERE home_id=%s AND retired_at IS NULL',(stamp,home_id))
        conn.execute('UPDATE annha_private.device_credentials SET revoked_at=%s WHERE camera_id IN(SELECT id FROM annha.cameras WHERE home_id=%s) AND revoked_at IS NULL',(stamp,home_id))
        conn.execute("UPDATE annha_private.invitations SET status='revoked' WHERE home_id=%s AND status='pending'",(home_id,))
        conn.execute('UPDATE annha.homes SET archived_at=%s WHERE id=%s',(stamp,home_id))
        db.audit(conn,home_id,current['id'],'home.archive',home_id)
    with db.connect('worker',home_id) as conn:
        conn.execute("UPDATE annha.commands SET status='expired' WHERE home_id=%s AND status IN ('pending','accepted','executing')",(home_id,))
        conn.execute("UPDATE annha.notification_channels SET enabled=false,revoked_at=COALESCE(revoked_at,now()) WHERE home_id=%s",(home_id,))
        conn.execute("UPDATE annha.notification_deliveries SET status='cancelled' WHERE home_id=%s AND status IN ('pending','sending')",(home_id,))
        conn.execute('UPDATE annha.reminders SET enabled=false,updated_at=now() WHERE home_id=%s AND deleted_at IS NULL',(home_id,))
        conn.execute("UPDATE annha_private.job_queue SET status='failed',last_error_code='HomeArchived',secret_ciphertext=NULL,key_id=NULL,lease_owner=NULL,lease_until=NULL WHERE home_id=%s AND kind IN ('tts','compile_config') AND status IN ('pending','running')",(home_id,))
    await svc.close_home_connections(home_id)
    return {'message':'Đã đưa nhà vào lưu trữ và ngắt quyền truy cập thiết bị. Lịch sử được giữ lại.'}

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
    with db.connect('app',home_id,current['id']) as conn:
        rows=conn.execute('SELECT * FROM annha.cameras WHERE retired_at IS NULL ORDER BY name').fetchall()
        permissions=effective_camera_permissions(home_id,current['id'],[str(row['id']) for row in rows])
        return svc.cameras_public(conn,rows,permissions)

@router.post('/device/pairing-ticket')
def pairing_ticket(request: Request):
    return device_pairing.issue_ticket(request.headers.get('authorization', ''))


@router.post('/homes/{home_id}/cameras/claim',status_code=201)
def claim(home_id:str,payload:m.Claim,current:Current):
    membership(home_id,current['id'],True);throttle('claim:'+current['id'],10,900);camera=db.uid()
    with db.connect('auth',home_id,current['id']) as conn:
        ticket = device_pairing.read_ticket(payload.code)
        if ticket:
            device_id, token_hash = ticket
            registered = conn.execute(
                """INSERT INTO annha_private.device_registry(id,model) VALUES(%s,%s)
                   ON CONFLICT(id) DO NOTHING RETURNING id""",
                (device_id, payload.name),
            ).fetchone()
            if registered:
                conn.execute(
                    'INSERT INTO annha_private.device_credentials(device_id,token_hash) VALUES(%s,%s)',
                    (device_id, token_hash),
                )
            credential = conn.execute(
                """SELECT camera_id FROM annha_private.device_credentials
                   WHERE device_id=%s AND token_hash=%s AND revoked_at IS NULL
                   AND (expires_at IS NULL OR expires_at>now())""",
                (device_id, token_hash),
            ).fetchone()
            if not credential:
                raise HTTPException(400, 'Mã ghép nối đã bị thu hồi.')
            claimed_camera = credential['camera_id']
        else:
            code = conn.execute(
                """SELECT * FROM annha_private.pairing_codes
                   WHERE code_hash=%s AND expires_at>now() FOR UPDATE""",
                (digest(payload.code),),
            ).fetchone()
            if not code:
                raise HTTPException(400,'Mã ghép nối sai, hết hạn hoặc đã dùng.')
            device_id, claimed_camera = code['device_id'], code['claimed_camera_id']
        if claimed_camera:
            existing = conn.execute(
                """SELECT id FROM annha.cameras
                   WHERE id=%s AND home_id=%s AND room_id=%s AND name=%s AND retired_at IS NULL""",
                (claimed_camera, home_id, payload.room_id, payload.name),
            ).fetchone()
            if not existing:
                raise HTTPException(400,'Mã ghép nối sai, hết hạn hoặc đã dùng.')
            camera = str(existing['id'])
        else:
            fail_if_missing(conn.execute('SELECT id FROM annha.rooms WHERE home_id=%s AND id=%s',(home_id,payload.room_id)).fetchone(),'Phòng không thuộc nhà.')
            conn.execute('INSERT INTO annha.cameras(id,home_id,room_id,device_id,name) VALUES(%s,%s,%s,%s,%s)',(camera,home_id,payload.room_id,device_id,payload.name))
            credential = conn.execute(
                """UPDATE annha_private.device_credentials SET camera_id=%s
                   WHERE device_id=%s AND camera_id IS NULL AND revoked_at IS NULL
                   AND (expires_at IS NULL OR expires_at>now()) RETURNING id""",
                (camera, device_id),
            ).fetchone()
            if not credential:
                raise HTTPException(409,'Thiết bị chưa có token hợp lệ. Hãy yêu cầu quản trị viên cấp lại.')
            if not ticket:
                conn.execute('UPDATE annha_private.pairing_codes SET consumed_at=now(),claimed_camera_id=%s WHERE code_hash=%s',(camera,digest(payload.code)))
            db.audit(conn,home_id,current['id'],'camera.claim',camera)
    svc.compile_config(home_id,camera)
    with db.connect('app',home_id,current['id']) as conn: return svc.camera_public(conn,conn.execute('SELECT * FROM annha.cameras WHERE id=%s',(camera,)).fetchone(),{'view':True,'events':True,'audio':True,'schedules':True,'manage':True})

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
    result=[]
    for row in rows:
        member=membership(home_id,str(row['id']))
        member['camera_permissions']=effective_camera_permissions(home_id,str(row['id']))
        result.append({**dict(row),**member,'id':row['id']})
    return result

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
            rights=payload.rights_for_camera(camera).model_dump() if payload.role=='caregiver' else {'audio':False,'schedules':False}
            conn.execute('INSERT INTO annha_private.invitation_camera_grants(home_id,invitation_id,camera_id,can_handle_events,can_play_audio,can_edit_reminders) VALUES(%s,%s,%s,%s,%s,%s)',
                (home_id,row['id'],camera,payload.role=='caregiver',rights['audio'],rights['schedules']))
        home_name=conn.execute('SELECT name FROM annha.homes WHERE id=%s',(home_id,)).fetchone()['name']
        inviter_name=conn.execute('SELECT name FROM annha_private.users WHERE id=%s',(current['id'],)).fetchone()['name']
        camera_rows=conn.execute('''SELECT c.name AS camera_name,r.name AS room_name FROM annha.cameras c
          LEFT JOIN annha.rooms r ON r.id=c.room_id AND r.home_id=c.home_id
          WHERE c.home_id=%s AND c.id=ANY(%s::uuid[]) AND c.retired_at IS NULL ORDER BY r.name,c.name''',(home_id,payload.scopes)).fetchall() if payload.scopes else []
        scope_text=', '.join(f"{item['room_name']+' · ' if item['room_name'] else ''}{item['camera_name']}" for item in camera_rows) or 'Chưa cấp quyền xem camera'
        rendered=svc.render_email('invitation',public_url=os.getenv('PUBLIC_URL','http://localhost:8188'),
            recipient_name='',inviter_name=inviter_name,home_name=home_name,
            role_label={'caregiver':'Người chăm sóc','viewer':'Người xem'}.get(payload.role,payload.role),
            scope_text=scope_text,token=token)
        svc.mail(conn,payload.email,rendered.subject,rendered.text,'invitation',rendered.html);db.audit(conn,home_id,current['id'],'invitation.create',row['id'])
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
    camera_permissions={str(g['camera_id']):{'audio':bool(g['can_play_audio']),'schedules':bool(g['can_edit_reminders'])} for g in grants}
    return {**{key:row[key] for key in ('id','home_id','role','status')},'home_name':name,'expires':row['expires_at'].timestamp(),
        'scopes':__import__('json').dumps([str(g['camera_id']) for g in grants]),'rights':__import__('json').dumps({'audio':any(g['can_play_audio'] for g in grants),'schedules':any(g['can_edit_reminders'] for g in grants)}),'camera_permissions':camera_permissions}

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
    return {'desired_version':state.get('desired_version',0),'applied_version':state.get('applied_version') or 0,'error':state.get('error'),'payload':svc.current_config_payload(row['payload'] if row else {})}

@router.get('/cameras/{camera_id}/smart-modes')
def get_smart_modes(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'])
    with db.connect('app',camera['home_id'],current['id']) as conn:
        state=conn.execute('SELECT * FROM annha.camera_config_state WHERE camera_id=%s',(camera_id,)).fetchone() or {}
        row=conn.execute('SELECT payload FROM annha.camera_configurations WHERE camera_id=%s ORDER BY version DESC LIMIT 1',(camera_id,)).fetchone()
    payload=svc.current_config_payload(row['payload'] if row else {})
    return {'camera_id':camera_id,'desired_version':state.get('desired_version',0),'applied_version':state.get('applied_version') or 0,'smart_modes':payload['smart_modes']}

@router.put('/cameras/{camera_id}/smart-modes')
def put_smart_modes(camera_id:str,payload:m.SmartModes,current:Current):
    camera=camera_access(camera_id,current['id'],'schedules');home=camera['home_id']
    updated=svc.compile_config(home,camera_id,{'smart_modes':payload.model_dump()})
    with db.connect('app',home,current['id']) as conn:
        state=conn.execute('SELECT * FROM annha.camera_config_state WHERE camera_id=%s',(camera_id,)).fetchone() or {}
        db.audit(conn,home,current['id'],'camera.smart_modes',camera_id)
    return {'camera_id':camera_id,'desired_version':updated['version'] if updated else state.get('desired_version',0),'applied_version':state.get('applied_version') or 0,'smart_modes':(updated or {}).get('smart_modes',payload.model_dump())}

@router.get('/homes/{home_id}/events')
def events(home_id:str,current:Current,limit:int=100,status:str|None=None,kind:str|None=None,
           room_id:str|None=None,camera_id:str|None=None,hours:int|None=None,page:int|None=None,page_size:int=10,start:str|None=None,end:str|None=None,severity:str|None=None):
    membership(home_id,current['id'])
    if not 1<=limit<=500 or not 1<=page_size<=50 or (page is not None and page<1): raise HTTPException(422,'Giới hạn/trang không hợp lệ.')
    if hours is not None and not 1<=hours<=87600: raise HTTPException(422,'Khoảng thời gian không hợp lệ.')
    if kind and kind not in ('fall','immobility','environment','device'): raise HTTPException(422,'Loại sự kiện không hợp lệ.')
    a,b=time_range(start,end,hours)
    if severity and severity not in ('info','warning','critical'): raise HTTPException(422,'Mức cảnh báo không hợp lệ.')
    clauses=['e.home_id=%s'];args=[home_id]
    if a: clauses.append('e.first_observed_at>=%s');args.append(a)
    if b: clauses.append('e.first_observed_at<%s');args.append(b)
    for column,value in [('e.status',status),('e.kind',kind),('c.room_id',room_id),('e.camera_id',camera_id),('e.severity',severity)]:
        if value: clauses.append(column+'=%s');args.append(value)
    source=' FROM annha.events e JOIN annha.cameras c ON c.id=e.camera_id AND c.home_id=e.home_id LEFT JOIN annha.rooms r ON r.id=c.room_id AND r.home_id=e.home_id WHERE '+' AND '.join(clauses)
    with db.connect('app',home_id,current['id']) as conn:
        count=conn.execute('SELECT count(*) AS n'+source,args) if page is not None else None
        rows=conn.execute('SELECT e.*,c.name AS camera_name,r.name AS room_name,EXISTS (SELECT 1 FROM annha.event_reads er WHERE er.event_id=e.id AND er.user_id=%s) AS is_read'+source+' ORDER BY e.received_at DESC,e.id DESC LIMIT %s OFFSET %s',[current['id']]+args+[page_size if page is not None else limit,(page-1)*page_size if page is not None else 0]).fetchall()
        total=count.fetchone()['n'] if count else 0
        items=svc.events_public(conn,rows)
    return {'items':items,'total':total,'page':page,'page_size':page_size,'total_pages':max(1,(total+page_size-1)//page_size)} if page is not None else items

@router.get('/homes/{home_id}/active-events')
def active_events(home_id:str,current:Current,page_size:int=5):
    membership(home_id,current['id'])
    if not 1<=page_size<=20: raise HTTPException(422,'Giới hạn trang không hợp lệ.')
    source=" FROM annha.events e JOIN annha.cameras c ON c.id=e.camera_id AND c.home_id=e.home_id LEFT JOIN annha.rooms r ON r.id=c.room_id AND r.home_id=c.home_id WHERE e.home_id=%s AND e.status IN ('OPEN','ACKNOWLEDGED')"
    as_of=db.now()
    with db.connect('app',home_id,current['id']) as conn:
        count=conn.execute('SELECT count(*) AS n'+source,(home_id,)).fetchone()['n']
        unread_count=conn.execute('SELECT count(*) AS n'+source+
            ' AND NOT EXISTS (SELECT 1 FROM annha.event_reads er WHERE er.event_id=e.id AND er.user_id=%s)',
            (home_id,current['id'])).fetchone()['n']
        rows=conn.execute('SELECT e.*,c.name AS camera_name,r.name AS room_name,'+
            'EXISTS (SELECT 1 FROM annha.event_reads er WHERE er.event_id=e.id AND er.user_id=%s) AS is_read'+source+
            ' ORDER BY is_read ASC,e.received_at DESC,e.id DESC LIMIT %s',(current['id'],home_id,page_size)).fetchall()
        items=svc.events_public(conn,rows)
    return {'count':count,'unread_count':unread_count,'items':items,'as_of':as_of}

def event_scope(event_id,current,action='view'):
    # Resolve the tenant from trusted records, then enforce RLS and camera permission.
    with db.connect('auth') as auth:
        homes=[str(row['home_id']) for row in auth.execute('SELECT home_id FROM annha_private.home_memberships WHERE user_id=%s AND revoked_at IS NULL',(current['id'],))]
    for home in homes:
        with db.connect('app',home,current['id']) as conn:
            row=conn.execute('SELECT * FROM annha.events WHERE id=%s',(event_id,)).fetchone()
            if row:
                allowed=conn.execute('SELECT annha_private.can_camera(%s,%s,%s) AS allowed',(home,row['camera_id'],action)).fetchone()['allowed']
                if not allowed:raise HTTPException(404 if action=='view' else 403,'Camera ngoài phạm vi quyền truy cập.')
                return home
    raise HTTPException(404,'Không tìm thấy sự kiện.')

@router.get('/events/{event_id}')
def get_event(event_id:str,current:Current):
    home=event_scope(event_id,current)
    with db.connect('app',home,current['id']) as conn: return svc.event_public(conn,conn.execute('SELECT e.*,EXISTS (SELECT 1 FROM annha.event_reads er WHERE er.event_id=e.id AND er.user_id=%s) AS is_read FROM annha.events e WHERE e.id=%s',(current['id'],event_id)).fetchone())

def _read_event(conn,event,current):
    conn.execute('''INSERT INTO annha.event_reads(home_id,camera_id,event_id,user_id)
        VALUES(%s,%s,%s,%s) ON CONFLICT(event_id,user_id) DO NOTHING''',
        (event['home_id'],event['camera_id'],event['id'],current['id']))
    allowed=conn.execute('SELECT annha_private.can_camera(%s,%s,%s) AS allowed',
        (event['home_id'],event['camera_id'],'events')).fetchone()['allowed']
    if allowed and event['status']=='OPEN':
        conn.execute("UPDATE annha.events SET status='ACKNOWLEDGED',updated_at=now() WHERE id=%s",(event['id'],))
        conn.execute('''INSERT INTO annha.event_actions(home_id,camera_id,event_id,user_id,action,request_id)
            VALUES(%s,%s,%s,%s,'acknowledge',%s)''',
            (event['home_id'],event['camera_id'],event['id'],current['id'],db.uid()))
        db.audit(conn,event['home_id'],current['id'],'event.acknowledge',event['id'])
        return True
    return False

@router.post('/events/{event_id}/read')
async def mark_event_read(event_id:str,current:Current):
    home=event_scope(event_id,current)
    with db.connect('app',home,current['id']) as conn:
        event=fail_if_missing(conn.execute('SELECT * FROM annha.events WHERE id=%s FOR UPDATE',(event_id,)).fetchone())
        changed=_read_event(conn,event,current)
        result=svc.event_public(conn,conn.execute('SELECT * FROM annha.events WHERE id=%s',(event_id,)).fetchone()) if changed else None
    if result: await svc.broadcast(result)
    return {'id':event_id,'read':True}

@router.post('/homes/{home_id}/events/read-all')
async def mark_all_events_read(home_id:str,current:Current):
    membership(home_id,current['id'])
    changed=[];count=0
    with db.connect('app',home_id,current['id']) as conn:
        rows=conn.execute("SELECT * FROM annha.events WHERE home_id=%s AND status IN ('OPEN','ACKNOWLEDGED') ORDER BY received_at FOR UPDATE",(home_id,)).fetchall()
        for event in rows:
            previously_read=conn.execute('SELECT 1 FROM annha.event_reads WHERE event_id=%s AND user_id=%s',(event['id'],current['id'])).fetchone()
            acknowledged=_read_event(conn,event,current)
            if not previously_read:count+=1
            if acknowledged:changed.append(event['id'])
        broadcasts=svc.events_public(conn,conn.execute('SELECT * FROM annha.events WHERE id=ANY(%s::uuid[])',(changed,)).fetchall()) if changed else []
    for event in broadcasts:await svc.broadcast(event)
    return {'read_count':count,'acknowledged_count':len(changed)}

@router.get('/events/{event_id}/updates')
def event_updates(event_id:str,current:Current,page:int=1,page_size:int=10):
    home=event_scope(event_id,current)
    with db.connect('app',home,current['id']) as conn:
        rows,total=select_page(conn,'sequence,observed_at,received_at,observation,severity,payload',
          ' FROM annha.event_updates WHERE event_id=%s AND home_id=%s',[event_id,home],'sequence DESC',page,page_size)
    return page_result(rows,total,page,page_size)

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

def telemetry_source(camera_id,start,end,hours,default_hours=None):
    a,b=time_range(start,end,hours,default_hours)
    clauses=['b.camera_id=%s'];args=[camera_id]
    if a:clauses.append('b.observed_at>=%s');args.append(a)
    if b:clauses.append('b.observed_at<%s');args.append(b)
    return ' FROM annha.telemetry_batches b WHERE '+' AND '.join(clauses),args,a,b


def telemetry_public(row):
    return {**{k:v for k,v in row.items() if k!='readings'},'payload':{'observed_at':row['observed_at'],'readings':row['readings']}}


TELEMETRY_COLUMNS="""b.*,COALESCE((SELECT jsonb_object_agg(r.metric,jsonb_build_object('value',r.value,'unit',r.unit,'quality',r.quality)) FROM annha.sensor_readings r WHERE r.batch_id=b.id),'{}'::jsonb) AS readings"""

@router.get('/cameras/{camera_id}/telemetry')
def telemetry(camera_id:str,current:Current,limit:int=100,hours:int|None=None,start:str|None=None,end:str|None=None,page:int|None=None,page_size:int=10):
    camera=camera_access(camera_id,current['id'])
    if not 1<=limit<=1000:raise HTTPException(422,'Giới hạn không hợp lệ.')
    source,args,_,_=telemetry_source(camera_id,start,end,hours)
    with db.connect('app',camera['home_id'],current['id']) as conn:
        rows,total=select_page(conn,TELEMETRY_COLUMNS,source,args,'b.observed_at DESC,b.received_at DESC,b.id DESC',page,page_size,limit)
    items=[telemetry_public(row) for row in rows]
    return page_result(items,total,page,page_size) if page is not None else items

@router.get('/cameras/{camera_id}/telemetry-summary')
def telemetry_summary(camera_id:str,current:Current,hours:int|None=None,start:str|None=None,end:str|None=None,buckets:int=120):
    import math
    camera=camera_access(camera_id,current['id'])
    if not 2<=buckets<=500:raise HTTPException(422,'Số khoảng biểu đồ không hợp lệ.')
    source,args,a,b=telemetry_source(camera_id,start,end,hours,24)
    if not a or not b:raise HTTPException(422,'Chọn đủ ngày bắt đầu và kết thúc.')
    seconds=max(1,math.ceil((b-a).total_seconds()/buckets));n=math.ceil((b-a).total_seconds()/seconds)
    with db.connect('app',camera['home_id'],current['id']) as conn:
        stats=conn.execute('SELECT count(*) AS sample_count,min(b.observed_at) AS first_observed_at,max(b.observed_at) AS last_observed_at'+source,args).fetchone()
        latest=conn.execute('SELECT '+TELEMETRY_COLUMNS+source+' ORDER BY b.observed_at DESC,b.received_at DESC,b.id DESC LIMIT 1',args).fetchone()
        occupied=conn.execute('SELECT floor(extract(epoch FROM (b.observed_at-%s::timestamptz))/%s)::int AS slot,count(*) AS n'+source+' GROUP BY slot',[a,seconds]+args).fetchall()
        grouped=conn.execute("""SELECT floor(extract(epoch FROM (b.observed_at-%s::timestamptz))/%s)::int AS slot,
          r.metric,r.unit,count(*) AS count,avg(r.value) AS mean,min(r.value) AS min,max(r.value) AS max
          FROM annha.sensor_readings r JOIN annha.telemetry_batches b ON b.id=r.batch_id
          WHERE """+source.split(' WHERE ',1)[1]+" AND r.quality='valid' GROUP BY slot,r.metric,r.unit",[a,seconds]+args).fetchall()
    series={};units={}
    for row in grouped:
        metric,unit=row['metric'],row['unit'];units.setdefault(metric,[])
        if unit not in units[metric]:units[metric].append(unit)
        points=series.setdefault(metric,{}).setdefault(unit,[{'x':(a.timestamp()+i*seconds)*1000,'y':None,'count':0} for i in range(n)])
        if 0<=row['slot']<n:points[row['slot']].update(y=float(row['mean']),min=float(row['min']),max=float(row['max']),count=row['count'])
    empty=n-len(occupied)
    return {**stats,'start':a,'end':b,'bucket_seconds':seconds,'bucket_count':n,'empty_buckets':empty,
      'coverage_percent':round(100*(n-empty)/n,1),'metric_units':{k:sorted(v) for k,v in units.items()},'series':series,
      'latest':telemetry_public(latest) if latest else None}

class Settings(m.Settings):
    email_enabled: bool=False
    notification_reminder_interval_seconds: int = 900
    notification_max_reminders: int = 3

@router.get('/homes/{home_id}/settings')
def settings(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('worker',home_id) as conn:
        base=dict(conn.execute('SELECT * FROM annha.home_settings WHERE home_id=%s',(home_id,)).fetchone())
        base.pop('home_id');base.pop('updated_at');base.pop('telemetry_retention_days');base.pop('event_retention_days')
        # Notification destinations and recipient policies belong to the dedicated
        # notification-settings API; never return a Telegram destination in this form.
        base.update(telegram_enabled=False,telegram_chat_id='',telegram_photos=False,email_enabled=False)
    return base

@router.put('/homes/{home_id}/settings')
def save_settings(home_id:str,payload:Settings,current:Current):
    membership(home_id,current['id'],True);values=payload.model_dump()
    columns=['retention_days','temperature_high','temperature_low','humidity_high','gas_high','gas_unit','environment_hold_seconds','hysteresis']
    with db.connect('app',home_id,current['id']) as conn:
        conn.execute('UPDATE annha.home_settings SET '+','.join(key+'=%s' for key in columns)+',telemetry_retention_days=%s,updated_at=now() WHERE home_id=%s',[values[key] for key in columns]+[payload.retention_days,home_id])
        db.audit(conn,home_id,current['id'],'settings.update',home_id)
    with db.connect('worker',home_id) as conn:
        cameras=[str(r['id']) for r in conn.execute('SELECT id FROM annha.cameras WHERE retired_at IS NULL')]
    for camera in cameras: svc.compile_config(home_id,camera)
    return values

def _notification_channel_public(row,secret,scopes):
    if not row:
        return {'id':None,'enabled':False,'event_kinds':['fall','immobility','environment','device'],
          'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[],'allow_media':False,
          'destination_configured':False,'destination_hint':''}
    hint=''
    if secret:
        try:
            chat=str(svc.decrypt(secret['destination_ciphertext']).get('chat_id',''))
            hint=('••••'+chat[-4:]) if len(chat)>4 else ('••••' if chat else '')
        except Exception:
            hint='Đã lưu an toàn'
    return {'id':str(row['id']),'enabled':bool(row['enabled']),'event_kinds':list(row['event_kinds']),
      'minimum_severity':row['minimum_severity'],'camera_scope_all':bool(row['camera_scope_all']),
      'camera_ids':scopes,'allow_media':bool(row['allow_media']),'destination_configured':bool(secret),
      'destination_hint':hint,'media_consent_at':row['media_consent_at']}

@router.get('/homes/{home_id}/notification-settings')
def notification_settings(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn:
        home=conn.execute('SELECT name,timezone FROM annha.homes WHERE id=%s',(home_id,)).fetchone()
        policy=conn.execute('SELECT notification_reminder_interval_seconds,notification_max_reminders FROM annha.home_settings WHERE home_id=%s',(home_id,)).fetchone()
        cameras=conn.execute('''SELECT c.id,c.name,r.name AS room_name FROM annha.cameras c
          LEFT JOIN annha.rooms r ON r.id=c.room_id AND r.home_id=c.home_id
          WHERE c.home_id=%s AND c.retired_at IS NULL ORDER BY c.name''',(home_id,)).fetchall()
        channel_rows=conn.execute("SELECT * FROM annha.notification_channels WHERE home_id=%s AND revoked_at IS NULL",(home_id,)).fetchall()
        scopes={str(row['id']):[str(item['camera_id']) for item in conn.execute(
          'SELECT camera_id FROM annha.notification_channel_cameras WHERE home_id=%s AND channel_id=%s ORDER BY camera_id',(home_id,row['id'])).fetchall()]
          for row in channel_rows}
    with db.connect('auth') as conn:
        members=conn.execute('''SELECT m.user_id,m.role,u.name,u.email,u.email_verified_at,u.disabled_at,u.deleted_at
          FROM annha_private.home_memberships m JOIN annha_private.users u ON u.id=m.user_id
          WHERE m.home_id=%s AND m.revoked_at IS NULL AND m.role IN ('owner','caregiver')
          ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END,u.name''',(home_id,)).fetchall()
        grants={str(row['user_id']):[str(item['camera_id']) for item in conn.execute(
          'SELECT camera_id FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s AND can_view ORDER BY camera_id',(home_id,row['user_id'])).fetchall()]
          for row in members if row['role']=='caregiver'}
    channel_by_recipient={}
    secrets_by_channel={}
    for row in channel_rows:
        channel_by_recipient.setdefault(str(row['recipient_user_id']),{})[row['kind']]=row
    with db.connect('worker',home_id) as conn:
        for row in channel_rows:
            if row['kind']=='telegram':
                secrets_by_channel[str(row['id'])]=conn.execute(
                  'SELECT destination_ciphertext FROM annha_private.notification_secrets WHERE home_id=%s AND channel_id=%s',(home_id,row['id'])).fetchone()
    recipients=[]
    camera_ids=[str(camera['id']) for camera in cameras]
    for member in members:
        user_id=str(member['user_id']); allowed=camera_ids if member['role']=='owner' else grants.get(user_id,[])
        if member['role']=='caregiver' and not allowed: continue
        stored=channel_by_recipient.get(user_id,{})
        telegram=stored.get('telegram');email=stored.get('email')
        recipients.append({'user_id':user_id,'name':member['name'],'email':member['email'],'role':member['role'],
          'email_verified':member['email_verified_at'] is not None,'camera_ids':allowed,
          'telegram':_notification_channel_public(telegram,secrets_by_channel.get(str(telegram['id'])) if telegram else None,
            scopes.get(str(telegram['id']),[]) if telegram else []),
          'email_channel':_notification_channel_public(email,None,scopes.get(str(email['id']),[]) if email else [])})
    return {'home':dict(home),'reminder_interval_minutes':int(policy['notification_reminder_interval_seconds']/60),
      'max_reminders':policy['notification_max_reminders'],'telegram_bot_configured':bool(os.getenv('TELEGRAM_BOT_TOKEN','').strip()),
      'email_provider_configured':os.getenv('EMAIL_ALERTS_ENABLED','false').lower()=='true' and bool(os.getenv('SMTP_HOST','').strip()),
      'telegram_pairing_ready':svc.telegram_pairing_ready(),
      'telegram_bot_url':'https://t.me/'+svc.telegram_bot_username(),
      'telegram_event_url_base':os.getenv('PUBLIC_URL','http://localhost:8188').rstrip('/')+'/#/event/',
      'cloudinary_configured':media_storage.cloudinary_configured(),'cameras':[dict(row) for row in cameras],
      'recipients':recipients,'default_event_kinds':['fall','immobility','environment','device'],'default_minimum_severity':'warning'}

@router.post('/homes/{home_id}/notification-recipients/{recipient_id}/telegram-pairing',status_code=201)
def create_telegram_pairing(home_id:str,recipient_id:str,current:Current):
    membership(home_id,current['id'],True)
    if not svc.telegram_pairing_ready():
        raise HTTPException(503,'Liên kết Telegram hiện chưa sẵn sàng. Vui lòng thử lại sau khi máy chủ kết nối với bot.')
    if not os.getenv('TELEGRAM_BOT_TOKEN','').strip():
        raise HTTPException(503,'Bot Telegram chưa được cấu hình trên máy chủ.')
    throttle('telegram-pair:'+home_id+':'+recipient_id,3,900)
    with db.connect('auth') as conn:
        recipient=conn.execute('''SELECT m.role,u.disabled_at,u.deleted_at FROM annha_private.home_memberships m
          JOIN annha_private.users u ON u.id=m.user_id WHERE m.home_id=%s AND m.user_id=%s AND m.revoked_at IS NULL''',
          (home_id,recipient_id)).fetchone()
        if not recipient or recipient['role'] not in ('owner','caregiver') or recipient['disabled_at'] or recipient['deleted_at']:
            raise HTTPException(404,'Người nhận không còn quyền nhận cảnh báo trong nhà này.')
        if recipient['role']=='caregiver' and not conn.execute(
          'SELECT 1 FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s AND can_view LIMIT 1',
          (home_id,recipient_id)).fetchone():
            raise HTTPException(422,'Người chăm sóc chưa được cấp quyền xem camera nào.')
    raw_token=secrets.token_urlsafe(32)
    with db.connect('worker',home_id) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('telegram-channel:'+home_id+':'+recipient_id,))
        # Bound table growth without a new scheduler; remove only expired pairing metadata.
        conn.execute('''WITH stale AS (
          SELECT id FROM annha_private.telegram_pairings WHERE expires_at<now()-interval '30 days'
          ORDER BY expires_at LIMIT 500 FOR UPDATE SKIP LOCKED
        ) DELETE FROM annha_private.telegram_pairings p USING stale WHERE p.id=stale.id''')
        channel=conn.execute('''SELECT id FROM annha.notification_channels WHERE home_id=%s AND recipient_user_id=%s
          AND kind='telegram' AND revoked_at IS NULL FOR UPDATE''',(home_id,recipient_id)).fetchone()
        if channel:
            channel_id=str(channel['id'])
        else:
            channel_id=db.uid()
            conn.execute('''INSERT INTO annha.notification_channels(id,home_id,recipient_user_id,kind,label,enabled,camera_scope_all)
              VALUES(%s,%s,%s,'telegram','Telegram',false,true)''',(channel_id,home_id,recipient_id))
        conn.execute('''UPDATE annha_private.telegram_pairings SET revoked_at=now()
          WHERE home_id=%s AND channel_id=%s AND completed_at IS NULL AND revoked_at IS NULL''',(home_id,channel_id))
        pairing=conn.execute('''INSERT INTO annha_private.telegram_pairings(home_id,channel_id,recipient_user_id,token_hash,created_by,expires_at)
          VALUES(%s,%s,%s,%s,%s,now()+interval '10 minutes') RETURNING id,expires_at''',
          (home_id,channel_id,recipient_id,digest(raw_token),current['id'])).fetchone()
        db.audit(conn,home_id,current['id'],'notification.telegram_pairing.create',pairing['id'])
    username=svc.telegram_bot_username()
    return {'pairing_id':str(pairing['id']),'expires_at':pairing['expires_at'].isoformat(),
      'url':f'https://t.me/{username}?start={raw_token}'}

@router.get('/homes/{home_id}/notification-recipients/{recipient_id}/telegram-pairing/{pairing_id}')
def telegram_pairing_status(home_id:str,recipient_id:str,pairing_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('worker',home_id) as conn:
        row=conn.execute('''SELECT p.expires_at,p.revoked_at,p.completed_at,c.revoked_at AS channel_revoked,
          EXISTS(SELECT 1 FROM annha_private.notification_secrets s WHERE s.home_id=p.home_id AND s.channel_id=p.channel_id) AS destination_configured
          FROM annha_private.telegram_pairings p JOIN annha.notification_channels c
            ON c.home_id=p.home_id AND c.id=p.channel_id AND c.recipient_user_id=p.recipient_user_id
          WHERE p.id=%s AND p.home_id=%s AND p.recipient_user_id=%s''',(pairing_id,home_id,recipient_id)).fetchone()
    if not row: raise HTTPException(404,'Không tìm thấy liên kết Telegram.')
    if row['completed_at'] and row['destination_configured'] and not row['channel_revoked']:
        status='connected'
    elif row['revoked_at'] or row['channel_revoked']:
        status='cancelled'
    elif row['expires_at']<=db.now():
        status='expired'
    else:
        status='pending'
    return {'status':status,'expires_at':row['expires_at'].isoformat()}

@router.put('/homes/{home_id}/notification-policy')
def save_notification_policy(home_id:str,payload:m.NotificationPolicyUpdate,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn:
        conn.execute('''UPDATE annha.home_settings SET notification_reminder_interval_seconds=%s,
          notification_max_reminders=%s,updated_at=now() WHERE home_id=%s''',
          (payload.reminder_interval_minutes*60,payload.max_reminders,home_id))
        db.audit(conn,home_id,current['id'],'notification.policy.update',home_id)
    return {'reminder_interval_minutes':payload.reminder_interval_minutes,'max_reminders':payload.max_reminders,
      'stop_when_acknowledged':True,'stop_when_closed':True,'persistent_environment_after_ack':'stop_until_new_episode'}

@router.put('/homes/{home_id}/notification-recipients/{recipient_id}')
def save_notification_recipient(home_id:str,recipient_id:str,payload:m.NotificationRecipientUpdate,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('auth') as conn:
        recipient=conn.execute('''SELECT m.role,u.email,u.email_verified_at,u.email_version,u.disabled_at,u.deleted_at
          FROM annha_private.home_memberships m JOIN annha_private.users u ON u.id=m.user_id
          WHERE m.home_id=%s AND m.user_id=%s AND m.revoked_at IS NULL''',(home_id,recipient_id)).fetchone()
    if not recipient or recipient['role'] not in ('owner','caregiver') or recipient['disabled_at'] or recipient['deleted_at']:
        raise HTTPException(404,'Người nhận không còn quyền nhận cảnh báo trong nhà này.')
    allowed_camera_ids=set()
    with db.connect('app',home_id,current['id']) as conn:
        allowed_camera_ids={str(row['id']) for row in conn.execute('SELECT id FROM annha.cameras WHERE home_id=%s AND retired_at IS NULL',(home_id,)).fetchall()}
    if recipient['role']=='caregiver':
        with db.connect('auth') as conn:
            allowed_camera_ids={str(row['camera_id']) for row in conn.execute(
              'SELECT camera_id FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s AND can_view',(home_id,recipient_id)).fetchall()}
        if not allowed_camera_ids: raise HTTPException(422,'Người chăm sóc chưa được cấp quyền xem camera nào.')
    token_ready=bool(os.getenv('TELEGRAM_BOT_TOKEN','').strip())
    if payload.telegram.enabled and not token_ready:
        raise HTTPException(409,'Bot Telegram chưa được cấu hình trên máy chủ.')
    if payload.email.enabled and not recipient['email_verified_at']:
        raise HTTPException(409,'Email của người nhận chưa được xác minh.')
    if payload.email.enabled and os.getenv('EMAIL_ALERTS_ENABLED','false').lower()!='true':
        raise HTTPException(409,'Kênh email cảnh báo chưa được bật trên máy chủ.')
    for preference in (payload.telegram,payload.email):
        if preference.camera_scope_all:
            preference.camera_ids=[]
        elif not preference.camera_ids or not set(preference.camera_ids)<=allowed_camera_ids:
            raise HTTPException(422,'Phạm vi camera phải nằm trong quyền xem hiện tại của người nhận.')
    if payload.telegram.clear_destination and payload.telegram.enabled:
        raise HTTPException(422,'Hãy tắt thông báo Telegram trước khi ngắt liên kết tài khoản.')
    configs=[('telegram',payload.telegram,None),('email',payload.email,recipient['email_version'])]
    with db.connect('worker',home_id) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('telegram-channel:'+home_id+':'+recipient_id,))
        current_channel=conn.execute("SELECT id FROM annha.notification_channels WHERE home_id=%s AND recipient_user_id=%s AND kind='telegram' AND revoked_at IS NULL FOR UPDATE",
          (home_id,recipient_id)).fetchone()
        secret=conn.execute('SELECT destination_ciphertext FROM annha_private.notification_secrets WHERE home_id=%s AND channel_id=%s FOR UPDATE',
          (home_id,current_channel['id'])).fetchone() if current_channel else None
        has_destination=(bool(secret) and not payload.telegram.clear_destination) or bool(payload.telegram.chat_id)
        if payload.telegram.enabled and not has_destination:
            raise HTTPException(422,'Hãy liên kết tài khoản Telegram của người nhận trước khi bật thông báo.')
        telegram_id=None
        for kind,preference,email_version in configs:
            row=conn.execute('''SELECT id FROM annha.notification_channels
              WHERE home_id=%s AND recipient_user_id=%s AND kind=%s AND revoked_at IS NULL FOR UPDATE''',
              (home_id,recipient_id,kind)).fetchone()
            channel=str(row['id']) if row else db.uid()
            if kind=='telegram': telegram_id=channel
            common=(preference.enabled,email_version,preference.event_kinds,preference.minimum_severity,
              preference.camera_scope_all,preference.allow_media if kind=='telegram' else False,
              db.now() if kind=='telegram' and preference.allow_media else None,
              current['id'] if kind=='telegram' and preference.allow_media else None)
            if row:
                conn.execute('''UPDATE annha.notification_channels SET enabled=%s,email_version=%s,event_kinds=%s,
                  minimum_severity=%s,camera_scope_all=%s,allow_media=%s,media_consent_at=%s,consent_by=%s WHERE id=%s''',common+(channel,))
            else:
                conn.execute('''INSERT INTO annha.notification_channels(id,home_id,recipient_user_id,kind,label,enabled,email_version,
                  event_kinds,minimum_severity,camera_scope_all,allow_media,media_consent_at,consent_by)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                  (channel,home_id,recipient_id,kind,'Telegram' if kind=='telegram' else 'Email',*common))
            conn.execute('DELETE FROM annha.notification_channel_cameras WHERE home_id=%s AND channel_id=%s',(home_id,channel))
            if not preference.camera_scope_all:
                for camera_id in preference.camera_ids:
                    conn.execute('INSERT INTO annha.notification_channel_cameras(home_id,channel_id,camera_id) VALUES(%s,%s,%s)',
                      (home_id,channel,camera_id))
        if payload.telegram.clear_destination:
            conn.execute('DELETE FROM annha_private.notification_secrets WHERE channel_id=%s',(telegram_id,))
            if conn.execute("SELECT to_regclass('annha_private.telegram_pairings') AS table_name").fetchone()['table_name']:
                conn.execute('''UPDATE annha_private.telegram_pairings SET revoked_at=now()
                  WHERE home_id=%s AND channel_id=%s AND completed_at IS NULL AND revoked_at IS NULL''',(home_id,telegram_id))
        elif payload.telegram.chat_id:
            conn.execute('''INSERT INTO annha_private.notification_secrets(home_id,channel_id,destination_ciphertext,key_id)
              VALUES(%s,%s,%s,%s) ON CONFLICT(channel_id) DO UPDATE SET destination_ciphertext=excluded.destination_ciphertext,key_id=excluded.key_id''',
              (home_id,telegram_id,svc.encrypt({'chat_id':payload.telegram.chat_id}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary')))
        db.audit(conn,home_id,current['id'],'notification.recipient.update',recipient_id)
    return {'message':'Đã lưu người nhận và bộ lọc cảnh báo.'}

@router.post('/homes/{home_id}/notification-recipients/{recipient_id}/telegram-test')
def telegram_connection_test(home_id:str,recipient_id:str,current:Current):
    membership(home_id,current['id'],True);throttle('telegram-test:'+home_id,3,900)
    if not os.getenv('TELEGRAM_BOT_TOKEN','').strip(): raise HTTPException(503,'Bot Telegram chưa được cấu hình trên máy chủ.')
    with db.connect('auth') as conn:
        recipient=conn.execute('''SELECT m.role,u.name,u.disabled_at,u.deleted_at FROM annha_private.home_memberships m
          JOIN annha_private.users u ON u.id=m.user_id WHERE m.home_id=%s AND m.user_id=%s AND m.revoked_at IS NULL''',
          (home_id,recipient_id)).fetchone()
        if not recipient or recipient['role'] not in ('owner','caregiver') or recipient['disabled_at'] or recipient['deleted_at']:
            raise HTTPException(404,'Người nhận không còn quyền nhận cảnh báo trong nhà này.')
        allowed=recipient['role']=='owner' or conn.execute(
          'SELECT 1 FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s AND can_view LIMIT 1',(home_id,recipient_id)).fetchone()
    if not allowed: raise HTTPException(403,'Người nhận chưa được cấp quyền xem camera.')
    with db.connect('app',home_id,current['id']) as conn:
        channel=conn.execute("SELECT id FROM annha.notification_channels WHERE home_id=%s AND recipient_user_id=%s AND kind='telegram' AND revoked_at IS NULL",
          (home_id,recipient_id)).fetchone()
        home=conn.execute('SELECT name FROM annha.homes WHERE id=%s',(home_id,)).fetchone()
    if not channel: raise HTTPException(404,'Chưa lưu cấu hình Telegram cho người nhận này.')
    with db.connect('worker',home_id) as conn:
        secret=conn.execute('SELECT destination_ciphertext FROM annha_private.notification_secrets WHERE home_id=%s AND channel_id=%s',
          (home_id,channel['id'])).fetchone()
    if not secret: raise HTTPException(422,'Chưa có Chat ID Telegram đã lưu.')
    chat_id=svc.decrypt(secret['destination_ciphertext'])['chat_id']
    message=f"AnNhà · Kiểm tra kết nối\nNhà: {home['name']}\nNgười nhận: {recipient['name']}\nĐây là tin nhắn thử do chủ nhà yêu cầu. Không phải cảnh báo thật."
    try:
        provider_id=svc.send_telegram_text(chat_id,message)
    except svc.TelegramDeliveryError as error:
        raise HTTPException(502,svc.telegram_error_message(error.code)) from None
    with db.connect('app',home_id,current['id']) as conn:
        db.audit(conn,home_id,current['id'],'notification.telegram_test.accepted',channel['id'])
    return {'status':'accepted','provider_message_id':provider_id,
      'message':'Telegram đã nhận yêu cầu gửi thử; điều này chưa xác nhận người nhận đã đọc.'}

@router.get('/homes/{home_id}/assets')
def assets(home_id:str,current:Current,page:int|None=None,page_size:int=10,camera_id:UUID|None=None,q:str='',status:str|None=None,audio_only:bool=False):
    membership(home_id,current['id'])
    if len(q)>160:raise HTTPException(422,'Từ khóa quá dài.')
    clauses=["a.home_id=%s","(a.mime_type NOT LIKE 'audio/%%' OR annha_private.can_camera(a.home_id,a.camera_id,'audio') OR annha_private.can_camera(a.home_id,a.camera_id,'schedules'))"]
    args=[home_id]
    if camera_id:clauses.append('a.camera_id=%s');args.append(camera_id)
    if audio_only:clauses.append("a.mime_type LIKE 'audio/%%'")
    if q:clauses.append('a.name ILIKE %s');args.append('%'+q+'%')
    if status:clauses.append("(CASE WHEN a.status='ready' AND a.expires_at<=now() THEN 'expired' ELSE a.status END)=%s");args.append(status)
    with db.connect('app',home_id,current['id']) as conn:
        rows,total=select_page(conn,'a.*',' FROM annha.media_assets a WHERE '+' AND '.join(clauses),args,'a.created_at DESC,a.id DESC',page,page_size,None)
        items=asset_usage(conn,[svc.asset_public(row) for row in rows])
    return page_result(items,total,page,page_size) if page is not None else items

@router.get('/homes/{home_id}/storage')
def storage_usage(home_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn:
        storage=fail_if_missing(conn.execute('SELECT * FROM annha.home_storage WHERE home_id=%s',(home_id,)).fetchone(),'Không tìm thấy thông tin lưu trữ.')
        settings=conn.execute('SELECT retention_days FROM annha.home_settings WHERE home_id=%s',(home_id,)).fetchone()
        states={row['status']:row['count'] for row in conn.execute('SELECT status,count(*) AS count FROM annha.media_assets GROUP BY status')}
        last=conn.execute("SELECT created_at,details FROM annha.audit_logs WHERE action='media.reconcile' ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
    used=int(storage['used_bytes']);reserved=int(storage['reserved_bytes']);quota=int(storage['quota_bytes'])
    percentage=round((used+reserved)*100/quota,1) if quota else 0
    return {'used_bytes':used,'reserved_bytes':reserved,'quota_bytes':quota,
        'available_bytes':max(0,quota-used-reserved),'used_percent':percentage,
        'warning_level':'critical' if percentage>=95 else 'near' if percentage>=80 else 'normal',
        'retention_days':settings['retention_days'] if settings else 14,
        'active_reminder_audio_retained':True,'event_records_retained_after_evidence_expiry':True,
        'assets':states,'failed_assets':int(states.get('failed',0)),
        'reconciliation':({'checked_at':last['created_at'],'report':last['details']} if last else None)}

def asset_scope(asset_id,current,action='view'):
    with db.connect('auth') as auth: homes=[str(r['home_id']) for r in auth.execute('SELECT home_id FROM annha_private.home_memberships WHERE user_id=%s AND revoked_at IS NULL',(current['id'],))]
    for home in homes:
        with db.connect('app',home,current['id']) as conn:
            row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(asset_id,)).fetchone()
            if row:
                rights=[action] if action=='manage' or not row['mime_type'].startswith('audio/') else ['audio','schedules']
                allowed=any(conn.execute('SELECT annha_private.can_camera(%s,%s,%s) AS allowed',(home,row['camera_id'],right)).fetchone()['allowed'] for right in rights)
                if not allowed:raise HTTPException(403,'Camera ngoài phạm vi quyền truy cập.')
                return home,row
    raise HTTPException(404,'Không tìm thấy file.')

async def write_asset(request,home,camera,event=None,current=None):
    mime=request.headers.get('content-type','').split(';')[0]
    extensions={'image/jpeg':'.jpg','image/png':'.png','video/mp4':'.mp4','video/webm':'.webm','audio/webm':'.webm','audio/mpeg':'.mp3','audio/wav':'.wav','audio/ogg':'.ogg'}
    if mime not in extensions: raise HTTPException(415,'Định dạng chưa hỗ trợ.')
    asset=db.uid()
    try:
        provider=media_storage.preferred_provider(db.MEDIA_ROOT)
    except (ValueError,media_storage.MediaStorageError):
        raise HTTPException(503,'Chưa cấu hình được kho media an toàn.') from None
    cloud=provider.name=='cloudinary'
    staging=db.MEDIA_ROOT/'.staging'
    path=(staging if cloud else db.MEDIA_ROOT)/(asset+extensions[mime]);size=0;prefix=b''
    if cloud: staging.mkdir(parents=True,exist_ok=True)
    from urllib.parse import unquote
    name=unquote(request.headers.get('x-file-name','Tài nguyên'))[:160] or 'Tài nguyên'
    staged_for_retry=False
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
        digest=hashlib.sha256(path.read_bytes()).digest()
        if cloud:
            cloud_environment=provider.environment
            public_id=provider.public_id(asset)
            resource_type=provider.resource_type(mime)
        with db.connect('worker',home,camera=camera) as conn:
            if cloud:
                reserved=conn.execute('UPDATE annha.home_storage SET reserved_bytes=reserved_bytes+%s WHERE home_id=%s AND used_bytes+reserved_bytes+%s<=quota_bytes RETURNING home_id',(size,home,size)).fetchone()
                if not reserved: raise HTTPException(413,'Dung lượng lưu trữ của nhà đã hết.')
            elif not conn.execute('UPDATE annha.home_storage SET used_bytes=used_bytes+%s WHERE home_id=%s AND used_bytes+reserved_bytes+%s<=quota_bytes RETURNING home_id',(size,home,size)).fetchone():
                raise HTTPException(413,'Dung lượng lưu trữ của nhà đã hết.')
            retention=conn.execute('SELECT retention_days FROM annha.home_settings WHERE home_id=%s',(home,)).fetchone()['retention_days']
            if cloud:
                conn.execute('''INSERT INTO annha.media_assets(id,home_id,camera_id,event_id,kind,name,mime_type,size_bytes,reserved_bytes,status,provider,
                    provider_environment,public_id,resource_type,delivery_type,local_object_key,expires_at,upload_key,created_by,sha256)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'uploading','cloudinary',%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (asset,home,camera,event,kind,name,mime,size,size,cloud_environment,public_id,resource_type,provider.delivery_type,path.name,
                     db.now()+timedelta(days=retention) if event or kind=='snapshot' else None,'upload:'+asset,current['id'] if current else None,digest))
                job=conn.execute('''INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,idempotency_key)
                    VALUES(%s,'upload',%s,%s,%s) RETURNING id''',(home,asset,db.J({}), 'media-upload:'+asset)).fetchone()
            else:
                conn.execute('''INSERT INTO annha.media_assets(id,home_id,camera_id,event_id,kind,name,mime_type,size_bytes,status,provider,local_object_key,ready_at,expires_at,upload_key,created_by,sha256)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'ready','local',%s,now(),%s,%s,%s,%s)''',
                    (asset,home,camera,event,kind,name,mime,size,path.name,db.now()+timedelta(days=retention) if event or kind=='snapshot' else None,db.uid(),current['id'] if current else None,digest))
        if cloud:
            staged_for_retry=True
            await asyncio.to_thread(svc.process_job,str(job['id']))
            with db.connect('worker',home,camera=camera) as conn:
                stored=conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
            return {'id':asset,'mime':mime,'size':size,'name':name,'status':stored['status'] if stored else 'uploading'}
        return {'id':asset,'mime':mime,'size':size,'name':name,'status':'ready'}
    except Exception:
        if not staged_for_retry: path.unlink(missing_ok=True)
        raise

@router.post('/cameras/{camera_id}/assets',status_code=201)
async def upload_audio(camera_id:str,request:Request,current:Current):
    camera=camera_access(camera_id,current['id'],'audio')
    if not request.headers.get('content-type','').startswith('audio/'): raise HTTPException(415,'Chỉ tải file âm thanh.')
    return await write_asset(request,camera['home_id'],camera_id,current=current)

@router.get('/assets/{asset_id}')
def asset_file(asset_id:str,request:Request,current:Current):
    _,asset=asset_scope(asset_id,current)
    return svc.asset_response(asset,request.headers.get('range'))

@router.get('/assets/{asset_id}/metadata')
def asset_metadata(asset_id:str,current:Current):
    home,asset=asset_scope(asset_id,current)
    with db.connect('app',home,current['id']) as conn:return asset_usage(conn,[svc.asset_public(asset)])[0]

@router.patch('/assets/{asset_id}')
def rename_asset(asset_id:str,payload:m.Name,current:Current):
    home,_=asset_scope(asset_id,current,'manage')
    with db.connect('worker',home) as conn:
        row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
        if not row or row['status'] in ('deleted','deleting','expired'):raise HTTPException(409,'File không còn khả dụng để đổi tên.')
        conn.execute('UPDATE annha.media_assets SET name=%s WHERE id=%s',(payload.name,asset_id))
        db.audit(conn,home,current['id'],'asset.rename',asset_id)
    return {'id':asset_id,'name':payload.name}

@router.delete('/assets/{asset_id}')
def delete_asset(asset_id:str,current:Current,payload:m.DeleteAsset|None=None):
    home,asset=asset_scope(asset_id,current,'manage')
    affected=[]
    with db.connect('worker',home) as conn:
        row=fail_if_missing(conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone())
        if row['status'] in ('deleted','expired'): return {'message':'File đã ngừng sử dụng.','deleted_reminder_count':0}
        if row['status']=='deleting': return {'message':'Yêu cầu xoá đang được xử lý.','deleted_reminder_count':0}
        try:
            affected=conn.execute('''SELECT r.id,r.name FROM annha.reminder_revisions v
                JOIN annha.reminders r ON r.id=v.reminder_id AND r.current_version=v.version
                WHERE v.asset_id=%s AND r.deleted_at IS NULL ORDER BY r.id FOR UPDATE OF r NOWAIT''',(asset_id,)).fetchall()
        except psycopg.errors.LockNotAvailable:
            raise HTTPException(409,'Lời nhắc đang được chỉnh sửa. Hãy thử xóa lại sau ít giây.') from None
        expected={str(item) for item in (payload.expected_reminder_ids if payload else [])}
        actual={str(item['id']) for item in affected}
        if expected!=actual: raise HTTPException(409,'Danh sách lời nhắc dùng file đã thay đổi. Hãy xem lại trước khi xóa.')
        for reminder in affected:
            conn.execute('UPDATE annha.reminders SET deleted_at=now(),enabled=false,updated_at=now() WHERE id=%s',(reminder['id'],))
            db.audit(conn,home,current['id'],'reminder.delete',reminder['id'])
        if affected:
            conn.execute('''INSERT INTO annha_private.job_queue(home_id,kind,payload,idempotency_key)
                VALUES(%s,'compile_config',%s,%s)''',
                (home,db.J({'camera_id':str(row['camera_id'])}),'compile-audio-delete:'+asset_id))
        conn.execute("UPDATE annha.media_assets SET status='deleting',deletion_requested_at=now() WHERE id=%s",(asset_id,))
        conn.execute('''INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,idempotency_key)
            VALUES(%s,'delete_media',%s,%s,%s) ON CONFLICT(idempotency_key) DO UPDATE
            SET status='pending',available_at=now(),lease_until=NULL,last_error_code=NULL''',
            (home,asset_id,db.J({'target_status':'deleted'}),'media-delete:'+asset_id))
        db.audit(conn,home,current['id'],'asset.delete',asset_id)
    return {'message':'Đã ngừng các lời nhắc liên quan và xếp xoá file khỏi kho lưu trữ.','deleted_reminder_count':len(affected)}

@router.post('/assets/{asset_id}/retry',status_code=202)
def retry_asset(asset_id:str,current:Current):
    home,asset=asset_scope(asset_id,current,'manage')
    if asset['kind']!='tts':
        with db.connect('worker',home) as conn:
            row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
            if not row or row['status']!='failed' or row['error_code']!='UploadFailed' or row['provider']!='cloudinary':
                raise HTTPException(409,'Chỉ có thể thử lại media Cloudinary đang thất bại.')
            try:
                staged=svc._staged_path(row['local_object_key'])
            except media_storage.MediaNotFound:
                raise HTTPException(409,'Bản tải lên tạm không còn; hãy tải file lên lại.') from None
            if (staged.stat().st_size!=row['size_bytes'] or not row['sha256']
                    or hashlib.sha256(staged.read_bytes()).digest()!=bytes(row['sha256'])):
                raise HTTPException(409,'Bản tải lên tạm không khớp dữ liệu ban đầu; hãy tải file lên lại.')
            provider=media_storage.CloudinaryStorage()
            if row['provider_environment']!=provider.environment:
                raise HTTPException(409,'Môi trường Cloudinary hiện tại khác với môi trường đã nhận file.')
            job=conn.execute("SELECT * FROM annha_private.job_queue WHERE kind='upload' AND asset_id=%s FOR UPDATE",(asset_id,)).fetchone()
            if not job or job['status']!='failed':
                raise HTTPException(409,'Yêu cầu tải lên không còn ở trạng thái có thể thử lại.')
            reserved=conn.execute('''UPDATE annha.home_storage SET reserved_bytes=reserved_bytes+%s
                WHERE home_id=%s AND used_bytes+reserved_bytes+%s<=quota_bytes RETURNING home_id''',
                (row['size_bytes'],home,row['size_bytes'])).fetchone()
            if not reserved:
                raise HTTPException(413,'Dung lượng lưu trữ của nhà đã hết.')
            conn.execute("UPDATE annha.media_assets SET status='uploading',reserved_bytes=size_bytes,error_code=NULL WHERE id=%s",(asset_id,))
            conn.execute("UPDATE annha_private.job_queue SET status='pending',attempts=0,available_at=now(),lease_owner=NULL,lease_until=NULL,last_error_code=NULL,completed_at=NULL WHERE id=%s",(job['id'],))
            db.audit(conn,home,current['id'],'media.retry',asset_id,row['camera_id'])
        return {'id':asset_id,'status':'uploading'}
    with db.connect('worker',home) as conn:
        row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(asset_id,)).fetchone()
        if not row or row['status']!='failed':
            raise HTTPException(409,'Chỉ có thể thử lại file đang thất bại.')
        referenced=conn.execute('''SELECT 1 FROM annha.reminder_revisions v JOIN annha.reminders r
            ON r.id=v.reminder_id AND r.current_version=v.version AND r.deleted_at IS NULL
            WHERE v.asset_id=%s AND r.home_id=%s AND r.camera_id=%s''',(asset_id,home,row['camera_id'])).fetchone()
        if not referenced:
            raise HTTPException(409,'File không còn được dùng trong lời nhắc đang bật.')
        job=conn.execute("SELECT * FROM annha_private.job_queue WHERE kind='tts' AND asset_id=%s FOR UPDATE",(asset_id,)).fetchone()
        if not job or job['status']!='failed' or not job['secret_ciphertext']:
            raise HTTPException(409,'Không còn dữ liệu an toàn để tạo lại âm thanh.')
        conn.execute('''UPDATE annha.media_assets SET status='processing',provider='local',provider_environment=NULL,
            provider_asset_id=NULL,public_id=NULL,resource_type=NULL,delivery_type=NULL,provider_version=NULL,
            local_object_key=NULL,size_bytes=NULL,reserved_bytes=0,sha256=NULL,width=NULL,height=NULL,duration_s=NULL,
            ready_at=NULL,error_code=NULL WHERE id=%s''',(asset_id,))
        conn.execute("UPDATE annha_private.job_queue SET status='pending',attempts=0,available_at=now(),lease_owner=NULL,lease_until=NULL,last_error_code=NULL,completed_at=NULL WHERE id=%s",(job['id'],))
        db.audit(conn,home,current['id'],'media.retry',asset_id,row['camera_id'])
    return {'id':asset_id,'status':'processing'}

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
            fail_if_missing(conn.execute("SELECT id FROM annha.media_assets WHERE id=%s AND camera_id=%s AND status='ready' AND kind IN ('audio','tts') FOR UPDATE",(asset,payload.camera_id)).fetchone(),'Âm thanh chưa sẵn sàng hoặc thuộc camera khác.')
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
        if new_tts:
            conn.execute('SELECT annha_private.enqueue_tts(%s,%s,%s,%s,%s,%s,%s)',
                (home,payload.camera_id,reminder,version,asset,svc.encrypt({'text':payload.text}),os.getenv('DATA_ENCRYPTION_KEY_ID','primary')))
        db.audit(conn,home,current['id'],'reminder.save',reminder)
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
def executions(home_id:str,current:Current,page:int|None=None,page_size:int=10,camera_id:UUID|None=None,status:str|None=None):
    membership(home_id,current['id']);clauses=['home_id=%s'];args=[home_id]
    if camera_id:clauses.append('camera_id=%s');args.append(camera_id)
    if status:clauses.append('status=%s');args.append(status)
    with db.connect('app',home_id,current['id']) as conn:
        rows,total=select_page(conn,'*,received_at AS created_at,occurrence_key AS occurrence',' FROM annha.reminder_executions WHERE '+' AND '.join(clauses),args,'received_at DESC,id DESC',page,page_size)
    return page_result(rows,total,page,page_size) if page is not None else rows

_PG_BT_STATE: dict[str, dict] = {}

@router.post('/cameras/{camera_id}/commands',status_code=201)
def command(camera_id:str,payload:m.Command,current:Current):
    camera=camera_access(camera_id,current['id'],'audio');home=camera['home_id']
    if payload.kind=='silence': raise HTTPException(422,'Hãy tắt âm từ đúng sự kiện.')
    body={'asset_id':payload.asset_id,'volume':payload.volume}
    if payload.kind in ('ptz_move','ptz_center'):
        body['direction']=payload.direction
        body['degrees']=payload.degrees
    if payload.kind in ('bt_scan','bt_connect','bt_disconnect'):
        body['bt_address']=payload.bt_address
        body['bt_name']=payload.bt_name
    with db.connect('app',home,current['id']) as conn:
        if payload.asset_id: fail_if_missing(conn.execute("SELECT id FROM annha.media_assets WHERE id=%s AND camera_id=%s AND status='ready' AND kind IN ('audio','tts')",(payload.asset_id,camera_id)).fetchone(),'File chưa sẵn sàng hoặc thuộc camera khác.')
        old=conn.execute('SELECT * FROM annha.commands WHERE requested_by=%s AND idempotency_key=%s',(current['id'],payload.idempotency_key)).fetchone()
        if old:
            if str(old['camera_id'])!=camera_id or old['kind']!=payload.kind or old['payload']!=body: raise HTTPException(409,'Mã lệnh đã dùng cho nội dung khác.')
            return {'id':old['id'],'status':old['status']}
        row=conn.execute('INSERT INTO annha.commands(home_id,camera_id,requested_by,idempotency_key,kind,asset_id,payload,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,status',(home,camera_id,current['id'],payload.idempotency_key,payload.kind,payload.asset_id,db.J(body),db.now()+timedelta(seconds=payload.ttl_seconds))).fetchone()
        db.audit(conn,home,current['id'],'command.create',row['id'])
    return row

@router.get('/cameras/{camera_id}/bluetooth')
def get_camera_bluetooth(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'])
    state=dict(_PG_BT_STATE.get(str(camera_id)) or {'connected':False,'deviceName':'','address':'','status':'disconnected','devices':[],'updated_at':None})
    with db.connect('app',camera['home_id'],current['id']) as conn:
        active_scan=conn.execute("SELECT id,status FROM annha.commands WHERE camera_id=%s AND kind='bt_scan' AND status IN ('pending','accepted','executing') AND expires_at>now()",(camera_id,)).fetchone()
        active_conn=conn.execute("SELECT id,status,payload FROM annha.commands WHERE camera_id=%s AND kind='bt_connect' AND status IN ('pending','accepted','executing') AND expires_at>now() ORDER BY created_at DESC LIMIT 1",(camera_id,)).fetchone()
        last_cmd=conn.execute("SELECT id,kind,status,result,created_at FROM annha.commands WHERE camera_id=%s AND kind IN ('bt_scan','bt_connect','bt_disconnect') ORDER BY created_at DESC LIMIT 1",(camera_id,)).fetchone()
    state['scanning']=bool(active_scan)
    state['connecting_address']=(active_conn['payload'] or {}).get('bt_address') if active_conn else None
    state['last_command']=dict(last_cmd) if last_cmd else None
    return state

@router.post('/device/bluetooth')
def device_bluetooth(payload:dict,current:Device):
    _PG_BT_STATE[str(current['id'])]={
        'connected':bool(payload.get('connected')),
        'deviceName':str(payload.get('deviceName') or '')[:120],
        'address':str(payload.get('address') or '')[:32],
        'status':'connected' if payload.get('connected') else 'disconnected',
        'devices':payload.get('devices') if isinstance(payload.get('devices'),list) else [],
        'updated_at':db.now().isoformat(),
    }
    return {'stored':True}

@router.get('/cameras/{camera_id}/commands')
def commands(camera_id:str,current:Current):
    camera=camera_access(camera_id,current['id'],'audio')
    with db.connect('app',camera['home_id'],current['id']) as conn:
        return [{**dict(row),'expires':row['expires_at'].timestamp()} for row in conn.execute('SELECT * FROM annha.commands WHERE camera_id=%s ORDER BY created_at DESC LIMIT 50',(camera_id,))]

@router.get('/homes/{home_id}/audit')
def audit(home_id:str,current:Current,page:int|None=None,page_size:int=10):
    membership(home_id,current['id'],True)
    with db.connect('app',home_id,current['id']) as conn: rows,total=select_page(conn,'*',' FROM annha.audit_logs WHERE home_id=%s',[home_id],'created_at DESC,id DESC',page,page_size)
    ids=list({row['user_id'] for row in rows if row['user_id']})
    with db.connect('auth') as conn: names={row['id']:row['name'] for row in conn.execute('SELECT id,name FROM annha_private.users WHERE id=ANY(%s::uuid[])',(ids,))} if ids else {}
    items=[{**dict(row),'user_name':names.get(row['user_id'],'Thiết bị' if row['actor_type']=='device' else 'Thành viên' if row['actor_type']=='user' else 'Hệ thống')} for row in rows]
    return page_result(items,total,page,page_size) if page is not None else items

@router.get('/homes/{home_id}/delivery-status')
def deliveries(home_id:str,current:Current,recipient_id:UUID|None=None,page:int|None=None,page_size:int=10,channel:str|None=None,status:str|None=None):
    membership(home_id,current['id'],True)
    if channel and channel not in ('email','telegram'):raise HTTPException(422,'Kênh không hợp lệ.')
    clauses=['d.home_id=%s'];args=[home_id]
    for col,value in [('nc.recipient_user_id',recipient_id),('nc.kind',channel),('d.status',status)]:
        if value:clauses.append(col+'=%s');args.append(value)
    source=""" FROM annha.notification_deliveries d JOIN annha.notification_channels nc ON nc.id=d.channel_id AND nc.home_id=d.home_id
      JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id JOIN annha.cameras c ON c.id=d.camera_id AND c.home_id=d.home_id
      LEFT JOIN annha.rooms r ON r.id=c.room_id AND r.home_id=d.home_id WHERE """+' AND '.join(clauses)
    with db.connect('app',home_id,current['id']) as conn:
        rows,total=select_page(conn,'d.*,d.attempt_count AS attempts,d.last_error_code AS error,nc.kind AS channel_kind,nc.recipient_user_id,e.kind AS event_kind,c.name AS camera_name,r.name AS room_name',source,args,'d.created_at DESC,d.id DESC',page,page_size)
    ids=list({row['recipient_user_id'] for row in rows if row['recipient_user_id']})
    with db.connect('auth') as conn:
        names={str(row['id']):row['name'] for row in conn.execute('SELECT id,name FROM annha_private.users WHERE id=ANY(%s::uuid[])',(ids,))} if ids else {}
    items=[{**dict(row),'recipient_name':names.get(str(row['recipient_user_id']),'Thành viên đã rời nhà')} for row in rows]
    return page_result(items,total,page,page_size) if page is not None else items

# Device identity comes from the registered token, never from a supplied tenant ID.
@router.post('/device/heartbeat')
def heartbeat(payload:m.Heartbeat,current:Device):
    with db.connect('worker',current['home_id'],camera=current['id']) as conn:
        conn.execute('UPDATE annha.cameras SET last_seen_at=now(),observation=%s,capabilities=%s WHERE id=%s',(payload.observation,db.J(payload.capabilities),current['id']))
        state=conn.execute('SELECT desired_version FROM annha.camera_config_state WHERE camera_id=%s',(current['id'],)).fetchone()
    if isinstance(payload.bluetooth,dict):
        _PG_BT_STATE[str(current['id'])]={
            'connected':bool(payload.bluetooth.get('connected')),
            'deviceName':str(payload.bluetooth.get('deviceName') or '')[:120],
            'address':str(payload.bluetooth.get('address') or '')[:32],
            'status':'connected' if payload.bluetooth.get('connected') else 'disconnected',
            'devices':payload.bluetooth.get('devices') if isinstance(payload.bluetooth.get('devices'),list) else [],
            'updated_at':db.now().isoformat(),
        }
    return {'server_time':db.now(),'desired_version':state['desired_version'] if state else 0}

@router.get('/device/config')
def device_config(current:Device):
    with db.connect('device',current['home_id'],camera=current['id']) as conn:
        row=conn.execute('SELECT payload FROM annha.camera_configurations WHERE camera_id=%s ORDER BY version DESC LIMIT 1',(current['id'],)).fetchone()
    return svc.device_config_payload(row['payload'] if row else {'version':0,'reminders':[]})

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
def device_asset(asset_id:str,request:Request,current:Device):
    with db.connect('device',current['home_id'],camera=current['id']) as conn:
        row=fail_if_missing(conn.execute('SELECT * FROM annha.media_assets WHERE id=%s AND camera_id=%s',(asset_id,current['id'])).fetchone())
        return svc.asset_response(row,request.headers.get('range'))

@router.post('/device/evidence',status_code=201)
async def evidence(request:Request,current:Device,event_id:str|None=None):
    if event_id:
        with db.connect('worker',current['home_id'],camera=current['id']) as conn:
            fail_if_missing(conn.execute('SELECT id FROM annha.events WHERE id=%s AND camera_id=%s',(event_id,current['id'])).fetchone())
    elif not request.headers.get('content-type','').startswith('image/'): raise HTTPException(422,'Cần sự kiện đích cho clip bằng chứng.')
    return await write_asset(request,current['home_id'],current['id'],event_id)

@router.get('/cameras/{camera_id}/snapshot')
def snapshot(camera_id:str,request:Request,current:Current):
    camera=camera_access(camera_id,current['id'])
    with db.connect('app',camera['home_id'],current['id']) as conn:
        row=fail_if_missing(conn.execute("SELECT * FROM annha.media_assets WHERE camera_id=%s AND kind='snapshot' AND mime_type LIKE 'image/%%' AND status='ready' AND upload_key<>'demo:snapshot' AND (expires_at IS NULL OR expires_at>now()) ORDER BY created_at DESC LIMIT 1",(camera_id,)).fetchone(),'Thiết bị chưa gửi hình ảnh.')
        return svc.asset_response(row,request.headers.get('range'),{'X-Captured-At':row['created_at'].isoformat()})


@router.post('/cameras/{camera_id}/tts-preview')
def tts_preview(camera_id:str,payload:m.TtsPreview,current:Current):
    from .tts import preview_audio
    camera_access(camera_id,current['id'],'schedules')
    throttle('tts-preview:'+current['id'],6,60)
    return Response(content=preview_audio(payload.text),media_type='audio/wav',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

# MVP shareable invitation codes. Legacy email invitation endpoints stay compatible.
@router.post('/homes/{home_id}/invitation-codes',status_code=201)
def create_invitation_code(home_id:str,current:Current):
    from . import invitation_codes as codes
    membership(home_id,current['id'],True)
    throttle('invitation-code-create:'+current['id'],20,3600)
    code=codes.generate()
    with db.connect('auth',home_id,current['id']) as conn:
        row=conn.execute('''INSERT INTO annha_private.invitation_codes(home_id,code_hash,created_by)
          SELECT h.id,%s,%s FROM annha.homes h JOIN annha_private.home_memberships m ON m.home_id=h.id
          WHERE h.id=%s AND h.archived_at IS NULL AND m.user_id=%s AND m.role='owner' AND m.revoked_at IS NULL
          RETURNING id,expires_at''',(codes.code_hash(code),current['id'],home_id,current['id'])).fetchone()
        fail_if_missing(row)
        db.audit(conn,home_id,current['id'],'invitation_code.create',row['id'])
    return {**dict(row),'code':code,'role':'member'}

@router.get('/homes/{home_id}/invitation-codes')
def list_invitation_codes(home_id:str,current:Current):
    from . import invitation_codes as codes
    membership(home_id,current['id'],True)
    with db.connect('auth',home_id,current['id']) as conn:
        rows=conn.execute('''SELECT id,created_at,expires_at,used_at,revoked_at FROM annha_private.invitation_codes
          WHERE home_id=%s ORDER BY created_at DESC LIMIT 50''',(home_id,)).fetchall()
    return [{**dict(row),'status':codes.status(row,db.now()),'role':'member'} for row in rows]

@router.delete('/homes/{home_id}/invitation-codes/{code_id}')
def revoke_invitation_code(home_id:str,code_id:str,current:Current):
    membership(home_id,current['id'],True)
    with db.connect('auth',home_id,current['id']) as conn:
        row=conn.execute('''UPDATE annha_private.invitation_codes SET revoked_at=now()
          WHERE id=%s AND home_id=%s AND used_at IS NULL AND revoked_at IS NULL AND expires_at>now() RETURNING id''',
          (code_id,home_id)).fetchone()
        if not row: raise HTTPException(409,'Mã mời không còn hiệu lực hoặc đã được sử dụng.')
        db.audit(conn,home_id,current['id'],'invitation_code.revoke',row['id'])
    return {'message':'Đã thu hồi mã mời.'}

@router.post('/invitation-codes/join')
def join_invitation_code(payload:m.JoinInvitationCode,request:Request,current:Current):
    from . import invitation_codes as codes
    if not current['verified']: raise HTTPException(403,'Vui lòng xác minh email trước khi tham gia nhà.')
    throttle('invitation-code-user:'+current['id'],5,900)
    throttle('invitation-code-ip:'+str(request.client.host if request.client else 'unknown'),20,900)
    with db.connect('auth',user=current['id']) as conn:
        row=conn.execute('SELECT * FROM annha_private.invitation_codes WHERE code_hash=%s FOR UPDATE',(codes.code_hash(payload.code),)).fetchone()
        codes.invalid(row,db.now())
        home=str(row['home_id'])
        # Home lock also serializes two different codes joining the same member.
        target=conn.execute('SELECT name FROM annha.homes WHERE id=%s AND archived_at IS NULL FOR UPDATE',(home,)).fetchone()
        if not target: raise HTTPException(400,'Nhà của mã mời này không còn khả dụng.')
        conn.execute("SELECT set_config('app.home_id',%s,true)",(home,))
        existing=conn.execute('SELECT revoked_at FROM annha_private.home_memberships WHERE home_id=%s AND user_id=%s',(home,current['id'])).fetchone()
        if existing and existing['revoked_at'] is None: raise HTTPException(409,'Bạn đã là thành viên của nhà này.')
        conn.execute('''INSERT INTO annha_private.home_memberships(home_id,user_id,role,granted_by)
          VALUES(%s,%s,'member',%s) ON CONFLICT(home_id,user_id) DO UPDATE
          SET revoked_at=NULL,role='member',granted_by=excluded.granted_by,version=annha_private.home_memberships.version+1''',
          (home,current['id'],row['created_by']))
        cameras=[str(item['id']) for item in conn.execute('SELECT id FROM annha.cameras WHERE home_id=%s AND retired_at IS NULL',(home,))]
        grant_rows(conn,home,current['id'],m.Access(role='member',scopes=cameras))
        conn.execute('UPDATE annha_private.invitation_codes SET used_by=%s,used_at=now() WHERE id=%s',(current['id'],row['id']))
        db.audit(conn,home,current['id'],'invitation_code.accept',row['id'])
    return {'home_id':home,'home_name':target['name'],'role':'member','message':'Đã tham gia nhà thành công.'}
