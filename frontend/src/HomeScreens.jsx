import React, { useState } from 'react';
import { Plus, VideoCamera, Thermometer, Drop, Leaf, WarningCircle, Clock, SpeakerHigh } from '@phosphor-icons/react';
import { api, go, roleNames, statusNames, eventNames, dateTime } from './api';
import { Badge, Button, CameraImage, Empty, Field, Heading, Modal } from './ui';
import { useApp, useResource, ResourceState } from './context';

export function Homes() {
  const { homes, selectHome, reloadHomes, notify } = useApp();
  const [form, setForm] = useState(false), [busy, setBusy] = useState(false);
  async function create(event) {
    event.preventDefault();setBusy(true);
    try { const home = await api('/homes', { method: 'POST', body: Object.fromEntries(new FormData(event.currentTarget)) });await reloadHomes();selectHome(home.id);setForm(false);go('/setup'); }
    catch (error) { notify(error.message); } finally { setBusy(false); }
  }
  return <><Heading title="Những ngôi nhà của bạn" text="Chọn cụm camera bạn sở hữu hoặc được người thân chia sẻ." action={<Button onClick={() => setForm(true)}><Plus/>Tạo nhà mới</Button>}/>
    {!homes.length ? <Empty title="Chưa có nhà nào" text="Tạo một nhà mới, hoặc mở liên kết lời mời từ người thân."/> : <div className="three-grid">{homes.map(home => <article className="panel" key={home.id}><h2>{home.name}</h2><Badge>{roleNames[home.role]}</Badge><p>{home.timezone}</p><Button onClick={() => { selectHome(home.id);go('/overview'); }}>Mở nhà</Button></article>)}</div>}
    {form && <Modal title="Tạo nhà mới" onClose={() => setForm(false)}><form onSubmit={create}><Field label="Tên nhà" name="name" required maxLength={120}/><Field label="Múi giờ" name="timezone" defaultValue="Asia/Ho_Chi_Minh" required/><Button type="submit" disabled={busy}>Tạo nhà</Button></form></Modal>}
  </>;
}

export function Setup() {
  const { home, rooms, cameras, reload, notify } = useApp();
  const [busy, setBusy] = useState(false);
  if (home.role !== 'owner') return <Empty title="Chỉ chủ nhà được thêm thiết bị"/>;
  async function room(event) {
    event.preventDefault();const form = event.currentTarget;
    try { await api(`/homes/${home.id}/rooms`, { method: 'POST', body: { name: new FormData(form).get('name') } });form.reset();reload();notify('Đã tạo phòng.'); } catch (e) { notify(e.message); }
  }
  async function claim(event) {
    event.preventDefault();setBusy(true);
    try { await api(`/homes/${home.id}/cameras/claim`, { method: 'POST', body: Object.fromEntries(new FormData(event.currentTarget)) });reload();go('/devices');notify('Đã đăng ký camera. Đang chờ thiết bị kết nối.'); }
    catch (e) { notify(e.message); } finally { setBusy(false); }
  }
  return <><Heading title="Kết nối camera với nhà" text="Mã ghép nối chỉ dùng một lần và có thời hạn. Thiết bị đang thuộc nhà khác không thể được nhận lại bằng mã cũ."/>
    <div className="two-grid"><form className="panel" onSubmit={room}><h2>1. Tạo phòng</h2><Field label="Tên phòng" name="name" required maxLength={120}/><Button type="submit">Thêm phòng</Button><p>{rooms.map(r => r.name).join(' · ') || 'Chưa có phòng'}</p></form>
    <form className="panel" onSubmit={claim}><h2>2. Ghép nối thiết bị</h2><Field label="Mã ghép nối từ thiết bị" name="code" required minLength={8} autoComplete="off"/><Field label="Tên camera" name="name" required maxLength={120}/><Field label="Phòng"><select name="room_id" required defaultValue=""><option value="" disabled>Chọn phòng</option>{rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field><Button type="submit" disabled={busy || !rooms.length}>{busy ? 'Đang ghép nối…' : 'Đăng ký camera'}</Button></form></div>
    <div className="notice">Sau khi ghép nối, kiểm tra hình ảnh và thiết lập vùng nghỉ ngơi trong trang camera. Chưa kết nối không có nghĩa là đang giám sát.</div>
  </>;
}

export function Overview() {
  const { user, home, cameras, events, reminders } = useApp();
  const active = events.filter(e => ['OPEN','ACKNOWLEDGED'].includes(e.status));
  const next = reminders.filter(r => r.enabled).sort((a,b) => a.time.localeCompare(b.time));
  return <><Heading title={`Xin chào, ${user.name}.`} text={`${home.name} · ${cameras.filter(c => c.online).length}/${cameras.length} thiết bị đang kết nối`}/>
    {active.length ? <div className="alert-banner"><WarningCircle size={36}/><div><strong>{active.length} sự kiện cần kiểm tra</strong><p>{eventNames[active[0].kind]} · {dateTime(active[0].observed_at)}</p></div><Button kind="critical" onClick={() => go('/event/' + active[0].id)}>Kiểm tra ngay</Button></div> : <div className="notice success">Không có cảnh báo đang mở. Trạng thái giám sát được hiển thị riêng theo từng camera.</div>}
    <Heading title="Không gian trong nhà" action={<a href="#/cameras">Xem tất cả</a>}/>
    {cameras.length ? <div className="overview-cameras"><CameraImage camera={cameras[0]} onClick={() => go('/camera/' + cameras[0].id)}/><div className="room-list">{cameras.map(c => <button className="room-row" key={c.id} onClick={() => go('/camera/' + c.id)}><VideoCamera size={26}/><span><strong>{c.name}</strong><small>{c.online ? 'Đang kết nối' : 'Chưa kết nối / quá hạn'} · {c.observation === 'clear' ? 'Quan sát rõ' : 'Cần kiểm tra khả năng quan sát'}</small></span></button>)}</div></div> : <Empty title="Nhà chưa có camera" text="Thêm camera để bắt đầu giám sát." action={home.role === 'owner' && <Button onClick={() => go('/setup')}>Thêm thiết bị</Button>}/>}
    <div className="two-grid spaced"><section className="panel"><h2>Sự kiện gần đây</h2>{events.slice(0,4).map(e => <a className="more-row" key={e.id} href={'#/event/' + e.id}><span><strong>{eventNames[e.kind]}</strong><small>{dateTime(e.observed_at)}</small></span><Badge tone={e.severity === 'critical' ? 'red' : 'teal'}>{statusNames[e.status]}</Badge></a>)}{!events.length && <p>Chưa có sự kiện từ thiết bị.</p>}</section><section className="panel"><h2>Lời nhắc theo lịch</h2>{next.slice(0,4).map(r => <a className="more-row" key={r.id} href="#/reminders"><Clock/><strong>{r.time} · {r.name}</strong><Badge>{statusNames[r.asset_status] || r.asset_status}</Badge></a>)}{!next.length && <p>Chưa có lịch nhắc đang bật.</p>}<a href="#/reminders">Quản lý lời nhắc</a></section></div>
  </>;
}

export function Cameras() {
  const { cameras, rooms, home } = useApp();const [filter, setFilter] = useState('');
  return <><Heading title="Camera trong nhà" text="Chỉ hiển thị camera thuộc phạm vi quyền của bạn." action={home.role === 'owner' && <Button onClick={() => go('/setup')}><Plus/>Thêm camera</Button>}/>
    <Field label="Lọc theo phòng"><select value={filter} onChange={e => setFilter(e.target.value)}><option value="">Tất cả phòng</option>{rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
    <div className="two-grid">{cameras.filter(c => !filter || c.room_id === filter).map(c => <article className="panel" key={c.id}><CameraImage camera={c} onClick={() => go('/camera/' + c.id)}/><div className="section-heading"><h2>{c.name}</h2><Button kind="secondary-btn" onClick={() => go('/camera/' + c.id)}>Mở camera</Button></div><p>Cập nhật: {dateTime(c.last_seen)}</p></article>)}</div>{!cameras.length && <Empty title="Chưa có camera được cấp quyền"/>}
  </>;
}

export function CameraDetail({ id }) {
  const { cameras, home, can, notify } = useApp();const camera = cameras.find(c => c.id === id);
  if (!camera) return <Empty title="Camera không tồn tại hoặc ngoài phạm vi quyền"/>;
  return <><Heading title={camera.name} text={`Kết nối cuối: ${dateTime(camera.last_seen)}`} action={can(camera, 'zones') && <Button onClick={() => go('/zones/' + id)}>Thiết lập vùng</Button>}/><CameraImage camera={camera}/>
    <div className="notice">Luồng hình chỉ hiển thị trực tiếp khi đang nhận frame mới từ thiết bị. Khi luồng gián đoạn, giao diện chuyển sang ảnh gần nhất và giữ thời điểm nhận để tránh nhầm với tình hình hiện tại.</div>
    <div className="two-grid"><section className="panel"><h2>Tình trạng giám sát</h2><p>Quan sát: {camera.observation}</p><p>Cấu hình: {camera.applied_version}/{camera.desired_version} · {statusNames[camera.sync_status]}</p>{camera.config_error && <p role="alert">{camera.config_error}</p>}</section><section className="panel"><h2>Kết nối với người thân</h2><p>Lệnh phát âm thanh chỉ được ghi nhận hoàn thành khi thiết bị phản hồi.</p>{can(camera, 'audio') && <Button onClick={() => go('/reminders/send?camera=' + id)}><SpeakerHigh/>Gửi âm thanh</Button>}<a className="button secondary-btn" href="#/environment">Xem môi trường</a></section></div>
  </>;
}

export function Devices() {
  const { cameras, home, notify, reload } = useApp();const [remove, setRemove] = useState(null);
  async function removeDevice() { try { await api('/cameras/' + remove.id, { method: 'DELETE' });setRemove(null);reload();notify('Đã gỡ thiết bị và vô hiệu credential cũ.'); } catch (e) { notify(e.message); } }
  return <><Heading title="Thiết bị trong nhà" action={home.role === 'owner' && <Button onClick={() => go('/setup')}>Thêm thiết bị</Button>}/>{cameras.map(c => <article className="panel device-row" key={c.id}><VideoCamera size={30}/><div><h2>{c.name}</h2><p>{dateTime(c.last_seen)}</p><small>{Object.entries(c.capabilities).filter(([,v]) => v).map(([k]) => k).join(', ') || 'Chưa có thông tin phần cứng'}</small><p>Cấu hình {c.applied_version}/{c.desired_version} · {statusNames[c.sync_status]}</p></div><Badge tone={c.online ? 'teal' : 'gray'}>{c.online ? 'Đang kết nối' : 'Offline / chưa kết nối'}</Badge><Button kind="secondary-btn" onClick={() => go('/camera/' + c.id)}>Chi tiết</Button>{home.role === 'owner' && <Button kind="ghost danger" onClick={() => setRemove(c)}>Gỡ thiết bị</Button>}</article>)}{!cameras.length && <Empty title="Chưa có thiết bị"/>}{remove && <Modal title="Gỡ thiết bị khỏi nhà?" onClose={() => setRemove(null)}><p>{remove.name} sẽ không thể nhận lệnh hoặc gửi dữ liệu bằng thông tin xác thực cũ. Lịch sử được giữ lại.</p><Button kind="critical" onClick={removeDevice}>Xác nhận gỡ</Button></Modal>}</>;
}

function Sensor({ reading, label }) {
  if (!reading) return <div><strong>{label}</strong><p>Chưa có dữ liệu</p></div>;
  return <div><strong>{label}</strong><h2>{reading.quality === 'valid' ? reading.value + ' ' + reading.unit : 'Không có số đo hợp lệ'}</h2><small>{reading.quality}</small></div>;
}
export function Environment() {
  const { cameras, tick } = useApp();const [chosen, setChosen] = useState('');const id = cameras.some(c => c.id === chosen) ? chosen : cameras[0]?.id;
  const resource = useResource(id ? `/cameras/${id}/telemetry?limit=100` : null, tick);
  const rows = resource.data || [], latest = rows[0];
  return <><Heading title="Môi trường sống" text="Dữ liệu đo từ thiết bị; khoảng trống không được thay bằng số 0."/><Field label="Thiết bị"><select value={id || ''} onChange={e => setChosen(e.target.value)}>{cameras.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
    <ResourceState resource={resource}>{latest ? <><div className="notice">Đo: {dateTime(latest.observed_at)} · Nhận: {dateTime(latest.received_at)}{Date.now() - new Date(latest.received_at).getTime() > 60000 && <strong> · Dữ liệu đã quá hạn</strong>}</div><div className="three-grid"><section className="panel"><Sensor reading={latest.payload.readings.temperature} label="Nhiệt độ"/></section><section className="panel"><Sensor reading={latest.payload.readings.humidity} label="Độ ẩm"/></section><section className="panel"><Sensor reading={latest.payload.readings.gas} label="Tín hiệu gas"/></section></div><section className="panel spaced"><h2>Lịch sử số đo</h2><div className="table-scroll"><table><thead><tr><th>Thời điểm đo</th><th>Nhiệt độ</th><th>Độ ẩm</th><th>Gas</th></tr></thead><tbody>{rows.map(r => <tr key={r.id}><td>{dateTime(r.observed_at)}</td>{['temperature','humidity','gas'].map(k => <td key={k}>{r.payload.readings[k]?.quality === 'valid' ? `${r.payload.readings[k].value} ${r.payload.readings[k].unit}` : '—'}</td>)}</tr>)}</tbody></table></div></section></> : <Empty title="Chưa nhận dữ liệu môi trường" text="Kết nối cảm biến để bắt đầu theo dõi điều kiện trong phòng."/>}</ResourceState>
  </>;
}
