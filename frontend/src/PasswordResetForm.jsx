import React, {useState} from 'react';
import {api,go,setCsrf} from './api';
import {Button,Field} from './ui';

export function PasswordResetForm({legacyToken}) {
  const [step,setStep]=useState(legacyToken?3:1),[email,setEmail]=useState(()=>sessionStorage.getItem('annha-reset-email')||''),[code,setCode]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  async function send() {
    const result=await api('/auth/forgot',{method:'POST',body:{email}});
    sessionStorage.setItem('annha-reset-email',email);setCode('');setStep(2);setMessage(result.message);
  }
  async function submit(event) {
    event.preventDefault();setBusy(true);setError('');setMessage('');
    try {
      if(step===1) await send();
      else if(step===2){await api('/auth/reset/check',{method:'POST',body:{email,code}});setStep(3);}
      else {
        const fields=new FormData(event.currentTarget);
        if(fields.get('password')!==fields.get('confirm'))throw new Error('Mật khẩu xác nhận chưa khớp.');
        const result=await api('/auth/reset',{method:'POST',body:{...(legacyToken?{token:legacyToken}:{email,code}),password:fields.get('password')}});
        setCsrf('');setCode('');sessionStorage.removeItem('annha-reset-email');setMessage(result.message);setStep(4);
      }
    }catch(error){setError(error.message);}finally{setBusy(false);}
  }
  async function resend(){setBusy(true);setError('');setMessage('');try{await send();}catch(error){setError(error.message);}finally{setBusy(false);}}
  return <div className="password-reset-flow">
    {!legacyToken&&step<4&&<ol className="reset-steps" aria-label="Các bước đặt lại mật khẩu">{['Email','Mã xác minh','Mật khẩu mới'].map((label,index)=><li key={label} aria-current={step===index+1?'step':undefined} className={step===index+1?'active':''}><span>{index+1}</span>{label}</li>)}</ol>}
    {error&&<div className="notice error" role="alert">{error}</div>}{message&&<div className="notice success" role="status">{message}</div>}
    {step<4?<form onSubmit={submit} className="reset-step-form">
      {step===1&&<><p>Nhập email tài khoản. AnNhà sẽ gửi mã 8 chữ số để bạn đặt mật khẩu mới.</p><Field label="Email" name="email" type="email" value={email} onChange={event=>setEmail(event.target.value)} required autoComplete="email"/></>}
      {step===2&&<><p>Nhập mã đã gửi đến <strong>{email}</strong>. Mã có hiệu lực trong 15 phút.</p><Field label="Mã đặt lại mật khẩu" value={code} onChange={event=>setCode(event.target.value)} name="code" inputMode="numeric" pattern="[0-9]{8}" maxLength={8} minLength={8} autoComplete="one-time-code" required className="verification-code-input"/></>}
      {step===3&&<><p>Chọn mật khẩu mới cho tài khoản. Các phiên đăng nhập cũ sẽ được kết thúc.</p><Field label="Mật khẩu mới" name="password" type="password" minLength={10} maxLength={256} required autoComplete="new-password" hint="Ít nhất 10 ký tự."/><Field label="Xác nhận mật khẩu mới" name="confirm" type="password" minLength={10} maxLength={256} required autoComplete="new-password"/></>}
      <Button type="submit" disabled={busy}>{busy?'Đang xử lý…':step===1?'Gửi mã đặt lại mật khẩu':step===2?'Xác nhận mã':'Lưu mật khẩu mới'}</Button>
      {step===1&&<Button kind="secondary-btn" disabled={busy} onClick={event=>{if(event.currentTarget.form.reportValidity()){setStep(2);setError('');setMessage('');}}}>Tôi đã có mã</Button>}
    </form>:<Button onClick={()=>go('/login')}>Đăng nhập bằng mật khẩu mới</Button>}
    {!legacyToken&&step>1&&step<4&&<div className="reset-flow-actions"><Button kind="ghost" disabled={busy} onClick={resend}>Gửi lại mã</Button><Button kind="ghost" disabled={busy} onClick={()=>{setStep(step===3?2:1);setError('');setMessage('');}}> {step===3?'Nhập lại mã':'Đổi email'}</Button></div>}
  </div>;
}
