"""Optional browser fixture setup after Phase6Tests, local PostgreSQL only; no provider calls."""
import os,json,logging
from pathlib import Path
from dotenv import dotenv_values
from datetime import timedelta
root=Path(__file__).resolve().parents[2];env=Path(os.environ['ANNHA_TEST_ENV']).resolve()
from urllib.parse import urlsplit
config=dotenv_values(env)
if any(urlsplit(config.get('DATABASE_URL_'+role,'')).hostname not in ('localhost','127.0.0.1') for role in ('APP','AUTH','DEVICE','WORKER')):raise RuntimeError('Only isolated local PostgreSQL is allowed.')
os.environ.update({k:v for k,v in dotenv_values(env).items() if v is not None});os.environ['ANNHA_TEST_ENV']=str(env)
import sys
sys.path.insert(0,str(root))
from backend.src import pgdb as db,pgservices as svc,models as m
for name in ('psycopg_pool','psycopg_pool.pool'):logging.getLogger(name).setLevel(logging.CRITICAL)
f=json.loads((root/'.secrets/phase6-ui.json').read_text());home=f['home'];camera=f['camera']
db.open_pools()
try:
    event=None
    for i in range(1,14):event=svc.ingest_event({'id':camera,'home_id':home},m.EventInput(event_id='phase6-browser',sequence=i,kind='fall',severity='critical',observed_at=(db.now()-timedelta(minutes=14-i)).isoformat(),reason='Quan sát kiểm thử '+str(i)))[0]
    f['event']=str(event['id'])
    with db.connect('worker',home) as conn:
        conn.execute("""INSERT INTO annha.telemetry_batches(home_id,camera_id,message_id,observed_at)
          SELECT %s,%s,'browser-'||i,now()-interval '20 hours'+i*interval '1 minute' FROM generate_series(0,604) i
          ON CONFLICT(camera_id,message_id) DO NOTHING""",(home,camera))
        conn.execute("""INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality)
          SELECT home_id,camera_id,id,'temperature',24+sin(extract(epoch FROM observed_at)/5000),'C','valid'
          FROM annha.telemetry_batches WHERE camera_id=%s ON CONFLICT DO NOTHING""",(camera,))
        for status in ('expired','deleted','failed'):
            conn.execute("INSERT INTO annha.media_assets(home_id,camera_id,event_id,kind,name,mime_type,status,provider,upload_key) VALUES(%s,%s,%s,'event_image',%s,'image/jpeg',%s,'local',%s)",(home,camera,event['id'],status,status,db.uid()))
        account=conn.execute('SELECT user_id FROM annha_private.home_memberships WHERE home_id=%s AND role=\'owner\'',(home,)).fetchone()['user_id']
        for i in range(25):db.audit(conn,home,account,'asset.rename',f['asset'])
    (root/'.secrets/phase6-ui.json').write_text(json.dumps(f))
    print('Local Phase 6 UI fixtures ready; no providers called.')
finally:db.close_pools()
