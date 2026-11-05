import {Bell,ClockCounterClockwise} from '@phosphor-icons/react';
import {activityLabel,deliveryLabel} from './activityLabels';
import React, { useEffect, useState } from 'react';
import { api, go, dateTime, roleNames, statusNames, eventNames } from './api';
import { InvitationCodes } from './InvitationCodes';
import {useServerPage,ServerPager} from './serverPaging';
import { NotificationSettings } from './NotificationSettings';
import { Badge, Button, Empty, Field, Heading, PagedList, Modal } from './ui';
import { useApp, useResource, ResourceState } from './context';

const formatStorage=bytes=>new Intl.NumberFormat('vi-VN',{maximumFractionDigits:1}).format(bytes>=1073741824?bytes/1073741824:bytes/1048576)+' '+(bytes>=1073741824?'GB':'MB');
const notificationErrorLabel=code=>({
  NotEligible:'Đã dừng vì sự kiện đã đóng hoặc quyền nhận cảnh báo đã thay đổi.',
  TelegramNotConfigured:'Bot Telegram hoặc Chat ID chưa được cấu hình.',
  TelegramRateLimited:'Telegram giới hạn tốc độ; hệ thống sẽ thử lại sau.',
  TelegramTimedOut:'Chưa xác định được Telegram đã nhận tin hay chưa.',
  TelegramRejected:'Telegram từ chối yêu cầu; hãy kiểm tra bot và Chat ID.',
  ProviderError:'Nhà cung cấp gửi thông báo gặp lỗi.',
  LeaseExpired:'Worker bị khởi động lại; kết quả gửi đang được xác minh.',
})[code]||'Không gửi được thông báo. Hãy kiểm tra cấu hình kênh nhận.';
const mediaResultLabel=value=>({
  not_requested:'Không kèm ảnh',consent_disabled:'Chưa cho phép gửi ảnh',missing:'Không có ảnh hợp lệ; chỉ gửi nội dung chữ',
  unavailable:'Ảnh tạm thời không truy cập được; chỉ gửi nội dung chữ',sent:'Đã gửi kèm ảnh',text_fallback:'Ảnh bị từ chối; đã chuyển sang gửi nội dung chữ',
})[value];

export function Members() {
  const { home, cameras, notify, confirm, tick, reload } = useApp();
  const resource = useResource(home.role === 'owner' ? '/homes/' + home.id + '/members' : null, tick);
  const [form, setForm] = useState(null), [role, setRole] = useState('viewer'), [scopes, setScopes] = useState([]), [cameraRights, setCameraRights] = useState({}), [busy, setBusy] = useState(false);
  if (home.role !== 'owner') return <Empty title="Bạn chưa có quyền quản lý thành viên"/>;
  function open(member) {
    const nextScopes = member?.scopes || [];
    const legacy = member?.rights || {};
    const nextRights = Object.fromEntries(nextScopes.map(id => [id, {
      audio: Boolean(member?.camera_permissions?.[id]?.audio ?? legacy.audio),
      schedules: Boolean(member?.camera_permissions?.[id]?.schedules ?? legacy.schedules),
    }]));
    setForm(member || {});setRole(member?.role || 'viewer');setScopes(nextScopes);setCameraRights(nextRights);
  }
  function toggleCamera(id, enabled) {
    setScopes(previous => enabled ? [...new Set([...previous,id])] : previous.filter(camera => camera !== id));
    if (enabled) setCameraRights(previous => ({ ...previous, [id]: previous[id] || { audio: false, schedules: false } }));
  }
  function toggleRight(camera, right, enabled) {
    setCameraRights(previous => ({ ...previous, [camera]: { ...(previous[camera] || { audio: false, schedules: false }), [right]: enabled } }));
  }
  async function save(event) {
    event.preventDefault();setBusy(true);
    try {
      const camera_permissions = Object.fromEntries(scopes.map(id => [id, role === 'caregiver' ? cameraRights[id] || { audio: false, schedules: false } : { audio: false, schedules: false }]));
      const rights = { audio: Object.values(camera_permissions).some(item => item.audio), schedules: Object.values(camera_permissions).some(item => item.schedules) };
      const body = { role, scopes, rights, camera_permissions };
      await api(`/homes/${home.id}/members/${form.id}`, { method: 'PATCH', body });
      setForm(null);resource.reload();reload();notify('Đã cập nhật quyền theo từng camera.');
    } catch (e) { notify(e.message); } finally { setBusy(false); }
  }
  return <><Heading title="Thành viên & quyền" text="Phạm vi xem và quyền bổ sung được cấu hình riêng cho từng camera."/><ResourceState resource={resource}><section className="panel">{<PagedList items={resource.data || []} label="thành viên" resetKey={home.id}>{member => <div className="member-row" key={member.id}><div className="avatar">{member.name.slice(0,1)}</div><span><strong>{member.name}</strong><small>{member.email}</small><small>{member.role === 'owner' ? 'Toàn bộ camera' : member.scopes.map(id => cameras.find(c => c.id === id)?.name || id).join(', ') || 'Chưa được cấp camera'}</small></span><Badge>{roleNames[member.role]}</Badge>{member.role !== 'owner' && <><Button kind="ghost" onClick={() => open(member)}>Sửa quyền</Button><Button kind="ghost danger" onClick={async () => { if (!await confirm({title:'Thu hồi quyền thành viên?',message:member.name+' sẽ không còn quyền truy cập nhà này.',confirmLabel:'Thu hồi quyền',tone:'danger'})) return;try { await api(`/homes/${home.id}/members/${member.id}`, { method: 'DELETE' });resource.reload();reload();notify('Đã thu hồi quyền và ngắt kết nối thuộc quyền bị thu hồi.'); } catch (e) { notify(e.message); } }}>Thu hồi</Button></>}</div>}</PagedList>}</section></ResourceState><InvitationCodes/>
    {form && <Modal title="Chỉnh sửa quyền" onClose={() => setForm(null)}><form onSubmit={save}><Field label="Email" name="email" type="email" required defaultValue={form.email} readOnly={!!form.id}/><Field label="Vai trò"><select value={role} onChange={e => setRole(e.target.value)}><option value="member">Thành viên</option><option value="viewer">Người xem</option><option value="caregiver">Người chăm sóc</option></select></Field><h3>Chọn camera và quyền</h3><div className="camera-grant-list">{cameras.map(camera => <div className="camera-grant" key={camera.id}><label className="checkbox"><input type="checkbox" checked={scopes.includes(camera.id)} onChange={e => toggleCamera(camera.id,e.target.checked)}/><span>{camera.name}</span></label>{role === 'caregiver' && scopes.includes(camera.id) && <div className="camera-grant-rights"><label className="checkbox"><input type="checkbox" checked={!!cameraRights[camera.id]?.schedules} onChange={e => toggleRight(camera.id,'schedules',e.target.checked)}/><span>Quản lý lời nhắc và nghe thử nội dung lịch</span></label><label className="checkbox"><input type="checkbox" checked={!!cameraRights[camera.id]?.audio} onChange={e => toggleRight(camera.id,'audio',e.target.checked)}/><span>Tải âm thanh lên và điều khiển loa</span></label></div>}</div>)}</div>{role === 'caregiver' && <p className="muted">Quyền lời nhắc không cấp quyền gửi lệnh loa thủ công. Chỉ chủ nhà mới xoá được file âm thanh.</p>}<Button type="submit" disabled={busy}>Lưu quyền</Button></form></Modal>}
  </>;
}

export function Invitation({ token }) {
  const { reloadHomes, selectHome, notify } = useApp();const resource = useResource(token ? '/invitations/' + token : null);
  async function accept() { try { const result = await api('/invitations/' + token + '/accept', { method: 'POST', body: {} });await reloadHomes();selectHome(result.home_id);go('/overview'); } catch (e) { notify(e.message); } }
  return <ResourceState resource={resource}>{resource.data && <section className="panel"><Heading title={'Lời mời tham gia ' + resource.data.home_name}/><p>Vai trò: {roleNames[resource.data.role]}</p><p>Hết hạn: {dateTime(resource.data.expires * 1000)}</p><p>Chỉ tài khoản email người nhận mới chấp nhận được lời mời này.</p><Button disabled={resource.data.status !== 'pending' || Date.now() > resource.data.expires * 1000} onClick={accept}>Chấp nhận lời mời</Button><Button kind="ghost" disabled={resource.data.status !== 'pending'} onClick={async () => { try { await api('/invitations/' + token + '/decline', { method: 'POST', body: {} });notify('Đã từ chối lời mời.');go('/homes'); } catch (e) { notify(e.message); } }}>Từ chối</Button></section>}</ResourceState>;
}

export function Settings() {
  const { home, rooms, notify, reload, reloadHomes, tick } = useApp();
  const resource = useResource(home.role === 'owner' ? '/homes/' + home.id + '/settings' : null);
  const storage = useResource(home.role === 'owner' ? '/homes/' + home.id + '/storage' : null,tick);
  const [activityOpen,setActivityOpen]=useState(false),[deliveryOpen,setDeliveryOpen]=useState(false),[deliveryRecipient,setDeliveryRecipient]=useState(''),[deliveryRecipients,setDeliveryRecipients]=useState([]);
  const [deliveryChannel,setDeliveryChannel]=useState(''),[deliveryStatus,setDeliveryStatus]=useState('');
  const audit=useServerPage(activityOpen&&home.role==='owner'?'/homes/'+home.id+'/audit':null);
  const deliveryQuery=new URLSearchParams({...deliveryRecipient&&{recipient_id:deliveryRecipient},...deliveryChannel&&{channel:deliveryChannel},...deliveryStatus&&{status:deliveryStatus}});
  const delivery=useServerPage(deliveryOpen&&home.role==='owner'?`/homes/${home.id}/delivery-status?${deliveryQuery}`:null);
  const [form, setForm] = useState(null), [roomEdit, setRoomEdit] = useState(null), [busy, setBusy] = useState(false);
  useEffect(() => { if (resource.data) setForm(resource.data); }, [resource.data]);
  useEffect(() => { setDeliveryRecipient('');setDeliveryRecipients([]);setDeliveryChannel('');setDeliveryStatus(''); }, [home.id]);

  if (home.role !== 'owner') return <Empty title="Chỉ chủ nhà được chỉnh cài đặt"/>;
  async function save(event) { event.preventDefault();setBusy(true);try { await api('/homes/' + home.id + '/settings', { method: 'PUT', body: form });reload();notify('Đã lưu chính sách, đang chờ thiết bị áp dụng.'); } catch (e) { notify(e.message); } finally { setBusy(false); } }
  return <><Heading title="Cài đặt nhà" text="Quản lý không gian, chính sách, thông báo và lưu trữ."/><div className="two-grid"><section className="panel"><h2>Thông tin nhà</h2><form onSubmit={async e => { e.preventDefault();try { await api('/homes/' + home.id, { method: 'PATCH', body: Object.fromEntries(new FormData(e.currentTarget)) });await reloadHomes();notify('Đã cập nhật nhà.'); } catch (error) { notify(error.message); } }}><Field label="Tên nhà" name="name" defaultValue={home.name} key={home.id} required/><Field label="Múi giờ" name="timezone" defaultValue={home.timezone} required/><Button type="submit">Lưu thông tin nhà</Button></form><div className="settings-room-section"><h3>Các phòng</h3>{rooms.map(r => <div className="setting-row room-settings-row" key={r.id}><span>{r.name}</span><Button kind="ghost" onClick={() => setRoomEdit(r)}>Đổi tên</Button></div>)}<Button kind="secondary-btn add-room-button" onClick={() => setRoomEdit({})}>Thêm phòng</Button></div></section><ResourceState resource={resource}>{form && <form className="panel" onSubmit={save}><h2>Ngưỡng cảnh báo môi trường</h2>{[['temperature_low','Nhiệt độ thấp'],['temperature_high','Nhiệt độ cao'],['humidity_high','Độ ẩm cao'],['gas_high','Ngưỡng tín hiệu gas'],['environment_hold_seconds','Thời gian duy trì (giây)'],['hysteresis','Khoảng hysteresis']].map(([id,label]) => <Field key={id} label={label} type="number" step="any" value={form[id]} onChange={e => setForm({ ...form, [id]: Number(e.target.value) })}/>)}<Field label="Đơn vị gas đã được thiết bị xác minh"><select value={form.gas_unit} onChange={e => setForm({ ...form, gas_unit: e.target.value })}><option value="ADC">ADC — tín hiệu cảm biến</option><option value="ppm">PPM — chỉ dùng khi đã hiệu chuẩn</option></select></Field><h2>Lưu trữ</h2><Field label="Số ngày lưu ảnh, video và số đo" type="number" min="1" max="90" value={form.retention_days} onChange={e => setForm({ ...form, retention_days: Number(e.target.value) })}/><Button type="submit" disabled={busy}>Lưu chính sách</Button></form>}</ResourceState></div>
    <NotificationSettings onRecipients={setDeliveryRecipients}/>
    <ResourceState resource={storage}>{storage.data&&<section className="panel spaced storage-panel"><div className="section-heading"><div><h2>Dung lượng lưu trữ</h2><p>{formatStorage(storage.data.used_bytes)} đã dùng · {formatStorage(storage.data.reserved_bytes)} đang xử lý · {formatStorage(storage.data.available_bytes)} còn lại</p></div><Badge tone={storage.data.warning_level==='critical'?'red':storage.data.warning_level==='near'?'amber':'teal'}>{storage.data.warning_level==='critical'?'Sắp đầy':storage.data.warning_level==='near'?'Đã dùng nhiều':'Đang ổn định'}</Badge></div><div className="storage-meter" role="progressbar" aria-label="Dung lượng lưu trữ đã dùng" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.min(100,storage.data.used_percent)}><span style={{width:Math.min(100,storage.data.used_percent)+'%'}}/></div><p className="storage-total">{storage.data.used_percent}% / {formatStorage(storage.data.quota_bytes)}</p><p>Ảnh camera và ảnh sự kiện được lưu tối đa {storage.data.retention_days} ngày. Âm thanh đang dùng trong lời nhắc được giữ lại; thông tin sự kiện vẫn còn nếu ảnh hết hạn.</p>{storage.data.reconciliation?<div className="storage-reconcile"><strong>Đối soát gần nhất: {dateTime(storage.data.reconciliation.checked_at)}</strong><span>{storage.data.reconciliation.report.cloud_inventory_status==='complete'?`${storage.data.reconciliation.report.cloud_assets_missing||0} tệp thiếu · ${storage.data.reconciliation.report.cloudinary_orphans||0} tệp chưa liên kết`:'Chưa thể kiểm tra kho media'}</span></div>:<p>Đang chờ lượt đối soát đầu tiên.</p>}</section>}</ResourceState>
    <details className="panel spaced settings-history" open={deliveryOpen} onToggle={event=>setDeliveryOpen(event.currentTarget.open)}>
      <summary><Bell/><span><strong>Lịch sử thông báo</strong><small>Xem tình trạng gửi cảnh báo qua Telegram và email.</small></span></summary>
      {deliveryOpen&&<ResourceState resource={delivery}>
        <div className="filters-grid"><Field label="Lọc theo người nhận"><select value={deliveryRecipient} onChange={event=>setDeliveryRecipient(event.target.value)}><option value="">Tất cả người nhận</option>{deliveryRecipients.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></Field><Field label="Kênh gửi"><select value={deliveryChannel} onChange={e=>setDeliveryChannel(e.target.value)}><option value="">Tất cả kênh</option><option value="email">Email</option><option value="telegram">Telegram</option></select></Field><Field label="Trạng thái gửi"><select value={deliveryStatus} onChange={e=>setDeliveryStatus(e.target.value)}><option value="">Tất cả trạng thái</option>{['pending','sending','accepted','delivered','failed','cancelled','unknown','bounced','rejected','complained'].map(s=><option key={s} value={s}>{deliveryLabel(s).label}</option>)}</select></Field></div>
        {delivery.items.map(d=>{const status=deliveryLabel(d.status);return <article className="notification-history-row" key={d.id}><div><strong>{d.channel_kind==='email'?'Email':d.channel_kind==='telegram'?'Telegram':'Thông báo'} · {eventNames[d.event_kind]||'Cảnh báo trong nhà'}</strong><p>{[d.recipient_name,d.room_name||d.camera_name,d.created_at&&dateTime(d.created_at)].filter(Boolean).join(' · ')}</p><div className="delivery-detail"><span>{d.dispatch_kind==='reminder'?`Nhắc lại lần ${d.reminder_number}`:d.dispatch_kind==='initial'?'Cảnh báo ban đầu':'Lịch sử cũ'}</span><span>{d.attempt_count||0} lần thử gửi qua nhà cung cấp</span>{mediaResultLabel(d.media_result)&&<span>{mediaResultLabel(d.media_result)}</span>}</div>{d.status==='accepted'&&<small>Dịch vụ gửi đã nhận yêu cầu; chưa xác nhận người nhận đã đọc.</small>}{d.last_error_code&&<small className="delivery-error">{notificationErrorLabel(d.last_error_code)}</small>}</div><Badge tone={status.tone}>{status.label}</Badge><a href={'#/event/'+d.event_id}>Xem sự kiện</a></article>;})}<ServerPager resource={delivery} label="thông báo"/>
        {!delivery.items.length&&<Empty title={deliveryRecipient?'Chưa có thông báo cho người nhận này':'Chưa có lịch sử gửi thông báo'} text="Các lần gửi cảnh báo qua Telegram và email sẽ xuất hiện tại đây."/>}
      </ResourceState>}
    </details>
    <details className="panel spaced settings-history" open={activityOpen} onToggle={event=>setActivityOpen(event.currentTarget.open)}><summary><ClockCounterClockwise/><span><strong>Hoạt động trong nhà</strong><small>Xem ai đã thay đổi cài đặt hoặc xử lý cảnh báo.</small></span></summary>{activityOpen&&<ResourceState resource={audit}>{audit.items.map(a=><article className="activity-history-row" key={a.id}><div><strong>{activityLabel(a.action)}</strong><small>{a.user_name||'Thành viên trong nhà'}</small></div><time>{dateTime(a.created_at)}</time></article>)}<ServerPager resource={audit} label="hoạt động"/>{!audit.items.length&&<Empty title="Chưa có hoạt động được ghi nhận"/>}</ResourceState>}</details>
    {roomEdit && <Modal title={roomEdit.id ? 'Đổi tên phòng' : 'Thêm phòng'} onClose={() => setRoomEdit(null)}><form onSubmit={async e => { e.preventDefault();try { await api(`/homes/${home.id}/rooms${roomEdit.id ? '/' + roomEdit.id : ''}`, { method: roomEdit.id ? 'PATCH' : 'POST', body: { name: new FormData(e.currentTarget).get('name') } });setRoomEdit(null);reload();notify('Đã lưu phòng.'); } catch (error) { notify(error.message); } }}><Field name="name" label="Tên phòng" required defaultValue={roomEdit.name}/><Button type="submit">Lưu phòng</Button></form></Modal>}
  </>;
}

export function Account() {
  const { user, setUser, notify, logout } = useApp();
  return <><Heading title="Tài khoản của bạn" text="Vai trò truy cập do chủ nhà cấp và được backend kiểm tra."/><section className="panel settings-form account-settings"><form className="account-profile-form" onSubmit={async e => { e.preventDefault();try { const result = await api('/account', { method: 'PATCH', body: { name: new FormData(e.currentTarget).get('name') } });setUser({ ...user, name: result.name });notify('Đã cập nhật hồ sơ.'); } catch (error) { notify(error.message); } }}><Field label="Họ và tên" name="name" required defaultValue={user.name}/><Field label="Email đã xác minh" value={user.email} readOnly/><Button type="submit">Lưu hồ sơ</Button></form><div className="account-security-section"><h2>Đổi mật khẩu</h2><p>Nhận mã xác minh qua email để đặt mật khẩu mới. Các phiên đăng nhập cũ sẽ bị thu hồi.</p><div className="account-security-actions"><Button kind="secondary-btn" onClick={() => { sessionStorage.setItem('annha-reset-email',user.email);go('/forgot'); }}>Đổi mật khẩu bằng mã</Button><Button kind="ghost danger" onClick={logout}>Đăng xuất</Button></div></div></section></>;
}
