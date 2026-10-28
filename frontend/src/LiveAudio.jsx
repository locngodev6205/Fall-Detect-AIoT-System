import React, { useEffect, useRef, useState } from 'react';
import { Button } from './ui';
import { useApp } from './context';
export function LiveAudio({ cameraId, disabled }) {
  const { notify } = useApp();const [status, setStatus] = useState('idle');
  const socket = useRef(), recorder = useRef(), stream = useRef(), deadline = useRef(), cancelled = useRef(false);
  function cleanup() {
    cancelled.current = true;clearTimeout(deadline.current);
    if (recorder.current?.state === 'recording') recorder.current.stop();
    stream.current?.getTracks().forEach(t => t.stop());
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ type: 'stop' }));
    socket.current?.close();setStatus('idle');
  }
  useEffect(() => () => cleanup(), [cameraId]);
  async function start() {
    setStatus('connecting');cancelled.current = false;
    try {
      const mime = ['audio/webm','audio/ogg'].find(type => window.MediaRecorder?.isTypeSupported(type));
      if (!mime) throw new Error('Trình duyệt chưa hỗ trợ truyền âm thanh.');
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (cancelled.current) { stream.current.getTracks().forEach(t => t.stop());return; }
      socket.current = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/audio/${cameraId}`);
      socket.current.onopen = () => socket.current.send(JSON.stringify({ mime }));
      socket.current.onmessage = event => {
        if (JSON.parse(event.data).type !== 'ready' || cancelled.current) return;
        recorder.current = new MediaRecorder(stream.current, { mimeType: mime });
        recorder.current.ondataavailable = event => {
          if (event.data.size && socket.current?.readyState === WebSocket.OPEN) {
            if (socket.current.bufferedAmount > 512 * 1024) { notify('Kết nối chậm, đã dừng để tránh phát lời nói trễ.');cleanup(); }
            else socket.current.send(event.data);
          }
        };
        recorder.current.start(250);setStatus('transmitting');deadline.current = setTimeout(cleanup, 60000);
      };
      socket.current.onerror = () => { notify('Không mở được kênh âm thanh. Kiểm tra thiết bị và quyền truy cập.');cleanup(); };
      socket.current.onclose = event => { if (!cancelled.current) notify(event.code === 1013 ? 'Loa chưa kết nối hoặc đang bận.' : 'Phiên âm thanh đã kết thúc.');cleanup(); };
      deadline.current = setTimeout(() => { if (recorder.current?.state !== 'recording') { notify('Thiết bị chưa sẵn sàng nhận âm thanh.');cleanup(); } }, 10000);
    } catch (error) { notify(error.message);cleanup(); }
  }
  return <section className="spaced"><h3>Nói trực tiếp đến loa</h3><p>Âm thanh truyền một chiều đến thiết bị. Tối đa 60 giây mỗi phiên; mất kết nối sẽ dừng và không phát lại.</p><Button disabled={disabled && status === 'idle'} kind={status === 'transmitting' ? 'critical' : 'secondary-btn'} onClick={status === 'idle' ? start : cleanup}>{status === 'idle' ? 'Bắt đầu nói' : status === 'connecting' ? 'Đang kết nối — bấm để hủy' : 'Đang truyền — bấm để dừng'}</Button></section>;
}
