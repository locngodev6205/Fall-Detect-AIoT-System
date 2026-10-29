"""Bounded, read-only API timing using an existing local account (no password output)."""
import argparse,json,time,statistics
from pathlib import Path
import httpx
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--runs',type=int,default=3);args=p.parse_args()
a=next(a for a in json.loads(Path('.secrets/demo-credentials.json').read_text())['accounts'] if a['role']=='owner')
with httpx.Client(base_url='http://localhost:8188',timeout=90) as c:
    r=c.post('/api/auth/login',json={'email':a['email'],'password':a['password']});r.raise_for_status()
    r=c.get('/api/homes');r.raise_for_status();home=r.json()[0]['id'];cameras=c.get(f'/api/homes/{home}/cameras').json();cam=cameras[0]['id']
    paths={'homes':'/api/homes','cameras':f'/api/homes/{home}/cameras','rooms':f'/api/homes/{home}/rooms','events':f'/api/homes/{home}/events','reminders':f'/api/homes/{home}/reminders','telemetry':f'/api/cameras/{cam}/telemetry?limit=100'}
    data={}
    for name,url in paths.items():
        samples=[];size=0
        for _ in range(args.runs):
            start=time.perf_counter();r=c.get(url);r.raise_for_status();samples.append(round((time.perf_counter()-start)*1000));size=len(r.content)
        data[name]={'median_ms':statistics.median(samples),'samples_ms':samples,'bytes':size};print(name,data[name],flush=True)
Path(args.output).write_text(json.dumps(data,indent=2))
