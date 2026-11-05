"""Human-readable, 80-bit single-use invitation codes. Never log raw codes."""
import hashlib
import secrets

ALPHABET='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

def generate():
    raw=''.join(secrets.choice(ALPHABET) for _ in range(16))
    return '-'.join(raw[i:i+4] for i in range(0,16,4))

def normalize(value):
    return ''.join(value.upper().split()).replace('-','')

def code_hash(value):
    return hashlib.sha256(normalize(value).encode('ascii')).digest()

def status(row,now):
    if row['used_at']: return 'used'
    if row['revoked_at']: return 'revoked'
    return 'expired' if row['expires_at']<=now else 'active'

def invalid(row,now):
    from fastapi import HTTPException
    state=status(row,now) if row else 'invalid'
    messages={'used':'Mã mời đã được sử dụng. Hãy xin chủ nhà mã mới.',
        'revoked':'Mã mời đã bị thu hồi. Hãy xin chủ nhà mã mới.',
        'expired':'Mã mời đã hết hạn. Hãy xin chủ nhà mã mới.',
        'invalid':'Mã mời không hợp lệ. Vui lòng kiểm tra lại.'}
    if state!='active': raise HTTPException(400,messages[state])
