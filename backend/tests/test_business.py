import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from fastapi.testclient import TestClient

from backend.src import db, main, services


class BusinessTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('SESSION_CSRF_KEY','phase5-sqlite-test-csrf-key-only-not-for-deployment')
        self.temp=tempfile.TemporaryDirectory()
        db.DB_PATH=Path(self.temp.name)/'test.sqlite3'
        db.MEDIA_ROOT=Path(self.temp.name)/'media'
        main.MQTT_ENABLED=False;main.WORKER_ENABLED=False
        self.context=TestClient(main.app)
        self.client=self.context.__enter__()
        self.clients=[]

    def tearDown(self):
        self.context.__exit__(None,None,None)
        for client in self.clients: client.close()
        self.temp.cleanup()

    def account(self,email):
        client=TestClient(main.app);self.clients.append(client)
        data={'name':email.split('@')[0],'email':email,'password':'correct password 123'}
        response=client.post('/api/auth/register',json=data)
        self.assertEqual(response.status_code,201,response.text)
        with db.connect() as conn:
            message=conn.execute('SELECT body FROM mail_jobs WHERE recipient=? ORDER BY created_at DESC',(email,)).fetchone()[0]
        code=re.search(r'Mã xác minh: (\d{8})',message)[1]
        self.assertEqual(client.post('/api/auth/verify',json={'code':code}).status_code,200)
        response=client.post('/api/auth/login',json={'email':email,'password':data['password']})
        self.assertEqual(response.status_code,200,response.text)
        client.headers['X-CSRF-Token']=response.json()['csrf']
        return client,response.json()['user']

    def home_camera(self,client):
        home=client.post('/api/homes',json={'name':'Nhà thử'}).json()
        room=client.post(f"/api/homes/{home['id']}/rooms",json={'name':'Phòng khách'}).json()
        provision=services.provision_device('Camera thử')
        response=client.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':provision['pairing_code'],'name':'Camera thử','room_id':room['id']})
        self.assertEqual(response.status_code,201,response.text)
        return home,room,response.json(),provision

    def device(self,provision):
        client=TestClient(main.app);self.clients.append(client)
        client.headers['Authorization']='Bearer '+provision['device_token']
        return client

    def test_pi_self_enrollment(self):
        from backend.tests.device_pairing_cases import exercise_self_enrollment
        exercise_self_enrollment(self)

    def test_auth_csrf_reset_and_password_hash(self):
        client,account=self.account('owner@example.com')
        self.assertEqual(self.client.get('/api/homes').status_code,401)
        self.assertEqual(client.post('/api/homes',json={'name':'A'},headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(client.post('/api/homes',json={'name':'A'},headers={'Origin':'https://evil.example'}).status_code,403)
        with db.connect() as conn:
            stored=conn.execute('SELECT password FROM users WHERE id=?',(account['id'],)).fetchone()[0]
        self.assertNotIn('correct password',stored)
        client.post('/api/auth/forgot',json={'email':account['email']})
        with db.connect() as conn: body=json.loads(services.mail_cipher().decrypt(conn.execute("SELECT secret_ciphertext FROM mail_jobs WHERE secret_ciphertext IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()[0]))['body']
        token=re.search(r'Mã đặt lại mật khẩu: (\d{8})',body)[1]
        self.assertEqual(client.post('/api/auth/reset',json={'email':account['email'],'code':token,'password':'new password 123'}).status_code,200)
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        self.assertEqual(client.post('/api/auth/reset',json={'email':account['email'],'code':token,'password':'new password 123'}).status_code,400)

    def test_scoped_invitation_revocation_and_device_claim(self):
        owner,_=self.account('owner@example.com');viewer,viewer_user=self.account('viewer@example.com')
        home,room,camera,provision=self.home_camera(owner)
        self.assertEqual(viewer.get(f"/api/homes/{home['id']}/cameras").status_code,404)
        payload={'email':viewer_user['email'],'role':'viewer','scopes':[camera['id']],'rights':{}}
        response=owner.post(f"/api/homes/{home['id']}/invitations",json=payload)
        self.assertEqual(response.status_code,201,response.text)
        with db.connect() as conn: body=conn.execute("SELECT body FROM mail_jobs WHERE subject='Lời mời tham gia AnNhà'").fetchone()[0]
        token=re.search(r'token=([\w-]+)',body)[1]
        self.assertEqual(owner.post(f'/api/invitations/{token}/accept',json={}).status_code,400)
        self.assertEqual(viewer.post(f'/api/invitations/{token}/accept',json={}).status_code,200)
        self.assertEqual(len(viewer.get(f"/api/homes/{home['id']}/cameras").json()),1)
        self.assertEqual(viewer.put(f"/api/cameras/{camera['id']}/zones",json={'base_version':1,'zones':[]}).status_code,404)
        self.assertEqual(owner.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':provision['pairing_code'],'name':'Again','room_id':room['id']}).status_code,400)
        with viewer.websocket_connect(f"/ws/alerts?home_id={home['id']}") as ws:
            response=owner.delete(f"/api/homes/{home['id']}/members/{viewer_user['id']}")
            self.assertEqual(response.status_code,200)
            self.assertEqual(ws.receive()['type'],'websocket.close')
        self.assertEqual(viewer.get(f"/api/homes/{home['id']}/cameras").status_code,404)

    def test_camera_permissions_are_isolated_and_schedule_right_is_not_speaker_control(self):
        from unittest.mock import patch
        owner,_=self.account('owner@example.com')
        caregiver,caregiver_user=self.account('caregiver@example.com')
        viewer,viewer_user=self.account('viewer@example.com')
        outsider,_=self.account('outsider@example.com')
        home,room,first,_=self.home_camera(owner)
        cameras=[first]
        for name in ('Audio only','Both rights'):
            provision=services.provision_device(name)
            response=owner.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':provision['pairing_code'],'name':name,'room_id':room['id']})
            self.assertEqual(response.status_code,201,response.text);cameras.append(response.json())
        ids=[camera['id'] for camera in cameras]

        def invite_account(account,role,camera_permissions=None):
            response=owner.post(f"/api/homes/{home['id']}/invitations",json={
                'email':account['email'],'role':role,'scopes':ids,'rights':{},'camera_permissions':camera_permissions or {}})
            self.assertEqual(response.status_code,201,response.text)
            with db.connect() as conn:
                body=conn.execute('SELECT body FROM mail_jobs WHERE recipient=? AND subject=? ORDER BY created_at DESC LIMIT 1',(account['email'],'Lời mời tham gia AnNhà')).fetchone()[0]
            token=re.search(r'token=([\w-]+)',body)[1]
            return token

        caregiver_token=invite_account(caregiver_user,'caregiver',{
            ids[0]:{'schedules':True},ids[1]:{'audio':True},ids[2]:{'audio':True,'schedules':True}})
        viewer_token=invite_account(viewer_user,'viewer')
        self.assertEqual(caregiver.post(f'/api/invitations/{caregiver_token}/accept',json={}).status_code,200)
        self.assertEqual(viewer.post(f'/api/invitations/{viewer_token}/accept',json={}).status_code,200)

        owner_permissions={item['id']:item['permissions'] for item in owner.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertTrue(all(owner_permissions[camera]['manage'] for camera in ids))
        caregiver_permissions={item['id']:item['permissions'] for item in caregiver.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertTrue(caregiver_permissions[ids[0]]['schedules']);self.assertFalse(caregiver_permissions[ids[0]]['audio'])
        self.assertTrue(caregiver_permissions[ids[1]]['audio']);self.assertFalse(caregiver_permissions[ids[1]]['schedules'])
        self.assertTrue(caregiver_permissions[ids[2]]['audio'] and caregiver_permissions[ids[2]]['schedules'])
        viewer_permissions={item['id']:item['permissions'] for item in viewer.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertTrue(all(value['view'] and not value['events'] and not value['audio'] and not value['schedules'] for value in viewer_permissions.values()))

        wav=b'RIFF'+(36).to_bytes(4,'little')+b'WAVEfmt '+b'\x00'*32
        schedule_asset=owner.post(f'/api/cameras/{ids[0]}/assets',content=wav,headers={'Content-Type':'audio/wav'}).json()
        self.assertEqual(caregiver.post(f'/api/homes/{home["id"]}/reminders',json={'camera_id':ids[0],'name':'Dùng file có sẵn','time':'06:30','source':'audio','asset_id':schedule_asset['id']}).status_code,201)
        uploaded=caregiver.post(f'/api/cameras/{ids[1]}/assets',content=wav,headers={'Content-Type':'audio/wav'})
        self.assertEqual(uploaded.status_code,201,uploaded.text);asset=uploaded.json()
        self.assertEqual(caregiver.post(f'/api/cameras/{ids[0]}/assets',content=wav,headers={'Content-Type':'audio/wav'}).status_code,403)
        self.assertEqual(caregiver.post(f'/api/cameras/{ids[1]}/commands',json={'kind':'test_speaker','idempotency_key':'audio-only-test'}).status_code,201)
        self.assertEqual(caregiver.post(f'/api/cameras/{ids[0]}/commands',json={'kind':'test_speaker','idempotency_key':'schedule-no-audio'}).status_code,403)
        self.assertEqual(caregiver.post(f'/api/homes/{home["id"]}/reminders',json={'camera_id':ids[0],'name':'Lịch TTS','time':'07:00','text':'Nhớ uống nước'}).status_code,201)
        self.assertEqual(caregiver.post(f'/api/homes/{home["id"]}/reminders',json={'camera_id':ids[1],'name':'Không có lịch','time':'07:00','text':'Không được phép'}).status_code,403)
        self.assertEqual(viewer.post(f'/api/homes/{home["id"]}/reminders',json={'camera_id':ids[0],'name':'Viewer','time':'07:00','text':'Không được phép'}).status_code,403)
        with patch('backend.src.tts.preview_audio',return_value=b'RIFF-preview-WAVE'):
            self.assertEqual(caregiver.post(f'/api/cameras/{ids[0]}/tts-preview',json={'text':'Thử nghe'}).status_code,200)
            self.assertEqual(caregiver.post(f'/api/cameras/{ids[1]}/tts-preview',json={'text':'Không có quyền lịch'}).status_code,403)
        self.assertEqual(caregiver.get(f'/api/assets/{asset["id"]}').status_code,200)
        self.assertEqual(viewer.get(f'/api/assets/{asset["id"]}').status_code,403)
        self.assertEqual(caregiver.delete(f'/api/assets/{asset["id"]}').status_code,403)
        self.assertNotIn(asset['id'],[item['id'] for item in viewer.get(f'/api/homes/{home["id"]}/assets').json()])
        self.assertNotIn(asset['id'],[item['id'] for item in caregiver.get(f'/api/homes/{home["id"]}/assets').json() if item['camera_id']==ids[0]])
        self.assertEqual(caregiver.post(f'/api/homes/{home["id"]}/reminders',json={'camera_id':ids[2],'name':'Tài nguyên sai camera','time':'08:00','source':'audio','asset_id':asset['id']}).status_code,422)
        self.assertEqual(owner.delete(f'/api/assets/{asset["id"]}').status_code,200)

        other_home=outsider.post('/api/homes',json={'name':'Nhà ngoài phạm vi'}).json()
        self.assertEqual(outsider.get(f'/api/assets/{asset["id"]}').status_code,404)
        self.assertEqual(outsider.get(f'/api/homes/{other_home["id"]}/cameras').status_code,200)

        revised={ids[0]:{'schedules':False},ids[1]:{'audio':True},ids[2]:{'audio':True,'schedules':True}}
        with caregiver.websocket_connect(f"/ws/alerts?home_id={home['id']}") as socket:
            response=owner.patch(f"/api/homes/{home['id']}/members/{caregiver_user['id']}",json={'role':'caregiver','scopes':ids,'rights':{},'camera_permissions':revised})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(socket.receive()['type'],'websocket.close')
        updated={item['id']:item['permissions'] for item in caregiver.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertFalse(updated[ids[0]]['schedules'])
        self.assertEqual(caregiver.post(f'/api/homes/{home["id"]}/reminders',json={'camera_id':ids[0],'name':'Thu hồi','time':'07:00','text':'Không được phép'}).status_code,403)
        self.assertEqual(caregiver.get('/api/auth/me').status_code,200)

    def test_sqlite_backfills_legacy_home_wide_camera_rights(self):
        owner,_=self.account('legacy-owner@example.com');caregiver,person=self.account('legacy-caregiver@example.com')
        home,_,camera,_=self.home_camera(owner)
        response=owner.post(f"/api/homes/{home['id']}/invitations",json={'email':person['email'],'role':'caregiver','scopes':[camera['id']],'rights':{'audio':True}})
        self.assertEqual(response.status_code,201,response.text)
        with db.connect() as conn: body=conn.execute('SELECT body FROM mail_jobs WHERE recipient=? ORDER BY created_at DESC LIMIT 1',(person['email'],)).fetchone()[0]
        token=re.search(r'token=([\w-]+)',body)[1]
        self.assertEqual(caregiver.post(f'/api/invitations/{token}/accept',json={}).status_code,200)
        with db.connect() as conn:
            conn.execute('DROP TABLE camera_grants')
            conn.execute('DROP TABLE invitation_camera_grants')
        db.initialize()
        permissions=caregiver.get(f"/api/homes/{home['id']}/cameras").json()[0]['permissions']
        self.assertTrue(permissions['audio'])
        self.assertFalse(permissions['schedules'])

    def test_config_version_event_realtime_and_persistence(self):
        owner,_=self.account('owner@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        response=owner.put(f"/api/homes/{home['id']}/settings",json={'temperature_high':34})
        self.assertEqual(response.status_code,200,response.text)
        config=owner.get(f"/api/cameras/{camera['id']}/config").json()
        self.assertEqual(config['applied_version'],0)
        self.assertEqual(device.post('/api/device/config/ack',json={'version':2,'success':True}).status_code,200)
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/config").json()['applied_version'],2)
        payload={'event_id':'edge-001','kind':'immobility','severity':'critical','observation':'abnormal','observed_at':db.now(),'config_version':2,'reason':'Nằm trên sàn'}
        with owner.websocket_connect(f"/ws/alerts?home_id={home['id']}") as ws:
            response=device.post('/api/device/events',json=payload)
            self.assertEqual(response.status_code,200,response.text)
            event_id=response.json()['id']
            self.assertEqual(ws.receive_json()['id'],event_id)
        self.assertEqual(device.post('/api/device/events',json=payload).json()['id'],event_id)
        history=owner.get(f"/api/homes/{home['id']}/events").json()
        self.assertEqual(len(history),1)
        self.assertEqual(owner.post(f'/api/events/{event_id}/actions',json={'action':'acknowledge'}).json()['status'],'ACKNOWLEDGED')
        self.assertEqual(owner.post(f'/api/events/{event_id}/actions',json={'action':'safe'}).status_code,409)
        self.assertEqual(owner.post(f'/api/events/{event_id}/actions',json={'action':'safe','note':'Đã kiểm tra','confirm_abnormal':True}).json()['status'],'RESOLVED')
        db.initialize()
        self.assertEqual(len(owner.get(f"/api/homes/{home['id']}/events").json()),1)

    def test_zones_disabled_and_legacy_config_retired_once(self):
        owner,user=self.account('owner@example.com')
        timezone_home=owner.post('/api/homes',json={'name':'Nhà múi giờ','timezone':'Asia/Tokyo'})
        self.assertEqual(timezone_home.status_code,201,timezone_home.text)
        self.assertEqual(timezone_home.json()['timezone'],'Asia/Tokyo')
        self.assertEqual(owner.post('/api/homes',json={'name':'Múi giờ không hợp lệ','timezone':'Mars/Olympus'}).status_code,422)
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        legacy={'version':1,'camera_id':camera['id'],'zones':[{'id':'old-sofa'}],'reference':{'width':640},'reminders':[]}
        with db.connect() as conn:
            conn.execute('UPDATE configurations SET payload=? WHERE camera_id=? AND version=1',(db.dumps(legacy),camera['id']))
            conn.execute('UPDATE cameras SET applied_version=1 WHERE id=?',(camera['id'],))
            conn.execute('UPDATE memberships SET rights=? WHERE home_id=? AND user_id=?',(db.dumps({'zones':True,'audio':True}),home['id'],user['id']))
        # The admin contract hides legacy fields; the device response retains only empty clear markers.
        self.assertEqual(device.get('/api/device/config').json()['zones'],[])
        self.assertNotIn('zones',owner.get(f"/api/cameras/{camera['id']}/config").json()['payload'])
        self.assertNotIn('reference',owner.get(f"/api/cameras/{camera['id']}/config").json()['payload'])
        self.assertNotIn('zones',owner.get('/api/homes').json()[0]['rights'])
        self.assertNotIn('zones',owner.get(f"/api/homes/{home['id']}/members").json()[0]['rights'])
        for client in (owner,self.client):
            self.assertEqual(client.put(f"/api/cameras/{camera['id']}/zones",json={'base_version':1,'zones':[]}).status_code,404)
        paths=main.app.openapi()['paths']
        self.assertNotIn('/api/cameras/{camera_id}/zones',paths)
        self.assertNotIn('Zones',main.app.openapi()['components']['schemas'])
        self.assertNotIn('zone_id',main.app.openapi()['components']['schemas']['EventInput']['properties'])
        self.assertEqual(owner.post(f"/api/homes/{home['id']}/invitations",json={'email':'other@example.com','role':'caregiver','scopes':[camera['id']],'rights':{'zones':True}}).status_code,422)
        event={'event_id':'legacy-zone-event','kind':'fall','severity':'warning','observed_at':db.now(),'zone_id':'old-sofa'}
        self.assertEqual(device.post('/api/device/events',json=event).status_code,422)
        with TestClient(main.app):
            pass
        config=owner.get(f"/api/cameras/{camera['id']}/config").json()
        self.assertEqual(config['desired_version'],2)
        self.assertEqual(config['applied_version'],1)
        self.assertNotIn('zones',config['payload'])
        self.assertNotIn('reference',config['payload'])
        self.assertIn('environment',config['payload'])
        self.assertEqual(device.post('/api/device/config/ack',json={'version':2,'success':True}).status_code,200)
        # A restart must retain revisions and not append the same cleanup again.
        with TestClient(main.app):
            self.assertEqual(device.get('/api/device/config').json()['version'],2)
        with db.connect() as conn:
            stored=json.loads(conn.execute('SELECT payload FROM configurations WHERE camera_id=? AND version=1',(camera['id'],)).fetchone()[0])
            self.assertEqual(stored,legacy)
            self.assertEqual(conn.execute("SELECT count(*) FROM audit WHERE action='zones.retire'").fetchone()[0],1)
            services.revision(conn,camera['id'])
            current=json.loads(conn.execute('SELECT payload FROM configurations WHERE camera_id=? AND version=3',(camera['id'],)).fetchone()[0])
            self.assertNotIn('zones',current)
            self.assertNotIn('reference',current)
        self.assertEqual(device.get('/api/device/config').json()['zones'],[])

    def test_reminder_commands_assets_and_telemetry(self):
        owner,_=self.account('owner@example.com');home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        payload={'camera_id':camera['id'],'name':'Nhắc ăn','time':'07:00','text':'Nhớ ăn sáng nhé','source':'tts'}
        response=owner.post(f"/api/homes/{home['id']}/reminders",json=payload)
        self.assertEqual(response.status_code,201,response.text)
        reminder=response.json()
        self.assertEqual(owner.get(f"/api/homes/{home['id']}/reminders").json()[0]['asset_status'],'pending')
        body=b'RIFF'+(36).to_bytes(4,'little')+b'WAVEfmt '+b'\x00'*32
        response=owner.post(f"/api/cameras/{camera['id']}/assets",content=body,headers={'Content-Type':'audio/wav'})
        self.assertEqual(response.status_code,201,response.text)
        asset=response.json()
        cmd={'kind':'play_audio','asset_id':asset['id'],'idempotency_key':'same-command-123'}
        first=owner.post(f"/api/cameras/{camera['id']}/commands",json=cmd)
        self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(owner.post(f"/api/cameras/{camera['id']}/commands",json=cmd).json()['id'],first.json()['id'])
        self.assertEqual(len(device.get('/api/device/commands').json()),1)
        self.assertEqual(device.post(f"/api/device/commands/{first.json()['id']}/ack",json={'status':'executed'}).status_code,200)
        self.assertEqual(device.get('/api/device/commands').json(),[])
        reading={'message_id':'reading-1','observed_at':db.now(),'readings':{'temperature':{'value':28,'unit':'C'}}}
        self.assertEqual(device.post('/api/device/telemetry',json=reading).status_code,200)
        self.assertEqual(len(owner.get(f"/api/cameras/{camera['id']}/telemetry").json()),1)
        self.assertEqual(device.post('/api/device/telemetry',json={**reading,'readings':{'temperature':{'value':None,'unit':'C'}}}).status_code,422)
        self.assertEqual(device.get(f"/api/device/assets/{asset['id']}").status_code,200)
        self.assertEqual(self.client.get(f"/api/assets/{asset['id']}").status_code,401)
        outsider,_=self.account('outsider@example.com')
        self.assertEqual(outsider.get(f"/api/assets/{asset['id']}").status_code,404)
        self.assertEqual(owner.post(f"/api/cameras/{camera['id']}/assets",content=b'<script>bad</script>',headers={'Content-Type':'audio/wav'}).status_code,415)

    def test_environment_hysteresis_duplicate_and_removed_history(self):
        owner,_=self.account('owner@example.com');home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        settings=owner.get(f"/api/homes/{home['id']}/settings").json()
        settings.update(environment_hold_seconds=0,temperature_high=30,hysteresis=2)
        self.assertEqual(owner.put(f"/api/homes/{home['id']}/settings",json=settings).status_code,200)
        def reading(message,value):
            return device.post('/api/device/telemetry',json={'message_id':message,'observed_at':db.now(),'readings':{'temperature':{'value':value,'unit':'C'}}})
        self.assertEqual(reading('m1',33).status_code,200)
        rows=owner.get(f"/api/homes/{home['id']}/events").json()
        self.assertEqual(len(rows),1);event_id=rows[0]['id']
        reading('m1',20) # same ID must not evaluate different forged content
        self.assertEqual(owner.get(f'/api/events/{event_id}').json()['observation'],'abnormal')
        reading('m2',29) # hysteresis band: still abnormal
        self.assertEqual(owner.get(f'/api/events/{event_id}').json()['observation'],'abnormal')
        reading('m3',27)
        self.assertEqual(owner.get(f'/api/events/{event_id}').json()['observation'],'recovered')
        self.assertEqual(owner.delete(f"/api/cameras/{camera['id']}").status_code,200)
        self.assertEqual(device.get('/api/device/config').status_code,401)
        self.assertEqual(len(owner.get(f"/api/homes/{home['id']}/events").json()),1)
        self.assertEqual(owner.get(f'/api/events/{event_id}').status_code,200)

    def test_media_requires_scope_and_relays_frames_and_audio(self):
        from starlette.websockets import WebSocketDisconnect
        owner,_=self.account('owner@example.com');outsider,_=self.account('outsider@example.com')
        home,room,camera,provision=self.home_camera(owner)
        with self.assertRaises(WebSocketDisconnect):
            with outsider.websocket_connect(f"/ws/cameras/{camera['id']}"): pass
        headers={'Authorization':'Bearer '+provision['device_token']}
        with owner.websocket_connect(f"/ws/cameras/{camera['id']}") as viewer:
            with self.client.websocket_connect('/ws/device/frames',headers=headers) as sender:
                frame=b'\xff\xd8\xff'+b'test-frame'
                sender.send_bytes(frame)
                self.assertEqual(viewer.receive_bytes(),frame)
        with self.client.websocket_connect('/ws/device/audio',headers=headers) as speaker:
            with owner.websocket_connect(f"/ws/audio/{camera['id']}") as microphone:
                microphone.send_json({'mime':'audio/webm'})
                self.assertEqual(speaker.receive_json()['type'],'start')
                self.assertEqual(microphone.receive_json()['type'],'ready')
                microphone.send_bytes(b'stream-chunk')
                self.assertEqual(speaker.receive_bytes(),b'stream-chunk')
                microphone.send_json({'type':'stop'})
                self.assertEqual(speaker.receive_json()['type'],'stop')

    def test_device_cannot_read_other_camera_assets_or_invent_config_ack(self):
        owner,_=self.account('owner@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        second=services.provision_device('Other camera')
        response=owner.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':second['pairing_code'],'name':'Other camera','room_id':room['id']})
        self.assertEqual(response.status_code,201,response.text)
        body=b'RIFF'+(36).to_bytes(4,'little')+b'WAVEfmt '+b'\x00'*32
        asset=owner.post(f"/api/cameras/{camera['id']}/assets",content=body,headers={'Content-Type':'audio/wav'}).json()
        self.assertEqual(self.device(second).get(f"/api/device/assets/{asset['id']}").status_code,404)
        self.assertEqual(device.post('/api/device/config/ack',json={'version':100,'success':True}).status_code,422)
        invalid={'base_version':1,'zones':[{'id':'bad','name':'Bad','kind':'sofa','points':[[0,0],[1,1],[1,0],[0,1]]}]}
        self.assertEqual(owner.put(f"/api/cameras/{camera['id']}/zones",json=invalid).status_code,404)


    def test_invitation_codes_single_use_permissions_and_concurrent_join(self):
        from .invitation_code_cases import exercise
        exercise(self,postgres=False)

    def test_fasttrack_password_reset_otp(self):
        from .fasttrack_cases import reset_otp_case
        reset_otp_case(self,postgres=False)

if __name__=='__main__': unittest.main()
