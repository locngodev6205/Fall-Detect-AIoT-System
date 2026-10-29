import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from fastapi.testclient import TestClient

from backend.src import db, main, services


class BusinessTests(unittest.TestCase):
    def setUp(self):
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
        token=re.search(r'token=([\w-]+)',message)[1]
        self.assertEqual(client.post('/api/auth/verify',json={'token':token}).status_code,200)
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

    def test_auth_csrf_reset_and_password_hash(self):
        client,account=self.account('owner@example.com')
        self.assertEqual(self.client.get('/api/homes').status_code,401)
        self.assertEqual(client.post('/api/homes',json={'name':'A'},headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(client.post('/api/homes',json={'name':'A'},headers={'Origin':'https://evil.example'}).status_code,403)
        with db.connect() as conn:
            stored=conn.execute('SELECT password FROM users WHERE id=?',(account['id'],)).fetchone()[0]
        self.assertNotIn('correct password',stored)
        client.post('/api/auth/forgot',json={'email':account['email']})
        with db.connect() as conn: body=conn.execute("SELECT body FROM mail_jobs WHERE subject LIKE 'Đặt lại%' LIMIT 1").fetchone()[0]
        token=re.search(r'token=([\w-]+)',body)[1]
        self.assertEqual(client.post('/api/auth/reset',json={'token':token,'password':'new password 123'}).status_code,200)
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        self.assertEqual(client.post('/api/auth/reset',json={'token':token,'password':'new password 123'}).status_code,400)

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
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        legacy={'version':1,'camera_id':camera['id'],'zones':[{'id':'old-sofa'}],'reference':{'width':640},'reminders':[]}
        with db.connect() as conn:
            conn.execute('UPDATE configurations SET payload=? WHERE camera_id=? AND version=1',(db.dumps(legacy),camera['id']))
            conn.execute('UPDATE cameras SET applied_version=1 WHERE id=?',(camera['id'],))
            conn.execute('UPDATE memberships SET rights=? WHERE home_id=? AND user_id=?',(db.dumps({'zones':True,'audio':True}),home['id'],user['id']))
        # Both read paths must filter old data even before retirement runs.
        self.assertEqual(device.get('/api/device/config').json()['zones'],[])
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/config").json()['payload']['reference'],{})
        self.assertNotIn('zones',owner.get('/api/homes').json()[0]['rights'])
        self.assertNotIn('zones',owner.get(f"/api/homes/{home['id']}/members").json()[0]['rights'])
        for client in (owner,self.client):
            self.assertEqual(client.put(f"/api/cameras/{camera['id']}/zones",json={'base_version':1,'zones':[]}).status_code,404)
        paths=main.app.openapi()['paths']
        self.assertNotIn('/api/cameras/{camera_id}/zones',paths)
        self.assertNotIn('Zones',main.app.openapi()['components']['schemas'])
        self.assertEqual(owner.post(f"/api/homes/{home['id']}/invitations",json={'email':'other@example.com','role':'caregiver','scopes':[camera['id']],'rights':{'zones':True}}).status_code,422)
        with TestClient(main.app):
            pass
        services.retire_zone_configs()
        config=owner.get(f"/api/cameras/{camera['id']}/config").json()
        self.assertEqual(config['desired_version'],2)
        self.assertEqual(config['applied_version'],1)
        self.assertEqual(config['payload']['zones'],[])
        self.assertEqual(config['payload']['reference'],{})
        self.assertIn('environment',config['payload'])
        self.assertEqual(device.post('/api/device/config/ack',json={'version':2,'success':True}).status_code,200)
        # A restart must not revive zones or create another revision.
        with TestClient(main.app):
            self.assertEqual(device.get('/api/device/config').json()['version'],2)
        with db.connect() as conn:
            stored=json.loads(conn.execute('SELECT payload FROM configurations WHERE camera_id=? AND version=1',(camera['id'],)).fetchone()[0])
            self.assertEqual(stored,legacy)
            self.assertEqual(conn.execute("SELECT count(*) FROM audit WHERE action='zones.retire'").fetchone()[0],1)
            services.revision(conn,camera['id'])
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


if __name__=='__main__': unittest.main()
