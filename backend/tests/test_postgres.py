"""Live integration tests on an isolated Neon branch (never a production test runner).
ANNHA_TEST_ENV=.secrets/neon-test-runtime.env python3 -m unittest backend.tests.test_postgres -v
Synthetic rows are retained on the expiring test branch for inspection.
"""
import os
import logging
from pathlib import Path
import re
import secrets
import tempfile
import unittest
from urllib.parse import parse_qs,urlsplit
from fastapi.testclient import TestClient
from backend.src import pgdb as db, pgmain as main, pgservices as services

class _Phase3Cloudinary:
    name='cloudinary';environment='phase3test';delivery_type='authenticated'
    def __init__(self): self.objects={};self.calls=0;self.timeout_once=False
    def public_id(self,asset): return 'annha/phase3test/'+asset
    def resource_type(self,mime): return 'video'
    def upload(self,path,asset,mime):
        import hashlib
        body=Path(path).read_bytes();key=self.public_id(asset)
        self.calls+=1;self.objects[key]=body
        if self.timeout_once:
            self.timeout_once=False
            raise TimeoutError('synthetic response timeout after provider write')
        return services.media_storage.ProviderAsset(provider='cloudinary',provider_environment=self.environment,
            provider_asset_id='fake-'+asset,public_id=key,resource_type='video',delivery_type='authenticated',
            provider_version=self.calls,size_bytes=len(body),sha256=hashlib.sha256(body).digest())

@unittest.skipUnless(os.getenv('ANNHA_TEST_ENV'),'Requires explicit isolated-branch runtime env')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for line in Path(os.environ['ANNHA_TEST_ENV']).read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                key,value=line.split('=',1)
                value=value.strip()
                if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
                    value=value[1:-1]
                os.environ[key.strip()]=value
        os.environ.setdefault('SESSION_CSRF_KEY','phase5-postgres-test-csrf-key-only-not-for-deployment')
        cls.temp=tempfile.TemporaryDirectory();db.MEDIA_ROOT=Path(cls.temp.name)/'media'
        main.MQTT_ENABLED=False;main.WORKER_ENABLED=False
        cls.pool_log_levels={}
        for name in ('psycopg_pool','psycopg_pool.pool'):
            logger=logging.getLogger(name);cls.pool_log_levels[name]=logger.level;logger.setLevel(logging.CRITICAL)
        try:
            cls.context=TestClient(main.app);cls.client=cls.context.__enter__()
        except Exception:
            for name,level in cls.pool_log_levels.items(): logging.getLogger(name).setLevel(level)
            cls.temp.cleanup()
            raise
    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None,None,None);cls.temp.cleanup()
        for name,level in cls.pool_log_levels.items(): logging.getLogger(name).setLevel(level)
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
        code=re.search(r'Mã xác minh: (\d{8})',services.decrypt(row['secret_ciphertext'])['body'])[1]
        self.assertEqual(client.post('/api/auth/verify',json={'code':code}).status_code,200)
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

    def test_pi_self_enrollment(self):
        from backend.tests.device_pairing_cases import exercise_self_enrollment
        exercise_self_enrollment(self)

    def test_pairing_retries_after_config_failure_and_rotates_token(self):
        from unittest.mock import patch

        owner, _ = self.account('owner@example.com')
        home, room, _, _ = self.home_camera(owner)
        provision = services.provision_device('Camera cần khôi phục')
        device = self.device(provision)
        self.assertEqual(device.get('/api/device/config').status_code, 401)

        device_id = provision['device_id']
        renewed = services.refresh_device(device_id, rotate_token=False)
        path = f"/api/homes/{home['id']}/cameras/claim"
        payload = {'code': provision['pairing_code'], 'name': 'Camera cần khôi phục', 'room_id': room['id']}
        self.assertEqual(owner.post(path, json=payload).status_code, 400)

        payload['code'] = renewed['pairing_code']
        with patch.object(services, 'compile_config', side_effect=RuntimeError('configuration unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'configuration unavailable'):
                owner.post(path, json=payload)

        claimed = owner.post(path, json=payload)
        self.assertEqual(claimed.status_code, 201, claimed.text)
        self.assertEqual(owner.post(path, json=payload).json()['id'], claimed.json()['id'])
        self.assertEqual(device.get('/api/device/config').status_code, 200)

        rotated = services.refresh_device(device_id, rotate_token=True)
        self.assertEqual(device.get('/api/device/config').status_code, 401)
        config = self.device(rotated).get('/api/device/config')
        self.assertEqual(config.status_code, 200)
        self.assertEqual(config.json()['camera_id'], claimed.json()['id'])
        self.assertGreater(config.json()['version'], 0)

    def test_scoped_invitation_revocation_and_device_claim(self):
        owner,_=self.account('owner@example.com');viewer,viewer_user=self.account('viewer@example.com')
        home,room,camera,provision=self.home_camera(owner)
        self.assertEqual(viewer.get(f"/api/homes/{home['id']}/cameras").status_code,404)
        payload={'email':viewer_user['email'],'role':'viewer','scopes':[camera['id']],'rights':{}}
        response=owner.post(f"/api/homes/{home['id']}/invitations",json=payload)
        self.assertEqual(response.status_code,201,response.text)
        with db.connect('auth') as conn:
            invitation_mail=services.decrypt(conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'='invitation' ORDER BY created_at DESC LIMIT 1").fetchone()['secret_ciphertext'])
        body=invitation_mail['body']
        self.assertIn('Nhà test '+self.suffix,invitation_mail['html_body'])
        self.assertIn('Người xem',invitation_mail['html_body'])
        self.assertIn('Phòng khách · Test camera',invitation_mail['html_body'])
        self.assertIn('7 ngày',invitation_mail['html_body'])
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

    def test_camera_permissions_are_isolated_and_schedule_tts_obeys_rls(self):
        owner,_=self.account('owner@example.com')
        caregiver,caregiver_user=self.account('caregiver@example.com')
        viewer,viewer_user=self.account('viewer@example.com')
        home,room,first,_=self.home_camera(owner)
        cameras=[first]
        for name in ('Audio only','Both rights'):
            provision=services.provision_device(name)
            response=owner.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':provision['pairing_code'],'name':name,'room_id':room['id']})
            self.assertEqual(response.status_code,201,response.text);cameras.append(response.json())
        ids=[camera['id'] for camera in cameras]

        def create_invitation(account,role,permissions=None):
            response=owner.post(f"/api/homes/{home['id']}/invitations",json={
                'email':account['email'],'role':role,'scopes':ids,'rights':{},'camera_permissions':permissions or {}})
            self.assertEqual(response.status_code,201,response.text)
            with db.connect('auth') as conn:
                row=conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'='invitation' ORDER BY created_at DESC LIMIT 1").fetchone()
            token=re.search(r'token=([\w-]+)',services.decrypt(row['secret_ciphertext'])['body'])[1]
            return token

        caregiver_token=create_invitation(caregiver_user,'caregiver',{
            ids[0]:{'schedules':True},ids[1]:{'audio':True},ids[2]:{'audio':True,'schedules':True}})
        viewer_token=create_invitation(viewer_user,'viewer')
        self.assertEqual(caregiver.post(f'/api/invitations/{caregiver_token}/accept',json={}).status_code,200)
        self.assertEqual(viewer.post(f'/api/invitations/{viewer_token}/accept',json={}).status_code,200)
        caregiver_permissions={row['id']:row['permissions'] for row in caregiver.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertTrue(caregiver_permissions[ids[0]]['schedules']);self.assertFalse(caregiver_permissions[ids[0]]['audio'])
        self.assertTrue(caregiver_permissions[ids[1]]['audio']);self.assertFalse(caregiver_permissions[ids[1]]['schedules'])
        self.assertTrue(caregiver_permissions[ids[2]]['audio'] and caregiver_permissions[ids[2]]['schedules'])
        viewer_permissions={row['id']:row['permissions'] for row in viewer.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertTrue(all(rights['view'] and not rights['audio'] and not rights['schedules'] for rights in viewer_permissions.values()))

        outsider, _ = self.account('outsider@example.com')
        other_home, _, other_camera, _ = self.home_camera(outsider)
        self.assertEqual(caregiver.get(f"/api/cameras/{other_camera['id']}/config").status_code,404)
        self.assertNotIn(other_camera['id'],[row['id'] for row in caregiver.get(f"/api/homes/{home['id']}/cameras").json()])

        wav=b'RIFF'+(36).to_bytes(4,'little')+b'WAVEfmt '+b'\x00'*32
        schedule_asset=owner.post(f"/api/cameras/{ids[0]}/assets",content=wav,headers={'Content-Type':'audio/wav'})
        self.assertEqual(schedule_asset.status_code,201,schedule_asset.text)
        self.assertEqual(caregiver.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':ids[0],'name':'Dùng file có sẵn','time':'06:30','source':'audio','asset_id':schedule_asset.json()['id']}).status_code,201)
        tts=caregiver.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':ids[0],'name':'Nhắc lịch','time':'07:00','text':'Nhớ uống nước'})
        self.assertEqual(tts.status_code,201,tts.text)
        self.assertEqual(caregiver.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':ids[1],'name':'Sai quyền','time':'07:00','text':'Không được phép'}).status_code,403)
        self.assertEqual(caregiver.post(f"/api/cameras/{ids[0]}/commands",json={'kind':'test_speaker','idempotency_key':'no-audio-scope'}).status_code,403)
        self.assertEqual(caregiver.post(f"/api/cameras/{ids[1]}/commands",json={'kind':'test_speaker','idempotency_key':'audio-scope'}).status_code,201)
        uploaded=caregiver.post(f"/api/cameras/{ids[1]}/assets",content=wav,headers={'Content-Type':'audio/wav'})
        self.assertEqual(uploaded.status_code,201,uploaded.text);asset=uploaded.json()
        self.assertEqual(caregiver.post(f"/api/cameras/{ids[0]}/assets",content=wav,headers={'Content-Type':'audio/wav'}).status_code,403)
        self.assertEqual(caregiver.get(f"/api/assets/{asset['id']}").status_code,200)
        self.assertEqual(viewer.get(f"/api/assets/{asset['id']}").status_code,403)
        self.assertEqual(caregiver.delete(f"/api/assets/{asset['id']}").status_code,403)
        self.assertEqual(caregiver.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':ids[2],'name':'Khác camera','time':'08:00','source':'audio','asset_id':asset['id']}).status_code,404)
        both_audio=caregiver.post(f"/api/cameras/{ids[2]}/assets",content=wav,headers={'Content-Type':'audio/wav'})
        self.assertEqual(both_audio.status_code,201,both_audio.text)
        self.assertEqual(caregiver.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':ids[2],'name':'Đủ hai quyền','time':'08:30','source':'audio','asset_id':both_audio.json()['id']}).status_code,201)

        revised={ids[0]:{'schedules':False},ids[1]:{'audio':True},ids[2]:{'audio':True,'schedules':True}}
        with caregiver.websocket_connect(f"/ws/alerts?home_id={home['id']}") as socket:
            response=owner.patch(f"/api/homes/{home['id']}/members/{caregiver_user['id']}",json={'role':'caregiver','scopes':ids,'rights':{},'camera_permissions':revised})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(socket.receive()['type'],'websocket.close')
        updated={row['id']:row['permissions'] for row in caregiver.get(f"/api/homes/{home['id']}/cameras").json()}
        self.assertFalse(updated[ids[0]]['schedules'])
        self.assertEqual(caregiver.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':ids[0],'name':'Thu hồi','time':'07:00','text':'Không được phép'}).status_code,403)
        self.assertEqual(caregiver.get('/api/auth/me').status_code,200)

    def test_cloud_media_storage_quota_ranges_delete_and_local_migration(self):
        import hashlib
        from io import BytesIO
        from unittest.mock import patch
        from backend.src import media_migration, media_storage

        class ProviderResponse:
            def __init__(self, body, start, end, full_size):
                self.body=BytesIO(body);self.status=206 if start or end < full_size-1 else 200
                self.headers={'Content-Length':str(len(body)),'Accept-Ranges':'bytes'}
                if self.status==206: self.headers['Content-Range']=f'bytes {start}-{end}/{full_size}'
            def read(self,size=-1): return self.body.read(size)
            def close(self): self.body.close()

        class FakeCloudinary:
            name='cloudinary'
            environment='test';delivery_type='authenticated'
            def __init__(self): self.assets={};self.deleted=[];self.fail_upload=False;self.fail_read=False
            def public_id(self,media_id): return f'annha/test/{media_id}'
            @staticmethod
            def resource_type(mime_type): return 'video' if mime_type.startswith(('audio/','video/')) else 'image'
            def upload(self,path,media_id,mime_type):
                if self.fail_upload: raise media_storage.MediaUnavailable('fixture upload failure')
                body=Path(path).read_bytes();digest=hashlib.sha256(body).digest()
                resource='video' if mime_type.startswith('audio/') or mime_type.startswith('video/') else 'image'
                public_id=f'annha/test/{media_id}';self.assets[public_id]=body
                return media_storage.ProviderAsset(provider='cloudinary',provider_environment='test',
                    provider_asset_id='provider-'+media_id,public_id=public_id,resource_type=resource,
                    delivery_type='authenticated',provider_version=1,size_bytes=len(body),sha256=digest)
            def open_read(self,row,range_header=None):
                if self.fail_read: raise media_storage.MediaUnavailable('fixture read failure')
                body=self.assets.get(row['public_id'])
                if body is None: raise media_storage.MediaNotFound('fixture asset missing')
                start,end=0,len(body)-1
                if range_header:
                    match=re.fullmatch(r'bytes=(\d+)-(\d*)',range_header)
                    if not match: raise media_storage.MediaUnavailable('unsupported test range')
                    start=int(match.group(1));end=int(match.group(2) or end)
                return ProviderResponse(body[start:end+1],start,end,len(body))
            def verify(self,row,expected_size,expected_sha256=None):
                body=self.assets.get(row['public_id'])
                return body is not None and len(body)==expected_size and (expected_sha256 is None or hashlib.sha256(body).digest()==bytes(expected_sha256))
            def delete(self,row):
                self.deleted.append(row['public_id']);self.assets.pop(row['public_id'],None)

        owner,_=self.account('media-owner@example.com');viewer,viewer_user=self.account('media-viewer@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        invitation=owner.post(f"/api/homes/{home['id']}/invitations",json={
            'email':viewer_user['email'],'role':'viewer','scopes':[camera['id']],'rights':{}})
        self.assertEqual(invitation.status_code,201,invitation.text)
        with db.connect('auth') as conn:
            body=services.decrypt(conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'='invitation' ORDER BY created_at DESC LIMIT 1").fetchone()['secret_ciphertext'])['body']
        token=re.search(r'token=([\w-]+)',body)[1]
        self.assertEqual(viewer.post(f'/api/invitations/{token}/accept',json={}).status_code,200)

        cloud=FakeCloudinary()
        with patch('backend.src.pgapi.media_storage.preferred_provider',return_value=cloud), \
             patch('backend.src.pgservices.media_storage.CloudinaryStorage',return_value=cloud):
            wav=b'RIFF'+(36).to_bytes(4,'little')+b'WAVEfmt '+b'\x00'*32
            uploaded=owner.post(f"/api/cameras/{camera['id']}/assets",content=wav,headers={'Content-Type':'audio/wav'})
            self.assertEqual(uploaded.status_code,201,uploaded.text);audio_id=uploaded.json()['id']
            self.assertEqual(uploaded.json()['status'],'ready')
            self.assertEqual(viewer.get(f"/api/assets/{audio_id}").status_code,403)
            ranged=owner.get(f"/api/assets/{audio_id}",headers={'Range':'bytes=1-3'})
            self.assertEqual(ranged.status_code,206);self.assertEqual(ranged.content,wav[1:4])
            self.assertEqual(ranged.headers['content-range'],f'bytes 1-3/{len(wav)}')

            event=device.post('/api/device/events',json={'event_id':'cloud-evidence','kind':'fall',
                'severity':'warning','observed_at':db.now().isoformat()})
            self.assertEqual(event.status_code,200,event.text)
            clip=b'\x00\x00\x00\x18ftypisom'+b'fixture-video'
            evidence=device.post(f"/api/device/evidence?event_id={event.json()['id']}",content=clip,
                headers={'Content-Type':'video/mp4'})
            self.assertEqual(evidence.status_code,201,evidence.text)
            event_detail=owner.get(f"/api/events/{event.json()['id']}").json()
            self.assertTrue(any(item['id']==evidence.json()['id'] and item['status']=='ready' for item in event_detail['evidence']))
            self.assertEqual(owner.get(f"/api/assets/{evidence.json()['id']}").content,clip)

            # Legacy local assets are copied and verified before Neon metadata changes;
            # the original remains available for fallback and rollback.
            with patch('backend.src.pgapi.media_storage.preferred_provider',side_effect=lambda root:media_storage.LocalStorage(root)):
                image=b'\x89PNG\r\n\x1a\nlocal-migration-fixture'
                local=device.post('/api/device/evidence',content=image,headers={'Content-Type':'image/png'})
            self.assertEqual(local.status_code,201,local.text)
            legacy_rows=[item for item in media_migration._assets() if item[0]==home['id']]
            eligible,summary=media_migration._eligible(db.MEDIA_ROOT,legacy_rows)
            self.assertEqual(summary['eligible'],1)
            migrated,errors=media_migration.migrate(eligible,db.MEDIA_ROOT,limit=1,batch_size=1)
            self.assertEqual(errors,[]);self.assertEqual(migrated['migrated'],1)
            with db.connect('worker',home['id']) as conn:
                local_row=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(local.json()['id'],)).fetchone()
                storage=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(local_row['provider'],'cloudinary');self.assertTrue(local_row['local_object_key'])
            self.assertTrue((db.MEDIA_ROOT/local_row['local_object_key']).is_file())
            self.assertEqual(storage['reserved_bytes'],0)
            cloud.fail_read=True
            fallback=owner.get(f"/api/assets/{local.json()['id']}")
            self.assertEqual(fallback.status_code,200);self.assertEqual(fallback.content,image)
            self.assertEqual(fallback.headers['x-media-source'],'local-fallback')
            cloud.fail_read=False

            before=storage['used_bytes']
            removed=owner.delete(f"/api/assets/{audio_id}")
            self.assertEqual(removed.status_code,200,removed.text)
            with db.connect('worker',home['id']) as conn:
                job=conn.execute("SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s",('media-delete:'+audio_id,)).fetchone()
            services.process_job(str(job['id']))
            with db.connect('worker',home['id']) as conn:
                deleted=conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(audio_id,)).fetchone()
                after=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(deleted['status'],'deleted');self.assertIn(f'annha/test/{audio_id}',cloud.deleted)
            self.assertEqual(before-after['used_bytes'],len(wav));self.assertEqual(after['reserved_bytes'],0)

            cloud.fail_upload=True
            failed_upload=owner.post(f"/api/cameras/{camera['id']}/assets",content=wav,headers={'Content-Type':'audio/wav'})
            self.assertEqual(failed_upload.status_code,201);failed_id=failed_upload.json()['id']
            self.assertEqual(failed_upload.json()['status'],'uploading')
            with db.connect('worker',home['id']) as conn:
                failed_job=conn.execute("SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s",('media-upload:'+failed_id,)).fetchone()
            for _ in range(4):
                with db.connect('worker',home['id']) as conn:
                    conn.execute("UPDATE annha_private.job_queue SET available_at=now() WHERE id=%s",(failed_job['id'],))
                services.process_job(str(failed_job['id']))
            with db.connect('worker',home['id']) as conn:
                failed=conn.execute('SELECT status,reserved_bytes FROM annha.media_assets WHERE id=%s',(failed_id,)).fetchone()
                quota=conn.execute('SELECT reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(failed['status'],'failed');self.assertEqual(failed['reserved_bytes'],0)
            self.assertEqual(quota['reserved_bytes'],0)
            staged_key=next((db.MEDIA_ROOT/'.staging').glob(f'{failed_id}.wav'))
            self.assertTrue(staged_key.is_file())
            with db.connect('worker',home['id']) as conn:
                used_before_retry=conn.execute('SELECT used_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()['used_bytes']
            self.assertEqual(owner.post(f'/api/assets/{failed_id}/retry').status_code,202)
            with db.connect('worker',home['id']) as conn:
                retry_quota=conn.execute('SELECT reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(retry_quota['reserved_bytes'],len(wav))
            cloud.fail_upload=False
            with db.connect('worker',home['id']) as conn:
                retry_job=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('media-upload:'+failed_id,)).fetchone()
            services.process_job(str(retry_job['id']))
            with db.connect('worker',home['id']) as conn:
                retried=conn.execute('SELECT status,ready_at FROM annha.media_assets WHERE id=%s',(failed_id,)).fetchone()
                retry_quota=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(retried['status'],'ready');self.assertIsNotNone(retried['ready_at'])
            self.assertEqual(retry_quota['used_bytes'],used_before_retry+len(wav));self.assertEqual(retry_quota['reserved_bytes'],0)
            self.assertFalse(staged_key.exists())
            self.assertEqual(owner.delete(f'/api/assets/{failed_id}').status_code,200)
            with db.connect('worker',home['id']) as conn:
                delete_job=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('media-delete:'+failed_id,)).fetchone()
            services.process_job(str(delete_job['id']))
            with db.connect('worker',home['id']) as conn:
                after_retry_delete=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(after_retry_delete['used_bytes'],used_before_retry);self.assertEqual(after_retry_delete['reserved_bytes'],0)

    def test_local_media_migration_resumes_after_provider_commit_interruption(self):
        import hashlib
        from unittest.mock import patch
        from backend.src import media_migration, media_storage

        owner,_=self.account('migration-recovery@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        image=b'\x89PNG\r\n\x1a\nresumable-migration-fixture'
        with patch('backend.src.pgapi.media_storage.preferred_provider',side_effect=lambda root:media_storage.LocalStorage(root)):
            uploaded=device.post('/api/device/evidence',content=image,headers={'Content-Type':'image/png'})
        self.assertEqual(uploaded.status_code,201,uploaded.text)
        rows=[item for item in media_migration._assets() if item[0]==home['id']]
        eligible,summary=media_migration._eligible(db.MEDIA_ROOT,rows)
        self.assertEqual(summary['eligible'],1)

        class ResumableCloudinary:
            def __init__(self): self.assets={};self.uploads=[]
            def upload(self,path,asset_id,mime_type):
                body=Path(path).read_bytes();digest=hashlib.sha256(body).digest()
                public_id=f'annha/recovery/{asset_id}';self.uploads.append(public_id);self.assets[public_id]=body
                return media_storage.ProviderAsset(provider='cloudinary',provider_environment='test',
                    provider_asset_id='provider-'+asset_id,public_id=public_id,resource_type='image',
                    delivery_type='authenticated',provider_version=1,size_bytes=len(body),sha256=digest)
            def verify(self,row,expected_size,expected_sha256=None):
                body=self.assets.get(row['public_id'])
                return body is not None and len(body)==expected_size and hashlib.sha256(body).digest()==expected_sha256

        cloud=ResumableCloudinary()
        with patch('backend.src.media_migration.media_storage.CloudinaryStorage',return_value=cloud):
            with patch('backend.src.media_migration._commit_cloud_metadata',side_effect=RuntimeError('simulated commit interruption')):
                interrupted,errors=media_migration.migrate(eligible,db.MEDIA_ROOT,limit=1,batch_size=1)
            self.assertEqual(interrupted['failed'],1);self.assertEqual(errors,['RuntimeError'])
            with db.connect('worker',home['id']) as conn:
                before=conn.execute('SELECT provider,status FROM annha.media_assets WHERE id=%s',(uploaded.json()['id'],)).fetchone()
            self.assertEqual((before['provider'],before['status']),('local','ready'))
            recovered,errors=media_migration.migrate(eligible,db.MEDIA_ROOT,limit=1,batch_size=1)
        self.assertEqual(errors,[]);self.assertEqual(recovered['migrated'],1)
        self.assertEqual(len(cloud.uploads),2);self.assertEqual(cloud.uploads[0],cloud.uploads[1])
        with db.connect('worker',home['id']) as conn:
            after=conn.execute('SELECT provider,status,public_id FROM annha.media_assets WHERE id=%s',(uploaded.json()['id'],)).fetchone()
        self.assertEqual(after['provider'],'cloudinary');self.assertEqual(after['status'],'ready')
        self.assertEqual(after['public_id'],cloud.uploads[0])
        self.assertTrue((db.MEDIA_ROOT/next(item[1]['local_object_key'] for item in rows if str(item[1]['id'])==uploaded.json()['id'])).is_file())

    @unittest.skipUnless(os.getenv('ANNHA_CLOUDINARY_LIVE_TEST')=='1','Explicit live Cloudinary smoke only')
    def test_cloudinary_live_smoke(self):
        from io import BytesIO
        import struct
        import zlib
        import wave
        import cloudinary.api
        from cloudinary.exceptions import NotFound
        from unittest.mock import patch
        from backend.src import media_storage

        def png_fixture():
            def chunk(kind,data):
                return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
            return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',1,1,8,6,0,0,0))+
                    chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00\xff'))+chunk(b'IEND',b''))

        def jpeg_fixture():
            import base64
            return base64.b64decode('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd3eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDnaKKK7T5M/9k=')

        def mp3_fixture():
            # Five valid MPEG-1 Layer III frames; synthetic silence, no user audio.
            return (bytes.fromhex('fffb9000')+bytes(413))*5

        owner,_=self.account('cloud-smoke-owner@example.com');outsider,_=self.account('cloud-smoke-outsider@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        cloud=media_storage.CloudinaryStorage()
        media_ids=[];rows_before_delete={};cloud_errors=[];reminders=[]
        try:
            image=png_fixture()
            event=device.post('/api/device/events',json={'event_id':'image-evidence','kind':'fall',
                'severity':'warning','observed_at':db.now().isoformat()})
            self.assertEqual(event.status_code,200,event.text)
            uploaded_image=device.post(f"/api/device/evidence?event_id={event.json()['id']}",content=image,headers={'Content-Type':'image/png'})
            self.assertEqual(uploaded_image.status_code,201,uploaded_image.text)
            image_id=uploaded_image.json()['id'];media_ids.append(image_id)
            self.assertEqual(uploaded_image.json()['status'],'ready')
            self.assertEqual(owner.get(f'/api/assets/{image_id}').content,image)
            event_detail=owner.get(f"/api/events/{event.json()['id']}").json()
            self.assertTrue(any(asset['id']==image_id and asset['kind']=='event_image' for asset in event_detail['evidence']))
            self.assertEqual(outsider.get(f'/api/assets/{image_id}').status_code,404)
            self.assertEqual(outsider.delete(f'/api/assets/{image_id}').status_code,404)

            jpeg=jpeg_fixture()
            snapshot=device.post('/api/device/evidence',content=jpeg,headers={'Content-Type':'image/jpeg'})
            self.assertEqual(snapshot.status_code,201,snapshot.text)
            snapshot_id=snapshot.json()['id'];media_ids.append(snapshot_id)
            self.assertEqual(snapshot.json()['status'],'ready')
            self.assertEqual(owner.get(f'/api/cameras/{camera["id"]}/snapshot').content,jpeg)
            self.assertTrue(owner.get(f"/api/homes/{home['id']}/cameras").json()[0]['snapshot_available'])

            buffer=BytesIO()
            with wave.open(buffer,'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000)
                stream.writeframes(b'\x00\x00'*800)
            audio=buffer.getvalue()
            uploaded_audio=owner.post(f'/api/cameras/{camera["id"]}/assets',content=audio,
                headers={'Content-Type':'audio/wav'})
            self.assertEqual(uploaded_audio.status_code,201,uploaded_audio.text)
            audio_id=uploaded_audio.json()['id'];media_ids.append(audio_id)
            self.assertEqual(uploaded_audio.json()['status'],'ready')
            self.assertEqual(owner.get(f'/api/assets/{audio_id}').content,audio)
            ranged=owner.get(f'/api/assets/{audio_id}',headers={'Range':'bytes=10-31'})
            self.assertEqual(ranged.status_code,206);self.assertEqual(ranged.content,audio[10:32])
            self.assertEqual(ranged.headers['content-range'],f'bytes 10-31/{len(audio)}')
            self.assertEqual(outsider.get(f'/api/assets/{audio_id}').status_code,404)

            mp3=mp3_fixture()
            uploaded_mp3=owner.post(f'/api/cameras/{camera["id"]}/assets',content=mp3,
                headers={'Content-Type':'audio/mpeg','X-File-Name':'fixture.mp3'})
            self.assertEqual(uploaded_mp3.status_code,201,uploaded_mp3.text)
            mp3_id=uploaded_mp3.json()['id'];media_ids.append(mp3_id)
            self.assertEqual(uploaded_mp3.json()['status'],'ready')
            self.assertEqual(owner.get(f'/api/assets/{mp3_id}').content,mp3)
            mp3_range=owner.get(f'/api/assets/{mp3_id}',headers={'Range':'bytes=4-27'})
            self.assertEqual(mp3_range.status_code,206);self.assertEqual(mp3_range.content,mp3[4:28])
            self.assertEqual(mp3_range.headers['content-range'],f'bytes 4-27/{len(mp3)}')
            self.assertEqual(outsider.get(f'/api/assets/{mp3_id}').status_code,404)

            preview=owner.post(f'/api/cameras/{camera["id"]}/tts-preview',json={'text':'Nhớ uống nước nhé.'})
            self.assertEqual(preview.status_code,200,preview.text)
            self.assertTrue(preview.content.startswith(b'RIFF') and preview.content[8:12]==b'WAVE')

            def create_tts(name,text):
                response=owner.post(f"/api/homes/{home['id']}/reminders",json={
                    'camera_id':camera['id'],'name':name,'time':'07:00','weekdays':[0,1,2,3,4,5,6],
                    'timezone':'Asia/Ho_Chi_Minh','enabled':True,'source':'tts','text':text,'volume':70,'late_seconds':0})
                self.assertEqual(response.status_code,201,response.text)
                reminder=response.json();reminders.append(reminder['id'])
                with db.connect('worker',home['id']) as conn:
                    job=conn.execute("SELECT id FROM annha_private.job_queue WHERE kind='tts' AND asset_id=%s",(reminder['asset_id'],)).fetchone()
                self.assertIsNotNone(job)
                return reminder,str(job['id'])

            first_tts,first_job=create_tts('Nhắc thử','Nhớ uống nước nhé.')
            services.process_job(first_job)
            ready_tts=owner.get(f"/api/assets/{first_tts['asset_id']}")
            self.assertEqual(ready_tts.status_code,200)
            self.assertTrue(ready_tts.content.startswith(b'RIFF') and ready_tts.content[8:12]==b'WAVE')
            tts_range=owner.get(f"/api/assets/{first_tts['asset_id']}",headers={'Range':'bytes=0-31'})
            self.assertEqual(tts_range.status_code,206);self.assertEqual(tts_range.content,ready_tts.content[:32])
            self.assertEqual(owner.delete(f"/api/assets/{first_tts['asset_id']}").status_code,409)
            with db.connect('worker',home['id']) as conn:
                tts_row=conn.execute('SELECT provider,resource_type,public_id,size_bytes FROM annha.media_assets WHERE id=%s',(first_tts['asset_id'],)).fetchone()
                quota=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(tts_row['provider'],'cloudinary');self.assertEqual(tts_row['resource_type'],'video')
            self.assertTrue(tts_row['public_id'].startswith('annha/phase2smoke/'))
            self.assertGreater(tts_row['size_bytes'],0);self.assertEqual(quota['reserved_bytes'],0)

            retry_tts,retry_job=create_tts('Nhắc thử lại','Thử lại một lần an toàn.')
            with db.connect('worker',home['id']) as conn:
                conn.execute('UPDATE annha_private.job_queue SET attempts=4 WHERE id=%s',(retry_job,))
            with patch.object(services,'_upload_cloud_asset',side_effect=media_storage.MediaUnavailable('synthetic provider failure')):
                services.process_job(retry_job)
            with db.connect('worker',home['id']) as conn:
                failed=conn.execute('SELECT status,reserved_bytes FROM annha.media_assets WHERE id=%s',(retry_tts['asset_id'],)).fetchone()
                quota=conn.execute('SELECT reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(failed['status'],'failed');self.assertEqual(failed['reserved_bytes'],0)
            self.assertEqual(quota['reserved_bytes'],0)
            self.assertEqual(owner.post(f"/api/assets/{retry_tts['asset_id']}/retry").status_code,202)
            services.process_job(retry_job)
            retried=owner.get(f"/api/assets/{retry_tts['asset_id']}")
            self.assertEqual(retried.status_code,200)
            self.assertTrue(retried.content.startswith(b'RIFF') and retried.content[8:12]==b'WAVE')
            with db.connect('worker',home['id']) as conn:
                retry_row=conn.execute('SELECT provider,public_id,status FROM annha.media_assets WHERE id=%s',(retry_tts['asset_id'],)).fetchone()
                quota=conn.execute('SELECT reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(retry_row['status'],'ready');self.assertEqual(retry_row['provider'],'cloudinary')
            self.assertEqual(retry_row['public_id'],'annha/phase2smoke/'+retry_tts['asset_id'])
            self.assertEqual(quota['reserved_bytes'],0)
            self.assertEqual(owner.delete(f"/api/assets/{retry_tts['asset_id']}").status_code,409)

            with db.connect('worker',home['id']) as conn:
                rows=conn.execute('SELECT * FROM annha.media_assets WHERE id=ANY(%s::uuid[])',([image_id,snapshot_id,audio_id,mp3_id],)).fetchall()
                quota=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(len(rows),4);self.assertEqual(quota['reserved_bytes'],0)
            self.assertEqual(quota['reserved_bytes'],0)
            rows_before_delete={str(row['id']):dict(row) for row in rows}
            self.assertTrue(all(row['provider']=='cloudinary' and row['delivery_type']=='authenticated'
                and row['provider_environment']=='phase2smoke' and row['public_id'].startswith('annha/phase2smoke/')
                for row in rows))

            storage_state=owner.get(f"/api/homes/{home['id']}/storage")
            self.assertEqual(storage_state.status_code,200,storage_state.text)
            self.assertGreater(storage_state.json()['quota_bytes'],storage_state.json()['used_bytes'])
            self.assertEqual(storage_state.json()['reserved_bytes'],0)

            for reminder_id in reminders:
                self.assertEqual(owner.delete(f'/api/reminders/{reminder_id}').status_code,200)
            for media_id in (first_tts['asset_id'],retry_tts['asset_id']):
                deleted=owner.delete(f'/api/assets/{media_id}')
                self.assertEqual(deleted.status_code,200,deleted.text)
                with db.connect('worker',home['id']) as conn:
                    job=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('media-delete:'+media_id,)).fetchone()
                services.process_job(str(job['id']))
                with db.connect('worker',home['id']) as conn:
                    rows_before_delete[media_id]=dict(conn.execute('SELECT * FROM annha.media_assets WHERE id=%s',(media_id,)).fetchone())
                with self.assertRaises(NotFound):
                    cloudinary.api.resource(rows_before_delete[media_id]['public_id'],resource_type='video',type='authenticated')
                with db.connect('worker',home['id']) as conn:
                    tts_state=conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(media_id,)).fetchone()
                self.assertEqual(tts_state['status'],'deleted')
            media_ids.extend((first_tts['asset_id'],retry_tts['asset_id']))

            for media_id in media_ids:
                deleted=owner.delete(f'/api/assets/{media_id}')
                self.assertEqual(deleted.status_code,200,deleted.text)
                with db.connect('worker',home['id']) as conn:
                    job=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('media-delete:'+media_id,)).fetchone()
                services.process_job(str(job['id']))
                with db.connect('worker',home['id']) as conn:
                    state=conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(media_id,)).fetchone()
                self.assertEqual(state['status'],'deleted')
                # CDN invalidation can lag after a successful provider deletion.
                # Confirm origin state through Cloudinary's Admin API instead of
                # requiring the signed delivery URL to stop serving cached bytes.
                with self.assertRaises(NotFound):
                    cloudinary.api.resource(rows_before_delete[media_id]['public_id'],
                        resource_type=rows_before_delete[media_id]['resource_type'],
                        type=rows_before_delete[media_id]['delivery_type'])
            with db.connect('worker',home['id']) as conn:
                quota=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
            self.assertEqual(quota['used_bytes'],0);self.assertEqual(quota['reserved_bytes'],0)
        finally:
            # Safety cleanup also covers an upload that reached Cloudinary but failed
            # before its provider identifiers were committed to PostgreSQL.
            if home:
                with db.connect('worker',home['id']) as conn:
                    rows=conn.execute('SELECT * FROM annha.media_assets WHERE home_id=%s',(home['id'],)).fetchall()
                for row in rows:
                    if row['provider']=='cloudinary' or row['status'] in ('uploading','failed'):
                        resource=row['resource_type'] or cloud.resource_type(row['mime_type'])
                        public_id=row['public_id'] or cloud.public_id(str(row['id']))
                        try: cloud.delete({'public_id':public_id,'resource_type':resource})
                        except Exception as error: cloud_errors.append(type(error).__name__)
                if cloud_errors: self.fail('Cloudinary smoke cleanup failed: '+','.join(sorted(set(cloud_errors))))

    def test_zone_fields_are_not_part_of_current_config_or_event_contract(self):
        owner,_=self.account('zone-contract@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        config=owner.get(f"/api/cameras/{camera['id']}/config").json()
        self.assertNotIn('zones',config['payload']);self.assertNotIn('reference',config['payload'])
        self.assertNotIn('zone_id',main.app.openapi()['components']['schemas']['EventInput']['properties'])
        self.assertNotIn('/api/cameras/{camera_id}/zones',main.app.openapi()['paths'])
        event={'event_id':'zone-field-rejected','kind':'fall','severity':'warning','observed_at':db.now().isoformat(),'zone_id':'old-zone'}
        self.assertEqual(device.post('/api/device/events',json=event).status_code,422)

        legacy={'version':config['desired_version']+1,'camera_id':camera['id'],'zones':[],'reference':{},'environment':{},'reminders':[]}
        with db.connect('worker',home['id'],camera=camera['id']) as conn:
            conn.execute('INSERT INTO annha.camera_configurations(home_id,camera_id,version,payload) VALUES(%s,%s,%s,%s)',(home['id'],camera['id'],legacy['version'],db.J(legacy)))
            conn.execute('UPDATE annha.camera_config_state SET desired_version=%s WHERE camera_id=%s',(legacy['version'],camera['id']))
        services.retire_zone_configs()
        current=owner.get(f"/api/cameras/{camera['id']}/config").json()
        self.assertEqual(current['desired_version'],legacy['version']+1)
        self.assertNotIn('zones',current['payload']);self.assertNotIn('reference',current['payload'])
        self.assertEqual(device.get('/api/device/config').json()['zones'],[])
        self.assertEqual(device.post('/api/device/config/ack',json={'version':current['desired_version'],'success':True}).status_code,200)
        with db.connect('worker',home['id'],camera=camera['id']) as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.camera_configurations WHERE camera_id=%s',(camera['id'],)).fetchone()['n'],3)

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
        with db.connect('worker',home['id']) as conn:
            queued=conn.execute("SELECT status,secret_ciphertext IS NOT NULL AS encrypted FROM annha_private.job_queue WHERE idempotency_key=%s",('tts:'+reminder['asset_id'],)).fetchone()
        self.assertEqual(queued,{'status':'pending','encrypted':True})
        self.assertEqual(owner.get(f"/api/homes/{home['id']}/reminders").json()[0]['asset_status'],'processing')
        from unittest.mock import patch
        with patch('backend.src.pgapi.svc.encrypt',side_effect=RuntimeError('qa-encryption-failure')):
            with self.assertRaisesRegex(RuntimeError,'qa-encryption-failure'):
                owner.post(f"/api/homes/{home['id']}/reminders",json={**payload,'name':'Phải rollback'})
        with db.connect('worker',home['id']) as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM annha.reminders WHERE name='Phải rollback'").fetchone()['n'],0)
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM annha.media_assets WHERE name='Phải rollback.wav'").fetchone()['n'],0)
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

    def test_tts_worker_finishes_asset_separately_and_quota_failure_is_retryable(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        owner,_=self.account('tts-worker@example.com');home,room,camera,provision=self.home_camera(owner)
        def create(name):
            response=owner.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':camera['id'],'name':name,'time':'08:00','text':'Nhắc uống nước','source':'tts'})
            self.assertEqual(response.status_code,201,response.text)
            with db.connect('worker',home['id']) as conn:
                return response.json(),conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('tts:'+response.json()['asset_id'],)).fetchone()['id']
        def render(command,**kwargs):
            output=command[command.index('-w')+1]
            Path(output).write_bytes(b'RIFF'+(36).to_bytes(4,'little')+b'WAVE'+b'\0'*40)
        successful,job_id=create('TTS worker thành công')
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=render), \
             patch('backend.src.pgservices.media_storage.preferred_provider',side_effect=lambda root:services.media_storage.LocalStorage(root)):
            services.process_job(job_id,['tts'])
        with db.connect('worker',home['id']) as conn:
            asset=conn.execute('SELECT status,error_code FROM annha.media_assets WHERE id=%s',(successful['asset_id'],)).fetchone()
            job=conn.execute("SELECT status,secret_ciphertext FROM annha_private.job_queue WHERE id=%s",(job_id,)).fetchone()
            compile_job=conn.execute("SELECT status FROM annha_private.job_queue WHERE idempotency_key=%s",('compile-tts:'+successful['asset_id'],)).fetchone()
        self.assertEqual(asset,{'status':'ready','error_code':None})
        self.assertEqual(job,{'status':'done','secret_ciphertext':None})
        self.assertEqual(compile_job['status'],'pending')

        with db.connect('worker',home['id']) as conn:
            conn.execute('UPDATE annha.home_storage SET used_bytes=quota_bytes WHERE home_id=%s',(home['id'],))
        quota_asset,quota_job_id=create('TTS worker vượt quota')
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=render), \
             patch('backend.src.pgservices.media_storage.preferred_provider',side_effect=lambda root:services.media_storage.LocalStorage(root)):
            services.process_job(quota_job_id,['tts'])
        with db.connect('worker',home['id']) as conn:
            asset=conn.execute('SELECT status,error_code,reserved_bytes FROM annha.media_assets WHERE id=%s',(quota_asset['asset_id'],)).fetchone()
            job=conn.execute('SELECT status,last_error_code,secret_ciphertext IS NOT NULL AS retryable FROM annha_private.job_queue WHERE id=%s',(quota_job_id,)).fetchone()
            storage=conn.execute('SELECT reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
        self.assertEqual(asset,{'status':'failed','error_code':'QuotaExceeded','reserved_bytes':0})
        self.assertEqual(job,{'status':'failed','last_error_code':'QuotaExceeded','retryable':True})
        self.assertEqual(storage['reserved_bytes'],0)

        cloud_quota_asset,cloud_quota_job=create('TTS Cloudinary vượt quota')
        provider=SimpleNamespace(name='cloudinary',environment='phase3test',delivery_type='authenticated',
            public_id=lambda asset:'annha/phase3test/'+asset,resource_type=lambda mime:'video')
        upload=Mock()
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=render), \
             patch('backend.src.pgservices.media_storage.preferred_provider',return_value=provider), \
             patch('backend.src.pgservices.media_storage.CloudinaryStorage',return_value=provider), \
             patch('backend.src.pgservices._upload_cloud_asset',upload):
            services.process_job(cloud_quota_job,['tts'])
        with db.connect('worker',home['id']) as conn:
            cloud_asset=conn.execute('SELECT status,error_code,reserved_bytes FROM annha.media_assets WHERE id=%s',(cloud_quota_asset['asset_id'],)).fetchone()
            cloud_job=conn.execute('SELECT status,last_error_code FROM annha_private.job_queue WHERE id=%s',(cloud_quota_job,)).fetchone()
            cloud_storage=conn.execute('SELECT reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home['id'],)).fetchone()
        self.assertEqual(cloud_asset,{'status':'failed','error_code':'QuotaExceeded','reserved_bytes':0})
        self.assertEqual(cloud_job,{'status':'failed','last_error_code':'QuotaExceeded'})
        self.assertEqual(cloud_storage['reserved_bytes'],0);upload.assert_not_called()

    def test_tts_worker_cancels_when_asset_is_deleted_during_generation(self):
        from unittest.mock import patch
        owner,_=self.account('tts-delete-race@example.com');home,room,camera,provision=self.home_camera(owner)
        response=owner.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':camera['id'],'name':'Nhắc sẽ bị xoá','time':'08:00','text':'Nhắc uống nước','source':'tts'})
        self.assertEqual(response.status_code,201,response.text)
        asset_id=response.json()['asset_id']
        with db.connect('worker',home['id']) as conn:
            job_id=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('tts:'+asset_id,)).fetchone()['id']
        def render_then_delete(command,**kwargs):
            Path(command[command.index('-w')+1]).write_bytes(b'RIFF'+(36).to_bytes(4,'little')+b'WAVE'+b'\0'*40)
            with db.connect('worker',home['id']) as conn:
                conn.execute("UPDATE annha.media_assets SET status='deleting',deletion_requested_at=now() WHERE id=%s",(asset_id,))
                conn.execute("""INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,idempotency_key)
                    VALUES(%s,'delete_media',%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING""",
                    (home['id'],asset_id,db.J({'target_status':'deleted'}),'media-delete:'+asset_id))
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=render_then_delete), \
             patch('backend.src.pgservices.media_storage.preferred_provider',side_effect=lambda root:services.media_storage.LocalStorage(root)):
            services.process_job(job_id,['tts'])
        generated=Path(db.MEDIA_ROOT)/(asset_id+'.wav')
        with db.connect('worker',home['id']) as conn:
            state=conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(asset_id,)).fetchone()
            job=conn.execute('SELECT status,secret_ciphertext FROM annha_private.job_queue WHERE id=%s',(job_id,)).fetchone()
            delete_job=conn.execute("SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s",('media-delete:'+asset_id,)).fetchone()
        self.assertEqual(state['status'],'deleting')
        self.assertEqual(job,{'status':'cancelled','secret_ciphertext':None})
        self.assertFalse(generated.exists())
        services.process_job(str(delete_job['id']),['delete_media'])
        with db.connect('worker',home['id']) as conn:
            self.assertEqual(conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(asset_id,)).fetchone()['status'],'deleted')
        self.assertFalse(generated.exists())

    def _phase3_tts_fixture(self):
        owner,_=self.account('phase3-worker@example.com');home,room,camera,_=self.home_camera(owner)
        response=owner.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':camera['id'],'name':'Phase 3 TTS','time':'08:00','text':'Nhắc uống nước','source':'tts'})
        self.assertEqual(response.status_code,201,response.text)
        asset=response.json()['asset_id']
        with db.connect('worker',home['id']) as conn:
            job=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('tts:'+asset,)).fetchone()['id']
        return home['id'],camera['id'],asset,job

    @staticmethod
    def _phase3_render(command,**kwargs):
        Path(command[command.index('-w')+1]).write_bytes(b'RIFF'+(36).to_bytes(4,'little')+b'WAVE'+b'\0'*40)

    def test_tts_worker_restart_reclaims_expired_lease_only(self):
        from unittest.mock import patch
        home,camera,asset,job=self._phase3_tts_fixture();old_lease=db.uid()
        with db.connect('worker') as conn:
            conn.execute("UPDATE annha_private.job_queue SET status='running',attempts=1,lease_owner=%s,lease_until=now()+interval '2 minutes' WHERE id=%s",(old_lease,job))
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=self._phase3_render) as render:
            services.process_job(job,['tts']);render.assert_not_called()
            with db.connect('worker') as conn:
                conn.execute("UPDATE annha_private.job_queue SET lease_until=now()-interval '1 second' WHERE id=%s",(job,))
            db.close_pools();db.open_pools()
            services.process_job(job,['tts']);self.assertEqual(render.call_count,1)
        with db.connect('worker',home) as conn:
            row=conn.execute('SELECT status,attempts,lease_owner,secret_ciphertext FROM annha_private.job_queue WHERE id=%s',(job,)).fetchone()
            media=conn.execute('SELECT status,size_bytes FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
            quota=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home,)).fetchone()
        self.assertEqual(row['status'],'done');self.assertEqual(row['attempts'],2)
        self.assertNotEqual(str(row['lease_owner']),old_lease);self.assertIsNone(row['secret_ciphertext'])
        self.assertEqual(media['status'],'ready');self.assertEqual(quota['used_bytes'],media['size_bytes']);self.assertEqual(quota['reserved_bytes'],0)

    def test_tts_provider_timeout_and_metadata_commit_rollback_retry_same_object(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        import psycopg
        home,camera,asset,job=self._phase3_tts_fixture();cloud=_Phase3Cloudinary();cloud.timeout_once=True
        real_connect=db.connect;failed_commit=False
        @contextmanager
        def commit_failure(role='app',home=None,user=None,camera=None):
            nonlocal failed_commit
            with real_connect(role,home,user,camera) as conn:
                yield conn
                if camera and not failed_commit:
                    row=conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
                    if row and row['status']=='ready':
                        failed_commit=True
                        raise psycopg.OperationalError('synthetic metadata transaction commit failure')
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=self._phase3_render), \
             patch('backend.src.pgservices.media_storage.preferred_provider',return_value=cloud), \
             patch('backend.src.pgservices.media_storage.CloudinaryStorage',return_value=cloud):
            services.process_job(job,['tts'])
            for expected in ['TimeoutError','OperationalError']:
                with db.connect('worker',home) as conn:
                    row=conn.execute('SELECT status,last_error_code FROM annha_private.job_queue WHERE id=%s',(job,)).fetchone()
                    media=conn.execute('SELECT status,reserved_bytes FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
                    storage=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home,)).fetchone()
                    self.assertEqual(row,{'status':'pending','last_error_code':expected})
                    self.assertEqual(media['status'],'uploading');self.assertGreater(media['reserved_bytes'],0)
                    self.assertEqual(storage['reserved_bytes'],media['reserved_bytes']);self.assertEqual(storage['used_bytes'],0)
                    conn.execute('UPDATE annha_private.job_queue SET available_at=now() WHERE id=%s',(job,))
                self.assertEqual(len(cloud.objects),1)
                if expected=='TimeoutError':
                    with patch('backend.src.pgservices.db.connect',side_effect=commit_failure): services.process_job(job,['tts'])
            self.assertTrue(failed_commit)
            services.process_job(job,['tts'])
            calls=cloud.calls;services.process_job(job,['tts']);self.assertEqual(cloud.calls,calls)
        with db.connect('worker',home) as conn:
            media=conn.execute('SELECT status,size_bytes FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()
            quota=conn.execute('SELECT used_bytes,reserved_bytes FROM annha.home_storage WHERE home_id=%s',(home,)).fetchone()
            row=conn.execute('SELECT status,attempts FROM annha_private.job_queue WHERE id=%s',(job,)).fetchone()
        self.assertEqual(media['status'],'ready');self.assertEqual(row,{'status':'done','attempts':3})
        self.assertEqual(quota,{'used_bytes':media['size_bytes'],'reserved_bytes':0});self.assertEqual(len(cloud.objects),1)

    def test_tts_ready_asset_survives_job_finalization_commit_failure(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        import psycopg
        home,camera,asset,job=self._phase3_tts_fixture();real_connect=db.connect;failed=False
        @contextmanager
        def fail_finalization(role='app',home=None,user=None,camera=None):
            nonlocal failed
            with real_connect(role,home,user,camera) as conn:
                yield conn
                if role=='worker' and home is None and not failed:
                    row=conn.execute('SELECT status FROM annha_private.job_queue WHERE id=%s',(job,)).fetchone()
                    if row and row['status']=='done':
                        failed=True
                        raise psycopg.OperationalError('synthetic finalization commit failure')
        with patch('backend.src.pgservices.shutil.which',return_value='espeak-ng'), \
             patch('backend.src.pgservices.subprocess.run',side_effect=self._phase3_render) as render:
            with patch('backend.src.pgservices.db.connect',side_effect=fail_finalization): services.process_job(job,['tts'])
            self.assertTrue(failed)
            with db.connect('worker',home) as conn:
                self.assertEqual(conn.execute('SELECT status FROM annha.media_assets WHERE id=%s',(asset,)).fetchone()['status'],'ready')
                conn.execute('UPDATE annha_private.job_queue SET available_at=now() WHERE id=%s',(job,))
            services.process_job(job,['tts']);self.assertEqual(render.call_count,1)
        with db.connect('worker',home) as conn:
            self.assertEqual(conn.execute('SELECT status FROM annha_private.job_queue WHERE id=%s',(job,)).fetchone()['status'],'done')
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha_private.job_queue WHERE idempotency_key=%s',('compile-tts:'+asset,)).fetchone()['n'],1)

    def test_active_alert_summary_obeys_camera_scope_and_revocation(self):
        owner,_=self.account('scope-owner@example.com');viewer,user=self.account('scope-viewer@example.com')
        home,room,first,_=self.home_camera(owner)
        second_provision=services.provision_device('Second camera')
        second=owner.post(f"/api/homes/{home['id']}/cameras/claim",json={'code':second_provision['pairing_code'],'name':'Second camera','room_id':room['id']}).json()
        from backend.src.models import EventInput
        for cam in [first,second]: services.ingest_event({'home_id':home['id'],'id':cam['id']},EventInput(event_id='scope-event',kind='fall',severity='critical',observed_at=db.now().isoformat()))
        response=owner.post(f"/api/homes/{home['id']}/invitations",json={'email':user['email'],'role':'viewer','scopes':[first['id']],'rights':{}})
        self.assertEqual(response.status_code,201,response.text)
        with db.connect('auth') as conn:
            message=services.decrypt(conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE payload->>'purpose'='invitation' ORDER BY created_at DESC LIMIT 1").fetchone()['secret_ciphertext'])['body']
        token=re.search(r'token=([\w-]+)',message)[1];self.assertEqual(viewer.post(f'/api/invitations/{token}/accept',json={}).status_code,200)
        summary=viewer.get(f"/api/homes/{home['id']}/active-events").json()
        self.assertEqual(summary['count'],1);self.assertEqual([item['camera_id'] for item in summary['items']],[first['id']]);self.assertIn('as_of',summary)
        with viewer.websocket_connect(f"/ws/alerts?home_id={home['id']}") as socket:
            changed=owner.patch(f"/api/homes/{home['id']}/members/{user['id']}",json={'role':'viewer','scopes':[],'rights':{}})
            self.assertEqual(changed.status_code,200,changed.text);self.assertEqual(socket.receive()['type'],'websocket.close')
        summary=viewer.get(f"/api/homes/{home['id']}/active-events").json()
        self.assertEqual(summary['count'],0);self.assertEqual(summary['items'],[])

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
        with db.connect('worker',home['id']) as conn:
            conn.execute("UPDATE annha.media_assets SET expires_at=now()-interval '1 minute' WHERE id=%s",(asset,))
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/snapshot").status_code,404)
        self.assertFalse(owner.get(f"/api/homes/{home['id']}/cameras").json()[0]['snapshot_available'])
        replacement=device.post('/api/device/evidence',content=body+b'-replacement',headers={'Content-Type':'image/png'})
        self.assertEqual(replacement.status_code,201,replacement.text)
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/snapshot").content,body+b'-replacement')
        event=device.post('/api/device/events',json={'event_id':'snapshot-regression-event','kind':'fall',
            'severity':'warning','observed_at':db.now().isoformat()})
        self.assertEqual(event.status_code,200,event.text)
        event_image=device.post(f"/api/device/evidence?event_id={event.json()['id']}",
            content=b'\x89PNG\r\n\x1a\nseparate-event-evidence',headers={'Content-Type':'image/png'})
        self.assertEqual(event_image.status_code,201,event_image.text)
        with db.connect('worker',home['id']) as conn:
            conn.execute("UPDATE annha.media_assets SET expires_at=now()-interval '1 minute' WHERE id=%s",(event_image.json()['id'],))
        event_after_expiry=owner.get(f"/api/events/{event.json()['id']}").json()
        self.assertEqual(event_after_expiry['id'],event.json()['id'])
        self.assertEqual(event_after_expiry['evidence'][0]['status'],'expired')
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/snapshot").content,body+b'-replacement')
        self.assertEqual(owner.delete(f"/api/assets/{replacement.json()['id']}").status_code,200)
        with db.connect('worker',home['id']) as conn:
            delete_job=conn.execute('SELECT id FROM annha_private.job_queue WHERE idempotency_key=%s',('media-delete:'+replacement.json()['id'],)).fetchone()
        services.process_job(str(delete_job['id']))
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/snapshot").status_code,404)
        self.assertFalse(owner.get(f"/api/homes/{home['id']}/cameras").json()[0]['snapshot_available'])
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

    def test_active_alert_summary_counts_beyond_feed_and_excludes_closed(self):
        owner,_=self.account('active-alerts@example.com');outsider,_=self.account('active-alerts-outside@example.com')
        home,room,camera,provision=self.home_camera(owner)
        with db.connect('worker',home['id'],camera=camera['id']) as conn:
            conn.execute('''INSERT INTO annha.events(home_id,camera_id,source_id,kind,severity,observation,first_observed_at,last_observed_at)
                SELECT %s,%s,'active-'||n,'fall','critical','abnormal',now()-n*interval '1 minute',now()-n*interval '1 minute'
                FROM generate_series(1,105) n''',(home['id'],camera['id']))
            conn.execute("UPDATE annha.events SET status='ACKNOWLEDGED' WHERE home_id=%s AND camera_id=%s AND source_id='active-105'",(home['id'],camera['id']))
            conn.execute("UPDATE annha.events SET status='RESOLVED' WHERE home_id=%s AND camera_id=%s AND source_id='active-104'",(home['id'],camera['id']))
            conn.execute("UPDATE annha.events SET status='FALSE_ALARM' WHERE home_id=%s AND camera_id=%s AND source_id='active-103'",(home['id'],camera['id']))
        response=owner.get(f"/api/homes/{home['id']}/active-events?page_size=20")
        self.assertEqual(response.status_code,200,response.text)
        summary=response.json()
        self.assertEqual(summary['count'],103)
        self.assertEqual(len(summary['items']),20)
        self.assertIn('camera_name',summary['items'][0])
        self.assertTrue(all(item['status'] in ('OPEN','ACKNOWLEDGED') for item in summary['items']))
        self.assertEqual(outsider.get(f"/api/homes/{home['id']}/active-events").status_code,404)

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

    def test_telegram_pairing_link_is_bound_single_use_and_expiring(self):
        from unittest.mock import patch
        owner,owner_user=self.account('telegram-pair-owner@example.com')
        home,_,_,_=self.home_camera(owner)
        with patch.dict(os.environ,{'TELEGRAM_UPDATE_MODE':'polling','TELEGRAM_BOT_USERNAME':'AnNhaSafetyAlertBot'}):
            bot_ref=services.telegram_bot_ref()
            with db.connect('worker') as conn:
                conn.execute('''INSERT INTO annha_private.telegram_polling_state(bot_ref,next_offset,last_poll_at)
                  VALUES(%s,0,now()) ON CONFLICT(bot_ref) DO UPDATE SET last_poll_at=now()''',(bot_ref,))
            pairing=owner.post(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}/telegram-pairing",json={})
            self.assertEqual(pairing.status_code,201,pairing.text)
            token=parse_qs(urlsplit(pairing.json()['url']).query)['start'][0]
            with db.connect('worker',home['id']) as conn:
                bound=conn.execute('SELECT recipient_user_id FROM annha_private.telegram_pairings WHERE id=%s',(pairing.json()['pairing_id'],)).fetchone()
            self.assertEqual(str(bound['recipient_user_id']),owner_user['id'])
            update={'update_id':9001,'message':{'text':'/start '+token,'chat':{'id':123456789,'type':'private'},'from':{'id':123456789}}}
            from backend.src import telegram_poller
            poll_calls=[]
            def telegram_api(method,payload=None,timeout=5):
                poll_calls.append((method,payload))
                if method=='getWebhookInfo': return {'url':''}
                return [update] if payload['offset']==0 else []
            with patch('backend.src.telegram_poller.services.telegram_poll_api',side_effect=telegram_api):
                self.assertEqual(telegram_poller.poll_once(),'polled')
                self.assertEqual(telegram_poller.poll_once(),'polled')
            self.assertEqual([payload['offset'] for method,payload in poll_calls if method=='getUpdates'],[0,9002])
            self.assertEqual(services.process_telegram_pairing_update(update),'duplicate')
            status=owner.get(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}/telegram-pairing/{pairing.json()['pairing_id']}")
            self.assertEqual(status.status_code,200,status.text)
            self.assertEqual(status.json()['status'],'connected')
            self.assertNotIn('123456789',status.text)
            reused={**update,'update_id':9002}
            self.assertEqual(services.process_telegram_pairing_update(reused),'duplicate')

            expired=owner.post(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}/telegram-pairing",json={})
            self.assertEqual(expired.status_code,201,expired.text)
            expired_token=parse_qs(urlsplit(expired.json()['url']).query)['start'][0]
            with db.connect('worker',home['id']) as conn:
                conn.execute('''UPDATE annha_private.telegram_pairings SET created_at=now()-interval '20 minutes',
                  expires_at=now()-interval '10 minutes' WHERE id=%s''',(expired.json()['pairing_id'],))
            expired_update={'update_id':9003,'message':{'text':'/start '+expired_token,'chat':{'id':123456789,'type':'private'},'from':{'id':123456789}}}
            self.assertEqual(services.process_telegram_pairing_update(expired_update),'expired')
            self.assertEqual(services.process_telegram_pairing_update(expired_update),'expired')

    def test_telegram_long_poll_allows_runtime_pairing_and_excludes_second_consumer(self):
        from contextlib import contextmanager
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from backend.src import telegram_poller
        import time

        owner,owner_user=self.account('telegram-runtime-owner@example.com')
        home,_,_,_=self.home_camera(owner)
        original_connect=db.connect
        role_evidence=[]

        @contextmanager
        def runtime_connect(role='app',home=None,user=None,camera=None):
            with original_connect(role,home,user,camera) as conn:
                identity=conn.execute('''SELECT session_user,current_user,r.rolsuper,r.rolbypassrls,
                  pg_has_role(session_user,c.relowner,'MEMBER') AS member_of_table_owner
                  FROM pg_roles r CROSS JOIN pg_class c
                  WHERE r.rolname=session_user AND c.oid='annha_private.telegram_pairings'::regclass''').fetchone()
                self.assertEqual(identity['session_user'],urlsplit(os.environ['DATABASE_URL_'+role.upper()]).username)
                self.assertEqual(identity['current_user'],db.ROLES[role])
                self.assertFalse(identity['rolsuper'])
                self.assertFalse(identity['rolbypassrls'])
                self.assertFalse(identity['member_of_table_owner'])
                role_evidence.append(role)
                yield conn

        entered=Event();release=Event()
        def telegram_api(method,payload=None,timeout=5):
            if method=='getWebhookInfo': return {'url':''}
            entered.set()
            if not release.wait(40): raise RuntimeError('test long poll was not released')
            return []

        with patch.dict(os.environ,{'TELEGRAM_UPDATE_MODE':'polling','DATABASE_STATEMENT_TIMEOUT_MS':'100'}), \
             patch('backend.src.pgdb.connect',side_effect=runtime_connect), \
             patch('backend.src.telegram_poller.services.telegram_poll_api',side_effect=telegram_api):
            for role in db.ROLES:
                with db.connect(role) as conn:
                    acl=conn.execute('''SELECT
                      has_table_privilege(current_user,'annha_private.telegram_pairings','SELECT') AS pairings,
                      has_table_privilege(current_user,'annha_private.telegram_polling_state','SELECT') AS state''').fetchone()
                    self.assertEqual(acl['pairings'],role=='worker')
                    self.assertEqual(acl['state'],role=='worker')
            bot_ref=services.telegram_bot_ref()
            with db.connect('worker') as conn:
                conn.execute('''INSERT INTO annha_private.telegram_polling_state(bot_ref,next_offset,last_poll_at)
                  VALUES(%s,0,now()) ON CONFLICT(bot_ref) DO UPDATE SET last_poll_at=now()''',(bot_ref,))
            with ThreadPoolExecutor(max_workers=1) as executor:
                task=executor.submit(telegram_poller.poll_once)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(telegram_poller.poll_once(),'consumer_active')
                    # This API call must complete while getUpdates is still waiting.
                    pairing=owner.post(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}/telegram-pairing",json={})
                    self.assertEqual(pairing.status_code,201,pairing.text)
                    self.assertFalse(task.done())
                    time.sleep(30)
                finally:
                    release.set()
                self.assertEqual(task.result(timeout=5),'polled')
            status=owner.get(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}/telegram-pairing/{pairing.json()['pairing_id']}")
            self.assertEqual(status.status_code,200,status.text)
            self.assertEqual(status.json()['status'],'pending')
        self.assertIn('worker',role_evidence)
        self.assertIn('auth',role_evidence)
        self.assertIn('app',role_evidence)

    def test_phase4_notification_filters_camera_revoke_and_unverified_email(self):
        from unittest.mock import patch
        owner,owner_user=self.account('phase4-owner@example.com')
        caregiver,caregiver_user=self.account('phase4-caregiver@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        second_provision=services.provision_device('Second Phase 4 camera')
        response=owner.post(f"/api/homes/{home['id']}/cameras/claim",json={
            'code':second_provision['pairing_code'],'name':'Camera two','room_id':room['id']})
        self.assertEqual(response.status_code,201,response.text);second_camera=response.json()
        outside,_=self.account('phase4-outside@example.com')
        other_home,_,other_camera,other_provision=self.home_camera(outside)
        invitation=owner.post(f"/api/homes/{home['id']}/invitations",json={
            'email':caregiver_user['email'],'role':'caregiver','scopes':[camera['id']],
            'rights':{},'camera_permissions':{camera['id']:{'audio':False,'schedules':False}}})
        self.assertEqual(invitation.status_code,201,invitation.text)
        with db.connect('auth') as conn:
            body=services.decrypt(conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'='invitation' ORDER BY created_at DESC LIMIT 1").fetchone()['secret_ciphertext'])['body']
        token=re.search(r'token=([\w-]+)',body)[1]
        self.assertEqual(caregiver.post('/api/invitations/'+token+'/accept',json={}).status_code,200)

        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'phase4-mock-token','EMAIL_ALERTS_ENABLED':'true','SMTP_HOST':'smtp.fixture.invalid'}):
            settings_url=f"/api/homes/{home['id']}/notification-recipients/"
            owner_chat='-100'+str(int(self.suffix,16))
            caregiver_chat='-100'+str(int(self.suffix,16)+1)
            owner_payload={
              'telegram':{'enabled':True,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':False,'camera_ids':[camera['id']],'chat_id':owner_chat,'allow_media':False},
              'email':{'enabled':True,'event_kinds':['device'],'minimum_severity':'critical','camera_scope_all':True,'camera_ids':[]},
            }
            saved=owner.put(settings_url+owner_user['id'],json=owner_payload)
            self.assertEqual(saved.status_code,200,saved.text)
            caregiver_payload={
              'telegram':{'enabled':True,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':False,'camera_ids':[camera['id']],'chat_id':caregiver_chat,'allow_media':False},
              'email':{'enabled':False,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[]},
            }
            saved=owner.put(settings_url+caregiver_user['id'],json=caregiver_payload)
            self.assertEqual(saved.status_code,200,saved.text)
            public=owner.get(f"/api/homes/{home['id']}/notification-settings")
            self.assertEqual(public.status_code,200,public.text)
            self.assertEqual(public.json()['reminder_interval_minutes'],15);self.assertEqual(public.json()['max_reminders'],3)
            self.assertNotIn('-100123456789',public.text)
            policy=owner.put(f"/api/homes/{home['id']}/notification-policy",json={'reminder_interval_minutes':15,'max_reminders':3})
            self.assertEqual(policy.status_code,200,policy.text)
            self.assertEqual(policy.json()['persistent_environment_after_ack'],'stop_until_new_episode')
            legacy=owner.get(f"/api/homes/{home['id']}/settings").json()
            self.assertEqual(legacy['telegram_chat_id'],'')
            with patch('backend.src.pgapi.svc.send_telegram_text',return_value='mock-test-message') as test_send:
                connection_test=owner.post(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}/telegram-test",json={})
            self.assertEqual(connection_test.status_code,200,connection_test.text)
            self.assertEqual(connection_test.json()['status'],'accepted')
            self.assertIn('chưa xác nhận người nhận đã đọc',connection_test.json()['message'])
            test_send.assert_called_once()

            invalid={**caregiver_payload,'telegram':{**caregiver_payload['telegram'],'camera_ids':[other_camera['id']]}}
            self.assertEqual(owner.put(settings_url+caregiver_user['id'],json=invalid).status_code,422)

            with db.connect('auth') as conn:
                conn.execute('UPDATE annha_private.users SET email_verified_at=NULL WHERE id=%s',(caregiver_user['id'],))
            unverified={**caregiver_payload,'email':{**caregiver_payload['email'],'enabled':True}}
            self.assertEqual(owner.put(settings_url+caregiver_user['id'],json=unverified).status_code,409)

            fall=device.post('/api/device/events',json={'event_id':'phase4-camera-filter-fall','kind':'fall','severity':'warning',
                'observation':'abnormal','observed_at':db.now().isoformat()})
            self.assertEqual(fall.status_code,200,fall.text)
            with db.connect('worker',home['id']) as conn:
                rows=conn.execute('''SELECT nc.recipient_user_id::text AS recipient_user_id,nc.kind,d.dispatch_kind FROM annha.notification_deliveries d
                  JOIN annha.notification_channels nc ON nc.id=d.channel_id AND nc.home_id=d.home_id
                  JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id WHERE e.id=%s ORDER BY nc.recipient_user_id''',(fall.json()['id'],)).fetchall()
            self.assertEqual({(row['recipient_user_id'],row['kind'],row['dispatch_kind']) for row in rows},
                {(owner_user['id'],'telegram','initial'),(caregiver_user['id'],'telegram','initial')})
            with db.connect('worker',home['id']) as conn:
                queued=conn.execute('''SELECT d.id,d.channel_id,c.recipient_user_id::text AS recipient_user_id FROM annha.notification_deliveries d
                    JOIN annha.notification_channels c ON c.id=d.channel_id WHERE d.event_id=%s''',(fall.json()['id'],)).fetchall()
                delivery_id=next(row['id'] for row in queued if row['recipient_user_id']==caregiver_user['id'])
                self.assertTrue(conn.execute('SELECT annha_private.can_dispatch_notification(%s) AS ok',(delivery_id,)).fetchone()['ok'])
            # Telegram message IDs are scoped to a destination chat; provider rows must keep that scope.
            per_chat_message={}
            def accepted_message(chat_id,message):
                per_chat_message[chat_id]=per_chat_message.get(chat_id,0)+1
                return str(per_chat_message[chat_id])
            with patch('backend.src.pgservices.send_telegram_text',side_effect=accepted_message):
                services.process_notifications()
                services.process_notifications()
            with db.connect('worker',home['id']) as conn:
                attempts=conn.execute('''SELECT a.provider_account_ref FROM annha.delivery_attempts a
                  WHERE a.delivery_id=ANY(%s) AND a.provider='telegram' ''',([row['id'] for row in queued],)).fetchall()
            self.assertEqual(len(attempts),2)
            self.assertEqual(len({row['provider_account_ref'] for row in attempts}),2)
            pending_event=device.post('/api/device/events',json={'event_id':'phase4-revocation-pending','kind':'fall','severity':'warning',
                'observation':'abnormal','observed_at':db.now().isoformat()})
            self.assertEqual(pending_event.status_code,200,pending_event.text)
            with db.connect('worker',home['id']) as conn:
                delivery_id=conn.execute('''SELECT d.id FROM annha.notification_deliveries d JOIN annha.notification_channels c ON c.id=d.channel_id
                    WHERE d.event_id=%s AND c.recipient_user_id=%s''',(pending_event.json()['id'],caregiver_user['id'])).fetchone()['id']
            revoked=owner.delete(f"/api/homes/{home['id']}/members/{caregiver_user['id']}")
            self.assertEqual(revoked.status_code,200,revoked.text)
            with patch('backend.src.pgservices.send_telegram_text',side_effect=accepted_message):
                services.process_notifications()
                services.process_notifications()
            with db.connect('worker',home['id']) as conn:
                self.assertEqual(conn.execute('SELECT status FROM annha.notification_deliveries WHERE id=%s',(delivery_id,)).fetchone()['status'],'cancelled')
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.delivery_attempts WHERE delivery_id=%s',(delivery_id,)).fetchone()['n'],0)

            device_two=self.device(second_provision)
            excluded=device_two.post('/api/device/events',json={'event_id':'phase4-camera-filter-excluded','kind':'fall','severity':'warning','observed_at':db.now().isoformat()})
            self.assertEqual(excluded.status_code,200,excluded.text)
            allowed_email=device_two.post('/api/device/events',json={'event_id':'phase4-email-independent','kind':'device','severity':'critical','observed_at':db.now().isoformat()})
            self.assertEqual(allowed_email.status_code,200,allowed_email.text)
            with db.connect('worker',home['id']) as conn:
                excluded_count=conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(excluded.json()['id'],)).fetchone()['n']
                email_rows=conn.execute('''SELECT nc.kind,nc.recipient_user_id::text AS recipient_user_id FROM annha.notification_deliveries d
                  JOIN annha.notification_channels nc ON nc.id=d.channel_id WHERE d.event_id=%s''',(allowed_email.json()['id'],)).fetchall()
            low_severity=device_two.post('/api/device/events',json={'event_id':'phase4-email-severity-filtered','kind':'device','severity':'warning','observed_at':db.now().isoformat()})
            self.assertEqual(low_severity.status_code,200,low_severity.text)
            with db.connect('worker',home['id']) as conn:
                low_severity_count=conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(low_severity.json()['id'],)).fetchone()['n']
            self.assertEqual(excluded_count,0)
            self.assertEqual([(row['kind'],row['recipient_user_id']) for row in email_rows],[('email',owner_user['id'])])
            self.assertEqual(low_severity_count,0)

            other_device=self.device(other_provision)
            cross_home=other_device.post('/api/device/events',json={'event_id':'phase4-other-home','kind':'fall','severity':'warning','observed_at':db.now().isoformat()})
            self.assertEqual(cross_home.status_code,200,cross_home.text)
            with db.connect('worker',other_home['id']) as conn:
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(cross_home.json()['id'],)).fetchone()['n'],0)

    def test_phase4_reminders_stop_on_ack_and_new_episode_restarts(self):
        from unittest.mock import patch
        owner,owner_user=self.account('phase4-reminders@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'phase4-mock-token'}):
            payload={'telegram':{'enabled':True,'event_kinds':['environment'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[],'chat_id':'-1005551234'},
              'email':{'enabled':False,'event_kinds':['environment'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[]}}
            saved=owner.put(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}",json=payload)
            self.assertEqual(saved.status_code,200,saved.text)
            event=device.post('/api/device/events',json={'event_id':'phase4-environment-episode-one','kind':'environment','severity':'warning',
                'observation':'abnormal','observed_at':db.now().isoformat()})
            self.assertEqual(event.status_code,200,event.text);event_id=event.json()['id']
            with db.connect('worker',home['id']) as conn:
                initial=conn.execute("SELECT id FROM annha.notification_deliveries WHERE event_id=%s AND dispatch_kind='initial'",(event_id,)).fetchone()
                self.assertIsNotNone(initial)
                conn.execute("UPDATE annha.notification_deliveries SET status='accepted',accepted_at=now()-interval '16 minutes',last_dispatch_at=now()-interval '16 minutes' WHERE id=%s",(initial['id'],))
            services.schedule_notification_reminders(home['id'])
            services.schedule_notification_reminders(home['id'])
            with db.connect('worker',home['id']) as conn:
                reminder=conn.execute("SELECT id,reminder_number FROM annha.notification_deliveries WHERE event_id=%s AND dispatch_kind='reminder'",(event_id,)).fetchone()
                self.assertIsNotNone(reminder);self.assertEqual(reminder['reminder_number'],1)
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(event_id,)).fetchone()['n'],2)
                conn.execute("UPDATE annha.notification_deliveries SET status='accepted',accepted_at=now()-interval '30 minutes',last_dispatch_at=now()-interval '2 minutes' WHERE id=%s",(reminder['id'],))
            services.schedule_notification_reminders(home['id'])
            services.schedule_notification_reminders(home['id'])
            with db.connect('worker',home['id']) as conn:
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(event_id,)).fetchone()['n'],2)

            acknowledged=owner.post(f"/api/events/{event_id}/actions",json={'action':'acknowledge','note':'Đã kiểm tra'})
            self.assertEqual(acknowledged.status_code,200,acknowledged.text)
            with db.connect('worker',home['id']) as conn:
                conn.execute("UPDATE annha.notification_deliveries SET status='accepted',accepted_at=now()-interval '16 minutes' WHERE id=%s",(reminder['id'],))
            services.schedule_notification_reminders(home['id'])
            with db.connect('worker',home['id']) as conn:
                self.assertFalse(conn.execute('SELECT annha_private.can_schedule_notification_reminder(%s) AS ok',(reminder['id'],)).fetchone()['ok'])
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(event_id,)).fetchone()['n'],2)

            same_episode=device.post('/api/device/events',json={'event_id':'phase4-environment-episode-one','sequence':2,'kind':'environment','severity':'warning',
                'observation':'abnormal','observed_at':db.now().isoformat()})
            self.assertEqual(same_episode.status_code,200,same_episode.text)
            recovered=device.post('/api/device/events',json={'event_id':'phase4-environment-episode-one','sequence':3,'kind':'environment','severity':'warning',
                'observation':'recovered','observed_at':db.now().isoformat()})
            self.assertEqual(recovered.status_code,200,recovered.text)
            new_episode=device.post('/api/device/events',json={'event_id':'phase4-environment-episode-two','kind':'environment','severity':'warning',
                'observation':'abnormal','observed_at':db.now().isoformat()})
            self.assertEqual(new_episode.status_code,200,new_episode.text)
            with db.connect('worker',home['id']) as conn:
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s',(same_episode.json()['id'],)).fetchone()['n'],2)
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM annha.notification_deliveries WHERE event_id=%s AND dispatch_kind='initial'",(new_episode.json()['id'],)).fetchone()['n'],1)

    def test_phase4_private_image_consent_expiry_and_text_fallback(self):
        from unittest.mock import patch
        owner,owner_user=self.account('phase4-images@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        png=b'\x89PNG\r\n\x1a\nphase4-private-image'
        chat_id='-100'+str(int(self.suffix,16))
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'phase4-mock-token','MEDIA_STORAGE_PROVIDER':'local'}):
            payload={'telegram':{'enabled':True,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[],'chat_id':chat_id,'allow_media':False},
              'email':{'enabled':False,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[]}}
            saved=owner.put(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}",json=payload)
            self.assertEqual(saved.status_code,200,saved.text)

            def create_event(source):
                result=device.post('/api/device/events',json={'event_id':source,'kind':'fall','severity':'warning','observation':'abnormal','observed_at':db.now().isoformat()})
                self.assertEqual(result.status_code,200,result.text)
                return result.json()['id']
            consent_off=create_event('phase4-media-consent-off')
            response=device.post(f'/api/device/evidence?event_id={consent_off}',content=png,headers={'Content-Type':'image/png'})
            self.assertEqual(response.status_code,201,response.text)
            photo_calls=[];text_calls=[];reject_photo_ids=set()
            def photo(chat_id,caption,mime,data):
                photo_calls.append(caption)
                match=re.search(r'#/event/([0-9a-f-]+)',caption)
                if match and match.group(1) in reject_photo_ids: raise services.TelegramDeliveryError('TelegramPhotoRejected')
                return f'mock-photo-{self.suffix}-{len(photo_calls)}'
            def text(chat_id,message):
                text_calls.append(message)
                return f'mock-text-{self.suffix}-{len(text_calls)}'
            with patch('backend.src.pgservices.send_telegram_photo',side_effect=photo), \
                 patch('backend.src.pgservices.send_telegram_text',side_effect=text):
                services.process_notifications()
                with db.connect('worker',home['id']) as conn:
                    consent_result=conn.execute('SELECT status,media_result FROM annha.notification_deliveries WHERE event_id=%s',(consent_off,)).fetchone()
                self.assertEqual((consent_result['status'],consent_result['media_result']),('accepted','consent_disabled'))

                enabled={**payload,'telegram':{**payload['telegram'],'allow_media':True}}
                saved=owner.put(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}",json=enabled)
                self.assertEqual(saved.status_code,200,saved.text)
                expired=create_event('phase4-media-expired')
                rejected=create_event('phase4-media-provider-reject')
                attached=create_event('phase4-media-provider-accept')
                reject_photo_ids.add(str(rejected))
                for event_id in (expired,rejected,attached):
                    response=device.post(f'/api/device/evidence?event_id={event_id}',content=png,headers={'Content-Type':'image/png'})
                    self.assertEqual(response.status_code,201,response.text)
                with db.connect('worker',home['id']) as conn:
                    conn.execute("UPDATE annha.media_assets SET expires_at=now()-interval '1 second' WHERE event_id=%s",(expired,))
                for _ in range(3): services.process_notifications()
                with db.connect('worker',home['id']) as conn:
                    rows=conn.execute('''SELECT d.event_id,d.status,d.media_result FROM annha.notification_deliveries d
                      JOIN annha.notification_channels c ON c.id=d.channel_id WHERE d.home_id=%s AND c.recipient_user_id=%s''',
                      (home['id'],owner_user['id'])).fetchall()
                    refs=conn.execute('''SELECT DISTINCT a.provider_account_ref FROM annha.delivery_attempts a
                      JOIN annha.notification_deliveries d ON d.id=a.delivery_id WHERE d.home_id=%s''',(home['id'],)).fetchall()
            media={str(row['event_id']):(row['status'],row['media_result']) for row in rows}
            self.assertEqual(media[consent_off],('accepted','consent_disabled'))
            self.assertEqual(media[expired],('accepted','missing'))
            self.assertEqual({media[rejected],media[attached]}, {('accepted','text_fallback'),('accepted','sent')})
            event_ids={str(value) for value in (consent_off,expired,rejected,attached)}
            text_event_ids={match.group(1) for value in text_calls if (match:=re.search(r'#/event/([0-9a-f-]+)',value))}
            photo_event_ids={match.group(1) for value in photo_calls if (match:=re.search(r'#/event/([0-9a-f-]+)',value))}
            self.assertEqual(text_event_ids & event_ids,{consent_off,expired,rejected})
            self.assertEqual(photo_event_ids & event_ids,{rejected,attached})
            self.assertEqual({row['provider_account_ref'] for row in refs},{services.telegram_destination_ref(chat_id)})

    def test_phase5_verification_resend_reset_expiry_and_session_revocation(self):
        from backend.src.pgsecurity import digest,reset_code_digest

        def new_client(label):
            client=TestClient(main.app,client=(label+'-'+self.suffix,50000));self.clients.append(client);return client

        def latest_email(purpose):
            with db.connect('auth') as conn:
                row=conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'=%s ORDER BY created_at DESC,id DESC LIMIT 1",(purpose,)).fetchone()
            self.assertIsNotNone(row)
            return services.decrypt(row['secret_ciphertext'])

        primary=new_client('phase5-auth')
        email='phase5-auth-'+self.suffix+'@example.test'
        self.assertEqual(primary.post('/api/auth/register',json={'email':email,'name':'An <Nha>','password':'correct password 123'}).status_code,201)
        first_verify=latest_email('verify_email')
        self.assertIn('&lt;Nha&gt;',first_verify['html_body'])
        self.assertIn('font-size:32px',first_verify['html_body'])
        first_code=re.search(r'Mã xác minh: (\d{8})',first_verify['body'])[1]
        wrong_code=f'{(int(first_code)+1)%100_000_000:08d}'
        self.assertEqual(primary.post('/api/auth/verify',json={'code':wrong_code}).status_code,400)
        self.assertEqual(primary.post('/api/auth/verify',json={'code':first_code}).status_code,200)
        self.assertEqual(primary.post('/api/auth/verify',json={'code':first_code}).status_code,400)

        resend_client=new_client('phase5-resend')
        resend_email='phase5-resend-'+self.suffix+'@example.test'
        self.assertEqual(resend_client.post('/api/auth/register',json={'email':resend_email,'name':'Người nhận','password':'correct password 123'}).status_code,201)
        old_verify=re.search(r'Mã xác minh: (\d{8})',latest_email('verify_email')['body'])[1]
        resend=resend_client.post('/api/auth/resend',json={'email':resend_email})
        self.assertEqual(resend.status_code,200,resend.text)
        new_verify=re.search(r'Mã xác minh: (\d{8})',latest_email('verify_email')['body'])[1]
        self.assertNotEqual(old_verify,new_verify)
        self.assertEqual(resend_client.post('/api/auth/verify',json={'code':old_verify}).status_code,400)
        self.assertEqual(resend_client.post('/api/auth/verify',json={'code':new_verify}).status_code,200)

        login=primary.post('/api/auth/login',json={'email':email,'password':'correct password 123'})
        self.assertEqual(login.status_code,200,login.text)
        primary.headers['X-CSRF-Token']=login.json()['csrf']
        unknown=primary.post('/api/auth/forgot',json={'email':'unknown-'+self.suffix+'@example.test'})
        known=primary.post('/api/auth/forgot',json={'email':email})
        self.assertEqual((unknown.status_code,unknown.json()['message']),(known.status_code,known.json()['message']))
        reset_mail=latest_email('reset_password')
        reset_token=re.search(r'Mã đặt lại mật khẩu: (\d{8})',reset_mail['body'])[1]
        self.assertIn('15 phút',reset_mail['html_body'])
        self.assertNotIn('href=',reset_mail['html_body'])
        with db.connect('auth') as conn:
            conn.execute('''UPDATE annha_private.email_tokens
              SET created_at=now()-interval '2 seconds',expires_at=now()-interval '1 second'
              WHERE token_hash=%s''',(reset_code_digest(email,reset_token),))
        self.assertEqual(primary.post('/api/auth/reset',json={'email':email,'code':reset_token,'password':'new secure password 456'}).status_code,400)

        self.assertEqual(primary.post('/api/auth/forgot',json={'email':email}).status_code,200)
        fresh_reset=re.search(r'Mã đặt lại mật khẩu: (\d{8})',latest_email('reset_password')['body'])[1]
        self.assertEqual(primary.post('/api/auth/reset',json={'email':email,'code':fresh_reset,'password':'new secure password 456'}).status_code,200)
        self.assertEqual(primary.get('/api/auth/me').status_code,401)
        self.assertEqual(primary.post('/api/auth/reset',json={'email':email,'code':fresh_reset,'password':'another secure password 789'}).status_code,400)
        self.assertEqual(primary.post('/api/auth/login',json={'email':email,'password':'correct password 123'}).status_code,401)
        self.assertEqual(primary.post('/api/auth/login',json={'email':email,'password':'new secure password 456'}).status_code,200)

    def test_phase5_safety_email_uses_policy_and_records_accepted_not_delivered(self):
        from unittest.mock import patch
        owner,owner_user=self.account('phase5-alert@example.com')
        home,room,camera,provision=self.home_camera(owner);device=self.device(provision)
        config={'telegram':{'enabled':False,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[]},
                'email':{'enabled':True,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[]}}
        with patch.dict(os.environ,{'EMAIL_ALERTS_ENABLED':'true'}):
            saved=owner.put(f"/api/homes/{home['id']}/notification-recipients/{owner_user['id']}",json=config)
            self.assertEqual(saved.status_code,200,saved.text)
            event=device.post('/api/device/events',json={'event_id':'phase5-email-worker','kind':'fall','severity':'critical',
                'observation':'abnormal','observed_at':db.now().isoformat(),'reason':'Cần kiểm tra tư thế'})
            self.assertEqual(event.status_code,200,event.text)
            with db.connect('worker',home['id']) as conn:
                delivery=conn.execute('''SELECT d.id FROM annha.notification_deliveries d JOIN annha.notification_channels c
                  ON c.id=d.channel_id WHERE d.event_id=%s AND c.kind='email' AND c.recipient_user_id=%s''',
                  (event.json()['id'],owner_user['id'])).fetchone()
                self.assertIsNotNone(delivery)
                conn.execute('UPDATE annha.notification_deliveries SET next_attempt_at=now()-interval \'1 hour\' WHERE id=%s',(delivery['id'],))
            with patch('backend.src.pgservices.send_mail') as send_mail, \
                 patch('backend.src.pgservices.send_telegram_text',return_value='mock-telegram-id'), \
                 patch('backend.src.pgservices.send_telegram_photo',return_value='mock-telegram-photo-id'), \
                 patch('backend.src.pgservices._read_notification_image',return_value=(None,'unavailable')):
                services.process_notifications()
            matching=[call for call in send_mail.call_args_list if call.args[0]==owner_user['email']]
            self.assertEqual(len(matching),1)
            self.assertIn('AnNhà',matching[0].args[1])
            self.assertIn('Nhà test '+self.suffix,matching[0].args[2])
            self.assertIn('Nghi ngờ té ngã',matching[0].args[2])
            self.assertIn('không đính kèm ảnh hoặc video',matching[0].args[2])
            self.assertIn('Nhà test '+self.suffix,matching[0].args[3])
            with db.connect('worker',home['id']) as conn:
                row=conn.execute('SELECT status,media_result FROM annha.notification_deliveries WHERE id=%s',(delivery['id'],)).fetchone()
                attempt=conn.execute('SELECT status,provider FROM annha.delivery_attempts WHERE delivery_id=%s ORDER BY attempt DESC LIMIT 1',(delivery['id'],)).fetchone()
            self.assertEqual((row['status'],row['media_result']),('accepted','not_requested'))
            self.assertEqual((attempt['status'],attempt['provider']),('accepted','smtp'))
            history=owner.get(f"/api/homes/{home['id']}/delivery-status")
            self.assertEqual(history.status_code,200,history.text)
            public=next(item for item in history.json() if item['id']==str(delivery['id']))
            self.assertEqual(public['status'],'accepted')
            self.assertNotEqual(public['status'],'delivered')
            self.assertEqual(public['recipient_user_id'],owner_user['id'])
            self.assertEqual(public['recipient_name'],owner_user['name'])
            filtered=owner.get(f"/api/homes/{home['id']}/delivery-status?recipient_id={owner_user['id']}")
            self.assertEqual(filtered.status_code,200,filtered.text)
            self.assertEqual([item['id'] for item in filtered.json()],[str(delivery['id'])])
            empty=owner.get(f"/api/homes/{home['id']}/delivery-status?recipient_id=00000000-0000-0000-0000-000000000000")
            self.assertEqual(empty.status_code,200,empty.text);self.assertEqual(empty.json(),[])
            outsider,_=self.account('phase5-outsider@example.com')
            self.assertEqual(outsider.get(f"/api/homes/{home['id']}/delivery-status").status_code,404)

    def test_invitation_codes_single_use_permissions_and_concurrent_join(self):
        from .invitation_code_cases import exercise
        exercise(self,postgres=True)

    def test_fasttrack_password_reset_otp(self):
        from .fasttrack_cases import reset_otp_case
        reset_otp_case(self,postgres=True)

    def test_fasttrack_safety_email_retry_and_single_target(self):
        from .fasttrack_cases import safety_retry_case
        safety_retry_case(self)
