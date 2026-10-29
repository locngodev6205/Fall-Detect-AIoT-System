import React,{useEffect,useRef,useState} from 'react';
import {Microphone,Stop,ArrowCounterClockwise,Check} from '@phosphor-icons/react';
import {api} from './api';
import {Button} from './ui';
export function ReminderRecording({camera,canUpload,onSaved,onBusy}) {
  const [recording,setRecording]=useState(false),[requesting,setRequesting]=useState(false),[seconds,setSeconds]=useState(0),[blob,setBlob]=useState(null),[url,setUrl]=useState(''),[error,setError]=useState(''),[uploading,setUploading]=useState(false),[saved,setSaved]=useState(false);
  const recorder=useRef(),stream=useRef(),chunks=useRef([]),timer=useRef(),mounted=useRef(true),objectUrl=useRef(),request=useRef(),callbacks=useRef();callbacks.current={onSaved,onBusy};
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;clearInterval(timer.current);if(recorder.current?.state==='recording')recorder.current.stop();stream.current?.getTracks().forEach(track=>track.stop());if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);request.current?.abort();callbacks.current.onBusy(false);};},[camera]);
  function stop(){clearInterval(timer.current);if(recorder.current?.state==='recording')recorder.current.stop();}
  async function start(){
    setError('');setSaved(false);
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){setError('Trình duyệt chưa hỗ trợ ghi âm. Bạn có thể chọn file âm thanh đã có.');return;}
    const mime=['audio/webm','audio/ogg'].find(type=>MediaRecorder.isTypeSupported(type));
    if(!mime){setError('Trình duyệt chưa hỗ trợ định dạng ghi âm phù hợp. Hãy chọn file âm thanh đã có.');return;}
    callbacks.current.onBusy(true);setRequesting(true);
    try{
      const media=await navigator.mediaDevices.getUserMedia({audio:true});if(!mounted.current){media.getTracks().forEach(track=>track.stop());return;}stream.current=media;callbacks.current.onSaved('');setRequesting(false);
      if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);setUrl('');setBlob(null);setSeconds(0);chunks.current=[];
      recorder.current=new MediaRecorder(media,{mimeType:mime});
      recorder.current.ondataavailable=event=>{if(event.data.size)chunks.current.push(event.data);};
      recorder.current.onstop=()=>{clearInterval(timer.current);media.getTracks().forEach(track=>track.stop());if(!mounted.current)return;setRecording(false);callbacks.current.onBusy(false);const audio=new Blob(chunks.current,{type:mime});if(!audio.size){setError('Chưa thu được âm thanh. Vui lòng ghi lại.');return;}setBlob(audio);objectUrl.current=URL.createObjectURL(audio);setUrl(objectUrl.current);};
      recorder.current.start();setRecording(true);let elapsed=0;timer.current=setInterval(()=>{elapsed++;setSeconds(elapsed);if(elapsed>=120)stop();},1000);
    }catch(error){stream.current?.getTracks().forEach(track=>track.stop());if(!mounted.current)return;callbacks.current.onBusy(false);setRequesting(false);setError(error.name==='NotAllowedError'?'Bạn chưa cho phép dùng microphone. Hãy bật quyền microphone trong trình duyệt rồi thử lại.':error.name==='NotFoundError'?'Không tìm thấy microphone. Hãy kết nối microphone hoặc chọn file âm thanh.':'Không thể bắt đầu ghi âm. Hãy kiểm tra microphone và thử lại.');}
  }
  async function useRecording(){
    if(!blob)return;setUploading(true);setError('');callbacks.current.onBusy(true);const controller=new AbortController();request.current=controller;
    try{const asset=await api('/cameras/'+camera+'/assets',{method:'POST',body:blob,signal:controller.signal,headers:{'Content-Type':blob.type,'X-File-Name':encodeURIComponent('Lời nhắc ghi âm '+new Date().toLocaleString('vi-VN')+(blob.type.includes('ogg')?'.ogg':'.webm'))}});if(!mounted.current)return;callbacks.current.onSaved(asset.id);setSaved(true);}
    catch(error){if(mounted.current&&!controller.signal.aborted)setError(error.message);}
    finally{if(mounted.current){setUploading(false);callbacks.current.onBusy(false);}}
  }
  return <section className="reminder-recording"><strong><Microphone/>Ghi lời nhắc bằng giọng của bạn</strong><p>Ghi tối đa 2 phút, nghe lại rồi chọn dùng bản ghi.</p>{recording?<div className="recording-actions"><span role="status" className="recording-timer"><span className="dot"/>Đang ghi {String(Math.floor(seconds/60)).padStart(2,'0')}:{String(seconds%60).padStart(2,'0')}</span><Button kind="critical" onClick={stop}><Stop/>Dừng ghi</Button></div>:<Button kind="secondary-btn" disabled={uploading||requesting||!canUpload} onClick={start}>{blob?<ArrowCounterClockwise/>:<Microphone/>}{requesting?'Đang mở microphone…':blob?'Ghi lại':'Bắt đầu ghi âm'}</Button>}{url&&!recording&&<audio controls src={url} aria-label="Nghe lại bản ghi"/>}{blob&&!recording&&<Button kind={saved?'secondary-btn':''} disabled={uploading||saved} onClick={useRecording}><Check/>{uploading?'Đang lưu bản ghi…':saved?'Đã chọn bản ghi':'Dùng bản ghi này'}</Button>}{!canUpload&&<p>Bạn cần được chủ nhà cấp quyền âm thanh cho camera này để lưu bản ghi.</p>}{error&&<p role="alert">{error}</p>}</section>;
}
