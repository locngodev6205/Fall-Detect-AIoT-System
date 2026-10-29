import React, { useEffect, useState } from 'react';
import { WarningCircle, PersonSimple, Leaf, VideoCamera, ImageSquare } from '@phosphor-icons/react';
const eventIcons = { fall: WarningCircle, immobility: PersonSimple, environment: Leaf, device: VideoCamera };
import { api, go, dateTime, eventNames, statusNames } from './api';
import { Badge, Button, Empty, Field, Heading, Pagination, PagedList } from './ui';
import { useApp, useResource, ResourceState } from './context';

export function Events() {
  const { home, cameras, rooms, tick } = useApp();
  const [filters,setFilters]=useState({status:'',kind:'',room_id:'',camera_id:'',hours:''}),[page,setPage]=useState(1);
  const update=(key,value)=>{setFilters(previous=>({...previous,[key]:value,...(key==='room_id'?{camera_id:''}:{})}));setPage(1);};
  const query=new URLSearchParams({page:String(page),page_size:'10',...Object.fromEntries(Object.entries(filters).filter(([,value])=>value))});
  const resource=useResource(`/homes/${home.id}/events?${query}`,tick);
  const data=resource.data,rows=Array.isArray(data)?data.slice((page-1)*10,page*10):data?.items||[],total=Array.isArray(data)?data.length:data?.total||0;
  useEffect(()=>{if(data&&!Array.isArray(data)&&page>data.total_pages)setPage(Math.max(1,data.total_pages));},[data,page]);
  return <><Heading title="Sự kiện & cảnh báo" text="Theo dõi và xử lý sự kiện từ những camera được cấp quyền."/>
    <div className="filters-grid event-filters">
      <Field label="Phòng"><select value={filters.room_id} onChange={e=>update('room_id',e.target.value)}><option value="">Tất cả phòng</option>{rooms.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></Field>
      <Field label="Camera"><select value={filters.camera_id} onChange={e=>update('camera_id',e.target.value)}><option value="">Tất cả camera</option>{cameras.filter(c=>!filters.room_id||c.room_id===filters.room_id).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
      <Field label="Trạng thái"><select value={filters.status} onChange={e=>update('status',e.target.value)}><option value="">Tất cả</option>{['OPEN','ACKNOWLEDGED','RESOLVED','FALSE_ALARM'].map(s=><option key={s} value={s}>{statusNames[s]}</option>)}</select></Field>
      <Field label="Loại sự kiện"><select value={filters.kind} onChange={e=>update('kind',e.target.value)}><option value="">Tất cả</option>{Object.entries(eventNames).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></Field>
      <Field label="Thời gian"><select value={filters.hours} onChange={e=>update('hours',e.target.value)}><option value="">Tất cả thời gian</option><option value="24">24 giờ qua</option><option value="168">7 ngày qua</option><option value="720">30 ngày qua</option></select></Field>
    </div>
    <ResourceState resource={resource}>{rows.map(e=><a className="panel event-live-row" href={'#/event/'+e.id} key={e.id}><span className={'event-kind-icon '+(e.severity==='critical'?'critical-icon':'')}>{React.createElement(eventIcons[e.kind]||WarningCircle,{size:26})}</span><div className="event-row-copy"><h2>{eventNames[e.kind]}</h2><p>{e.room_name||rooms.find(r=>r.id===cameras.find(c=>c.id===e.camera_id)?.room_id)?.name||'Trong nhà'} · {e.camera_name||cameras.find(c=>c.id===e.camera_id)?.name||'Camera'} · {dateTime(e.observed_at)}</p><small>{e.payload.reason}</small></div><Badge tone={['RESOLVED','FALSE_ALARM'].includes(e.status)?'teal':e.severity==='critical'?'red':'amber'}>{statusNames[e.status]}</Badge></a>)}{!rows.length&&<Empty icon={WarningCircle} title="Chưa có sự kiện phù hợp" text="Thử thay đổi bộ lọc hoặc khoảng thời gian."/>}<Pagination page={page} pageSize={10} total={total} onChange={setPage} label="sự kiện"/></ResourceState></>;
}

export function EventDetail({ id }) {
  const { tick, cameras, can, notify, reload } = useApp();const resource = useResource('/events/' + id, tick);
  const event = resource.data;const [note, setNote] = useState(''), [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false);
  async function action(kind) {
    setBusy(true);
    try { await api('/events/' + id + '/actions', { method: 'POST', body: { action: kind, note, confirm_abnormal: confirm } });setNote('');setConfirm(false);resource.reload();reload();notify('Đã lưu thao tác xử lý.'); }
    catch (e) { notify(e.message); } finally { setBusy(false); }
  }
  const camera = event && cameras.find(c => c.id === event.camera_id);
  return <ResourceState resource={resource}>{event && <><Heading title={eventNames[event.kind]} text={`${camera?.name || 'Camera'} · ${dateTime(event.observed_at)}`} action={<Button kind="secondary-btn" onClick={() => go('/camera/' + event.camera_id)}>Mở camera</Button>}/><div className="two-grid"><section className="panel"><h2>Bằng chứng sự kiện</h2>{event.evidence.length ? event.evidence.map(asset => <div key={asset.id}>{asset.status !== 'ready' ? <p>{asset.name}: {statusNames[asset.status] || asset.status}</p> : asset.mime.startsWith('image/') ? <img className="evidence-image" src={'/api/assets/' + asset.id} alt="Ảnh bằng chứng sự kiện"/> : asset.mime.startsWith('video/') ? <video className="evidence-image" src={'/api/assets/' + asset.id} controls/> : <a href={'/api/assets/' + asset.id}>{asset.name}</a>}</div>) : <Empty icon={ImageSquare} title="Chưa có ảnh hoặc clip" text="Cảnh báo vẫn được lưu khi thiết bị chưa gửi bằng chứng."/>}<p>Hệ thống nhận: {dateTime(event.received_at)}</p></section><section className="panel"><h2>Thông tin và xử lý</h2><Badge tone={['RESOLVED','FALSE_ALARM'].includes(event.status) ? 'teal' : event.severity === 'critical' ? 'red' : 'amber'}>{statusNames[event.status]}</Badge><p>Quan sát: {({ suspected: 'Đang nghi ngờ', abnormal: 'Vẫn bất thường', recovered: 'Đã có dấu hiệu phục hồi', unknown: 'Thiếu quan sát' })[event.observation]}</p><p>{event.payload.reason || 'Thiết bị chưa cung cấp lý do chi tiết.'}</p>{event.payload.duration_s != null && <p>Thời lượng quan sát: {event.payload.duration_s} giây</p>}<p>Phiên bản cấu hình: {event.payload.config_version}</p>
      {camera && can(camera, 'events') && <><Field label="Ghi chú"><textarea value={note} onChange={e => setNote(e.target.value)} maxLength={2000}/></Field>{['suspected','abnormal'].includes(event.observation) && <label className="checkbox"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)}/>Tôi đã kiểm tra thực tế và muốn kết thúc dù quan sát vẫn bất thường.</label>}<div className="actions">{event.status === 'OPEN' && <Button disabled={busy} onClick={() => action('acknowledge')}>Tiếp nhận</Button>}{['OPEN','ACKNOWLEDGED'].includes(event.status) && <><Button kind="secondary-btn" disabled={busy} onClick={() => action('safe')}>Xác nhận an toàn</Button><Button kind="secondary-btn" disabled={busy} onClick={() => action('resolve')}>Đã xử lý</Button><Button kind="ghost" disabled={busy} onClick={() => action('false_alarm')}>Báo động giả</Button><Button kind="ghost" disabled={busy} onClick={() => action('silence')}>Tắt âm 1 phút</Button></>}<Button kind="ghost" disabled={busy || !note.trim()} onClick={() => action('note')}>Thêm ghi chú</Button></div></>}
    </section></div><section className="panel spaced"><h2>Nhật ký xử lý</h2>{<PagedList items={event.actions} label="nhật ký xử lý">{a => <div className="timeline-row" key={a.id}><span>{dateTime(a.created_at)}</span><strong>{a.user_name} · {({ acknowledge: 'Tiếp nhận', safe: 'Xác nhận an toàn', resolve: 'Đã xử lý', false_alarm: 'Báo giả', silence: 'Yêu cầu tắt âm', note: 'Ghi chú' })[a.action]}</strong><p>{a.note}</p></div>}</PagedList>}{!event.actions.length && <p>Chưa có người tiếp nhận hoặc ghi chú.</p>}</section></>}</ResourceState>;
}
