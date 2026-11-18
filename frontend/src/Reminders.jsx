import React, { useEffect, useRef, useState } from 'react';
import { Clock, SpeakerHigh, Play, Trash, WarningCircle } from '@phosphor-icons/react';
import { api, dateTime, statusNames } from './api';
import { Badge, Button, Empty, Field, Heading, Modal, PagedList } from './ui';
import { useApp, useResource, ResourceState } from './context';
import { LiveAudio } from './LiveAudio';
import {AudioPicker} from './AudioPicker';
import {useServerPage,ServerPager} from './serverPaging';
import { ReminderRecording } from './ReminderRecording';
import { BluetoothSpeakerCard } from './BluetoothSpeakerCard';

function ReminderPreview({camera,source,text,asset,volume}) {
  const [url,setUrl]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const request=useRef(),objectUrl=useRef(),player=useRef();
  useEffect(()=>{request.current?.abort();player.current?.pause();if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);objectUrl.current=null;setUrl('');setError('');setLoading(false);return()=>{request.current?.abort();player.current?.pause();if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);};},[camera,source,text,asset]);
  useEffect(()=>{if(player.current)player.current.volume=Math.max(0,Math.min(1,volume/100));},[volume,url,asset,source]);
  useEffect(()=>{if(source==='tts'&&url)player.current?.play().catch(()=>{});},[url,source]);
  async function preview(){
    request.current?.abort();const controller=new AbortController();request.current=controller;setLoading(true);setError('');
    try{const blob=await api('/cameras/'+camera+'/tts-preview',{method:'POST',body:{text},responseType:'blob',signal:controller.signal});if(controller.signal.aborted)return;if(objectUrl.current)URL.revokeObjectURL(objectUrl.current);objectUrl.current=URL.createObjectURL(blob);setUrl(objectUrl.current);}
    catch(error){if(!controller.signal.aborted)setError(error.message);}finally{if(!controller.signal.aborted)setLoading(false);}
  }
  const audio=source==='audio'?(asset?'/api/assets/'+asset:''):url;
  return <div className="reminder-preview"><strong><SpeakerHigh/>Nghe thử âm thanh</strong><p>Phát trên thiết bị bạn đang sử dụng.</p>{source==='tts'&&<Button kind="secondary-btn" disabled={!camera||!text.trim()||loading} onClick={preview}><Play/>{loading?'Đang tạo giọng nói…':url?'Tạo lại bản nghe thử':'Phát thử lời nhắc'}</Button>}{source==='audio'&&!asset&&<small>Chọn file âm thanh để nghe thử.</small>}{audio&&<audio ref={player} key={audio} controls preload="metadata" src={audio} aria-label="Phát thử lời nhắc" onError={()=>setError('Không thể tải âm thanh. Hãy chọn lại file hoặc thử lại.')}/>} {error&&<p role="alert">{error}</p>}</div>;
}

function ReminderForm({ initial, onClose }) {
  const { home, cameras, can, notify, reload } = useApp();
  const eligible = cameras.filter(c => can(c, 'schedules'));
  const [camera, setCamera] = useState(initial?.camera_id || eligible[0]?.id || ''), [source, setSource] = useState(initial?.source || 'tts'), [recordBusy,setRecordBusy]=useState(false), [busy, setBusy] = useState(false);
  const [text,setText]=useState(initial?.text||''),[asset,setAsset]=useState(initial?.asset_id||''),[volume,setVolume]=useState(initial?.volume??70),[assetReady,setAssetReady]=useState(false);
  const [days, setDays] = useState(initial?.weekdays || [0,1,2,3,4,5,6]);
  const recordingRef=useRef(null),[recordReady,setRecordReady]=useState(false);
  const savedAudioReady=initial?.source==='audio'&&initial.asset_status==='ready'&&asset===initial.asset_id;
  const audioReady=source==='record'?recordReady:!!asset&&(assetReady||savedAudioReady);
  function chooseAsset(id) { setAsset(id);setAssetReady(false);setRecordReady(false); }
  async function save(event) {
    event.preventDefault();setBusy(true);const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const selectedAsset=source==='record'?await recordingRef.current.upload():asset;
      const body = { camera_id: camera, name: data.name, time: data.time, weekdays: data.once_date ? [] : days, once_date: data.once_date || null, timezone: home.timezone, enabled: data.enabled === 'on', source:source==='tts'?'tts':'audio', text: source === 'tts' ? data.text : '', asset_id: source === 'tts' ? null : selectedAsset, volume: Number(data.volume), late_seconds: Number(data.late_seconds) };
      await api(initial ? '/reminders/' + initial.id : '/homes/' + home.id + '/reminders', { method: initial ? 'PUT' : 'POST', body });reload();notify('Đã lưu lịch. Chờ chuẩn bị file và thiết bị áp dụng cấu hình.');onClose();
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  }
  return <Modal title={initial ? 'Chỉnh sửa lời nhắc' : 'Tạo lời nhắc'} onClose={onClose}><form onSubmit={save}><Field label="Tên lịch" name="name" required defaultValue={initial?.name}/><Field label="Camera/loa đích"><select value={camera} onChange={e => {setCamera(e.target.value);chooseAsset('');}} disabled={recordBusy||!!initial} required>{eligible.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><Field label="Giờ phát" name="time" type="time" required defaultValue={initial?.time || '07:00'}/><p>Múi giờ: {home.timezone}</p><div className="weekday-picker">{['T2','T3','T4','T5','T6','T7','CN'].map((label,i) => <label key={i}><input type="checkbox" checked={days.includes(i)} onChange={e => setDays(e.target.checked ? [...days,i] : days.filter(d => d !== i))}/>{label}</label>)}</div><Field label="Hoặc chỉ phát một lần vào ngày" type="date" name="once_date" defaultValue={initial?.once_date || ''}/><Field label="Nguồn âm thanh"><select value={source} disabled={recordBusy} onChange={e => {setSource(e.target.value);chooseAsset('');}}><option value="tts">Văn bản thành giọng nói</option><option value="audio">Âm thanh đã tải lên</option><option value="record">Ghi âm trực tiếp</option></select></Field>{source === 'tts' ? <Field label="Nội dung lời nhắc"><textarea name="text" required maxLength={3000} value={text} onChange={e=>setText(e.target.value)} placeholder="Mẹ nhớ ăn sáng nhé."/></Field> : source==='record'?<ReminderRecording ref={recordingRef} key={camera} camera={camera} canUpload={can(cameras.find(item=>item.id===camera),'audio')} onBusy={setRecordBusy} onReady={setRecordReady}/> : <AudioPicker key={camera} camera={camera} value={asset} onChange={chooseAsset} onReady={setAssetReady} upload={can(cameras.find(c=>c.id===camera),'audio')}/>}{source!=='record'&&<ReminderPreview camera={camera} source={source} text={text} asset={asset} volume={volume}/>}<Field label="Âm lượng (0–100)" name="volume" type="number" min="0" max="100" value={volume} onChange={e=>setVolume(Number(e.target.value))}/><Field label="Cho phép phát trễ tối đa (giây, 0 = bỏ qua)" name="late_seconds" type="number" min="0" max="3600" defaultValue={initial?.late_seconds ?? 0}/><label className="checkbox"><input name="enabled" type="checkbox" defaultChecked={initial?.enabled ?? true}/>Bật lịch nhắc</label><Button type="submit" disabled={busy || recordBusy || !eligible.length || (source!=='tts'&&!audioReady)}>{busy ? 'Đang lưu…' : initial ? 'Lưu thay đổi' : 'Lưu lời nhắc'}</Button></form></Modal>;
}

export function Reminders({ initialTab = 'schedule' }) {
  const { home, reminders, cameras, can, tick, notify, confirm, reload } = useApp();
  const [tab, setTab] = useState(initialTab), [form, setForm] = useState(null), [retrying,setRetrying]=useState({});
  const [deleteAudio,setDeleteAudio]=useState(null),[deletingAudio,setDeletingAudio]=useState(false),[openingDeleteId,setOpeningDeleteId]=useState('');
  const [sendCameraId,setSendCameraId]=useState('');
  const [search,setSearch]=useState(''),[query,setQuery]=useState(''),[cameraFilter,setCameraFilter]=useState(''),[statusFilter,setStatusFilter]=useState(''),[rename,setRename]=useState(null),[historyCamera,setHistoryCamera]=useState(''),[historyStatus,setHistoryStatus]=useState('');
  useEffect(()=>{const timer=setTimeout(()=>setQuery(search.trim()),250);return()=>clearTimeout(timer);},[search]);
  const assets=useServerPage(tab==='library'?`/homes/${home.id}/assets?audio_only=true&q=${encodeURIComponent(query)}${cameraFilter?'&camera_id='+cameraFilter:''}${statusFilter?'&status='+statusFilter:''}`:null,tick);
  const executions=useServerPage(tab==='history'?`/homes/${home.id}/executions?${new URLSearchParams({...historyCamera&&{camera_id:historyCamera},...historyStatus&&{status:historyStatus}})}`:null,tick);
  useEffect(()=>{setSearch('');setQuery('');setCameraFilter('');setStatusFilter('');setSendCameraId('');setForm(null);setRename(null);setDeleteAudio(null);},[home.id]);
  const canCreate = cameras.some(c => can(c, 'schedules'));
  async function remove(reminder) { if (!await confirm({title:'Xóa lịch nhắc?',message:'Lịch '+reminder.name+' sẽ được xóa.',confirmLabel:'Xóa lịch nhắc',tone:'danger'})) return;try { await api('/reminders/' + reminder.id, { method: 'DELETE' });reload();notify('Đã xóa lịch. Chờ thiết bị đồng bộ.'); } catch (e) { notify(e.message); } }
  async function showDeleteAudio(asset) {
    setOpeningDeleteId(asset.id);
    try { setDeleteAudio(await api('/assets/'+asset.id+'/metadata')); }
    catch(error) { notify(error.message); }
    finally { setOpeningDeleteId(''); }
  }
  async function confirmDeleteAudio() {
    if (!deleteAudio || deletingAudio) return;
    setDeletingAudio(true);
    try {
      const result=await api('/assets/'+deleteAudio.id,{method:'DELETE',body:{expected_reminder_ids:deleteAudio.used_by.map(reminder=>reminder.id)}});
      setDeleteAudio(null);assets.reload();reload();notify(result.deleted_reminder_count?`Đã xóa ${result.deleted_reminder_count} lời nhắc và xếp xóa âm thanh. Chờ thiết bị đồng bộ.`:'Đã xếp xóa âm thanh khỏi kho lưu trữ.');
    } catch(error) {
      if(error.status===409){try {setDeleteAudio(await api('/assets/'+deleteAudio.id+'/metadata'));assets.reload();} catch {setDeleteAudio(null);} }
      notify(error.message);
    } finally {setDeletingAudio(false);}
  }
  const audioCameras=cameras.filter(c=>can(c,'audio'));
  const btCameraId=tab==='send'
    ? audioCameras.find(c=>c.id===sendCameraId)?.id||audioCameras[0]?.id
    : (tab==='library'&&cameraFilter)||audioCameras[0]?.id||cameras[0]?.id;
  const canControlBt=can(cameras.find(c=>c.id===btCameraId),'audio');
  return <><Heading title="Lời nhắc & âm thanh" text="Kết quả đã phát chỉ được ghi khi thiết bị gửi phản hồi." action={canCreate && <Button onClick={() => setForm({})}>Tạo lời nhắc</Button>}/>{btCameraId && <BluetoothSpeakerCard cameraId={btCameraId} canControl={canControlBt}/>}<div className="tabs">{[['schedule','Lịch nhắc'],['library','Thư viện âm thanh'],['send','Phát đến thiết bị'],['history','Lịch sử phát']].map(([id,name]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{name}</button>)}</div>
    {tab === 'schedule' && <>{<PagedList items={reminders} label="lịch nhắc" resetKey={home.id}>{r => <article className="panel setting-row reminder-item" key={r.id}><div><h2>{r.time} · {r.name}</h2><p>{cameras.find(c => c.id === r.camera_id)?.name} · {r.once_date || r.weekdays.map(d => ['T2','T3','T4','T5','T6','T7','CN'][d]).join(', ')}</p><small>{r.source === 'tts' ? r.text : 'Audio thu sẵn'} · {r.enabled ? 'Đang bật' : 'Đã tắt'}</small>{r.asset_error && <p role="alert">{r.asset_error}</p>}</div><Badge tone={r.asset_status === 'failed' ? 'red' : 'teal'}>{statusNames[r.asset_status] || 'Đang chuẩn bị'}</Badge>{can(cameras.find(c => c.id === r.camera_id), 'schedules') && <><Button kind="secondary-btn" onClick={() => setForm(r)}>Chỉnh sửa</Button><Button kind="ghost danger" onClick={() => remove(r)}>Xóa</Button></>}</article>}</PagedList>}{!reminders.length && <Empty icon={Clock} title="Chưa có lời nhắc" text="Tạo lịch nhắc ăn sáng, uống thuốc hoặc sinh hoạt."/>}</>}
    {tab === 'library' && <><div className="filters-grid"><Field label="Tìm âm thanh"><input type="search" placeholder="Tên file…" value={search} onChange={e=>setSearch(e.target.value)}/></Field><Field label="Camera"><select value={cameraFilter} onChange={e=>setCameraFilter(e.target.value)}><option value="">Tất cả camera</option>{cameras.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><Field label="Trạng thái"><select value={statusFilter} onChange={e=>setStatusFilter(e.target.value)}><option value="">Tất cả trạng thái</option>{['ready','uploading','processing','failed','expired','deleted'].map(status=><option key={status} value={status}>{statusNames[status]||status}</option>)}</select></Field></div><ResourceState resource={assets}>{assets.items.filter(a => !a.mime || a.mime.startsWith('audio/')).map(a => {
      const camera = cameras.find(c => c.id === a.camera_id);
      return <article className="panel audio-library-card" key={a.id}>
        <div className="audio-library-info"><h2>{a.name}</h2><p>{camera?.name || 'Camera không còn trong nhà'}</p><small>{dateTime(a.created_at)}</small>{!!a.used_count&&<p className="audio-usage">Đang dùng: {a.used_by.map(r=>r.name+(r.enabled?'':' (tắt)')).join(', ')}</p>}</div>
        <Badge>{statusNames[a.status]}</Badge>
        {a.status === 'ready' && (can(camera, 'audio') || can(camera, 'schedules')) ? <audio controls preload="none" aria-label={'Nghe ' + a.name} src={'/api/assets/' + a.id}/> : <span className="audio-library-state">{a.error || 'Âm thanh chưa sẵn sàng'}</span>}
        <div className="audio-library-actions">{a.status==='failed'&&can(camera,'manage')&&<Button kind="secondary-btn audio-library-retry" disabled={retrying[a.id]} onClick={async()=>{setRetrying(previous=>({...previous,[a.id]:true}));try{await api('/assets/'+a.id+'/retry',{method:'POST'});assets.reload();reload();notify(a.kind==='tts'?'Đã xếp lại yêu cầu tạo âm thanh.':'Đã xếp lại yêu cầu tải âm thanh lên.');}catch(error){notify(error.message);}finally{setRetrying(previous=>({...previous,[a.id]:false}));}}}>{retrying[a.id]?'Đang xếp…':a.kind==='tts'?'Thử tạo lại':'Thử tải lại'}</Button>}{can(camera,'manage')&&!['deleted','expired','deleting'].includes(a.status)&&<Button kind="secondary-btn" onClick={()=>setRename(a)}>Đổi tên</Button>}{can(camera, 'manage') && <Button disabled={openingDeleteId===a.id||['deleted','expired','deleting'].includes(a.status)} kind="ghost danger audio-library-delete" aria-label={'Xóa ' + a.name} onClick={()=>showDeleteAudio(a)}><Trash aria-hidden="true"/>{openingDeleteId===a.id?'Đang kiểm tra…':'Xóa'}</Button>}</div>
        {a.error && <p className="audio-library-error" role="alert">{a.error}</p>}
      </article>;
    })}{!assets.items.filter(a => !a.mime || a.mime.startsWith('audio/')).length&&<Empty icon={SpeakerHigh} title="Chưa có âm thanh phù hợp"/>}<ServerPager resource={assets} label="âm thanh"/></ResourceState></>}
    {tab === 'send' && <SendAudio chosen={sendCameraId} onChosen={setSendCameraId}/>}
    {tab === 'history' && <><div className="filters-grid"><Field label="Camera"><select value={historyCamera} onChange={e=>setHistoryCamera(e.target.value)}><option value="">Tất cả camera</option>{cameras.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><Field label="Kết quả phát"><select value={historyStatus} onChange={e=>setHistoryStatus(e.target.value)}><option value="">Tất cả</option>{['played','failed','skipped'].map(s=><option key={s} value={s}>{statusNames[s]||s}</option>)}</select></Field></div><ResourceState resource={executions}>{executions.items.map(e=><article className="panel" key={e.id}><strong>{statusNames[e.status]} · {dateTime(e.created_at)}</strong><p>{cameras.find(c=>c.id===e.camera_id)?.name} · Theo lịch: {dateTime(e.scheduled_at||e.created_at)}</p><p>{e.detail}</p></article>)}{!executions.items.length&&<Empty title="Chưa có phản hồi phát phù hợp"/>}<ServerPager resource={executions} label="lịch sử phát"/></ResourceState></>}
    {rename&&<Modal title="Đổi tên âm thanh" onClose={()=>setRename(null)}><form onSubmit={async e=>{e.preventDefault();try{await api('/assets/'+rename.id,{method:'PATCH',body:{name:new FormData(e.currentTarget).get('name')}});setRename(null);assets.reload();notify('Đã đổi tên âm thanh.');}catch(error){notify(error.message);}}}><Field label="Tên âm thanh" name="name" required maxLength={120} defaultValue={rename.name}/><Button type="submit">Lưu tên</Button></form></Modal>}
    {deleteAudio&&<Modal title={deleteAudio.used_count?'Xóa âm thanh và lời nhắc?':'Xóa âm thanh?'} className="audio-delete-modal" onClose={()=>{if(!deletingAudio)setDeleteAudio(null);}}>
      <div className="audio-delete-warning"><span className="audio-delete-icon"><WarningCircle size={34} weight="duotone" aria-hidden="true"/></span><strong>{deleteAudio.name}</strong><p>{deleteAudio.used_count?`Xóa âm thanh này sẽ xóa cả ${deleteAudio.used_count} lời nhắc đang sử dụng nó, kể cả lời nhắc đã tắt.`:'Âm thanh này sẽ được xóa khỏi thư viện và kho lưu trữ.'}</p></div>
      {!!deleteAudio.used_count&&<div className="audio-delete-affected"><strong>Các lời nhắc sẽ bị xóa</strong><ul>{deleteAudio.used_by.map(reminder=><li key={reminder.id}>{reminder.name}{!reminder.enabled&&<span> · Đang tắt</span>}</li>)}</ul></div>}
      <p className="audio-delete-note">Lịch sử phát vẫn được giữ. File sẽ được xóa khỏi Cloudinary sau khi hệ thống xử lý yêu cầu.</p>
      <div className="audio-delete-actions"><Button kind="secondary-btn" disabled={deletingAudio} onClick={()=>setDeleteAudio(null)}>Hủy</Button><Button kind="danger-confirm" disabled={deletingAudio} onClick={confirmDeleteAudio}>{deletingAudio?'Đang xóa…':deleteAudio.used_count?'Xóa âm thanh và lời nhắc':'Xóa âm thanh'}</Button></div>
    </Modal>}
    {form && <ReminderForm initial={form.id ? form : null} onClose={() => setForm(null)}/>}
  </>;
}

function SendAudio({chosen,onChosen}) {
  const { cameras, can, notify, tick } = useApp();const eligible = cameras.filter(c => can(c, 'audio'));
  const [asset, setAsset] = useState(''), [busy, setBusy] = useState(false), [recording, setRecording] = useState(false),[assetReady,setAssetReady]=useState(false);
  const id = eligible.some(c => c.id === chosen) ? chosen : eligible[0]?.id;
  const recorder = useRef(), stream = useRef(), chunks = useRef([]);
  const commands = useResource(id ? '/cameras/' + id + '/commands' : null, tick);
  useEffect(() => () => { if (recorder.current?.state === 'recording') recorder.current.stop();stream.current?.getTracks().forEach(t => t.stop()); }, []);
  function chooseAsset(id) { setAsset(id);setAssetReady(false); }
  async function upload(file, name) {
    if (!id || !file) return;
    setBusy(true);
    try { const result = await api('/cameras/' + id + '/assets', { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'audio/wav', 'X-File-Name': encodeURIComponent(name || file.name || 'Lời nhắn.webm') } });chooseAsset(result.id);notify('Đã lưu âm thanh trên backend. Chưa phát đến thiết bị.'); }
    catch (e) { notify(e.message); } finally { setBusy(false); }
  }
  async function record() {
    if (recording) { recorder.current.stop();setRecording(false);return; }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ['audio/webm','audio/ogg'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mime) { stream.current.getTracks().forEach(t => t.stop());throw new Error('Trình duyệt chưa hỗ trợ định dạng ghi âm của hệ thống.'); }
      recorder.current = new MediaRecorder(stream.current, { mimeType: mime });chunks.current = [];
      recorder.current.ondataavailable = e => { if (e.data.size) chunks.current.push(e.data); };
      recorder.current.onstop = () => { stream.current.getTracks().forEach(t => t.stop());upload(new Blob(chunks.current, { type: mime }), 'Lời nhắn ' + new Date().toLocaleTimeString('vi-VN')); };
      recorder.current.start();setRecording(true);
    } catch (e) { notify(e.message); }
  }
  async function send(kind = 'play_audio') {
    if (busy || recording || !id) return;
    if (kind==='play_audio'&&!asset) {notify('Hãy chọn hoặc tải một file âm thanh trước khi gửi lệnh phát.');return;}
    if (kind==='play_audio'&&!assetReady) {notify('File âm thanh chưa sẵn sàng. Hãy chờ xử lý xong rồi thử lại.');return;}
    setBusy(true);
    try { await api('/cameras/' + id + '/commands', { method: 'POST', body: { kind, asset_id: kind === 'play_audio' ? asset : null, volume: 70, ttl_seconds: 60, idempotency_key: crypto.randomUUID() } });commands.reload();notify('Đã xếp lệnh, chờ thiết bị nhận. Lệnh sẽ hết hạn sau 60 giây.'); }
    catch (e) { notify(e.message); }
    finally { setBusy(false); }
  }
  if (!eligible.length) return <Empty icon={SpeakerHigh} title="Chưa có camera được cấp quyền phát âm thanh"/>;
  return <><section className="panel"><Field label="Camera/loa đích"><select value={id} onChange={e => { onChosen(e.target.value);chooseAsset(''); }} disabled={recording}>{eligible.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><Field label="Tải file âm thanh"><input type="file" accept="audio/wav,audio/mpeg,audio/webm,audio/ogg" disabled={busy || recording} onChange={e => upload(e.target.files?.[0])}/></Field><Button kind="secondary-btn" disabled={busy} onClick={record}>{recording ? 'Dừng ghi và lưu lời nhắn' : 'Ghi âm lời nhắn'}</Button><p>Cho phép truy cập microphone để ghi âm lời nhắn, sau đó gửi đến thiết bị.</p><AudioPicker key={id} camera={id} value={asset} onChange={chooseAsset} onReady={setAssetReady}/>{asset && <audio controls src={'/api/assets/' + asset}/>}{!cameras.find(camera => camera.id === id)?.online && <div className="notice">Chưa nhận tín hiệu mới từ thiết bị. Bạn vẫn có thể chuẩn bị âm thanh và gửi lệnh; thiết bị cần nhận lệnh trước khi hết hạn.</div>}<div className="actions"><Button disabled={busy || recording} onClick={() => send()}>Gửi lệnh phát</Button><Button kind="secondary-btn" disabled={busy || recording} onClick={() => send('test_speaker')}>Yêu cầu thử loa</Button></div><LiveAudio cameraId={id} disabled={recording || busy}/></section><section className="panel spaced"><h2>Lệnh gần đây</h2><ResourceState resource={commands}>{<PagedList items={commands.data || []} label="lệnh" resetKey={id}>{c => <div className="setting-row" key={c.id}><span>{c.kind} · {dateTime(c.created_at)}<small>{typeof c.result === 'string' ? c.result : c.result?.detail || ''}</small></span><Badge tone={c.status === 'failed' ? 'red' : 'teal'}>{statusNames[c.status]}</Badge></div>}</PagedList>}</ResourceState></section></>;
}
