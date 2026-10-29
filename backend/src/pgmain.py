"""AnNhà application entry point."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
import psycopg
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from . import pgdb as db, models, pgservices as services
from .pgapi import router
from .pgmedia import router as media_router
from .pgsecurity import COOKIE, camera_access, check_origin, digest, membership, session_user, device_identity

logger=logging.getLogger(__name__)
MQTT_ENABLED=os.getenv('MQTT_ENABLED','true').lower()=='true'
WORKER_ENABLED=os.getenv('WORKER_ENABLED','true').lower()=='true'
mqtt_connected=False

TB_HOST = os.getenv("TB_HOST", "127.0.0.1")
TB_HTTP_PORT = int(os.getenv("TB_HTTP_PORT", 8080))
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")
DEVICE_NAME = os.getenv("DEVICE_ID", "RASPI_ROOM_101")
alerts_history = []


def _tb_login() -> str:
    url = f"http://{TB_HOST}:{TB_HTTP_PORT}/api/auth/login"
    req = urllib.request.Request(
        url,
        data=json.dumps({"username": TB_USERNAME, "password": TB_PASSWORD}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))["token"]


def _tb_get_device_id(jwt_token: str) -> str:
    url = f"http://{TB_HOST}:{TB_HTTP_PORT}/api/tenant/devices?deviceName={DEVICE_NAME}"
    req = urllib.request.Request(url, headers={"X-Authorization": f"Bearer {jwt_token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))["id"]["id"]


def start_mqtt(loop):
    import paho.mqtt.client as mqtt
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='annha-backend')
    if os.getenv('MQTT_USER'): client.username_pw_set(os.environ['MQTT_USER'],os.getenv('MQTT_PASSWORD'))
    def connected(client,userdata,flags,reason,properties):
        global mqtt_connected
        mqtt_connected=not reason.is_failure
        if mqtt_connected: client.subscribe(os.getenv('MQTT_TOPIC_FALL_ALERT','smartfall/alerts'),qos=1)
    def disconnected(client,userdata,flags,reason,properties):
        global mqtt_connected
        mqtt_connected=False
    async def process(payload):
        # The registered credential, not a claimed home_id/device_id in payload, is authoritative.
        token=payload.pop('device_token','')
        camera=await asyncio.to_thread(device_identity,token)
        legacy=payload.get('event')
        if legacy:
            payload={
                'event_id':str(payload.get('event_id') or payload.get('timestamp') or ''),
                'kind':'immobility' if 'IMMOB' in legacy else 'fall','severity':'critical',
                'observed_at':payload.get('timestamp'), 'confidence':payload.get('confidence'),
                'observation':'suspected','reason':'Thông báo từ bộ nhận diện',
                'duration_s':payload.get('duration_s',payload.get('immobility_duration_s')),
            }
        else:
            payload.pop('device_id',None)
        event,changed=await asyncio.to_thread(services.ingest_event,dict(camera),models.EventInput(**payload))
        if changed: await services.broadcast(event)
    def completed(future):
        try: future.result()
        except Exception: logger.warning('Rejected invalid or unauthenticated MQTT event')
    def message(client,userdata,msg):
        try:
            if len(msg.payload)>65536: raise ValueError()
            payload=json.loads(msg.payload)
            if not isinstance(payload,dict): raise ValueError()
            asyncio.run_coroutine_threadsafe(process(payload),loop).add_done_callback(completed)
        except (ValueError,UnicodeError): logger.warning('Rejected malformed MQTT payload')
    client.on_connect=connected;client.on_disconnect=disconnected;client.on_message=message
    client.connect_async(os.getenv('MQTT_BROKER','127.0.0.1'),int(os.getenv('MQTT_PORT','1883')),60)
    client.loop_start()
    return client


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(db.open_pools)
    client=start_mqtt(asyncio.get_running_loop()) if MQTT_ENABLED else None
    worker=asyncio.create_task(services.worker()) if WORKER_ENABLED else None
    yield
    if worker:
        worker.cancel()
        with suppress(asyncio.CancelledError): await worker
    for socket in tuple(services.connections):
        with suppress(Exception): await socket.close(code=1001)
    services.connections.clear()
    from . import pgmedia as media
    for socket in tuple(media.media_sessions):
        with suppress(Exception): await socket.close(code=1001)
    media.media_sessions.clear();media.viewers.clear();media.audio_devices.clear();media.audio_senders.clear()
    if client: client.disconnect();client.loop_stop()
    db.close_pools()


app=FastAPI(title='AnNhà Business API',version='3.0.0',lifespan=lifespan)
app.include_router(router)
app.include_router(media_router)


@app.middleware('http')
async def protect_origin(request:Request,call_next):
    if request.url.path == '/api/tb-webhook':
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response
    if request.method not in ('GET','HEAD','OPTIONS') and not check_origin(request.headers.get('origin')):
        return JSONResponse({'detail':'Nguồn truy cập không được phép.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response


@app.exception_handler(psycopg.IntegrityError)
async def conflict(request,exc):
    return JSONResponse({'detail':'Dữ liệu xung đột hoặc tài nguyên liên quan không tồn tại.'},status_code=409)


def database_ok():
    with db.connect('auth') as conn: return conn.execute('SELECT 1 AS ok').fetchone()['ok']==1


@app.get('/')
@app.get('/api/health')
def health():
    return {
        'status':'online',
        'mode':'business-api',
        'database':'postgres',
        'database_connected':database_ok(),
        'mqtt_connected':mqtt_connected,
        'authentication':'server-session',
        'thingsboard_url':f'http://{TB_HOST}:{TB_HTTP_PORT}',
        'device_id':DEVICE_NAME
    }


@app.post('/api/tb-webhook')
async def thingsboard_webhook(request:Request):
    # Route ThingsBoard through the same registered-device identity and event validation.
    header=request.headers.get('authorization','')
    camera=await asyncio.to_thread(device_identity,header[7:] if header.startswith('Bearer ') else '')
    payload=models.EventInput(**(await request.json()))
    event,changed=await asyncio.to_thread(services.ingest_event,camera,payload)
    if changed: await services.broadcast(event)
    return {'stored':True,'id':event['id']}


@app.websocket('/ws/alerts')
async def websocket_alerts(socket:WebSocket):
    token=socket.cookies.get(COOKIE)
    home_id=socket.query_params.get('home_id','')
    try:
        if not check_origin(socket.headers.get('origin')): raise HTTPException(403,'Invalid origin')
        current=await asyncio.to_thread(session_user,token)
        await asyncio.to_thread(membership,home_id,current['id'])
    except HTTPException:
        await socket.close(code=1008);return
    await socket.accept()
    services.connections[socket]=(token,home_id)
    try:
        while True:
            try: await asyncio.wait_for(socket.receive_text(),timeout=5)
            except asyncio.TimeoutError: pass
            current=await asyncio.to_thread(session_user,token)
            await asyncio.to_thread(membership,home_id,current['id'])
    except (WebSocketDisconnect,HTTPException,RuntimeError):
        with suppress(Exception): await socket.close(code=1008)
    finally:
        services.connections.pop(socket,None)

@app.exception_handler(psycopg.DataError)
async def invalid_database_value(request,exc):
    return JSONResponse({'detail':'Định dạng dữ liệu không hợp lệ.'},status_code=422)

@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(request,exc):
    return JSONResponse({'detail':'Cơ sở dữ liệu tạm thời không khả dụng.'},status_code=503)
