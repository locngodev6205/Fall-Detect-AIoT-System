"""AnNhà application entry point."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from . import db, models, services
from .api import router
from .media import router as media_router
from .security import COOKIE, camera_access, check_origin, digest, membership, session_user

logger=logging.getLogger(__name__)
MQTT_ENABLED=os.getenv('MQTT_ENABLED','true').lower()=='true'
WORKER_ENABLED=os.getenv('WORKER_ENABLED','true').lower()=='true'
mqtt_connected=False


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
        with db.connect() as conn:
            camera=conn.execute('SELECT * FROM cameras WHERE token_hash=? AND claimed=1',(digest(token),)).fetchone() if token else None
        if not camera: raise ValueError('Unauthenticated MQTT device')
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
        event,changed=services.ingest_event(dict(camera),models.EventInput(**payload))
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
    db.initialize()
    client=start_mqtt(asyncio.get_running_loop()) if MQTT_ENABLED else None
    worker=asyncio.create_task(services.worker()) if WORKER_ENABLED else None
    yield
    if worker:
        worker.cancel()
        with suppress(asyncio.CancelledError): await worker
    for socket in tuple(services.connections):
        with suppress(Exception): await socket.close(code=1001)
    services.connections.clear()
    from . import media
    for socket in tuple(media.media_sessions):
        with suppress(Exception): await socket.close(code=1001)
    media.media_sessions.clear();media.viewers.clear();media.audio_devices.clear();media.audio_senders.clear()
    if client: client.disconnect();client.loop_stop()


app=FastAPI(title='AnNhà Business API',version='3.0.0',lifespan=lifespan)
app.include_router(router)
app.include_router(media_router)


@app.middleware('http')
async def protect_origin(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS') and not check_origin(request.headers.get('origin')):
        return JSONResponse({'detail':'Nguồn truy cập không được phép.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    return response


@app.exception_handler(sqlite3.IntegrityError)
async def conflict(request,exc):
    return JSONResponse({'detail':'Dữ liệu xung đột hoặc tài nguyên liên quan không tồn tại.'},status_code=409)


@app.get('/')
@app.get('/api/health')
def health():
    return {'status':'online','mode':'business-api','mqtt_connected':mqtt_connected,'authentication':'server-session'}


@app.websocket('/ws/alerts')
async def websocket_alerts(socket:WebSocket):
    token=socket.cookies.get(COOKIE)
    home_id=socket.query_params.get('home_id','')
    try:
        if not check_origin(socket.headers.get('origin')): raise HTTPException(403,'Invalid origin')
        current=session_user(token)
        with db.connect() as conn: membership(conn,home_id,current['id'])
    except HTTPException:
        await socket.close(code=1008);return
    await socket.accept()
    services.connections[socket]=(token,home_id)
    try:
        while True:
            try: await asyncio.wait_for(socket.receive_text(),timeout=5)
            except asyncio.TimeoutError: pass
            current=session_user(token)
            with db.connect() as conn: membership(conn,home_id,current['id'])
    except (WebSocketDisconnect,HTTPException,RuntimeError):
        with suppress(Exception): await socket.close(code=1008)
    finally:
        services.connections.pop(socket,None)
