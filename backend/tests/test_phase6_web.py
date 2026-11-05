"""Phase 6 only: restricted-role PostgreSQL fixtures, no live provider calls."""
from datetime import timedelta
import json
from pathlib import Path
import os,unittest
from urllib.parse import urlsplit
from dotenv import dotenv_values
from backend.tests import test_postgres as fixtures
from backend.src import pgdb as db,models as m,pgservices as svc

@unittest.skipUnless(os.getenv('ANNHA_TEST_ENV'),'Requires isolated local PostgreSQL runtime env')
class Phase6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        values=dotenv_values(os.environ['ANNHA_TEST_ENV'])
        if any(urlsplit(values.get('DATABASE_URL_'+role,'')).hostname not in ('localhost','127.0.0.1') for role in ('APP','AUTH','DEVICE','WORKER')):
            raise RuntimeError('Phase 6 fixtures require local isolated PostgreSQL; no cloud writes allowed.')
        fixtures.PostgresTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):fixtures.PostgresTests.tearDownClass.__func__(cls)
    setUp=fixtures.PostgresTests.setUp
    tearDown=fixtures.PostgresTests.tearDown
    account=fixtures.PostgresTests.account
    home_camera=fixtures.PostgresTests.home_camera
    device=fixtures.PostgresTests.device
    def test_range_aggregation_and_paged_raw(self):
        owner,_=self.account('phase6-sensor@example.com');home,room,camera,_=self.home_camera(owner)
        start=db.now()-timedelta(days=2);end=start+timedelta(hours=24)
        with db.connect('worker',home['id']) as conn:
            for i in range(605):
                batch=db.uid();stamp=start+timedelta(minutes=i)
                conn.execute('INSERT INTO annha.telemetry_batches(id,home_id,camera_id,message_id,observed_at) VALUES(%s,%s,%s,%s,%s)',(batch,home['id'],camera['id'],'phase6-'+str(i),stamp))
                conn.execute("INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality) VALUES(%s,%s,%s,'temperature',%s,'C','valid'),(%s,%s,%s,'gas',%s,%s,%s)",(home['id'],camera['id'],batch,10 if i==0 else 30,home['id'],camera['id'],batch,i,'ADC' if i%2 else 'ppm','error' if i==20 else 'valid'))
        params={'start':start.isoformat(),'end':end.isoformat(),'buckets':24}
        response=owner.get(f"/api/cameras/{camera['id']}/telemetry-summary",params=params);self.assertEqual(response.status_code,200,response.text);summary=response.json()
        self.assertEqual(summary['sample_count'],605);self.assertEqual(summary['empty_buckets'],13)
        points=summary['series']['temperature']['C'];self.assertEqual(sum(p['count'] for p in points),605)
        self.assertAlmostEqual(points[0]['y'],(10+59*30)/60);self.assertEqual(points[0]['min'],10)
        self.assertEqual(summary['metric_units']['gas'],['ADC','ppm'])
        self.assertEqual(sum(p['count'] for unit in summary['series']['gas'].values() for p in unit),604)
        first=owner.get(f"/api/cameras/{camera['id']}/telemetry",params={**params,'page':1,'page_size':10}).json()
        last=owner.get(f"/api/cameras/{camera['id']}/telemetry",params={**params,'page':61,'page_size':10}).json()
        self.assertEqual(first['total'],605);self.assertEqual(len(last['items']),5);self.assertNotEqual(first['items'][0]['id'],last['items'][0]['id'])
        self.assertEqual(owner.get(f"/api/cameras/{camera['id']}/telemetry-summary",params={**params,'end':start.isoformat()}).status_code,422)
        outsider,_=self.account('phase6-outside@example.com')
        self.assertIn(outsider.get(f"/api/cameras/{camera['id']}/telemetry-summary",params=params).status_code,[403,404])

    def test_event_filters_timeline_and_evidence_states(self):
        owner,_=self.account('phase6-events@example.com');home,room,camera,_=self.home_camera(owner)
        stamp=db.now()-timedelta(hours=1)
        for i in range(1,14):
            event=svc.ingest_event({'id':camera['id'],'home_id':home['id']},m.EventInput(event_id='phase6-timeline',sequence=i,kind='fall',severity='critical' if i>1 else 'warning',observed_at=(stamp+timedelta(seconds=i)).isoformat(),observation='recovered' if i==13 else 'abnormal',reason='Cập nhật '+str(i)))
        event_id=str(event[0]['id']);url=f"/api/homes/{home['id']}/events"
        response=owner.get(url,params={'page':1,'severity':'critical','start':(stamp-timedelta(seconds=1)).isoformat(),'end':db.now().isoformat()});self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['total'],1)
        self.assertEqual(owner.get(url,params={'page':1,'severity':'warning'}).json()['total'],0)
        self.assertEqual(owner.get(url,params={'page':1,'start':'2026-01-01'}).status_code,422)
        a=owner.get(f'/api/events/{event_id}/updates?page=1').json();b=owner.get(f'/api/events/{event_id}/updates?page=2').json()
        self.assertEqual(a['total'],13);self.assertEqual(a['items'][0]['sequence'],13);self.assertEqual(len(b['items']),3)
        with db.connect('worker',home['id']) as conn:
            for status in ('expired','deleted','failed'):
                conn.execute("INSERT INTO annha.media_assets(home_id,camera_id,event_id,kind,name,mime_type,status,provider,upload_key) VALUES(%s,%s,%s,'event_image',%s,'image/jpeg',%s,'local',%s)",(home['id'],camera['id'],event_id,status,status,db.uid()))
        evidence=owner.get('/api/events/'+event_id).json()['evidence'];self.assertEqual({x['status'] for x in evidence},{'expired','deleted','failed'})
        outsider,_=self.account('phase6-hidden@example.com');self.assertEqual(outsider.get(f'/api/events/{event_id}/updates?page=1').status_code,404)

    def test_audio_usage_rename_and_pagination_permissions(self):
        owner,account=self.account('phase6-audio@example.com');home,room,camera,_=self.home_camera(owner)
        with db.connect('worker',home['id']) as conn:
            for i in range(23):
                conn.execute("INSERT INTO annha.media_assets(id,home_id,camera_id,kind,name,mime_type,status,provider,upload_key,local_object_key,size_bytes,ready_at) VALUES(%s,%s,%s,'audio',%s,'audio/wav','ready','local',%s,%s,44,now())",(db.uid(),home['id'],camera['id'],'Âm thanh '+str(i),db.uid(),db.uid()+'.wav'))
        url=f"/api/homes/{home['id']}/assets"
        first=owner.get(url,params={'audio_only':True,'page':1,'page_size':10}).json();last=owner.get(url,params={'audio_only':True,'page':3,'page_size':10}).json()
        self.assertEqual(first['total'],23);self.assertEqual(len(last['items']),3)
        asset=first['items'][0];self.assertEqual(owner.patch('/api/assets/'+asset['id'],json={'name':'Đã đổi tên'}).status_code,200)
        self.assertEqual(owner.get(url,params={'page':1,'q':'Đã đổi tên'}).json()['total'],1)
        r=owner.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':camera['id'],'name':'Lịch dùng file','time':'09:00','source':'audio','asset_id':asset['id']});self.assertEqual(r.status_code,201,r.text);reminder=r.json()
        meta=owner.get('/api/assets/'+asset['id']+'/metadata').json();self.assertEqual(meta['used_count'],1);self.assertEqual(meta['used_by'][0]['name'],'Lịch dùng file')
        self.assertEqual(owner.delete('/api/assets/'+asset['id']).status_code,409)
        viewer,person=self.account('phase6-viewer@example.com')
        with db.connect('auth') as conn:
            conn.execute("INSERT INTO annha_private.home_memberships(home_id,user_id,role) VALUES(%s,%s,'viewer')",(home['id'],person['id']))
            conn.execute('INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_view) VALUES(%s,%s,%s,true)',(home['id'],camera['id'],person['id']))
        self.assertEqual(viewer.get(url+'?page=1&audio_only=true').json()['total'],0)
        self.assertEqual(viewer.patch('/api/assets/'+asset['id'],json={'name':'Không cho phép'}).status_code,403)
        # Browser fixture contains private local-only account credentials; never printed.
        Path('.secrets/phase6-ui.json').write_text(json.dumps({'email':account['email'],'password':'correct password 123','home':home['id'],'camera':camera['id'],'asset':asset['id'],'reminder':reminder['id']}))

    def test_history_backend_pages_and_filters(self):
        owner,account=self.account('phase6-history@example.com');home,room,camera,_=self.home_camera(owner)
        reminder=owner.post(f"/api/homes/{home['id']}/reminders",json={'camera_id':camera['id'],'name':'Lịch history','time':'07:00','source':'tts','text':'Nhắc thử'}).json()
        event=svc.ingest_event({'id':camera['id'],'home_id':home['id']},m.EventInput(event_id='phase6-history',kind='fall',severity='critical',observed_at=db.now().isoformat()))
        with db.connect('worker',home['id']) as conn:
            channel=conn.execute("INSERT INTO annha.notification_channels(home_id,recipient_user_id,kind,label,email_version) VALUES(%s,%s,'email','Phase 6 fixture',1) RETURNING id",(home['id'],account['id'])).fetchone()['id']
            for i in range(205):
                conn.execute("INSERT INTO annha.reminder_executions(home_id,camera_id,reminder_id,reminder_version,occurrence_key,scheduled_at,status) VALUES(%s,%s,%s,1,%s,now(),%s)",(home['id'],camera['id'],reminder['id'],str(i),'played' if i%2 else 'failed'))
                db.audit(conn,home['id'],account['id'],'phase6.history',db.uid())
                conn.execute("INSERT INTO annha.notification_deliveries(home_id,camera_id,event_id,channel_id,generation,status,attempt_count,sent_count) VALUES(%s,%s,%s,%s,%s,%s,1,%s)",(home['id'],camera['id'],event[0]['id'],channel,i+10,'accepted' if i%2 else 'failed',1 if i%2 else 0))
        root=f"/api/homes/{home['id']}"
        for endpoint in ('executions','audit','delivery-status'):
            a=owner.get(root+'/'+endpoint+'?page=1&page_size=10');self.assertEqual(a.status_code,200,a.text)
            b=owner.get(root+'/'+endpoint+'?page=21&page_size=10').json();self.assertGreaterEqual(a.json()['total'],205);self.assertTrue(b['items']);self.assertNotEqual(a.json()['items'][0]['id'],b['items'][0]['id'])
            self.assertEqual(owner.get(root+'/'+endpoint+'?page=0').status_code,422)
        filtered=owner.get(root+'/delivery-status',params={'page':1,'channel':'email','status':'accepted','recipient_id':account['id']}).json()
        self.assertEqual(filtered['total'],102);self.assertEqual({r['status'] for r in filtered['items']},{'accepted'})
        self.assertEqual(owner.get(root+'/delivery-status?page=1&status=delivered').json()['total'],0)
        outsider,_=self.account('phase6-history-out@example.com');self.assertEqual(outsider.get(root+'/audit?page=1').status_code,404)

    def test_concurrent_event_and_asset_reads_keep_pool_available(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        owner,_=self.account('phase6-parallel@example.com');home,room,camera,_=self.home_camera(owner)
        event=svc.ingest_event({'id':camera['id'],'home_id':home['id']},m.EventInput(event_id='phase6-parallel',kind='fall',severity='critical',observed_at=db.now().isoformat()))[0]
        asset=db.uid()
        with db.connect('worker',home['id']) as conn:
            conn.execute("INSERT INTO annha.media_assets(id,home_id,camera_id,kind,name,mime_type,status,provider,upload_key) VALUES(%s,%s,%s,'audio','Parallel','audio/wav','failed','local',%s)",(asset,home['id'],camera['id'],db.uid()))
        paths=[f"/api/events/{event['id']}",f"/api/events/{event['id']}/updates?page=1",f'/api/assets/{asset}/metadata']*3
        before=time.monotonic()
        with ThreadPoolExecutor(max_workers=9) as executor:
            responses=list(executor.map(owner.get,paths))
        self.assertTrue(all(r.status_code==200 for r in responses));self.assertLess(time.monotonic()-before,10)
        outsider,_=self.account('phase6-parallel-out@example.com')
        self.assertEqual(outsider.get(paths[0]).status_code,404)
        self.assertEqual(outsider.get(paths[2]).status_code,404)
