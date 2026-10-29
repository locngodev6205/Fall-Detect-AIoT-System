import React, { useEffect, useRef } from 'react';
import { House, X, WifiSlash, VideoCamera, Image as ImageIcon, CheckCircle } from '@phosphor-icons/react';
import { dateTime } from './api';
import { usePagination } from './pagination';
import { roomImage, connectionLabel } from './cameraState';
export function Logo({ href = '#/' }) { return <a className="brand" href={href}><House weight="bold"/><span><strong>AnNhà</strong><small>Nhà an tâm, mình an lòng</small></span></a>; }
export function Button({ children, kind = '', type = 'button', ...rest }) { return <button type={type} className={'button ' + kind} {...rest}>{children}</button>; }
export function Badge({ children, tone = 'teal' }) { return <span className={'badge ' + tone}>{children}</span>; }
export function Field({ label, children, hint, ...props }) { return <label className="field"><span>{label}</span>{children ? React.cloneElement(children, { 'aria-label': label }) : <input aria-label={label} {...props}/ >}{hint && <small>{hint}</small>}</label>; }
export function Empty({ title, text, action, icon: Icon = House }) { return <div className="empty"><Icon size={40}/><h2>{title}</h2><p>{text}</p>{action}</div>; }
export function Heading({ title, text, action, level = 1 }) { const Tag = level === 1 ? 'h1' : 'h2';return <div className="section-heading"><div><Tag>{title}</Tag>{text && <p>{text}</p>}</div>{action}</div>; }
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
export function CameraThumbnail({ name, className = '' }) {
  return <img className={'room-thumbnail ' + className} src={roomImage(name)} alt={'Ảnh minh hoạ ' + name} loading="lazy"/>;
}
export function CameraImage({ camera, roomName, onClick }) {
  const [frame, setFrame] = React.useState(null), [live, setLive] = React.useState(false);
  const fallback = roomImage(roomName || camera.name);
  useEffect(() => {
    let stopped = false, objectUrl, lastFrame = 0, socket, retry;
    const controller = new AbortController();
    function show(blob, timestamp) {
      if (stopped) return;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(blob);
      setFrame({ cameraId: camera.id, url: objectUrl, captured: timestamp });
    }
    async function load() {
      if (camera.snapshot_available === false || Date.now() - lastFrame < 5000) return;
      try {
        const response = await fetch('/api/cameras/' + camera.id + '/snapshot', { signal: controller.signal });
        if (!response.ok) {
          if ([401,403,404].includes(response.status) && !stopped) setFrame(null);
          return;
        }
        if (!response.headers.get('content-type')?.startsWith('image/')) return;
        const blob = await response.blob();
        if (Date.now() - lastFrame >= 5000) show(blob, response.headers.get('X-Captured-At'));
      } catch {}
    }
    function connect() {
      if (stopped || !camera.online) return;
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/cameras/${camera.id}`);
      socket.binaryType = 'blob';
      socket.onmessage = event => { if (!stopped && event.data instanceof Blob) { lastFrame = Date.now();show(event.data, new Date().toISOString());setLive(true); } };
      socket.onclose = () => { if (!stopped) { setLive(false);retry = setTimeout(connect, 5000); } };
    }
    setFrame(null);setLive(false);load();connect();
    const watchdog = setInterval(() => { if (Date.now() - lastFrame > 5000) setLive(false); }, 1000);
    const timer = setInterval(() => { if (Date.now() - lastFrame > 5000) load(); }, 10000);
    return () => { stopped = true;controller.abort();clearTimeout(retry);clearInterval(watchdog);clearInterval(timer);socket?.close();if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [camera.id, camera.online, camera.snapshot_available]);
  const current = frame?.cameraId === camera.id ? frame : null;
  const receiving = !!current && live;
  const Tag = onClick ? 'button' : 'div';
  return <Tag type={onClick ? 'button' : undefined} className={'camera-photo real-camera ' + (onClick ? 'clickable' : '')} onClick={onClick} aria-label={onClick ? 'Mở camera ' + camera.name : undefined}>
    <img src={current?.url || fallback} alt={current ? 'Ảnh nhận từ ' + camera.name : 'Ảnh minh hoạ ' + (roomName || camera.name)} onError={() => { if (current) { setFrame(null);setLive(false); } }}/>
    <div className="photo-top"><Badge tone={receiving ? 'dark' : 'camera-status'}>{receiving ? <><span className="dot"/>Đang nhận hình trực tiếp</> : camera.online ? <><CheckCircle/>Đang chờ hình ảnh</> : <><WifiSlash/>{connectionLabel(camera)}</>}</Badge><span className="photo-source">{current ? (receiving ? 'Trực tiếp' : 'Ảnh gần nhất') : <><ImageIcon/>Ảnh minh hoạ</>}</span></div>
    <div className="photo-bottom"><div><strong>{roomName || camera.name}</strong><span>{current ? 'Nhận ảnh: ' + dateTime(current.captured) : 'Hình ảnh thiết bị sẽ xuất hiện tại đây khi kết nối.'}</span></div>{!current && <VideoCamera size={24}/>}</div>
  </Tag>;
}

export class ScreenBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <section className="panel quiet-state" role="alert"><VideoCamera size={32}/><h2>Chưa thể hiển thị trang này</h2><p>Hãy tải lại nội dung. Dữ liệu của bạn vẫn được lưu trên hệ thống.</p><Button onClick={() => { this.setState({ failed: false });this.props.onRetry?.(); }}>Thử lại</Button></section>;
    return this.props.children;
  }
}

export function Pagination({ page, pageSize, total, onChange, label='danh sách' }) {
  if (!total) return null;
  const pages=Math.max(1,Math.ceil(total/pageSize));
  if(pages===1)return <div className="pagination"><span>{total} kết quả</span></div>;
  const first=Math.max(1,Math.min(page-2,pages-4));
  const numbers=Array.from({length:Math.min(5,pages)},(_,index)=>first+index);
  return <nav className="pagination" aria-label={'Phân trang '+label}>
    <span>{(page-1)*pageSize+1}–{Math.min(page*pageSize,total)} / {total} kết quả</span>
    <div className="pagination-controls"><button disabled={page<=1} onClick={()=>onChange(page-1)} aria-label="Trang trước">Trước</button>
      <div className="pagination-numbers">{first>1 && <button onClick={()=>onChange(1)} aria-label="Trang 1">1</button>}{first>2 && <span className="pager-ellipsis">…</span>}{numbers.map(number=><button key={number} aria-label={'Trang '+number} aria-current={page===number?'page':undefined} onClick={()=>onChange(number)}>{number}</button>)}{numbers.at(-1)<pages-1 && <span className="pager-ellipsis">…</span>}{numbers.at(-1)<pages && <button onClick={()=>onChange(pages)} aria-label={'Trang '+pages}>{pages}</button>}</div>
      <button disabled={page>=pages} onClick={()=>onChange(page+1)} aria-label="Trang sau">Sau</button>
    </div>
  </nav>;
}
export function PagedList({ items, children, pageSize=10, label='danh sách', resetKey='' }) {
  const state=usePagination(items,pageSize,resetKey);
  return <>{state.items.map(children)}<Pagination page={state.page} pageSize={pageSize} total={state.total} onChange={state.setPage} label={label}/></>;
}
