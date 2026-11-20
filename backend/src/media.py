"""Authenticated, bounded JPEG/audio relay. No public camera URL or arbitrary proxy."""
import asyncio
from contextlib import suppress
import time
from .audio_relay import AudioRelay
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from . import db
from .security import COOKIE, camera_access, check_origin, digest, session_user

router=APIRouter()
viewers={}  # camera -> {socket: session token}
audio_devices={}  # camera -> device WebSocket
audio_senders={}  # camera -> browser WebSocket
media_sessions={}  # browser socket -> (token, camera, permission)


def device_identity(socket):
    header=socket.headers.get('authorization','')
    token=header[7:] if header.startswith('Bearer ') else ''
    with db.connect() as conn:
        camera=conn.execute('SELECT * FROM cameras WHERE token_hash=? AND claimed=1',(digest(token),)).fetchone() if token else None
    if not camera: raise HTTPException(401,'Device credential required')
    return dict(camera),token


def authorize(socket,camera_id,action='view'):
    if not check_origin(socket.headers.get('origin')): raise HTTPException(403,'Invalid origin')
    token=socket.cookies.get(COOKIE)
    current=session_user(token)
    with db.connect() as conn: camera_access(conn,camera_id,current['id'],action)
    return token


async def close(socket,code=1008):
    with suppress(Exception): await socket.close(code=code)


async def revalidate():
    for socket,(token,camera_id,permission) in tuple(media_sessions.items()):
        try:
            current=session_user(token)
            with db.connect() as conn: camera_access(conn,camera_id,current['id'],permission)
        except HTTPException:
            media_sessions.pop(socket,None);await close(socket)
    for camera_id,socket in tuple(audio_devices.items()):
        try: device_identity(socket)
        except HTTPException:
            audio_devices.pop(camera_id,None);await close(socket)


@router.websocket('/ws/device/frames')
async def device_frames(socket:WebSocket):
    try: camera,token=device_identity(socket)
    except HTTPException: await close(socket);return
    await socket.accept()
    last=0
    try:
        while True:
            frame=await socket.receive_bytes()
            camera,_=device_identity(socket)
            if len(frame)>1024*1024 or not frame.startswith(b'\xff\xd8\xff'): await close(socket,1009);return
            if time.monotonic()-last<0.18: continue
            last=time.monotonic()
            for viewer,session_token in tuple(viewers.get(camera['id'],{}).items()):
                try:
                    authorize(viewer,camera['id'])
                    await asyncio.wait_for(viewer.send_bytes(frame),timeout=.5)
                except Exception:
                    viewers.get(camera['id'],{}).pop(viewer,None)
                    await close(viewer)
    except (WebSocketDisconnect,RuntimeError,HTTPException): pass
    finally: await close(socket)


@router.websocket('/ws/cameras/{camera_id}')
async def browser_frames(socket:WebSocket,camera_id:str):
    try: token=authorize(socket,camera_id)
    except HTTPException: await close(socket);return
    await socket.accept()
    viewers.setdefault(camera_id,{})[socket]=token
    media_sessions[socket]=(token,camera_id,'view')
    try:
        while True:
            try: await asyncio.wait_for(socket.receive_text(),timeout=3)
            except asyncio.TimeoutError: pass
            authorize(socket,camera_id)
    except (WebSocketDisconnect,RuntimeError,HTTPException): pass
    finally:
        viewers.get(camera_id,{}).pop(socket,None);media_sessions.pop(socket,None)
        await close(socket)


audio_relay = AudioRelay(authorize, device_identity, close, audio_devices, audio_senders, media_sessions)


@router.websocket('/ws/device/audio')
async def device_audio(socket: WebSocket):
    await audio_relay.device(socket)


@router.websocket('/ws/audio/{camera_id}')
async def browser_audio(socket: WebSocket, camera_id: str):
    await audio_relay.browser(socket, camera_id)
