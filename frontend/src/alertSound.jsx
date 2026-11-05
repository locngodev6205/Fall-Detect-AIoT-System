import React, {useEffect, useRef, useState} from 'react';
import {SpeakerHigh} from '@phosphor-icons/react';

function closeAudio(context) {
  try { if (context && context.state !== 'closed') Promise.resolve(context.close()).catch(() => {}); }
  catch { /* The visual alert remains available if audio cleanup fails. */ }
}

export function useAlertSound(userId) {
  const contextRef=useRef(null), enabledRef=useRef(false), generationRef=useRef(0);
  const [enabled,setEnabled]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState('');
  function disable(message='') {
    generationRef.current++;enabledRef.current=false;
    closeAudio(contextRef.current);contextRef.current=null;
    setEnabled(false);setBusy(false);setError(message);
  }
  useEffect(() => {
    disable();
    return () => {
      generationRef.current++;enabledRef.current=false;
      closeAudio(contextRef.current);contextRef.current=null;
    };
  },[userId]);
  async function toggle() {
    if (enabledRef.current) { disable();return; }
    const generation=++generationRef.current;
    setBusy(true);setError('');
    let context,timer;
    try {
      const AudioContext=window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('unsupported');
      // Construct/resume synchronously from the user's click, never from an alert.
      context=new AudioContext();contextRef.current=context;
      await Promise.race([context.resume(),new Promise((_,reject) => { timer=setTimeout(() => reject(new Error('blocked')),3000); })]);
      if (generation !== generationRef.current) { closeAudio(context);return; }
      if (context.state !== 'running') throw new Error('blocked');
      enabledRef.current=true;setEnabled(true);setBusy(false);
    } catch {
      closeAudio(context);
      if (generation === generationRef.current) disable('Chưa bật được âm báo. Hãy kiểm tra quyền âm thanh của trình duyệt rồi bật lại.');
    } finally { clearTimeout(timer); }
  }
  function play() {
    if (!enabledRef.current) return;
    const context=contextRef.current;
    if (!context || context.state !== 'running') {
      disable('Trình duyệt đã tạm dừng âm báo. Bật lại để tiếp tục nghe.');return;
    }
    try {
      const tone=context.createOscillator(), volume=context.createGain(), now=context.currentTime;
      tone.type='sine';tone.frequency.setValueAtTime(880,now);tone.frequency.setValueAtTime(660,now+0.14);
      volume.gain.setValueAtTime(0,now);volume.gain.linearRampToValueAtTime(0.08,now+0.02);
      volume.gain.linearRampToValueAtTime(0,now+0.32);
      tone.connect(volume);volume.connect(context.destination);tone.start(now);tone.stop(now+0.34);
    } catch { disable('Không phát được âm báo. Bạn có thể bật lại để thử.'); }
  }
  return {enabled,busy,error,toggle,play};
}

export function AlertSoundControl({sound}) {
  return <div className="alert-sound-control"><label><SpeakerHigh aria-hidden="true"/><span><strong>Âm báo cảnh báo mới</strong><small>Chỉ bật trong tab này.</small></span><input type="checkbox" role="switch" aria-label="Âm báo cảnh báo mới" checked={sound.enabled} disabled={sound.busy} onChange={sound.toggle}/></label>{sound.error&&<p role="status">{sound.error}</p>}</div>;
}
