import React, { useEffect, useRef, useState } from 'react';
import { api, dateTime, statusNames } from './api';
import { Badge, Button, Empty, Field, Heading, Modal } from './ui';
import { useApp, useResource, ResourceState } from './context';
import { LiveAudio } from './LiveAudio';

function ReminderForm({ initial, onClose }) {
  const { home, cameras, can, notify, reload } = useApp();
  const eligible = cameras.filter(c => can(c, 'schedules'));
  const [camera, setCamera] = useState(initial?.camera_id || eligible[0]?.id || ''), [source, setSource] = useState(initial?.source || 'tts'), [busy, setBusy] = useState(false);
  const [days, setDays] = useState(initial?.weekdays || [0,1,2,3,4,5,6]);
  const resources = useResource('/homes/' + home.id + '/assets');
  async function save(event) {
    event.preventDefault();setBusy(true);const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const body = { camera_id: camera, name: data.name, time: data.time, weekdays: data.once_date ? [] : days, once_date: data.once_date || null, timezone: home.timezone, enabled: data.enabled === 'on', source, text: source === 'tts' ? data.text : '', asset_id: source === 'audio' ? data.asset_id : null, volume: Number(data.volume), late_seconds: Number(data.late_seconds) };
      await api(initial ? '/reminders/' + initial.id : '/homes/' + home.id + '/reminders', { method: initial ? 'PUT' : 'POST', body });reload();notify('Đã lưu lịch. Chờ chuẩn bị file và thiết bị áp dụng cấu hình.');onClose();
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  }
  return <Modal title={initial ? 'Chỉnh sửa lời nhắc' : 'Tạo lời nhắc'} onClose={onClose}><form onSubmit={save}><Field label="Tên lịch" name="name" required defaultValue={initial?.name}/><Field label="Camera/loa đích"><select value={camera} onChange={e => setCamera(e.target.value)} required>{eligible.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><Field label="Giờ phát" name="time" type="time" required defaultValue={initial?.time || '07:00'}/><p>Múi giờ: {home.timezone}</p><div className="weekday-picker">{['T2','T3','T4','T5','T6','T7','CN'].map((label,i) => <label key={i}><input type="checkbox" checked={days.includes(i)} onChange={e => setDays(e.target.checked ? [...days,i] : days.filter(d => d !== i))}/>{label}</label>)}</div><Field label="Hoặc chỉ phát một lần vào ngày" type="date" name="once_date" defaultValue={initial?.once_date || ''}/><Field label="Nguồn âm thanh"><select value={source} onChange={e => setSource(e.target.value)}><option value="tts">Văn bản thành giọng nói</option><option value="audio">Âm thanh đã tải lên</option></select></Field>{source === 'tts' ? <Field label="Nội dung lời nhắc"><textarea name="text" required maxLength={3000} defaultValue={initial?.text} placeholder="Mẹ nhớ ăn sáng nhé."/></Field> : <Field label="Chọn file"><select name="asset_id" required defaultValue={initial?.asset_id || ''}><option value="">Chọn file thuộc camera đích</option>{(resources.data || []).filter(a => a.camera_id === camera && a.mime.startsWith('audio/') && a.status === 'ready').map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>}<Field label="Âm lượng (0–100)" name="volume" type="number" min="0" max="100" defaultValue={initial?.volume ?? 70}/><Field label="Cho phép phát trễ tối đa (giây, 0 = bỏ qua)" name="late_seconds" type="number" min="0" max="3600" defaultValue={initial?.late_seconds ?? 0}/><label className="checkbox"><input name="enabled" type="checkbox" defaultChecked={initial?.enabled ?? true}/>Bật lịch nhắc</label><Button type="submit" disabled={busy || !eligible.length}>{busy ? 'Đang lưu…' : 'Lưu lời nhắc'}</Button></form></Modal>;
}

export function Reminders({ initialTab = 'schedule' }) {
  const { home, reminders, cameras, can, tick, notify, reload } = useApp();
  const [tab, setTab] = useState(initialTab), [form, setForm] = useState(null);
  const assets = useResource('/homes/' + home.id + '/assets', tick);
  const executions = useResource('/homes/' + home.id + '/executions', tick);
  const canCreate = cameras.some(c => can(c, 'schedules'));
  async function remove(reminder) { if (!window.confirm('Xóa lịch nhắc ' + reminder.name + '?')) return;try { await api('/reminders/' + reminder.id, { method: 'DELETE' });reload();notify('Đã xóa lịch. Chờ thiết bị đồng bộ.'); } catch (e) { notify(e.message); } }
  return <><Heading title="Lời nhắc & âm thanh" text="Kết quả đã phát chỉ được ghi khi thiết bị gửi phản hồi." action={canCreate && <Button onClick={() => setForm({})}>Tạo lời nhắc</Button>}/><div className="tabs">{[['schedule','Lịch nhắc'],['library','Thư viện âm thanh'],['send','Phát đến thiết bị'],['history','Lịch sử phát']].map(([id,name]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{name}</button>)}</div>
    {tab === 'schedule' && <>{reminders.map(r => <article className="panel setting-row" key={r.id}><div><h2>{r.time} · {r.name}</h2><p>{cameras.find(c => c.id === r.camera_id)?.name} · {r.once_date || r.weekdays.map(d => ['T2','T3','T4','T5','T6','T7','CN'][d]).join(', ')}</p><small>{r.source === 'tts' ? r.text : 'Audio thu sẵn'} · {r.enabled ? 'Đang bật' : 'Đã tắt'}</small>{r.asset_error && <p role="alert">{r.asset_error}</p>}</div><Badge tone={r.asset_status === 'failed' ? 'red' : 'teal'}>{statusNames[r.asset_status] || 'Đang chuẩn bị'}</Badge>{can(cameras.find(c => c.id === r.camera_id), 'schedules') && <><Button kind="secondary-btn" onClick={() => setForm(r)}>Chỉnh sửa</Button><Button kind="ghost danger" onClick={() => remove(r)}>Xóa</Button></>}</article>)}{!reminders.length && <Empty title="Chưa có lời nhắc" text="Tạo lịch nhắc ăn sáng, uống thuốc hoặc sinh hoạt."/>}</>}
    {tab === 'library' && <ResourceState resource={assets}>{(assets.data || []).filter(a => a.mime.startsWith('audio/')).map(a => <article className="panel" key={a.id}><div className="section-heading"><h2>{a.name}</h2><Badge>{statusNames[a.status]}</Badge></div>{a.status === 'ready' && <audio controls preload="none" src={'/api/assets/' + a.id}/>}<p>{a.error}</p>{can(cameras.find(c => c.id === a.camera_id), 'audio') && <Button kind="ghost danger" onClick={async () => { if (!window.confirm('Xóa file âm thanh này?')) return;try { await api('/assets/' + a.id, { method: 'DELETE' });assets.reload(); } catch (e) { notify(e.message); } }}>Xóa âm thanh</Button>}</article>)}<p>Tải thêm file ở tab “Phát đến thiết bị”.</p></ResourceState>}
    {tab === 'send' && <SendAudio assets={assets.data || []} refreshAssets={assets.reload}/>}
    {tab === 'history' && <ResourceState resource={executions}>{(executions.data || []).map(e => <article className="panel" key={e.id}><strong>{statusNames[e.status]} · {dateTime(e.created_at)}</strong><p>Lần phát: {e.occurrence}</p><p>{e.detail}</p></article>)}{!executions.data?.length && <Empty title="Chưa có phản hồi phát từ thiết bị"/>}</ResourceState>}
    {form && <ReminderForm initial={form.id ? form : null} onClose={() => setForm(null)}/>}
  </>;
}

function SendAudio({ assets, refreshAssets }) {
  const { cameras, can, notify, tick } = useApp();const eligible = cameras.filter(c => can(c, 'audio'));
  const [chosen, setChosen] = useState(''), [asset, setAsset] = useState(''), [busy, setBusy] = useState(false), [recording, setRecording] = useState(false);
  const id = eligible.some(c => c.id === chosen) ? chosen : eligible[0]?.id;
  const recorder = useRef(), stream = useRef(), chunks = useRef([]);
  const commands = useResource(id ? '/cameras/' + id + '/commands' : null, tick);
  useEffect(() => () => { if (recorder.current?.state === 'recording') recorder.current.stop();stream.current?.getTracks().forEach(t => t.stop()); }, []);
  async function upload(file, name) {
    if (!id || !file) return;
    setBusy(true);
    try { const result = await api('/cameras/' + id + '/assets', { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'audio/wav', 'X-File-Name': encodeURIComponent(name || file.name || 'Lời nhắn.webm') } });setAsset(result.id);refreshAssets();notify('Đã lưu âm thanh trên backend. Chưa phát đến thiết bị.'); }
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
    try { await api('/cameras/' + id + '/commands', { method: 'POST', body: { kind, asset_id: kind === 'play_audio' ? asset : null, volume: 70, ttl_seconds: 60, idempotency_key: crypto.randomUUID() } });commands.reload();notify('Đã xếp lệnh, chờ thiết bị nhận. Lệnh sẽ hết hạn sau 60 giây.'); } catch (e) { notify(e.message); }
  }
  if (!eligible.length) return <Empty title="Chưa có camera được cấp quyền phát âm thanh"/>;
  return <><section className="panel"><Field label="Camera/loa đích"><select value={id} onChange={e => { setChosen(e.target.value);setAsset(''); }} disabled={recording}>{eligible.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field><Field label="Tải file âm thanh"><input type="file" accept="audio/wav,audio/mpeg,audio/webm,audio/ogg" disabled={busy || recording} onChange={e => upload(e.target.files?.[0])}/></Field><Button kind="secondary-btn" disabled={busy} onClick={record}>{recording ? 'Dừng ghi và lưu lời nhắn' : 'Ghi âm lời nhắn'}</Button><p>Ghi âm dùng microphone thật sau khi bạn cho phép. Đây là lời nhắn thu xong rồi gửi, chưa phải truyền giọng nói trực tiếp.</p><Field label="Âm thanh đã lưu"><select value={asset} onChange={e => setAsset(e.target.value)}><option value="">Chọn âm thanh</option>{assets.filter(a => a.camera_id === id && a.mime.startsWith('audio/') && a.status === 'ready').map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>{asset && <audio controls src={'/api/assets/' + asset}/>}<div className="actions"><Button disabled={!asset || busy || recording} onClick={() => send()}>Gửi lệnh phát</Button><Button kind="secondary-btn" onClick={() => send('test_speaker')}>Yêu cầu thử loa</Button></div><LiveAudio cameraId={id} disabled={recording || busy}/></section><section className="panel spaced"><h2>Lệnh gần đây</h2><ResourceState resource={commands}>{(commands.data || []).map(c => <div className="setting-row" key={c.id}><span>{c.kind} · {dateTime(c.created_at)}<small>{c.result}</small></span><Badge tone={c.status === 'failed' ? 'red' : 'teal'}>{statusNames[c.status]}</Badge></div>)}</ResourceState></section></>;
}
