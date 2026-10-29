"""Non-destructive end-to-end checks against the running Docker/Neon demo.
Uses private demo credentials. Sends mail only to configured local Mailpit.
Creates labelled smoke events/accounts/reminder history; never resets the DB.
"""
import argparse
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import secrets
import time
import httpx
import websockets


def require(response,status=200):
    if response.status_code!=status: raise AssertionError(f'{response.request.method} {response.request.url.path}: HTTP {response.status_code}: {response.text[:250]}')
    return response.json() if response.headers.get('content-type','').startswith('application/json') else response.content

def wait_mail(mail,recipient,page=None,timeout=60,contains=None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        messages=require(mail.get('/api/v1/messages'))['messages']
        for item in messages:
            if not any(r['Address']==recipient for r in item['To']): continue
            text=require(mail.get('/api/v1/message/'+item['ID']))['Text']
            if page and '/#/'+page+'?' not in text: continue
            if contains and contains not in text: continue
            return text
        time.sleep(1)
    raise AssertionError('Expected message was not delivered to local Mailpit.')

def login(base,account):
    client=httpx.Client(base_url=base,timeout=30)
    data=require(client.post('/api/auth/login',json={'email':account['email'],'password':account['password']}))
    client.headers['X-CSRF-Token']=data['csrf']
    return client

async def realtime(base,owner,device):
    cookie='; '.join(k+'='+v for k,v in owner.cookies.items())
    home=require(owner.get('/api/homes'))[0]['id']
    url=base.replace('http://','ws://').replace('https://','wss://')+'/ws/alerts?home_id='+home
    async with websockets.connect(url,additional_headers={'Cookie':cookie},open_timeout=20) as socket:
        event=require(device.post('/api/device/events',json={'event_id':'smoke:'+secrets.token_hex(8),'kind':'fall','severity':'critical','observation':'suspected','observed_at':datetime.now(timezone.utc).isoformat(),'reason':'SMOKE · Kiểm tra Neon và WebSocket'}))
        delivered=json.loads(await asyncio.wait_for(socket.recv(),20));assert delivered['id']==event['id']
    return event

def run(base,credentials,mail_url):
    accounts={a['role']:a for a in json.loads(Path(credentials).read_text())['accounts']}
    credentials_data=json.loads(Path(credentials).read_text());clients={role:login(base,account) for role,account in accounts.items()}
    mail=httpx.Client(base_url=mail_url,timeout=10)
    health=require(httpx.get(base+'/api/health'));assert health['database']=='postgres' and health['database_connected'];print('PASS Docker HTTP health -> Neon PostgreSQL')
    owner=clients['owner'];home=require(owner.get('/api/homes'))[0]['id'];cameras=require(owner.get(f'/api/homes/{home}/cameras'));assert len(cameras)==2
    cam=cameras[0]['id'];device_config=next(d for d in credentials_data['devices'] if d['camera_id']==cam)
    device=httpx.Client(base_url=base,headers={'Authorization':'Bearer '+device_config['device_token']},timeout=30)
    viewer=clients['viewer'];assert len(require(viewer.get(f'/api/homes/{home}/cameras')))==1
    require(clients['outsider'].get(f'/api/homes/{home}/cameras'),404)
    require(viewer.post(f'/api/cameras/{cam}/commands',json={'kind':'test_speaker','idempotency_key':'smoke:'+secrets.token_hex(8)}),403)
    print('PASS owner/caregiver/viewer/independent-home accounts and access restrictions')
    snapshot=require(owner.get(f'/api/cameras/{cam}/snapshot'));assert snapshot.startswith(b'\x89PNG')
    assets=require(owner.get(f'/api/homes/{home}/assets'));audio=next(a for a in assets if a['camera_id']==cam and a['mime']=='audio/wav')
    require(device.get('/api/device/assets/'+audio['id']))
    print('PASS local PNG snapshot and WAV media, metadata read from Neon')
    require(device.post('/api/device/heartbeat',json={'observation':'clear','capabilities':{'camera':True,'speaker':True,'sensors':True}}))
    config=require(device.get('/api/device/config'));assert config.get('zones',[])==[]
    require(device.post('/api/device/config/ack',json={'version':config['version'],'success':True}))
    command=require(owner.post(f'/api/cameras/{cam}/commands',json={'kind':'play_audio','asset_id':audio['id'],'idempotency_key':'smoke:'+secrets.token_hex(8)}),201)
    assert command['id'] in [c['id'] for c in require(device.get('/api/device/commands'))]
    require(device.post('/api/device/commands/'+command['id']+'/ack',json={'status':'executed'}))
    print('PASS authenticated device config/ACK and audio command/ACK')
    previous=require(owner.get(f'/api/homes/{home}/settings'));enabled={**previous,'email_enabled':True};require(owner.put(f'/api/homes/{home}/settings',json=enabled))
    try:
        event=asyncio.run(realtime(base,owner,device));print('PASS device event -> Neon -> browser WebSocket')
        wait_mail(mail,accounts['owner']['email'],contains=event['id'])
        deliveries=require(owner.get(f'/api/homes/{home}/delivery-status'))
        assert any(d['event_id']==event['id'] and d['sent_count']>=1 for d in deliveries)
        print('PASS email alert -> durable Neon delivery -> SMTP -> Mailpit')
        require(owner.post('/api/events/'+event['id']+'/actions',json={'action':'acknowledge'}))
    finally: require(owner.put(f'/api/homes/{home}/settings',json=previous))
    reminder=require(owner.post(f'/api/homes/{home}/reminders',json={'camera_id':cam,'name':'SMOKE · TTS','time':'09:15','source':'tts','text':'Đây là âm thanh kiểm tra An Nhà.'}),201)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        rows=require(owner.get(f'/api/homes/{home}/reminders'));row=next(r for r in rows if r['id']==reminder['id'])
        if row['asset_status']=='ready': break
        if row['asset_status']=='failed': raise AssertionError('TTS job failed')
        time.sleep(2)
    else: raise AssertionError('TTS timed out')
    require(device.get('/api/device/assets/'+reminder['asset_id']));require(owner.delete('/api/reminders/'+reminder['id']))
    print('PASS encrypted TTS queue -> espeak -> local WAV -> Neon config revision')
    # Transactional mail and verification exercise a real registered session.
    account={'name':'SMOKE email test','email':'smoke-'+secrets.token_hex(6)+'@example.test','password':secrets.token_urlsafe(16)}
    new=httpx.Client(base_url=base,timeout=30);require(new.post('/api/auth/register',json=account),201)
    body=wait_mail(mail,account['email'],'verify');token=re.search(r'token=([\w-]+)',body)[1]
    require(new.post('/api/auth/verify',json={'token':token}));require(new.post('/api/auth/verify',json={'token':token}),400)
    session=login(base,account);require(session.get('/api/auth/me'))
    require(session.post('/api/homes',json={'name':'Invalid CSRF'},headers={'X-CSRF-Token':''}),403)
    require(new.post('/api/auth/forgot',json={'email':account['email']}))
    body=wait_mail(mail,account['email'],'reset');token=re.search(r'token=([\w-]+)',body)[1]
    require(new.post('/api/auth/reset',json={'token':token,'password':secrets.token_urlsafe(18)}));require(session.get('/api/auth/me'),401)
    print('PASS registration -> Mailpit verification -> login -> CSRF rejection -> reset -> session revocation')
    for client in [*clients.values(),device,new,session,mail]: client.close()
    print('ALL LIVE SMOKE CHECKS PASSED')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://localhost:8188');p.add_argument('--credentials',default='.secrets/demo-credentials.json');p.add_argument('--mailpit',default='http://localhost:8125');a=p.parse_args();run(a.base,a.credentials,a.mailpit)
