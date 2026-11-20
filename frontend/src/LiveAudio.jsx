import React, { useEffect, useRef, useState } from 'react';
import { Button } from './ui';
import { useApp } from './context';

const MAX_CHUNK = 32 * 1024;
const MAX_SOCKET_BUFFER = 12 * 1024;

function dispose(session) {
  clearTimeout(session.deadline);
  if (session.recorder?.state === 'recording') session.recorder.stop();
  session.media?.getTracks().forEach(track => track.stop());
  if (session.ws?.readyState === WebSocket.OPEN) {
    session.ws.send(JSON.stringify({ type: 'stop' }));
  }
  session.ws?.close();
}

export function LiveAudio({ cameraId, disabled }) {
  const { notify } = useApp();
  const [status, setStatus] = useState('idle');
  const active = useRef(null);

  function stop(session, message) {
    if (active.current !== session) return;
    active.current = null;
    if (session) dispose(session);
    setStatus('idle');
    if (message) notify(message);
  }

  useEffect(() => {
    setStatus('idle');
    return () => {
      const session = active.current;
      active.current = null;
      if (session) dispose(session);
    };
  }, [cameraId]);

  async function start() {
    if (active.current || !cameraId) return;
    const session = {};
    active.current = session;
    setStatus('connecting');
    try {
      const mime = ['audio/webm', 'audio/ogg'].find(type =>
        window.MediaRecorder?.isTypeSupported(type + ';codecs=opus'));
      if (!mime) throw new Error('Trình duyệt chưa hỗ trợ truyền giọng nói Opus.');
      const media = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      if (active.current !== session) {
        media.getTracks().forEach(track => track.stop());
        return;
      }
      session.media = media;
      const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(protocol + '://' + location.host + '/ws/audio/' + encodeURIComponent(cameraId));
      session.ws = ws;
      ws.onopen = () => {
        if (active.current === session) ws.send(JSON.stringify({ mime }));
      };
      ws.onmessage = event => {
        if (active.current !== session || session.recorder) return;
        try {
          const ready = JSON.parse(event.data);
          if (ready.type !== 'ready') return;
          if (ready.protocol !== 2) throw new Error('Máy chủ chưa hỗ trợ truyền âm thanh trực tiếp.');
          const recorder = new MediaRecorder(media, { mimeType: mime + ';codecs=opus', audioBitsPerSecond: 48000 });
          session.recorder = recorder;
          recorder.ondataavailable = ({ data }) => {
            if (!data.size || active.current !== session || ws.readyState !== WebSocket.OPEN) return;
            if (data.size > MAX_CHUNK || ws.bufferedAmount + data.size > MAX_SOCKET_BUFFER) {
              stop(session, 'Kết nối chậm, phiên âm thanh đã dừng.');
            } else {
              ws.send(data);
            }
          };
          recorder.onerror = () => stop(session, 'Microphone đã dừng ghi âm.');
          recorder.start(200);
          clearTimeout(session.deadline);
          session.deadline = setTimeout(() => stop(session), 60000);
          setStatus('transmitting');
        } catch (error) {
          stop(session, error.message);
        }
      };
      ws.onerror = () => stop(session, 'Không mở được kênh âm thanh.');
      ws.onclose = event => stop(session, event.code === 1013
        ? 'Loa đang bận hoặc thiết bị chưa sẵn sàng.'
        : 'Phiên âm thanh đã kết thúc.');
      session.deadline = setTimeout(() => stop(session, 'Thiết bị chưa sẵn sàng nhận âm thanh.'), 8000);
    } catch (error) {
      stop(session, error.message);
    }
  }

  return <section className="spaced"><h3>Nói trực tiếp đến loa</h3><p>Âm thanh truyền một chiều đến thiết bị. Tối đa 60 giây mỗi phiên.</p><Button disabled={disabled && status === 'idle'} kind={status === 'transmitting' ? 'critical' : 'secondary-btn'} onClick={status === 'idle' ? start : () => stop(active.current)}>{status === 'idle' ? 'Bắt đầu nói' : status === 'connecting' ? 'Đang kết nối — bấm để hủy' : 'Đang truyền — bấm để dừng'}</Button></section>;
}
