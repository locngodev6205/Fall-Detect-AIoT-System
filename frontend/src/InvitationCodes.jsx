import React, { useState } from 'react';
import { Copy, Key, Plus, SignIn } from '@phosphor-icons/react';
import { api, dateTime, go } from './api';
import { useApp, useResource, ResourceState } from './context';
import { Badge, Button, Empty, Field, Modal, PagedList } from './ui';

export function JoinHomeByCode({ onClose }) {
  const { reloadHomes, selectHome, notify } = useApp();
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function join(event) {
    event.preventDefault();setBusy(true);setError('');
    try {
      const result=await api('/invitation-codes/join',{method:'POST',body:{code:new FormData(event.currentTarget).get('code')}});
      await reloadHomes();selectHome(result.home_id);onClose();go('/overview');notify(`Đã tham gia ${result.home_name}.`);
    } catch(error) { setError(error.message); } finally { setBusy(false); }
  }
  return <Modal title="Tham gia nhà bằng mã" onClose={onClose}><form className="invitation-code-form" onSubmit={join}>
    <p>Nhập mã chủ nhà đã chia sẻ với bạn. Mỗi mã chỉ dành cho một người và có hiệu lực trong 7 ngày.</p>
    {error&&<div className="notice error" role="alert">{error}</div>}
    <Field label="Mã mời" name="code" placeholder="XXXX-XXXX-XXXX-XXXX" required maxLength={40} autoCapitalize="characters" autoComplete="off" spellCheck={false} className="invitation-code-input"/>
    <p className="muted">Bạn cần xác minh email trước khi tham gia. Sau khi tham gia, bạn có thể xem các camera được chia sẻ.</p>
    <div className="actions"><Button kind="secondary-btn" onClick={onClose} disabled={busy}>Huỷ</Button><Button type="submit" disabled={busy}><SignIn/>{busy?'Đang tham gia…':'Tham gia nhà'}</Button></div>
  </form></Modal>;
}

export function InvitationCodes() {
  const {home,notify,confirm}=useApp();
  const resource=useResource(`/homes/${home.id}/invitation-codes`);
  const [created,setCreated]=useState(null),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false);
  async function create() {
    setBusy(true);
    try {const result=await api(`/homes/${home.id}/invitation-codes`,{method:'POST',body:{}});setCreated(result);setCopied(false);resource.reload();}
    catch(error){notify(error.message);}finally{setBusy(false);}
  }
  async function revoke(item) {
    if(!await confirm({title:'Thu hồi mã mời?',message:'Người nhận sẽ không thể dùng mã này để tham gia nhà.',confirmLabel:'Thu hồi mã',tone:'danger'}))return;
    try {await api(`/homes/${home.id}/invitation-codes/${item.id}`,{method:'DELETE'});resource.reload();notify('Đã thu hồi mã mời.');}
    catch(error){notify(error.message);}
  }
  const names={active:'Còn hiệu lực',used:'Đã sử dụng',expired:'Đã hết hạn',revoked:'Đã thu hồi'};
  return <section className="panel spaced invitation-codes-panel">
    <header className="section-heading"><div><h2><Key/>Mã mời thành viên</h2><p>Tạo mã và chia sẻ riêng cho người thân để họ tham gia nhà.</p></div><Button onClick={create} disabled={busy}><Plus/>{busy?'Đang tạo…':'Tạo mã mời'}</Button></header>
    <ResourceState resource={resource}><PagedList items={resource.data||[]} label="mã mời" pageSize={8} resetKey={home.id}>{item=><article className="invitation-code-row" key={item.id}>
      <div><strong>Mời tham gia nhà</strong><small>Thành viên · Tạo {dateTime(item.created_at)}</small><small>{item.status==='used'?`Đã dùng ${dateTime(item.used_at)}`:`Hết hạn ${dateTime(item.expires_at)}`}</small></div>
      <Badge tone={item.status==='active'?'teal':'gray'}>{names[item.status]}</Badge>
      {item.status==='active'&&<Button kind="ghost danger" onClick={()=>revoke(item)}>Thu hồi</Button>}
    </article>}</PagedList>{!resource.data?.length&&<Empty icon={Key} title="Chưa có mã mời" text="Tạo mã để mời người thân vào nhà của bạn."/>}</ResourceState>
    {created&&<Modal title="Mã mời đã sẵn sàng" onClose={()=>setCreated(null)}><div className="invitation-code-form">
      <p>Gửi mã này riêng cho người bạn muốn mời. Họ mở trang Nhà, chọn “Tham gia nhà bằng mã” và nhập mã.</p>
      <Field label="Mã mời vừa tạo" value={created.code} readOnly className="invitation-code-input" onFocus={event=>event.target.select()}/>
      <div className="invitation-code-meta"><Badge>Thành viên</Badge><span>Hết hạn {dateTime(created.expires_at)}</span></div>
      <p className="muted">Mã chỉ hiển thị tại đây một lần và chỉ dùng được cho một người. Bạn có thể thu hồi mã chưa dùng trong danh sách.</p>
      <div className="actions"><Button kind="secondary-btn" onClick={()=>setCreated(null)}>Đóng</Button><Button onClick={async()=>{try{await navigator.clipboard.writeText(created.code);setCopied(true);}catch{notify('Hãy chọn mã rồi sao chép để chia sẻ.');}}}><Copy/>{copied?'Đã sao chép':'Sao chép mã'}</Button></div>
    </div></Modal>}
  </section>;
}
