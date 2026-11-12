import React from 'react';
import { go } from './api';
import { AlertSoundControl } from './alertSound';

export function AlertPopover({ alerts, sound, onRead, onReadAll, readingId, onClose }) {
  return <section className="alert-popover" aria-label="Thông báo sự kiện">
    <header><strong>Thông báo</strong><button onClick={() => { onClose();go('/events'); }}>Xem tất cả</button></header>
    <AlertSoundControl sound={sound}/>
    {!!alerts.unread_count&&<button className="alert-popover-read-all" disabled={Boolean(readingId)} onClick={onReadAll}>Đánh dấu tất cả đã đọc</button>}
    {alerts.items.length ? alerts.items.map(event => <div className="alert-popover-entry" key={event.id}>
      {event.is_read ? <div className="alert-popover-row is-read">
        <span className={'alert-dot '+(event.severity==='critical'?'critical':'')}/>
        <span><strong>{event.camera_name||'Camera'}</strong><small>{event.reason||'Cần kiểm tra'} · Đã đọc</small></span>
      </div> : <button className="alert-popover-row" disabled={Boolean(readingId)} onClick={() => onRead(event.id)}>
        <span className={'alert-dot '+(event.severity==='critical'?'critical':'')}/>
        <span><strong>{event.camera_name||'Camera'}</strong><small>{event.reason||'Cần kiểm tra'} · {readingId===event.id?'Đang lưu…':'Đánh dấu đã đọc'}</small></span>
      </button>}
      <a className="alert-popover-detail" href={'#/event/'+event.id} onClick={onClose}>Xem chi tiết sự kiện</a>
    </div>) : <p className="alert-empty">Không có cảnh báo đang mở.</p>}
  </section>;
}
