"""Run inside backend: docker compose exec -T backend python - < scripts/cloud/smoke_mqtt.py
Publishes labelled demo events only to the internal broker; uses private demo tokens.
"""
from datetime import datetime,timezone
import http.cookiejar
import json
from pathlib import Path
import secrets
import time
import urllib.request
import paho.mqtt.client as mqtt

credentials=json.loads(Path('/app/data/demo-credentials.json').read_text())
owner=next(a for a in credentials['accounts'] if a['role']=='owner');device=credentials['devices'][0]
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def api(path,body=None):
    request=urllib.request.Request('http://127.0.0.1:8000/api'+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=20) as response: return json.load(response)
api('/auth/login',{'email':owner['email'],'password':owner['password']})
home=api('/homes')[0]['id'];source='mqtt-smoke:'+secrets.token_hex(8)
client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect('mqtt',1883,30);client.loop_start()
payload={'device_token':device['device_token'],'event_id':source,'kind':'fall','severity':'warning','observation':'suspected','observed_at':datetime.now(timezone.utc).isoformat(),'reason':'SMOKE · MQTT thật qua broker nội bộ'}
info=client.publish('smartfall/alerts',json.dumps(payload),qos=1);info.wait_for_publish(timeout=5)
deadline=time.monotonic()+30
while time.monotonic()<deadline:
    rows=api('/homes/'+home+'/events')
    if any(r['source_id']==source and r['camera_id']==device['camera_id'] for r in rows): break
    time.sleep(1)
else: raise AssertionError('MQTT event did not reach the Neon event feed')
payload['event_id']=source+':invalid';payload['device_token']='invalid-device-token'
client.publish('smartfall/alerts',json.dumps(payload),qos=1).wait_for_publish(timeout=5)
time.sleep(2)
assert not any(r['source_id']==payload['event_id'] for r in api('/homes/'+home+'/events'))
client.disconnect();client.loop_stop()
print('PASS MQTT -> registered device -> Neon event feed; invalid device token rejected')
