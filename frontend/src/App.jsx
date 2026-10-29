import React, { useEffect, useState } from 'react';
import { House, SquaresFour, VideoCamera, Bell, Leaf, SpeakerHigh, DeviceMobile, Users, Gear, CaretDown, DotsThree, UserCircle, CheckCircle, X, ShieldCheck, SignOut } from '@phosphor-icons/react';
import { Landing } from './Landing';
import { Auth } from './Auth';
import { api, go, setCsrf, roleNames } from './api';
import { AppContext } from './context';
import { Logo, Button, Empty, ScreenBoundary } from './ui';
import { Homes, Setup, Overview, Cameras, CameraDetail, Devices, Environment } from './HomeScreens';
import { Events, EventDetail } from './EventScreens';
import { Reminders } from './Reminders';
import { Account, Invitation, Members, Settings } from './AdminScreens';

const nav = [['overview','Tổng quan',SquaresFour],['cameras','Camera',VideoCamera],['events','Sự kiện',Bell],['environment','Môi trường',Leaf],['reminders','Lời nhắc & âm thanh',SpeakerHigh],['devices','Thiết bị',DeviceMobile],['members','Thành viên & quyền',Users],['settings','Cài đặt',Gear]];
const emptyData = { cameras: [], rooms: [], events: [], reminders: [], loaded: {} };
export function App() {
  const [path, setPath] = useState(location.hash.slice(1) || '/');
  const [user, setUser] = useState(null), [boot, setBoot] = useState(true), [homes, setHomes] = useState([]), [homeId, setHomeId] = useState(sessionStorage.getItem('annha-active-home') || '');
  const [data, setData] = useState({ ...emptyData, homeId: null }), [dataError, setDataError] = useState(''), [tick, setTick] = useState(0), [toast, setToast] = useState(''), [menu, setMenu] = useState(false);
  const [homesError, setHomesError] = useState(''), [homesLoading, setHomesLoading] = useState(false);
  const route = path.split('?')[0], params = new URLSearchParams(path.split('?')[1] || '');
  const [section = '', id] = route.replace(/^\//, '').split('/');
  const home = homes.find(h => h.id === homeId) || homes[0] || null;
  const publicPage = ['', 'login','register','verify','forgot','reset','privacy','terms','support'].includes(section);
  const needsHomeData = !publicPage && !['homes','account','invitation'].includes(section);
  function notify(message) { setToast(message); }
  function reload() { setTick(v => v + 1); }
  function selectHome(value) { setHomeId(value);sessionStorage.setItem('annha-active-home', value);setData({ ...emptyData, homeId: null }); }
  async function reloadHomes() {
    setHomesLoading(true);
    try { const result = await api('/homes');setHomes(result);setHomesError('');return result; }
    catch (e) { setHomesError(e.message);if (e.status === 401) { setUser(null);setCsrf(''); }throw e; }
    finally { setHomesLoading(false); }
  }
  async function logout() {
    try { await api('/auth/logout', { method: 'POST', body: {} });setUser(null);setHomes([]);setData({ ...emptyData, homeId: null });setCsrf('');sessionStorage.removeItem('annha-active-home');go('/login'); }
    catch (e) { notify(e.message); }
  }
  function can(camera, action) {
    if (!camera || !home) return false;
    if (home.role === 'owner') return true;
    if (!home.scopes.includes(camera.id)) return false;
    if (action === 'view') return true;
    if (action === 'events') return home.role === 'caregiver';
    return home.role === 'caregiver' && !!home.rights[action];
  }
  useEffect(() => { const listener = () => { setPath(location.hash.slice(1) || '/');setMenu(false); };window.addEventListener('hashchange',listener);return () => window.removeEventListener('hashchange',listener); }, []);
  useEffect(() => { let active = true;api('/auth/me').then(result => { if (active) { setUser(result.user);setCsrf(result.csrf); } }).catch(() => {}).finally(() => { if (active) setBoot(false); });return () => { active = false; }; }, []);
  useEffect(() => { if (user) reloadHomes().catch(() => {}); }, [user?.id]);
  useEffect(() => { const timer = setInterval(() => { if (document.visibilityState === 'visible') reload(); },10000);return () => clearInterval(timer); }, []);
  useEffect(() => { if (!toast) return;const timer = setTimeout(() => setToast(''),6000);return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    if (!boot && !user && !publicPage) { sessionStorage.setItem('annha-after-login', path);go('/login'); }
  }, [boot,user,publicPage,path]);
  useEffect(() => {
    if (!user || !home || !needsHomeData) return;
    let active = true;
    const controller = new AbortController(), received = {}, failures = {};
    const targetHomeId = home.id;
    for (const type of ['cameras','rooms','events','reminders']) {
      api(`/homes/${targetHomeId}/${type}`, { signal: controller.signal }).then(result => {
        if (!active) return;
        received[type] = result;delete failures[type];
        setData(previous => {
          const existing = previous.targetHomeId === targetHomeId ? previous : { ...emptyData, homeId: null };
          return { ...existing, [type]: result, targetHomeId,
            homeId: received.cameras && received.rooms ? targetHomeId : existing.homeId,
            loaded: { ...existing.loaded, [type]: true } };
        });
        setDataError(Object.values(failures).join(' · '));
      }).catch(error => {
        if (!active) return;
        failures[type] = error.message;setDataError(Object.values(failures).join(' · '));
        if ([401,403,404].includes(error.status)) {
          active = false;controller.abort();setData({ ...emptyData, homeId: null });
          if (error.status === 401) { setUser(null);setCsrf(''); }
          else reloadHomes().catch(() => {});
        }
      });
    }
    return () => { active = false;controller.abort(); };
  }, [user?.id,home?.id,tick,needsHomeData]);
  useEffect(() => {
    if (!user || !home) return;
    let stopped = false, socket, timer;
    function connect() {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/alerts?home_id=${encodeURIComponent(home.id)}`);
      socket.onmessage = () => reload();
      socket.onclose = () => { if (!stopped) { reloadHomes().catch(() => {});timer = setTimeout(connect,4000); } };
    }
    connect();return () => { stopped = true;clearTimeout(timer);socket?.close(); };
  }, [user?.id,home?.id]);
  const currentData = data.homeId === home?.id ? data : emptyData;
  const value = { user, setUser, home, homes, homeId: home?.id, selectHome, reloadHomes, ...currentData, tick, reload, notify, can, logout };
  function screen() {
    if (section === 'homes') return homesError ? <div className="notice error">{homesError}<Button onClick={() => reloadHomes().catch(() => {})}>Thử lại</Button></div> : homesLoading && !homes.length ? <p>Đang tải danh sách nhà…</p> : <Homes/>;
    if (section === 'account') return <Account/>;
    if (section === 'invitation') return <Invitation token={params.get('token') || ''}/>;
    if (!home && homesError) return <div className="notice error" role="alert">{homesError}<Button kind="secondary-btn" onClick={() => reloadHomes().catch(() => {})}>Thử lại</Button></div>;
    if (!home) return homesLoading ? <p>Đang tải nhà…</p> : <Empty title="Bạn chưa tham gia nhà nào" text="Tạo nhà hoặc mở lời mời từ người thân." action={<Button onClick={() => go('/homes')}>Chọn / tạo nhà</Button>}/>;
    if (dataError && data.homeId !== home.id) return <div className="notice error" role="alert">{dataError}<Button onClick={reload}>Thử lại</Button></div>;
    if (data.homeId !== home.id) return <p>Đang tải dữ liệu nhà…</p>;
    if ((section === 'reminders' && !data.loaded.reminders)) return <div className="panel loading-state" role="status">Đang tải nội dung…</div>;
    switch (section) {
      case 'overview': return <Overview/>;
      case 'setup': return <Setup/>;
      case 'cameras': return <Cameras/>;
      case 'camera': return <CameraDetail id={id}/>;
      case 'events': case 'backend-alerts': return <Events/>;
      case 'event': return <EventDetail key={id} id={id}/>;
      case 'environment': return <Environment/>;
      case 'reminders': return <Reminders key={home.id + (id || '')} initialTab={id === 'send' ? 'send' : 'schedule'}/>;
      case 'devices': return <Devices/>;
      case 'members': return <Members/>;
      case 'settings': return <Settings key={home.id}/>;
      case 'more': return <><h1>Thêm</h1>{nav.filter(([key]) => home.role === 'owner' || !['members','settings'].includes(key)).map(([key,label,Icon]) => <a className="more-row" href={'#/' + key} key={key}><Icon/>{label}</a>)}<a className="more-row" href="#/homes">Chọn nhà</a><a className="more-row" href="#/account">Tài khoản</a></>;
      default: return <Empty title="Không tìm thấy trang" action={<Button onClick={() => go('/overview')}>Về tổng quan</Button>}/>;
    }
  }
  let content;
  if (section === '') content = <Landing/>;
  else if (['login','register','verify','forgot','reset'].includes(section)) content = <Auth key={section + (params.get('token') || '')} page={section} token={params.get('token') || ''} onLogin={setUser}/>;
  else if (['privacy','terms','support'].includes(section)) content = <main className="public-document"><Logo/><h1>{({privacy:'Quyền riêng tư',terms:'Điều khoản sử dụng',support:'Hỗ trợ AnNhà'})[section]}</h1><p>Chỉ người được cấp quyền mới có thể xem camera và dữ liệu theo nhà. Chủ nhà quản lý thành viên, thời gian lưu trữ và chia sẻ Telegram trong cài đặt.</p><p>Hệ thống hỗ trợ nhận biết tình huống cần kiểm tra, không chẩn đoán bệnh lý hoặc thay thế chăm sóc trực tiếp.</p><a href="#/">Về trang chủ</a></main>;
  else if (boot || !user) content = <main className="public-document"><Logo/><p>Đang kiểm tra phiên đăng nhập…</p></main>;
  else content = <div className="app-shell"><aside className="sidebar"><Logo href="#/overview"/><button className="home-selector" onClick={() => go('/homes')}><House/><strong>{home?.name || 'Chọn nhà'}</strong><CaretDown/></button><nav>{nav.filter(([key]) => home?.role === 'owner' || !['members','settings'].includes(key)).map(([key,label,Icon]) => <a key={key} className={section === key || (key === 'cameras' && section === 'camera') || (key === 'events' && section === 'event') ? 'active' : ''} href={'#/' + key}><Icon/><span>{label}</span></a>)}</nav><footer className="sidebar-footer"><button className="sidebar-logout" onClick={logout}><SignOut/>Đăng xuất</button><div className="sidebar-bottom"><ShieldCheck/><span>Không gian riêng của gia đình<small>{roleNames[home?.role] || 'Tài khoản đã xác minh'}</small></span></div></footer></aside><div className="app-main"><header className="topbar"><span>{nav.find(([key]) => key === section)?.[1] || 'AnNhà'}</span><div><small>{new Date().toLocaleDateString('vi-VN')}</small><button className="icon" aria-label="Thông báo" onClick={() => go('/events')}><Bell/></button><button className="icon" title="Đăng xuất" aria-label="Đăng xuất" onClick={logout}><SignOut/></button><button className="account-button" onClick={() => setMenu(!menu)}><span className="avatar small">{user.name.slice(0,1)}</span><span>{user.name}</span><CaretDown/></button></div>{menu && <div className="account-menu"><strong>{user.name}</strong><small>{user.email}</small><a href="#/account">Tài khoản</a><a href="#/homes">Chuyển nhà</a><button className="button ghost" onClick={logout}>Đăng xuất</button></div>}</header><main className="workspace">{dataError && data.homeId === home?.id && <div className="notice error" role="status">Chưa thể cập nhật dữ liệu. Nội dung gần nhất được giữ lại.<Button kind="ghost" onClick={reload}>Thử lại</Button></div>}<ScreenBoundary key={home?.id + path} onRetry={reload}>{screen()}</ScreenBoundary></main></div><nav className="bottom-nav">{[['overview','Tổng quan',SquaresFour],['cameras','Camera',VideoCamera],['events','Sự kiện',Bell],['reminders','Lời nhắc',SpeakerHigh],['more','Thêm',DotsThree]].map(([key,label,Icon]) => <a key={key} className={section === key ? 'active' : ''} href={'#/' + key}><Icon/>{label}</a>)}</nav></div>;
  return <AppContext.Provider value={value}>{content}{toast && <div className="toast" role="status"><CheckCircle/>{toast}<button className="icon" aria-label="Đóng thông báo" onClick={() => setToast('')}><X/></button></div>}</AppContext.Provider>;
}
