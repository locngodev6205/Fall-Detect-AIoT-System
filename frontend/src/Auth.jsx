import React, { useState } from 'react';
import { api, go, setCsrf } from './api';
import { Logo, Button, Field } from './ui';
export function Auth({ page, token, onLogin }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  const titles = { login: 'Chào mừng bạn trở lại', register: 'Tạo tài khoản AnNhà', verify: 'Xác minh email', forgot: 'Khôi phục tài khoản', reset: 'Đặt lại mật khẩu' };
  async function submit(event) {
    event.preventDefault();setBusy(true);setError('');setMessage('');
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (page === 'register' && data.password !== data.confirm) throw new Error('Mật khẩu xác nhận chưa khớp.');
      delete data.confirm;
      const body = page === 'verify' ? { token } : page === 'reset' ? { token, password: data.password } : data;
      const result = await api('/auth/' + page, { method: 'POST', body });
      if (page === 'login') { setCsrf(result.csrf);onLogin(result.user);go(sessionStorage.getItem('annha-after-login') || '/homes');sessionStorage.removeItem('annha-after-login'); }
      else { setMessage(result.message);event.target.reset(); }
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
    <form onSubmit={submit}>
      {page === 'register' && <Field label="Họ và tên" name="name" required maxLength={120} autoComplete="name"/>}
      {['login','register','forgot'].includes(page) && <Field label="Email" name="email" type="email" required autoComplete="email"/>}
      {['login','register','reset'].includes(page) && <Field label="Mật khẩu" name="password" type="password" required minLength={page === 'login' ? 1 : 10} autoComplete={page === 'login' ? 'current-password' : 'new-password'} hint={page !== 'login' ? 'Ít nhất 10 ký tự.' : undefined}/>}
      {page === 'register' && <><Field label="Nhập lại mật khẩu" name="confirm" type="password" required minLength={10} autoComplete="new-password"/><label className="checkbox"><input type="checkbox" required/>Tôi đồng ý điều khoản và chính sách riêng tư.</label></>}
      {page === 'verify' && <p>{token ? 'Xác nhận để hoàn tất xác minh tài khoản.' : 'Mở liên kết trong email để xác minh tài khoản.'}</p>}
      <Button type="submit" disabled={busy || (['verify','reset'].includes(page) && !token)}>{busy ? 'Đang xử lý…' : ({ login: 'Đăng nhập', register: 'Tạo tài khoản', forgot: 'Gửi hướng dẫn', verify: 'Xác minh email', reset: 'Lưu mật khẩu mới' }[page])}</Button>
    </form>
    {page === 'verify' && <form onSubmit={resend}><Field label="Gửi lại email xác minh" type="email" name="email" required/><Button type="submit" kind="secondary-btn" disabled={busy}>Gửi lại</Button></form>}
    <div className="auth-links"><a href="#/login">Đăng nhập</a><a href="#/register">Đăng ký</a><a href="#/forgot">Quên mật khẩu</a></div>
    <small>Kiểm tra hộp thư của bạn để nhận hướng dẫn xác minh hoặc khôi phục tài khoản.</small>
  </section><aside className="auth-visual"><img src="/images/living.png" alt="Không gian gia đình minh họa"/><div><h2>Nhà an tâm,<br/>mình an lòng.</h2><p>Thêm một cách để quan tâm người thân, mỗi ngày.</p></div></aside></div>;
}
