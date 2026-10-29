import React, { lazy, Suspense, useState } from 'react';
import { Plus, VideoCamera, Thermometer, Drop, Leaf, WarningCircle, Clock, SpeakerHigh, CaretRight, ArrowRight, ArrowClockwise, Trash, Shield, Globe, WifiSlash, CheckCircle, ShieldCheck, House } from '@phosphor-icons/react';
import { api, go, roleNames, statusNames, eventNames, dateTime } from './api';
import { Badge, Button, CameraImage, CameraThumbnail, Empty, Field, Heading, Modal, PagedList, Pagination } from './ui';
import { useApp, useResource, ResourceState } from './context';
const EnvironmentChart=lazy(()=>import('./EnvironmentChart').then(module=>({default:module.EnvironmentChart})));
import { usePagination } from './pagination';
import { roomImage, roomEntries, connectionLabel, observationNames } from './cameraState';

export function Homes() {
  const { homes, home: activeHome, selectHome, reloadHomes, notify } = useApp();
  const [form, setForm] = useState(false), [busy, setBusy] = useState(false), [removing,setRemoving]=useState(null), [confirmation,setConfirmation]=useState('');
  async function create(event) {
    event.preventDefault();setBusy(true);
    try { const home = await api('/homes', { method: 'POST', body: Object.fromEntries(new FormData(event.currentTarget)) });await reloadHomes();selectHome(home.id);setForm(false);go('/setup'); }
    catch (error) { notify(error.message); } finally { setBusy(false); }
  }
  return <><Heading title="Những ngôi nhà của bạn" text="Chọn không gian để theo dõi, chăm sóc và kết nối với người thân." action={<div className="actions"><Button kind="secondary-btn" onClick={() => reloadHomes().catch(error => notify(error.message))}><ArrowClockwise/>Làm mới</Button><Button onClick={() => setForm(true)}><Plus/>Tạo nhà mới</Button></div>}/>
    {!homes.length ? <div className="home-welcome panel"><img src="/images/living.png" alt="Không gian sống ấm cúng"/><div><House size={32}/><h2>Bắt đầu từ ngôi nhà của bạn</h2><p>Thêm nhà, tạo phòng và chia sẻ quyền truy cập khi người thân cần. Hình ảnh và dữ liệu thiết bị sẽ hiển thị khi kết nối.</p><Button onClick={() => setForm(true)}><Plus/>Tạo nhà đầu tiên</Button></div></div> : <div className="home-gallery"><PagedList items={homes} pageSize={4} label="nhà">{(item,index) => <article className="home-tile panel" key={item.id}><div className="home-cover"><img src={index % 2 ? '/images/entrance.png' : '/images/living.png'} alt={'Ảnh minh hoạ ' + item.name}/><Badge tone="camera-status"><House/>{roleNames[item.role]}</Badge><small>Ảnh minh hoạ</small></div><div className="home-tile-content"><h2>{item.name}</h2><p><ShieldCheck/>{item.role === 'owner' ? 'Bạn quản lý không gian này' : 'Được người thân chia sẻ'}</p><div className="home-tile-facts"><span><House/>{item.room_count ?? '—'} phòng</span><span><VideoCamera/>{item.camera_count ?? '—'} camera trong phạm vi</span></div><div className="home-tile-footer"><span><Globe/>{item.timezone === 'Asia/Ho_Chi_Minh' ? 'Việt Nam · UTC+7' : item.timezone}</span><Button onClick={() => { selectHome(item.id);go('/overview'); }}>Mở nhà<ArrowRight/></Button></div>{item.role === 'owner' && item.archive_supported && <button className="home-remove-button" aria-label={'Xoá nhà '+item.name} onClick={()=>{setRemoving(item);setConfirmation('');}}><Trash/>Xoá nhà</button>}</div></article>}</PagedList></div>}
    {removing && <Modal title="Xoá nhà" onClose={()=>{if(!busy)setRemoving(null);}}><p>Nhà <strong>{removing.name}</strong> sẽ được đưa vào lưu trữ. Thành viên và thiết bị sẽ ngừng truy cập; lịch sử được giữ lại.</p><form onSubmit={async event=>{event.preventDefault();setBusy(true);try{await api('/homes/'+removing.id,{method:'DELETE',body:{confirmation}});if(activeHome?.id===removing.id)selectHome('');await reloadHomes();setRemoving(null);notify('Đã xoá nhà khỏi danh sách. Lịch sử được lưu trữ.');}catch(error){notify(error.message);}finally{setBusy(false);}}}><Field label="Nhập tên nhà để xác nhận" value={confirmation} onChange={event=>setConfirmation(event.target.value)} autoComplete="off"/><div className="actions"><Button kind="secondary-btn" disabled={busy} onClick={()=>setRemoving(null)}>Huỷ</Button><Button kind="critical" type="submit" disabled={busy || confirmation.trim()!==removing.name}>Xác nhận xoá nhà</Button></div></form></Modal>}
    {form && <Modal title="Tạo nhà mới" onClose={() => setForm(false)}><form onSubmit={create}><p>Bạn có thể tạo phòng và thêm thiết bị sau khi tạo nhà.</p><Field label="Tên nhà" name="name" required maxLength={120}/><Field label="Múi giờ" name="timezone" defaultValue="Asia/Ho_Chi_Minh" required/><Button type="submit" disabled={busy}>Tạo nhà</Button></form></Modal>}
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
  return <><Heading title="Kết nối camera với nhà" action={<Button kind="secondary-btn" onClick={()=>go('/overview')}>Thiết lập sau<ArrowRight/></Button>} text="Mã ghép nối chỉ dùng một lần và có thời hạn. Thiết bị đang thuộc nhà khác không thể được nhận lại bằng mã cũ."/>
    <div className="two-grid"><form className="panel" onSubmit={room}><h2>1. Tạo phòng</h2><Field label="Tên phòng" name="name" required maxLength={120}/><Button type="submit">Thêm phòng</Button><p>{rooms.map(r => r.name).join(' · ') || 'Chưa có phòng'}</p></form>
    <form className="panel" onSubmit={claim}><h2>2. Ghép nối thiết bị</h2><Field label="Mã ghép nối từ thiết bị" name="code" required minLength={8} autoComplete="off"/><Field label="Tên camera" name="name" required maxLength={120}/><Field label="Phòng"><select name="room_id" required defaultValue=""><option value="" disabled>Chọn phòng</option>{rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field><Button type="submit" disabled={busy || !rooms.length}>{busy ? 'Đang ghép nối…' : 'Đăng ký camera'}</Button></form></div>
    <div className="notice">Sau khi ghép nối, kiểm tra hình ảnh và tình trạng kết nối trong trang camera. Chưa kết nối không có nghĩa là đang giám sát.</div>
  </>;
}

function RoomRow({ entry, selected, owner, onSelect }) {
  const camera = entry.camera;
  return <button className={'room-row ' + (selected ? 'active' : '')} onClick={onSelect} aria-pressed={selected}>
    <CameraThumbnail name={entry.name}/><span><strong>{entry.name}</strong><small className={camera?.online ? 'teal-text' : ''}>{camera?.online ? <CheckCircle/> : <WifiSlash/>}{connectionLabel(camera)}</small><span className="room-source">Ảnh minh hoạ</span></span><CaretRight/>
  </button>;
}

function RoomWaiting({ name, owner }) {
  return <div className="camera-photo real-camera room-waiting"><img src={roomImage(name)} alt={'Ảnh minh hoạ ' + name}/><div className="photo-top"><Badge tone="camera-status"><WifiSlash/>Chưa ghép nối camera</Badge><span className="photo-source">Ảnh minh hoạ</span></div><div className="photo-bottom"><div><strong>{name}</strong><span>{owner ? 'Ghép nối thiết bị để bắt đầu xem hình ảnh.' : 'Chưa có camera trong phạm vi truy cập.'}</span></div></div></div>;
}

export function Overview() {
  const { user, home, cameras, rooms, events, reminders, loaded } = useApp();
  const [selected, setSelected] = useState('');
  const entries = roomEntries(cameras, rooms, home.role === 'owner');
  const chosen = entries.find(entry => entry.id === selected) || entries[0];
  const active = events.filter(e => ['OPEN','ACKNOWLEDGED'].includes(e.status));
  const next = reminders.filter(r => r.enabled).sort((a,b) => a.time.localeCompare(b.time));
  const online = cameras.filter(camera => camera.online).length;
  return <><Heading title={`Xin chào, ${user.name}.`} text={`${home.name} · Không gian thân thuộc, an tâm mỗi ngày.`}/>
    <div className="home-summary"><span><House/><strong>{rooms.length}</strong> phòng</span><span><VideoCamera/><strong>{online}/{cameras.length}</strong> thiết bị kết nối</span><span><Clock/><strong>{loaded.reminders ? next.length : '—'}</strong> lời nhắc đang bật</span></div>
    {loaded.events ? active.length ? <div className="alert-banner"><WarningCircle size={32}/><div><strong>{active.length} sự kiện cần kiểm tra</strong><p>{eventNames[active[0].kind]} · {dateTime(active[0].observed_at)}</p></div><Button kind="critical" onClick={() => go('/event/' + active[0].id)}>Kiểm tra ngay</Button></div> : <div className="notice success"><ShieldCheck/>Chưa có sự kiện đang mở. Tình trạng kết nối được hiển thị riêng theo từng phòng.</div> : <div className="notice" role="status">Đang cập nhật sự kiện gần đây…</div>}
    <Heading level={2} title="Không gian trong nhà" text="Chọn một phòng để xem hình ảnh và tình trạng thiết bị." action={<a href="#/cameras">Xem tất cả <CaretRight/></a>}/>
    {chosen ? <div className="overview-cameras">{chosen.camera ? <CameraImage camera={chosen.camera} roomName={chosen.name} onClick={() => go('/camera/' + chosen.camera.id)}/> : <RoomWaiting name={chosen.name} owner={home.role === 'owner'}/>}<div className="room-list">{entries.map(entry => <RoomRow key={entry.id} entry={entry} selected={chosen.id === entry.id} owner={home.role === 'owner'} onSelect={() => setSelected(entry.id)}/>)}</div></div> : <div className="empty-home-preview"><RoomWaiting name="Phòng khách" owner={home.role === 'owner'}/><section className="panel"><h2>Bắt đầu với không gian của bạn</h2><p>Thêm phòng trước, ghép nối camera khi thiết bị đã sẵn sàng. Mỗi phòng luôn có ảnh minh hoạ và trạng thái rõ ràng.</p>{home.role === 'owner' && <Button onClick={() => go('/setup')}>Thêm phòng & thiết bị</Button>}</section></div>}
    <div className="two-grid spaced"><section className="panel"><div className="section-heading"><h2>Sự kiện gần đây</h2><a href="#/events">Xem tất cả</a></div>{events.slice(0,4).map(e => <a className="more-row event-summary-row" key={e.id} href={'#/event/' + e.id}><span><strong>{eventNames[e.kind]}</strong><small>{dateTime(e.observed_at)}</small></span><Badge tone={e.status === 'OPEN' ? 'amber' : 'gray'}>{statusNames[e.status]}</Badge></a>)}{!loaded.events ? <div className="quiet-state" role="status">Đang tải sự kiện…</div> : !events.length && <div className="quiet-state"><ShieldCheck/><strong>Chưa có sự kiện</strong><p>Các sự kiện từ thiết bị sẽ được lưu tại đây.</p></div>}</section><section className="panel"><div className="section-heading"><h2>Lịch nhắc đang bật</h2><a href="#/reminders">Quản lý</a></div>{next.slice(0,4).map(r => <a className="more-row reminder-summary-row" key={r.id} href="#/reminders"><span className="reminder-clock"><Clock/></span><span><strong>{r.time} · {r.name}</strong><small>{rooms.find(room => room.id === cameras.find(camera => camera.id === r.camera_id)?.room_id)?.name || 'Trong nhà'}</small></span><Badge tone="gray">{statusNames[r.asset_status] || 'Đang chuẩn bị'}</Badge></a>)}{!loaded.reminders ? <div className="quiet-state" role="status">Đang tải lịch nhắc…</div> : !next.length && <div className="quiet-state"><Clock/><strong>Một lời nhắc, thêm an tâm</strong><p>Tạo lịch sinh hoạt và chuẩn bị âm thanh trước khi thiết bị kết nối.</p><a href="#/reminders">Tạo lời nhắc đầu tiên</a></div>}</section></div>
  </>;
}

export function Cameras() {
  const { cameras, rooms, home } = useApp();const [filter, setFilter] = useState('');
  const entries = roomEntries(cameras, rooms, home.role === 'owner').filter(entry => !filter || (entry.camera?.room_id || entry.id) === filter);
  return <><Heading title="Không gian & camera" text="Mỗi phòng một góc nhìn. Ảnh minh hoạ được thay bằng hình thiết bị khi có dữ liệu." action={home.role === 'owner' && <Button onClick={() => go('/setup')}><Plus/>Thêm phòng / camera</Button>}/>
    <div className="camera-filter"><Field label="Lọc theo phòng"><select value={filter} onChange={e => setFilter(e.target.value)}><option value="">Tất cả phòng</option>{rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field><span>{entries.length} không gian</span></div>
    <div className="two-grid camera-grid">{<PagedList items={entries} pageSize={6} label="camera" resetKey={filter}>{entry => <article className="panel camera-card" key={entry.id}>{entry.camera ? <CameraImage camera={entry.camera} roomName={entry.name} onClick={() => go('/camera/' + entry.camera.id)}/> : <RoomWaiting name={entry.name} owner={home.role === 'owner'}/>}<div className="camera-card-info"><div><h2>{entry.name}</h2><p>{entry.camera?.online ? 'Thiết bị đang kết nối' : entry.camera?.last_seen ? 'Kết nối cuối: ' + dateTime(entry.camera.last_seen) : entry.camera ? 'Đã ghép nối · Chờ thiết bị kết nối' : 'Sẵn sàng ghép nối khi thiết bị có mặt'}</p></div><Button kind="secondary-btn" onClick={() => go(entry.camera ? '/camera/' + entry.camera.id : '/setup')}>{entry.camera ? 'Chi tiết' : 'Ghép nối'}</Button></div></article>}</PagedList>}</div>{!entries.length && <Empty title={filter ? 'Phòng chưa có camera trong phạm vi truy cập' : 'Chưa có không gian được cấp quyền'} text="Chủ nhà có thể thêm phòng hoặc chia sẻ camera cho bạn." action={home.role === 'owner' && <Button onClick={() => go('/setup')}>Thêm phòng</Button>}/>}
  </>;
}

export function CameraDetail({ id }) {
  const { cameras, rooms, home, can, notify } = useApp();const camera = cameras.find(c => c.id === id);
  if (!camera) return <Empty title="Camera không tồn tại hoặc ngoài phạm vi quyền"/>;
  return <><Heading title={camera.name} text={`Kết nối cuối: ${dateTime(camera.last_seen)}`}/><CameraImage camera={camera} roomName={rooms.find(room => room.id === camera.room_id)?.name}/>
    <div className="notice">Luồng hình chỉ hiển thị trực tiếp khi đang nhận frame mới từ thiết bị. Khi luồng gián đoạn, giao diện chuyển sang ảnh gần nhất và giữ thời điểm nhận để tránh nhầm với tình hình hiện tại.</div>
    <div className="two-grid"><section className="panel"><h2>Tình trạng giám sát</h2><p>Quan sát: {camera.online ? observationNames[camera.observation] || 'Chưa có quan sát' : 'Chưa nhận quan sát mới'}</p><p>Cấu hình: {camera.applied_version}/{camera.desired_version} · {statusNames[camera.sync_status]}</p>{camera.config_error && <p role="alert">{camera.config_error}</p>}</section><section className="panel"><h2>Kết nối với người thân</h2><p>Lệnh phát âm thanh chỉ được ghi nhận hoàn thành khi thiết bị phản hồi.</p>{can(camera, 'audio') && <Button onClick={() => go('/reminders/send?camera=' + id)}><SpeakerHigh/>Gửi âm thanh</Button>}<a className="button secondary-btn" href="#/environment">Xem môi trường</a></section></div>
  </>;
}

export function Devices() {
  const { cameras, home, notify, reload } = useApp();const [remove, setRemove] = useState(null);
  async function removeDevice() { try { await api('/cameras/' + remove.id, { method: 'DELETE' });setRemove(null);reload();notify('Đã gỡ thiết bị và vô hiệu credential cũ.'); } catch (e) { notify(e.message); } }
  return <><Heading title="Thiết bị trong nhà" action={home.role === 'owner' && <Button onClick={() => go('/setup')}>Thêm thiết bị</Button>}/>{<PagedList items={cameras} label="thiết bị" resetKey={home.id}>{c => <article className="panel device-row" key={c.id}><CameraThumbnail name={c.name}/><div><h2>{c.name}</h2><p>{dateTime(c.last_seen)}</p><small>{Object.entries(c.capabilities).filter(([,v]) => v).map(([k]) => k).join(', ') || 'Chưa có thông tin phần cứng'}</small><p>Cấu hình {c.applied_version}/{c.desired_version} · {statusNames[c.sync_status]}</p></div><Badge tone={c.online ? 'teal' : 'gray'}>{c.online ? 'Đang kết nối' : 'Offline / chưa kết nối'}</Badge><Button kind="secondary-btn" onClick={() => go('/camera/' + c.id)}>Chi tiết</Button>{home.role === 'owner' && <Button kind="ghost danger" onClick={() => setRemove(c)}>Gỡ thiết bị</Button>}</article>}</PagedList>}{!cameras.length && <Empty title="Chưa có thiết bị"/>}{remove && <Modal title="Gỡ thiết bị khỏi nhà?" onClose={() => setRemove(null)}><p>{remove.name} sẽ không thể nhận lệnh hoặc gửi dữ liệu bằng thông tin xác thực cũ. Lịch sử được giữ lại.</p><Button kind="critical" onClick={removeDevice}>Xác nhận gỡ</Button></Modal>}</>;
}

function Sensor({ reading, label, icon: Icon }) {
  return <div className="sensor-summary"><span className="sensor-icon"><Icon size={28}/></span><div><strong>{label}</strong><h2>{reading?.quality === 'valid' ? new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(reading.value) + ' ' + reading.unit : '—'}</h2><small>{reading ? ({valid:'Hợp lệ tại thời điểm đo',error:'Cảm biến báo lỗi',warming_up:'Cảm biến đang khởi động'})[reading.quality] : 'Chưa có dữ liệu'}</small></div></div>;
}
export function Environment() {
  const { cameras, rooms, tick } = useApp();const [chosen,setChosen]=useState(''),[room,setRoom]=useState(''),[hours,setHours]=useState('24');
  const available=cameras.filter(camera=>!room||camera.room_id===room),id=available.some(camera=>camera.id===chosen)?chosen:available[0]?.id;
  const resource=useResource(id?`/cameras/${id}/telemetry?limit=500&hours=${hours}`:null,tick);
  const rows=resource.data||[],latest=rows[0],table=usePagination(rows,10,id+':'+hours);
  return <><Heading title="Môi trường sống" text="Theo dõi nhiệt độ, độ ẩm và xu hướng môi trường trong từng phòng."/><div className="filters-grid"><Field label="Phòng"><select value={room} onChange={event=>{setRoom(event.target.value);setChosen('');}}><option value="">Tất cả phòng</option>{rooms.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="Thiết bị"><select value={id||''} onChange={event=>setChosen(event.target.value)}>{available.map(camera=><option key={camera.id} value={camera.id}>{camera.name}</option>)}</select></Field><Field label="Khoảng thời gian"><select value={hours} onChange={event=>setHours(event.target.value)}><option value="1">1 giờ qua</option><option value="6">6 giờ qua</option><option value="24">24 giờ qua</option><option value="168">7 ngày qua</option></select></Field></div>
  <ResourceState resource={resource}>{latest?<><div className="notice">Đo: {dateTime(latest.observed_at)} · Nhận: {dateTime(latest.received_at)}{Date.now()-new Date(latest.observed_at).getTime()>60000&&<strong> · Dữ liệu đã quá hạn</strong>}</div><div className="three-grid"><section className="panel"><Sensor icon={Thermometer} reading={latest.payload.readings.temperature} label="Nhiệt độ"/></section><section className="panel"><Sensor icon={Drop} reading={latest.payload.readings.humidity} label="Độ ẩm"/></section><section className="panel"><Sensor icon={Leaf} reading={latest.payload.readings.gas} label="Tín hiệu gas"/></section></div><Suspense fallback={<div className="panel" role="status">Đang tải biểu đồ…</div>}><EnvironmentChart rows={rows}/></Suspense><section className="panel spaced"><h2>Lịch sử số đo</h2><p className="secondary">Tối đa 500 bản ghi gần nhất trong khoảng đã chọn.</p><div className="table-scroll"><table><thead><tr><th>Thời điểm đo</th><th>Nhiệt độ</th><th>Độ ẩm</th><th>Gas</th></tr></thead><tbody>{table.items.map(row=><tr key={row.id}><td>{dateTime(row.observed_at)}</td>{['temperature','humidity','gas'].map(key=><td key={key}>{row.payload.readings[key]?.quality==='valid'?`${new Intl.NumberFormat('vi-VN',{maximumFractionDigits:1}).format(row.payload.readings[key].value)} ${row.payload.readings[key].unit==='C'?'°C':row.payload.readings[key].unit}`:'—'}</td>)}</tr>)}</tbody></table></div><Pagination page={table.page} pageSize={10} total={table.total} onChange={table.setPage} label="số đo"/></section></>:<Empty icon={Leaf} title="Chưa có số đo trong khoảng đã chọn" text="Thử khoảng thời gian khác, hoặc kết nối cảm biến để bắt đầu theo dõi."/>}</ResourceState></>;
}
