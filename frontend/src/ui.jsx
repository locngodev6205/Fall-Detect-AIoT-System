import React, { useEffect, useRef } from 'react';
import { House, X, WifiSlash, VideoCamera } from '@phosphor-icons/react';
import { dateTime } from './api';
export function Logo() { return <a className="brand" href="#/"><House weight="bold"/><span><strong>AnNhà</strong><small>Nhà an tâm, mình an lòng</small></span></a>; }
export function Button({ children, kind = '', type = 'button', ...rest }) { return <button type={type} className={'button ' + kind} {...rest}>{children}</button>; }
export function Badge({ children, tone = 'teal' }) { return <span className={'badge ' + tone}>{children}</span>; }
export function Field({ label, children, hint, ...props }) { return <label className="field"><span>{label}</span>{children ? React.cloneElement(children, { 'aria-label': label }) : <input aria-label={label} {...props}/ >}{hint && <small>{hint}</small>}</label>; }
export function Empty({ title, text, action }) { return <div className="empty"><House size={40}/><h2>{title}</h2><p>{text}</p>{action}</div>; }
export function Heading({ title, text, action }) { return <div className="section-heading"><div><h1>{title}</h1>{text && <p>{text}</p>}</div>{action}</div>; }
export function Modal({ title, children, onClose, wide = false }) {
  const ref = useRef();
  useEffect(() => {
    const old = document.activeElement;ref.current?.focus();
    function key(event) {
      if (event.key === 'Escape') onClose();
      if (event.key === 'Tab') {
        const nodes = [...ref.current.querySelectorAll('button,input,select,textarea,a[href]')].filter(x => !x.disabled);
        if (!nodes.length) return;
        if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault();nodes.at(-1).focus(); }
        else if (!event.shiftKey && document.activeElement === nodes.at(-1)) { event.preventDefault();nodes[0].focus(); }
      }
    }
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key);old?.focus(); };
  }, []);
  return <div className="modal-backdrop"><section ref={ref} tabIndex={-1} className={'modal ' + (wide ? 'wide' : '')} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="icon" onClick={onClose} aria-label="Đóng"><X/></button></header>{children}</section></div>;
}
export function CameraImage({ camera, onClick }) {
  const [image, setImage] = React.useState(null), [captured, setCaptured] = React.useState(null), [live, setLive] = React.useState(false);
  useEffect(() => {
    let stopped = false, objectUrl, lastFrame = 0, socket, retry;
    function show(blob, timestamp) {
      if (stopped) return;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(blob);setImage(objectUrl);setCaptured(timestamp);
    }
    async function load() {
      if (Date.now() - lastFrame < 5000) return;
      try {
        const response = await fetch('/api/cameras/' + camera.id + '/snapshot');
        if (!response.ok) return;
        const blob = await response.blob();
        if (Date.now() - lastFrame >= 5000) show(blob, response.headers.get('X-Captured-At'));
      } catch {}
    }
    function connect() {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/cameras/${camera.id}`);
      socket.binaryType = 'blob';
      socket.onmessage = event => { if (event.data instanceof Blob) { lastFrame = Date.now();show(event.data, new Date().toISOString());setLive(true); } };
      socket.onclose = () => { if (!stopped) { setLive(false);retry = setTimeout(connect, 4000); } };
    }
    setImage(null);setCaptured(null);setLive(false);load();connect();
    const timer = setInterval(() => { if (Date.now() - lastFrame > 5000) { setLive(false);load(); } }, 5000);
    return () => { stopped = true;clearTimeout(retry);clearInterval(timer);socket?.close();if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [camera.id]);
  return <div className="camera-photo real-camera" onClick={onClick}>
    {image ? <img src={image} alt={'Ảnh nhận từ ' + camera.name}/> : <div className="camera-empty"><VideoCamera size={44}/><strong>Chưa có hình ảnh từ thiết bị</strong><span>Kiểm tra nguồn điện và kết nối của thiết bị.</span></div>}
    <div className="photo-top"><Badge tone={live ? 'dark' : 'gray'}>{live ? 'Đang nhận hình trực tiếp' : camera.online ? 'Đang chờ hình / ảnh gần nhất' : <><WifiSlash/>Mất kết nối / chưa kết nối</>}</Badge></div>
    <div className="photo-bottom"><strong>{camera.name}</strong><span>Nhận ảnh: {dateTime(captured)}</span></div>
  </div>;
}
