import React, { useEffect, useState } from 'react';
import { WarningCircle, PersonSimple, Leaf, VideoCamera, ImageSquare } from '@phosphor-icons/react';
const eventIcons = { fall: WarningCircle, immobility: PersonSimple, environment: Leaf, device: VideoCamera };
import { deliveryLabel } from './activityLabels';
import { api, go, dateTime, eventNames, statusNames } from './api';
import { Badge, Button, Empty, Field, Heading, Pagination } from './ui';
import {useServerPage,ServerPager} from './serverPaging';
import { useApp, useResource, ResourceState } from './context';

const emptyFilters = { status:'', kind:'', room_id:'', camera_id:'', hours:'', start:'', end:'', severity:'', active_only:'' };

export function Events({initialStatus=''}) {
  const { home, cameras, rooms, can, alertTick, reloadAlerts, reload, notify } = useApp();
  const [filters,setFilters]=useState({...emptyFilters,status:initialStatus}),[page,setPage]=useState(1),[busy,setBusy]=useState(false);
  useEffect(()=>{setFilters(previous=>({...previous,status:initialStatus,active_only:''}));setPage(1);},[initialStatus]);
  const update=(key,value)=>{setFilters(previous=>({...previous,active_only:'',[key]:value,...(key==='room_id'?{camera_id:''}:{}),...(key==='hours'?{start:'',end:''}:key==='start'||key==='end'?{hours:''}:{})}));setPage(1);};
  function clearFilters() {
    setFilters(emptyFilters);
    setPage(1);
  }
  function showOtaBlockers() {
    if (!filters.camera_id) return;
    setFilters({...emptyFilters,camera_id:filters.camera_id,active_only:'true'});
    setPage(1);
  }
  const query=new URLSearchParams({page:String(page),page_size:'10',...Object.fromEntries(Object.entries(filters).filter(([,value])=>value).map(([key,value])=>[key,['start','end'].includes(key)?new Date(value).toISOString():value]))});
  const resource=useResource(`/homes/${home.id}/events?${query}`,alertTick);
  async function markRead(event){setBusy(true);try{await api('/events/'+event.id+'/read',{method:'POST',body:{}});resource.reload();reloadAlerts();reload();notify(event.status==='OPEN'&&can(cameras.find(c=>c.id===event.camera_id),'events')?'Đã đọc và tiếp nhận sự kiện.':'Đã đánh dấu sự kiện đã đọc.');}catch(error){notify(error.message);}finally{setBusy(false);}}
  async function markAll(){setBusy(true);try{const result=await api('/homes/'+home.id+'/events/read-all',{method:'POST',body:{}});resource.reload();reloadAlerts();reload();notify(`Đã đánh dấu ${result.read_count} sự kiện đã đọc.`);}catch(error){notify(error.message);}finally{setBusy(false);}}
  const data=resource.data,rows=Array.isArray(data)?data.slice((page-1)*10,page*10):data?.items||[],total=Array.isArray(data)?data.length:data?.total||0;
  useEffect(()=>{if(data&&!Array.isArray(data)&&page>data.total_pages)setPage(Math.max(1,data.total_pages));},[data,page]);
  return <><Heading title="Sự kiện & cảnh báo" text="Xem bằng chứng và đánh dấu đã đọc để tiếp nhận sự kiện." action={<Button disabled={busy} onClick={markAll}>Đánh dấu mọi sự kiện đang mở đã đọc</Button>}/>
    <div className="filters-grid event-filters">
      <Field label="Phòng"><select value={filters.room_id} onChange={e=>update('room_id',e.target.value)}><option value="">Tất cả phòng</option>{rooms.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
      <Field label="Camera"><select value={filters.camera_id} onChange={e=>update('camera_id',e.target.value)}><option value="">Tất cả camera</option>{cameras.filter(c=>!filters.room_id||c.room_id===filters.room_id).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <Field label="Trạng thái"><select value={filters.status} onChange={e=>update('status',e.target.value)}><option value="">Tất cả</option>{['OPEN','ACKNOWLEDGED','RESOLVED','FALSE_ALARM'].map(s=><option key={s} value={s}>{statusNames[s]}</option>)}</select></Field>
      <Field label="Loại sự kiện"><select value={filters.kind} onChange={e=>update('kind',e.target.value)}><option value="">Tất cả</option>{Object.entries(eventNames).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></Field>
      <Field label="Thời gian"><select value={filters.hours} onChange={e=>update('hours',e.target.value)}><option value="">Tất cả thời gian</option><option value="24">24 giờ qua</option><option value="168">7 ngày qua</option><option value="720">30 ngày qua</option></select></Field>
      <Field label="Mức cảnh báo"><select value={filters.severity} onChange={e=>update('severity',e.target.value)}><option value="">Tất cả mức độ</option><option value="info">Thông tin</option><option value="warning">Trung bình</option><option value="critical">Nghiêm trọng</option></select></Field>
      <Field label="Từ ngày giờ"><input type="datetime-local" value={filters.start} onChange={e=>update('start',e.target.value)}/></Field>
      <Field label="Đến trước ngày giờ"><input type="datetime-local" min={filters.start} value={filters.end} onChange={e=>update('end',e.target.value)}/></Field>
    </div>
    <div className="actions">
      <Button kind="secondary-btn" onClick={clearFilters} disabled={!Object.values(filters).some(Boolean)}>Xóa bộ lọc</Button>
      <Button kind="secondary-btn" onClick={showOtaBlockers} disabled={!filters.camera_id} aria-pressed={!!filters.active_only}>Cảnh báo đang chặn OTA</Button>
    </div>
    {filters.active_only ? <p className="muted" role="status">Đang xem cảnh báo Đang mở và Đã tiếp nhận của camera đã chọn.</p>
      : !filters.camera_id && <p className="muted">Chọn một camera để xem cảnh báo đang chặn OTA.</p>}
    <ResourceState resource={resource}>{rows.map(e=><article className="panel event-live-row" key={e.id}><span className={'event-kind-icon '+(e.severity==='critical'?'critical-icon':'')}>{React.createElement(eventIcons[e.kind]||WarningCircle,{size:26})}</span><div className="event-row-copy"><a href={'#/event/'+e.id}><h2>{e.report?.title || eventNames[e.kind]}</h2></a><p>{e.room_name||rooms.find(r=>r.id===cameras.find(c=>c.id===e.camera_id)?.room_id)?.name||'Trong nhà'} · {e.camera_name||cameras.find(c=>c.id===e.camera_id)?.name||'Camera'} · {e.report?.observed || dateTime(e.observed_at)}</p>
      {e.report?.severity && <small>{e.report.severity}</small>}
      {e.report?.facts?.length > 0 && <p>{e.report.facts.slice(0, 2).map(([label, value]) => `${label} ${value}`).join(' · ')}</p>}
      <small>{e.payload.reason}</small>
      {can(cameras.find(c=>c.id===e.camera_id),'events') && <EventClosingControls
        event={e} notify={notify} disabled={busy}
        onSaved={() => { resource.reload(); reloadAlerts(); reload(); }}/>}
      </div><Badge tone={['RESOLVED','FALSE_ALARM'].includes(e.status)?'teal':e.severity==='critical'?'red':'amber'}>{e.is_read?'Đã đọc · ':''}{statusNames[e.status]}</Badge>{!e.is_read&&<Button kind="secondary-btn" disabled={busy} onClick={()=>markRead(e)}>Đánh dấu đã đọc</Button>}</article>)}{!rows.length&&<Empty icon={WarningCircle} title="Chưa có sự kiện phù hợp" text={filters.active_only ? "Camera này không còn sự kiện đang mở hoặc đã tiếp nhận." : "Thử thay đổi bộ lọc hoặc khoảng thời gian."}/>}<Pagination page={page} pageSize={10} total={total} onChange={setPage} label="sự kiện"/></ResourceState></>;
}

function EvidenceImage({asset}) {
  const [unavailable,setUnavailable]=useState(false);
  if(unavailable)return <div className="evidence-unavailable" role="status"><ImageSquare/><strong>Ảnh không khả dụng</strong><span>Thông tin sự kiện vẫn được lưu.</span></div>;
  return <img className="evidence-image" src={'/api/assets/'+asset.id} alt="Ảnh bằng chứng sự kiện" onError={()=>setUnavailable(true)}/>;
}

const observationLabels = {
  suspected: 'Đang nghi ngờ', abnormal: 'Vẫn bất thường',
  recovered: 'Có dấu hiệu phục hồi', unknown: 'Thiếu quan sát',
};
const severityLabels = { info: 'Thông tin', warning: 'Trung bình', critical: 'Nghiêm trọng' };
const closingLabels = { safe: 'Xác nhận đã an toàn', false_alarm: 'Xác nhận báo động giả' };

function EventClosingControls({ event, notify, onSaved, disabled = false }) {
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const active = ['OPEN', 'ACKNOWLEDGED'].includes(event.status);
  const needsConfirm = ['abnormal', 'suspected'].includes(event.observation);

  function choose(next) {
    setAction(next);
    setNote('');
    setConfirmed(false);
    setError('');
  }

  async function closeEvent(submitEvent) {
    submitEvent.preventDefault();
    if (!active || !action || busy || disabled) return;
    if (needsConfirm && (!confirmed || !note.trim())) {
      setError('Hãy xác nhận đã kiểm tra tình trạng và nhập ghi chú xử lý.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result = await api('/events/' + event.id + '/actions', {
        method: 'POST', body: { action, note: note.trim(), confirm_abnormal: needsConfirm && confirmed },
      });
      onSaved(result);
      choose('');
      notify(action === 'safe' ? 'Đã kết thúc sự kiện.' : 'Đã ghi nhận báo động giả.');
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  if (!active) return null;
  return <div className="event-close-controls">
    {!action && <div className="actions">
        {Object.entries(closingLabels).map(([value, label]) =>
          <Button key={value} kind="secondary-btn" disabled={busy || disabled} onClick={() => choose(value)}>{label}</Button>)}
    </div>}
      {action && <form onSubmit={closeEvent}>
        <h3>{closingLabels[action]}</h3>
        <Field label={needsConfirm ? 'Ghi chú xử lý (bắt buộc)' : 'Ghi chú xử lý'}>
          <textarea value={note} onChange={e => setNote(e.target.value)} maxLength={2000} required={needsConfirm} disabled={busy}/>
        </Field>
        {needsConfirm && <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} required disabled={busy}/>
          Tôi đã kiểm tra tình trạng và xác nhận có thể kết thúc cảnh báo.</label>}
        <div className="actions">
          <Button type="submit" disabled={busy}>{busy ? 'Đang lưu…' : 'Xác nhận kết thúc'}</Button>
          <Button kind="secondary-btn" disabled={busy} onClick={() => choose('')}>Hủy</Button>
        </div>
      </form>}
    {error && <p className="notice error" role="alert">{error}</p>}
  </div>;
}

export function EventDetail({ id }) {
  const { alertTick, cameras, can, notify, reloadAlerts, reload } = useApp();
  const resource = useResource('/events/' + id, alertTick);
  const updates = useServerPage('/events/' + id + '/updates', alertTick);
  return <ResourceState resource={resource}>{resource.data && <EventRecord key={id}
    record={resource.data} updates={updates} camera={cameras.find(c => c.id === resource.data.camera_id)}
    can={can} notify={notify} refresh={() => { resource.reload(); updates.reload(); reloadAlerts(); reload(); }}/>}</ResourceState>;
}

function EventDeliveryHistory({ eventId }) {
  const { home, alertTick } = useApp();
  const deliveries = useServerPage(`/homes/${home.id}/delivery-status?event_id=${encodeURIComponent(eventId)}`, alertTick);
  const mediaLabels = {sent:'Kèm bằng chứng', text_fallback:'Đã gửi chữ thay ảnh', missing:'Chưa có ảnh',
    unavailable:'Ảnh không khả dụng', consent_disabled:'Chưa có đồng ý gửi ảnh', not_requested:'Không kèm ảnh'};
  return <section className="panel spaced">
    <h2>Lịch sử thông báo</h2>
    <ResourceState resource={deliveries}>
      {deliveries.items.map(entry => {
        const status = deliveryLabel(entry.status);
        return <article className="notification-history-row" key={entry.id}>
          <div>
            <strong>{entry.channel_kind === 'email' ? 'Email' : 'Telegram'} · {entry.recipient_name}</strong>
            <p>{[dateTime(entry.delivered_at || entry.last_dispatch_at || entry.created_at),
              mediaLabels[entry.media_result], entry.last_error_code].filter(Boolean).join(' · ')}</p>
          </div>
          <Badge tone={status.tone}>{status.label}</Badge>
        </article>;
      })}
      {!deliveries.items.length && <p>Chưa có lịch sử gửi cho sự kiện này.</p>}
      <ServerPager resource={deliveries} label="thông báo"/>
    </ResourceState>
  </section>;
}

function EventRecord({ record, updates, camera, can, notify, refresh }) {
  const { home } = useApp();
  const [saved, setSaved] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const event = saved?.base === record ? saved.event : record;
  const active = ['OPEN', 'ACKNOWLEDGED'].includes(event.status);
  const canHandle = can(camera, 'events');

  async function markRead() {
    setBusy(true);
    setError('');
    try {
      await api('/events/' + event.id + '/read', { method: 'POST', body: {} });
      setSaved({ base: record, event: { ...event, is_read: true } });
      notify('Đã đánh dấu sự kiện đã đọc.');
      refresh();
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }

  return <>
    <Heading title={event.report?.title || eventNames[event.kind]} text={
      [event.home_name, event.room_name, event.camera_name || camera?.name,
        event.report?.observed || dateTime(event.observed_at)].filter(Boolean).join(' · ')
    }
      action={<Button kind="secondary-btn" onClick={() => go('/events')}>← Quay lại sự kiện</Button>}/>
    <div className="two-grid">
      <section className="panel">
        <h2>Bằng chứng sự kiện</h2>
        {event.evidence.length ? event.evidence.map(asset => <div key={asset.id}>
          {asset.status !== 'ready' ? <div className="evidence-unavailable" role="status"><ImageSquare/>
            <strong>{({failed:'Không thể tải bằng chứng',expired:'Bằng chứng đã hết hạn',deleted:'Bằng chứng đã được xóa',deleting:'Bằng chứng đang được xóa',uploading:'Đang tải bằng chứng',processing:'Đang xử lý bằng chứng'})[asset.status] || 'Bằng chứng chưa sẵn sàng'}</strong>
            <span>{asset.name}</span></div>
            : asset.mime.startsWith('image/') ? <EvidenceImage asset={asset}/>
            : asset.mime.startsWith('video/') ? <video className="evidence-image" src={'/api/assets/' + asset.id} controls/>
            : <a href={'/api/assets/' + asset.id}>{asset.name}</a>}
          {asset.created_at && <small>Đã lưu bằng chứng lúc {dateTime(asset.created_at)}</small>}
        </div>) : <Empty icon={ImageSquare} title="Chưa có ảnh hoặc clip" text="Cảnh báo vẫn được lưu khi thiết bị chưa gửi bằng chứng."/>}
        <p>Hệ thống nhận lúc {event.report?.received || dateTime(event.received_at)}</p>
      </section>
      <section className="panel">
        <h2>Thông tin sự kiện</h2>
        <Badge tone={!active ? 'teal' : event.severity === 'critical' ? 'red' : 'amber'}>{statusNames[event.status]}</Badge>
        {event.report?.severity && <p>Mức độ · {event.report.severity}</p>}
        {event.report?.source && <p>Nguồn phát hiện · {event.report.source}</p>}
        <p>Quan sát hiện tại · {observationLabels[event.observation]}</p>
        <p>{event.payload.reason || 'Thiết bị chưa cung cấp lý do chi tiết.'}</p>
        {event.report?.facts?.length > 0 && <dl>
          {event.report.facts.map(([label, value]) => <div className="setting-row" key={label}>
            <dt>{label}</dt><dd>{value}</dd>
          </div>)}
        </dl>}
        {!event.report?.facts?.length && event.payload.duration_s != null && <p>Thời lượng quan sát · {event.payload.duration_s} giây</p>}
        {event.report?.guidance && <><h3>Hướng xử lý</h3><p>{event.report.guidance}</p></>}
        <p>{event.is_read ? 'Bạn đã đọc sự kiện này.' : 'Sự kiện chưa được bạn đánh dấu đã đọc.'}</p>
      </section>
    </div>
    <section className="panel spaced">
      <h2>Xử lý sự kiện</h2>
      {active && <p>Cảnh báo đang hoạt động cho tới khi được kết thúc.</p>}
      <div className="actions">
        {!event.is_read && <Button kind="secondary-btn" disabled={busy} onClick={markRead}>Đánh dấu đã đọc</Button>}
      </div>
      {canHandle && <EventClosingControls event={event} notify={notify} disabled={busy}
        onSaved={result => {
          setSaved({ base: record, event: { ...result, is_read: event.is_read } });
          refresh();
        }}/>}
      {error && <p className="notice error" role="alert">{error}</p>}
      {!!event.actions?.length && <ul>
        {event.actions.map(entry => <li key={entry.id}>
          {dateTime(entry.created_at)} · {entry.user_name || 'Người xử lý'} · {closingLabels[entry.action] ||
            ({ acknowledge:'Đã tiếp nhận', resolve:'Đã xử lý', note:'Ghi chú', silence:'Tạm tắt âm báo' })[entry.action]}
          {entry.note && <p>{entry.note}</p>}
        </li>)}
      </ul>}
    </section>
    {home.role === "owner" && event.report && <EventDeliveryHistory eventId={event.id}/>}
    <section className="panel spaced">
      <h2>Diễn biến quan sát</h2>
      <ResourceState resource={updates}>
        {updates.items.map(update => <article className="timeline-row observation-row" key={update.sequence}>
          <span>{dateTime(update.observed_at)} · Lần {update.sequence}</span>
          <strong>{observationLabels[update.observation]} · {severityLabels[update.severity]}</strong>
          <p>{update.payload?.reason || '—'}</p>
          <small>Nhận lúc {dateTime(update.received_at)}</small>
        </article>)}
        {!updates.error && !updates.items.length && <p>Chưa có diễn biến quan sát bổ sung.</p>}
        <ServerPager resource={updates} label="diễn biến"/>
      </ResourceState>
    </section>
  </>;
}
