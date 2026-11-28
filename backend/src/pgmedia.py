"""Authenticated, bounded JPEG/audio relay. No public camera URL or arbitrary proxy."""
import asyncio
from contextlib import suppress
import time
from .audio_relay import AudioRelay
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from psycopg import Error as DatabaseError
from .pgsecurity import COOKIE, camera_access, check_origin, session_user, device_identity as lookup_device

router=APIRouter()
VIEW_RECHECK_SECONDS = 3
AUTH_LEASE_SECONDS = 8
viewers={}  # camera -> {socket: authorization deadline}
video_devices={}  # device socket -> verified camera ID
audio_devices={}  # camera -> device WebSocket
audio_senders={}  # camera -> browser WebSocket
media_sessions={}  # browser socket -> (token, camera, permission)


def device_identity(socket):
    header=socket.headers.get('authorization','')
    token=header[7:] if header.startswith('Bearer ') else ''
    return lookup_device(token),token


def viewer_authorization(socket,camera_id,action='view'):
    if not check_origin(socket.headers.get('origin')): raise HTTPException(403,'Invalid origin')
    token=socket.cookies.get(COOKIE)
    current=session_user(token)
    camera_access(camera_id,current['id'],action)
    return token,current.get('session_expires_at')


def authorize(socket,camera_id,action='view'):
    return viewer_authorization(socket,camera_id,action)[0]


def authorization_deadline(started, expires_at):
    deadline = started + AUTH_LEASE_SECONDS
    if expires_at is not None:
        now = time.monotonic()
        deadline = min(deadline, now + expires_at.timestamp() - time.time())
    if deadline <= time.monotonic():
        raise HTTPException(401)
    return deadline


async def close(socket,code=1008):
    with suppress(Exception): await socket.close(code=code)


def remove_viewer(camera_id, socket):
    sockets = viewers.get(camera_id)
    if sockets is not None:
        sockets.pop(socket, None)
        if not sockets:
            viewers.pop(camera_id, None)


async def revalidate():
    for socket,(token,camera_id,permission) in tuple(media_sessions.items()):
        try:
            current=await asyncio.to_thread(session_user,token)
            await asyncio.to_thread(camera_access,camera_id,current['id'],permission)
        except (HTTPException,DatabaseError):
            media_sessions.pop(socket,None)
            remove_viewer(camera_id,socket)
            await close(socket)
    for socket,camera_id in tuple(video_devices.items()):
        try:
            camera,_=await asyncio.to_thread(device_identity,socket)
            if camera['id'] != camera_id:
                raise HTTPException(403)
        except (HTTPException,DatabaseError):
            video_devices.pop(socket,None)
            await close(socket)
    for camera_id,socket in tuple(audio_devices.items()):
        try: await asyncio.to_thread(device_identity,socket)
        except HTTPException:
            audio_devices.pop(camera_id,None);await close(socket)


@router.websocket('/ws/device/frames')
async def device_frames(socket:WebSocket):
    started=time.monotonic()
    try:
        camera,_=await asyncio.to_thread(device_identity,socket)
        deadline=authorization_deadline(started,camera.get('credential_expires_at'))
    except (HTTPException,DatabaseError): await close(socket);return
    camera_id=camera['id']
    await socket.accept()
    video_devices[socket]=camera_id
    last=0
    try:
        while socket in video_devices:
            try: frame=await asyncio.wait_for(socket.receive_bytes(),timeout=max(0,deadline-time.monotonic()))
            except asyncio.TimeoutError: frame=None
            if time.monotonic()>=deadline:
                started=time.monotonic()
                camera,_=await asyncio.to_thread(device_identity,socket)
                if camera['id']!=camera_id: break
                deadline=authorization_deadline(started,camera.get('credential_expires_at'))
            if socket not in video_devices: break
            if frame is None: continue
            if len(frame)>1024*1024 or not frame.startswith(b'\xff\xd8\xff'): await close(socket,1009);return
            if time.monotonic()-last<0.18: continue
            last=time.monotonic()
            for viewer in tuple(viewers.get(camera_id,{})):
                now=time.monotonic()
                if socket not in video_devices or now>=deadline: break
                remaining=min(deadline,viewers.get(camera_id,{}).get(viewer,0))-now
                if remaining<=0: continue
                try:
                    await asyncio.wait_for(viewer.send_bytes(frame),timeout=min(.5,remaining))
                except Exception:
                    remove_viewer(camera_id,viewer)
                    await close(viewer)
    except (WebSocketDisconnect,RuntimeError,HTTPException,DatabaseError): pass
    finally:
        video_devices.pop(socket,None)
        await close(socket)


@router.websocket('/ws/cameras/{camera_id}')
async def browser_frames(socket:WebSocket,camera_id:str):
    started=time.monotonic()
    try:
        token,expires_at=await asyncio.to_thread(viewer_authorization,socket,camera_id)
        deadline=authorization_deadline(started,expires_at)
    except (HTTPException,DatabaseError): await close(socket);return
    await socket.accept()
    viewers.setdefault(camera_id,{})[socket]=deadline
    media_sessions[socket]=(token,camera_id,'view')
    try:
        while socket in media_sessions and socket in viewers.get(camera_id,{}):
            recheck=min(deadline,started+VIEW_RECHECK_SECONDS)
            try: await asyncio.wait_for(socket.receive_text(),timeout=max(0,recheck-time.monotonic()))
            except asyncio.TimeoutError: pass
            if time.monotonic()<recheck: continue
            started=time.monotonic()
            _,expires_at=await asyncio.to_thread(viewer_authorization,socket,camera_id)
            deadline=authorization_deadline(started,expires_at)
            # Do not restore access if a concurrent revocation removed this connection.
            if socket not in media_sessions or socket not in viewers.get(camera_id,{}): break
            viewers[camera_id][socket]=deadline
    except (WebSocketDisconnect,RuntimeError,HTTPException,DatabaseError): pass
    finally:
        remove_viewer(camera_id,socket)
        media_sessions.pop(socket,None)
        await close(socket)


audio_relay = AudioRelay(authorize, device_identity, close, audio_devices, audio_senders, media_sessions)


@router.websocket('/ws/device/audio')
async def device_audio(socket: WebSocket):
    await audio_relay.device(socket)


@router.websocket('/ws/audio/{camera_id}')
async def browser_audio(socket: WebSocket, camera_id: str):
    await audio_relay.browser(socket, camera_id)
