"""Live integration tests on an isolated Neon branch (never a production test runner).
ANNHA_TEST_ENV=.secrets/neon-test-runtime.env python3 -m unittest backend.tests.test_postgres -v
Synthetic rows are retained on the expiring test branch for inspection.
"""
import os
from pathlib import Path
import re
import secrets
import tempfile
import unittest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from backend.src import pgdb as db, pgmain as main, pgservices as services

@unittest.skipUnless(os.getenv('ANNHA_TEST_ENV'),'Requires explicit isolated-branch runtime env')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for key,value in dotenv_values(os.environ['ANNHA_TEST_ENV']).items():
            if value is not None: os.environ[key]=value
        cls.temp=tempfile.TemporaryDirectory();db.MEDIA_ROOT=Path(cls.temp.name)/'media'
        main.MQTT_ENABLED=False;main.WORKER_ENABLED=False
        cls.context=TestClient(main.app);cls.client=cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None,None,None);cls.temp.cleanup()
    def setUp(self): self.clients=[];self.suffix=secrets.token_hex(5)
    def tearDown(self):
        for client in self.clients: client.close()
    def account(self,email):
        email=email.replace('@','+'+self.suffix+'@')
        client=TestClient(main.app,client=('test-'+self.suffix,50000));self.clients.append(client)
        response=client.post('/api/auth/register',json={'email':email,'name':email.split('@')[0],'password':'correct password 123'})
        self.assertEqual(response.status_code,201,response.text)
        with db.connect('auth') as conn:
            row=conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND secret_ciphertext IS NOT NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        token=re.search(r'token=([\w-]+)',services.decrypt(row['secret_ciphertext'])['body'])[1]
        self.assertEqual(client.post('/api/auth/verify',json={'token':token}).status_code,200)
        response=client.post('/api/auth/login',json={'email':email,'password':'correct password 123'})
        self.assertEqual(response.status_code,200,response.text)
        client.headers['X-CSRF-Token']=response.json()['csrf']
        return client,response.json()['user']
    def home_camera(self,client):
        response=client.post('/api/homes',json={'name':'Nhà test '+self.suffix});self.assertEqual(response.status_code,201,response.text);home=response.json()
        response=client.post(f"/api/homes/{home['id']}/rooms",json={'name':'Phòng khách'});self.assertEqual(response.status_code,201,response.text);room=response.json()
        provision=services.provision_device('Test camera')
        response=client.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':provision['pairing_code'],'name':'Test camera','room_id':room['id']})
        self.assertEqual(response.status_code,201,response.text)
        return home,room,response.json(),provision
    def device(self,provision):
        client=TestClient(main.app);self.clients.append(client);client.headers['Authorization']='Bearer '+provision['device_token'];return client

    def test_scoped_invitation_revocation_and_device_claim(self):
        owner,_=self.account('owner@example.com');viewer,viewer_user=self.account('viewer@example.com')
        home,room,camera,provision=self.home_camera(owner)
        self.assertEqual(viewer.get(f"/api/homes/{home['id']}/cameras").status_code,404)
        payload={'email':viewer_user['email'],'role':'viewer','scopes':[camera['id']],'rights':{}}
        response=owner.post(f"/api/homes/{home['id']}/invitations",json=payload)
        self.assertEqual(response.status_code,201,response.text)
        with db.connect('auth') as conn: body=services.decrypt(conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'='invitation' ORDER BY created_at DESC LIMIT 1").fetchone()['secret_ciphertext'])['body']
        token=re.search(r'token=([\w-]+)',body)[1]
        self.assertEqual(owner.post(f'/api/invitations/{token}/accept',json={}).status_code,404)
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
        payload={'event_id':'edge-001','kind':'immobility','severity':'critical','observation':'abnormal','observed_at':db.now().isoformat(),'config_version':2,'reason':'Nằm trên sàn'}
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
        # Re-read persisted data from PostgreSQL.
        self.assertEqual(len(owner.get(f"/api/homes/{home['id']}/events").json()),1)

    def test_reminder_commands_assets_and_telemetry(self):
        owner,_=self.account('owner@example.com');home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        payload={'camera_id':camera['id'],'name':'Nhắc ăn','time':'07:00','text':'Nhớ ăn sáng nhé','source':'tts'}
        response=owner.post(f"/api/homes/{home['id']}/reminders",json=payload)
        self.assertEqual(response.status_code,201,response.text)
        reminder=response.json()
        self.assertEqual(owner.get(f"/api/homes/{home['id']}/reminders").json()[0]['asset_status'],'processing')
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
        reading={'message_id':'reading-1','observed_at':db.now().isoformat(),'readings':{'temperature':{'value':28,'unit':'C'}}}
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
            return device.post('/api/device/telemetry',json={'message_id':message,'observed_at':db.now().isoformat(),'readings':{'temperature':{'value':value,'unit':'C'}}})
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

    def test_snapshots_never_substitute_demo_art_for_device_evidence(self):
        owner,_=self.account('snapshot@example.com');home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        self.assertFalse(owner.get(f"/api/homes/{home['id']}/cameras").json()[0]['snapshot_available'])
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/snapshot").status_code,404)
        body=b'\x89PNG\r\n\x1a\n'+b'test-device-image'
        response=device.post('/api/device/evidence',content=body,headers={'Content-Type':'image/png'})
        self.assertEqual(response.status_code,201,response.text);asset=response.json()['id']
        with db.connect('worker',home['id']) as conn: conn.execute("UPDATE annha.media_assets SET upload_key='demo:snapshot' WHERE id=%s",(asset,))
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/snapshot").status_code,404)
        with db.connect('worker',home['id']) as conn: conn.execute("UPDATE annha.media_assets SET upload_key='actual-snapshot' WHERE id=%s",(asset,))
        self.assertTrue(owner.get(f"/api/homes/{home['id']}/cameras").json()[0]['snapshot_available'])
        response=owner.get(f"/api/cameras/{camera['id']}/snapshot")
        self.assertEqual(response.content,body);self.assertTrue(response.headers.get('X-Captured-At'))
        self.assertEqual(owner.delete(f"/api/cameras/{camera['id']}").status_code,200)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            services.ingest_event({'id':camera['id'],'home_id':home['id']},__import__('backend.src.models',fromlist=['EventInput']).EventInput(event_id='stale-token-race',kind='fall',severity='critical',observed_at=db.now().isoformat()))

    def test_buffered_telemetry_keeps_newest_observation_first(self):
        from datetime import timedelta
        owner,_=self.account('sensor@example.com');home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        for message,stamp,value in [('fresh',db.now(),24),('buffered',db.now()-timedelta(hours=2),39)]:
            response=device.post('/api/device/telemetry',json={'message_id':message,'observed_at':stamp.isoformat(),'readings':{'temperature':{'value':value,'unit':'C'}}})
            self.assertEqual(response.status_code,200,response.text)
        rows=owner.get(f"/api/cameras/{camera['id']}/telemetry").json()
        self.assertEqual(rows[0]['payload']['readings']['temperature']['value'],24)
        self.assertEqual(device.post('/api/device/telemetry',json={'message_id':'bad-unit','observed_at':db.now().isoformat(),'readings':{'temperature':{'value':24,'unit':'%'}}}).status_code,422)

    def test_pipeline_rolls_back_and_pool_does_not_leak_role_or_tenant(self):
        import psycopg
        owner,account=self.account('pool@example.com');home,room,camera,_=self.home_camera(owner)
        with self.assertRaises(psycopg.errors.DivisionByZero):
            with db.connect('app',home['id'],account['id']) as conn:
                self.assertEqual(str(conn.execute("SELECT current_setting('app.home_id') AS id").fetchone()['id']),home['id'])
                conn.execute('SELECT 1/0').fetchone()
        with db.POOLS['app'].connection() as conn:
            row=conn.execute("SELECT current_user=session_user AS reset,coalesce(current_setting('app.home_id',true),'') AS home").fetchone()
            self.assertTrue(row['reset']);self.assertEqual(row['home'],'')
        with db.connect('app') as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.cameras').fetchone()['n'],0)
        self.assertEqual(len(owner.get(f"/api/homes/{home['id']}/cameras").json()),1)

    def test_event_pagination_filters_and_home_archive(self):
        from backend.src.models import EventInput
        owner,user=self.account('pages@example.com');outsider,_=self.account('outside-pages@example.com')
        home,room,camera,provision=self.home_camera(owner)
        for index in range(13):
            services.ingest_event({'id':camera['id'],'home_id':home['id']},EventInput(event_id='pages-'+str(index),kind='fall' if index%2 else 'environment',severity='critical',observed_at=db.now().isoformat()))
        url=f"/api/homes/{home['id']}/events"
        first=owner.get(url+'?page=1&page_size=10').json();second=owner.get(url+'?page=2&page_size=10').json()
        self.assertEqual(first['total'],13);self.assertEqual(len(first['items']),10);self.assertEqual(len(second['items']),3)
        self.assertFalse({item['id'] for item in first['items']}&{item['id'] for item in second['items']})
        filtered=owner.get(url+f"?page=1&kind=fall&room_id={room['id']}&camera_id={camera['id']}&hours=24").json()
        self.assertEqual(filtered['total'],6);self.assertTrue(all(item['kind']=='fall' for item in filtered['items']))
        self.assertEqual(owner.get(url+'?page=0').status_code,422)
        self.assertEqual(outsider.get(url+'?page=1').status_code,404)
        self.assertEqual(owner.request('DELETE',f"/api/homes/{home['id']}",json={'confirmation':'wrong'}).status_code,422)
        self.assertEqual(outsider.request('DELETE',f"/api/homes/{home['id']}",json={'confirmation':home['name']}).status_code,404)
        result=owner.request('DELETE',f"/api/homes/{home['id']}",json={'confirmation':home['name']})
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn(home['id'],[item['id'] for item in owner.get('/api/homes').json()])
        self.assertEqual(owner.get(url).status_code,404)
        self.assertEqual(self.device(provision).post('/api/device/heartbeat',json={'message_id':'after-archive'}).status_code,401)
        with db.connect('app',home['id'],user['id']) as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.events').fetchone()['n'],0)
        with db.connect('worker',home['id']) as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.events WHERE home_id=%s',(home['id'],)).fetchone()['n'],13)

    def test_tts_preview_is_ephemeral_and_scoped(self):
        from unittest.mock import patch
        owner,_=self.account('preview@example.com');outsider,_=self.account('preview-outside@example.com')
        home,room,camera,_=self.home_camera(owner)
        url=f"/api/cameras/{camera['id']}/tts-preview"
        history=owner.get(f"/api/homes/{home['id']}/audit")
        self.assertEqual(history.status_code,200,history.text)
        self.assertTrue(any(item['user_name'] for item in history.json()))
        self.assertEqual(owner.get(f"/api/homes/{home['id']}/delivery-status").status_code,200)
        with patch('backend.src.tts.preview_audio',return_value=b'RIFF-preview-WAVE') as render:
            self.assertEqual(outsider.post(url,json={'text':'Xin chào'}).status_code,403)
            render.assert_not_called()
            self.assertEqual(owner.post(url,json={'text':' '}).status_code,422)
            response=owner.post(url,json={'text':'Xin chào'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.headers['content-type'],'audio/wav')
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(response.content,b'RIFF-preview-WAVE')
            render.assert_called_once_with('Xin chào')
        self.assertEqual(owner.get(f"/api/homes/{home['id']}/reminders").json(),[])
        self.assertEqual(owner.get(f"/api/homes/{home['id']}/assets").json(),[])
