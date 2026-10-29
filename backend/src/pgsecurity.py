"""Server-side identity lookup; never trust tenant or camera IDs from device bodies."""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from fastapi import HTTPException, Request
from . import pgdb as db
from .security import password_hash,password_matches,check_origin,COOKIE,SESSION_SECONDS

def digest(value): return hashlib.sha256(value.encode()).digest()
def csrf_for(token): return hmac.new(os.environ['SESSION_CSRF_KEY'].encode(),token.encode(),hashlib.sha256).hexdigest()
def public_user(row): return {**{key:row[key] for key in ('id','name','email')},'verified':bool(row.get('email_verified_at'))}

def session_user(token):
    if not token: raise HTTPException(401,'Vui lòng đăng nhập.')
    with db.connect('auth') as conn:
        row=conn.execute('''SELECT u.*,s.token_hash,s.csrf_hash FROM annha_private.sessions s JOIN annha_private.users u ON u.id=s.user_id
          WHERE s.token_hash=%s AND s.expires_at>now() AND s.revoked_at IS NULL AND s.auth_version=u.auth_version
          AND u.disabled_at IS NULL AND u.deleted_at IS NULL''',(digest(token),)).fetchone()
    if not row: raise HTTPException(401,'Phiên đăng nhập đã hết hạn.')
    row=dict(row);row['id']=str(row['id']);row['verified']=bool(row['email_verified_at']);row['csrf']=csrf_for(token)
    if not hmac.compare_digest(digest(row['csrf']),bytes(row['csrf_hash'])): raise HTTPException(401,'Phiên không còn hợp lệ.')
    return row

def user(request:Request):
    result=session_user(request.cookies.get(COOKIE))
    if request.method not in ('GET','HEAD','OPTIONS') and not hmac.compare_digest(request.headers.get('x-csrf-token',''),result['csrf']):
        raise HTTPException(403,'Mã bảo vệ phiên không hợp lệ. Hãy tải lại trang.')
    return result

def membership(home,user_id,owner=False):
    with db.connect('auth') as conn:
        row=conn.execute('SELECT * FROM annha_private.home_memberships WHERE home_id=%s AND user_id=%s AND revoked_at IS NULL',(home,user_id)).fetchone()
        if not row: raise HTTPException(404,'Không tìm thấy nhà hoặc chưa được cấp quyền.')
        grants=conn.execute('SELECT * FROM annha_private.camera_grants WHERE home_id=%s AND user_id=%s',(home,user_id)).fetchall()
    if owner and row['role']!='owner': raise HTTPException(403,'Thao tác này cần quyền chủ nhà.')
    return {**dict(row),'scopes':[str(g['camera_id']) for g in grants if g['can_view']],
            'rights':{'audio':any(g['can_play_audio'] for g in grants),'schedules':any(g['can_edit_reminders'] for g in grants)}}

def camera_access(camera_id,user_id,action='view',historical=False):
    with db.connect('auth') as conn:
        row=conn.execute('SELECT * FROM annha.cameras WHERE id=%s',(camera_id,)).fetchone()
    if not row or (row['retired_at'] and not historical): raise HTTPException(404,'Không tìm thấy camera.')
    home=str(row['home_id'])
    with db.connect('app',home,user_id) as conn:
        allowed=conn.execute('SELECT annha_private.can_camera(%s,%s,%s) AS allowed',(home,camera_id,action)).fetchone()['allowed']
    if not allowed: raise HTTPException(404 if action=='view' else 403,'Camera ngoài phạm vi quyền truy cập.')
    return {**dict(row),'id':str(row['id']),'home_id':home}

def device_identity(token):
    if not token: raise HTTPException(401,'Thông tin xác thực thiết bị không hợp lệ.')
    with db.connect('auth') as conn:
        row=conn.execute('''SELECT c.* FROM annha_private.device_credentials t JOIN annha.cameras c ON c.id=t.camera_id AND c.device_id=t.device_id
          WHERE t.token_hash=%s AND t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>now()) AND c.retired_at IS NULL''',(digest(token),)).fetchone()
    if not row: raise HTTPException(401,'Thông tin xác thực thiết bị không hợp lệ.')
    return {**dict(row),'id':str(row['id']),'home_id':str(row['home_id'])}

def device(request:Request):
    header=request.headers.get('authorization','')
    return device_identity(header[7:] if header.startswith('Bearer ') else '')

def throttle(key,maximum=10,seconds=900):
    with db.connect('auth') as conn:
        row=conn.execute('''INSERT INTO annha_private.rate_limits(key_hash,hits,window_end) VALUES(%s,1,now()+%s)
           ON CONFLICT(key_hash) DO UPDATE SET hits=CASE WHEN annha_private.rate_limits.window_end<now() THEN 1 ELSE annha_private.rate_limits.hits+1 END,
            window_end=CASE WHEN annha_private.rate_limits.window_end<now() THEN excluded.window_end ELSE annha_private.rate_limits.window_end END RETURNING hits''',(digest(key),timedelta(seconds=seconds))).fetchone()
    if row['hits']>maximum: raise HTTPException(429,'Quá nhiều lần thử. Vui lòng thử lại sau.')
