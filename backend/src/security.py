import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from . import db

COOKIE = 'annha_session'
SESSION_SECONDS = 7 * 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def verification_code_digest(value):
    key = os.environ['SESSION_CSRF_KEY'].encode()
    return hmac.new(key, b'annha:email-verification-code:' + value.encode(), hashlib.sha256).hexdigest()

def reset_code_digest(email,value):
    return hmac.new(os.environ['SESSION_CSRF_KEY'].encode(),
        b'annha:password-reset-code:'+email.encode()+b':'+value.encode(),hashlib.sha256).hexdigest()


def password_hash(password):
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${value}'


def password_matches(password, stored):
    try:
        _, iterations, salt, expected = stored.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def check_origin(origin):
    if not origin:
        return True
    origins = os.getenv('APP_ORIGINS', 'http://localhost:8188,http://127.0.0.1:8188,http://localhost:5188,http://127.0.0.1:5188')
    return origin.rstrip('/') in {x.strip().rstrip('/') for x in origins.split(',')}


def session_user(token):
    if not token:
        raise HTTPException(401, 'Vui lòng đăng nhập.')
    with db.connect() as conn:
        row = conn.execute('SELECT u.id,u.email,u.name,u.verified,s.csrf,s.token_hash FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>?', (digest(token),time.time())).fetchone()
    if not row:
        raise HTTPException(401, 'Phiên đăng nhập đã hết hạn.')
    return dict(row)


def user(request: Request):
    result = session_user(request.cookies.get(COOKIE))
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        supplied = request.headers.get('x-csrf-token', '')
        if not hmac.compare_digest(supplied, result['csrf']):
            raise HTTPException(403, 'Mã bảo vệ phiên không hợp lệ. Hãy tải lại trang.')
    return result


def public_user(value):
    return {k:value[k] for k in ('id','name','email','verified')}


def throttle(key, maximum=10, seconds=900):
    key = digest(key)
    with db.connect() as conn:
        conn.execute('DELETE FROM rate_limits WHERE expires<?', (time.time(),))
        conn.execute('INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key,time.time()+seconds))
        count = conn.execute('SELECT count FROM rate_limits WHERE key=?',(key,)).fetchone()[0]
    if count > maximum:
        raise HTTPException(429, 'Quá nhiều lần thử. Vui lòng thử lại sau.')


def active_rights(value):
    # Retain legacy values in storage, but expose only current camera rights.
    import json
    return {key:enabled for key,enabled in json.loads(value).items() if key in ('audio','schedules')}


def membership(conn, home_id, user_id, owner=False):
    row = conn.execute('SELECT * FROM memberships WHERE home_id=? AND user_id=?',(home_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Không tìm thấy nhà hoặc chưa được cấp quyền.')
    result = dict(row)
    import json
    result['scopes'] = json.loads(result['scopes'])
    result['rights'] = active_rights(result['rights'])
    if owner and result['role'] != 'owner':
        raise HTTPException(403, 'Thao tác này cần quyền chủ nhà.')
    return result


def camera_access(conn, camera_id, user_id, action='view', historical=False):
    if action not in ('view','events','audio','schedules','manage'):
        raise HTTPException(404, 'Không tìm thấy chức năng.')
    camera = conn.execute('SELECT * FROM cameras WHERE id=? AND (claimed=1 OR ?)',(camera_id,int(historical))).fetchone()
    if not camera or not camera['home_id']:
        raise HTTPException(404, 'Không tìm thấy camera.')
    member = membership(conn,camera['home_id'],user_id)
    if member['role'] == 'owner': return dict(camera)
    grant=conn.execute('''SELECT can_view,can_handle_events,can_play_audio,can_edit_reminders
        FROM camera_grants WHERE home_id=? AND camera_id=? AND user_id=?''',(camera['home_id'],camera_id,user_id)).fetchone()
    if not grant or not grant['can_view']:
        raise HTTPException(404,'Camera ngoài phạm vi truy cập.')
    allowed={'view':True,'events':member['role']=='caregiver' and bool(grant['can_handle_events']),
        'audio':member['role']=='caregiver' and bool(grant['can_play_audio']),
        'schedules':member['role']=='caregiver' and bool(grant['can_edit_reminders'])}
    if action=='manage': raise HTTPException(403,'Thao tác này cần quyền chủ nhà.')
    if not allowed[action]: raise HTTPException(403,'Bạn chưa được cấp quyền thực hiện thao tác này.')
    return dict(camera)


def effective_camera_permissions(conn,home_id,user_id,camera_ids=None):
    member=membership(conn,home_id,user_id)
    if member['role']=='owner':
        ids=camera_ids if camera_ids is not None else [r['id'] for r in conn.execute('SELECT id FROM cameras WHERE home_id=? AND claimed=1',(home_id,))]
        return {camera:{'view':True,'events':True,'audio':True,'schedules':True,'manage':True} for camera in ids}
    rows=conn.execute('''SELECT camera_id,can_view,can_handle_events,can_play_audio,can_edit_reminders
        FROM camera_grants WHERE home_id=? AND user_id=?''',(home_id,user_id)).fetchall()
    result={}
    for row in rows:
        if camera_ids is not None and row['camera_id'] not in camera_ids: continue
        if not row['can_view']: continue
        caregiver=member['role']=='caregiver'
        result[row['camera_id']]={'view':True,'events':caregiver and bool(row['can_handle_events']),
            'audio':caregiver and bool(row['can_play_audio']),'schedules':caregiver and bool(row['can_edit_reminders']),'manage':False}
    return result


def device(request: Request):
    header = request.headers.get('authorization','')
    token = header[7:] if header.startswith('Bearer ') else ''
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM cameras WHERE token_hash=? AND claimed=1',(digest(token),)).fetchone() if token else None
    if not row or not row['home_id']:
        raise HTTPException(401,'Thông tin xác thực thiết bị không hợp lệ.')
    return dict(row)
