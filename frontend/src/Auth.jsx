import React, { useState } from 'react';
import { api, go, setCsrf } from './api';
import { Logo, Button, Field } from './ui';
import { PasswordResetForm } from './PasswordResetForm';
export function Auth({ page, token, onLogin }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  const [verifyEmail, setVerifyEmail] = useState(() => page === 'verify' ? sessionStorage.getItem('annha-verify-email') || '' : '');
  const [verified, setVerified] = useState(false);
  const titles = { login: 'Chào mừng bạn trở lại', register: 'Tạo tài khoản AnNhà', verify: 'Xác minh email', forgot: 'Khôi phục tài khoản', reset: 'Đặt lại mật khẩu' };
  async function submit(event) {
    event.preventDefault();setBusy(true);setError('');setMessage('');
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (page === 'register' && data.password !== data.confirm) throw new Error('Mật khẩu xác nhận chưa khớp.');
      delete data.confirm;
      const body = page === 'verify' ? (token ? { token } : { code: data.code }) : page === 'reset' ? { token, password: data.password } : data;
      const result = await api('/auth/' + page, { method: 'POST', body });
      if (page === 'login') { setCsrf(result.csrf);onLogin(result.user);go(sessionStorage.getItem('annha-after-login') || '/homes');sessionStorage.removeItem('annha-after-login'); }
      else if (page === 'register') {
        sessionStorage.setItem('annha-verify-email', data.email);
        go('/verify');
      } else {
        setMessage(result.message);event.target.reset();
        if (page === 'verify') { setVerified(true);sessionStorage.removeItem('annha-verify-email'); }
      }
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function resend(event) {
    event.preventDefault();setBusy(true);
    try { const data = await api('/auth/resend', { method: 'POST', body: { email: new FormData(event.currentTarget).get('email') } });setMessage(data.message); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <div className="auth-page"><section className="auth-card"><Logo/><h1>{titles[page]}</h1>
    <p>Chỉ bạn và người thân được cấp quyền mới có thể truy cập camera.</p>
    {error && <div className="notice error" role="alert">{error}</div>}{message && <div className="notice success" role="status">{message}</div>}
    {['forgot','reset'].includes(page)?<PasswordResetForm key={page+token} legacyToken={token}/>:<form onSubmit={submit}>
      {page === 'register' && <Field label="Họ và tên" name="name" required maxLength={120} autoComplete="name"/>}
      {['login','register','forgot'].includes(page) && <Field label="Email" name="email" type="email" required autoComplete="email"/>}
      {['login','register','reset'].includes(page) && <Field label="Mật khẩu" name="password" type="password" required minLength={page === 'login' ? 1 : 10} autoComplete={page === 'login' ? 'current-password' : 'new-password'} hint={page !== 'login' ? 'Ít nhất 10 ký tự.' : undefined}/>}
      {page === 'register' && <><Field label="Nhập lại mật khẩu" name="confirm" type="password" required minLength={10} autoComplete="new-password"/><label className="checkbox"><input type="checkbox" required/>Tôi đồng ý điều khoản và chính sách riêng tư.</label></>}
      {page === 'verify' && (token ? <p>Xác nhận để hoàn tất xác minh tài khoản.</p> : <>
        <p>{verifyEmail ? `Nhập mã gồm 8 chữ số đã gửi tới ${verifyEmail}.` : 'Nhập mã gồm 8 chữ số trong email xác minh.'}</p>
        {!verified && <Field label="Mã xác minh" name="code" inputMode="numeric" pattern="[0-9]{8}" maxLength={8} minLength={8} autoComplete="one-time-code" required className="verification-code-input"/>}
      </>)}
      {!verified && <Button type="submit" disabled={busy || (page === 'reset' && !token)}>{busy ? 'Đang xử lý…' : ({ login: 'Đăng nhập', register: 'Tạo tài khoản', verify: token ? 'Xác minh email' : 'Xác nhận mã', forgot: 'Gửi hướng dẫn', reset: 'Lưu mật khẩu mới' }[page])}</Button>}
      {verified && <Button type="button" kind="secondary-btn" onClick={() => go('/login')}>Đăng nhập</Button>}
    </form>}
    {page === 'verify' && !token && !verified && <form onSubmit={resend}><Field label="Gửi lại mã đến email" type="email" name="email" defaultValue={verifyEmail} required/><Button type="submit" kind="secondary-btn" disabled={busy}>Gửi lại mã</Button></form>}
    <div className="auth-links"><a href="#/login">Đăng nhập</a><a href="#/register">Đăng ký</a><a href="#/forgot">Quên mật khẩu</a></div>
    <small>Kiểm tra hộp thư của bạn để nhận hướng dẫn xác minh hoặc khôi phục tài khoản.</small>
  </section><aside className="auth-visual"><img src="/images/living.png" alt="Không gian gia đình minh họa"/><div><h2>Nhà an tâm,<br/>mình an lòng.</h2><p>Thêm một cách để quan tâm người thân, mỗi ngày.</p></div></aside></div>;
}
