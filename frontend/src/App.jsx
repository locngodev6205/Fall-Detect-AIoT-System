import React, { useEffect, useRef, useState } from 'react';
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
import { canCamera } from './cameraPermissions';
import {useAlertSound} from './alertSound';
import { AlertPopover } from './AlertPopover';
import { useConfirmation } from './confirmation';

const nav = [['overview','Tổng quan',SquaresFour],['cameras','Camera',VideoCamera],['events','Sự kiện',Bell],['environment','Môi trường',Leaf],['reminders','Lời nhắc & âm thanh',SpeakerHigh],['devices','Thiết bị',DeviceMobile],['members','Thành viên & quyền',Users],['settings','Cài đặt',Gear]];
const emptyData = { cameras: [], rooms: [], events: [], reminders: [], loaded: {} };
export function App() {
  const { confirm, dialog } = useConfirmation();
  const [path, setPath] = useState(location.hash.slice(1) || '/');
  const [user, setUser] = useState(null), [boot, setBoot] = useState(true), [homes, setHomes] = useState([]), [homeId, setHomeId] = useState(sessionStorage.getItem('annha-active-home') || '');
  const alertSound=useAlertSound(user?.id);
  const [data, setData] = useState({ ...emptyData, homeId: null }), [dataError, setDataError] = useState(''), [tick, setTick] = useState(0), [alertTick, setAlertTick] = useState(0), [activeAlerts, setActiveAlerts] = useState({ count: 0, items: [] }), [alertOpen, setAlertOpen] = useState(false), [toast, setToast] = useState(''), [menu, setMenu] = useState(false);
  const [readingAlertId,setReadingAlertId]=useState('');
  const knownAlertIds = useRef(null);
  const activeHomeRef = useRef(null);
  const alertSessionRef = useRef(0), alertRequestRef = useRef(0), alertBaselineRef = useRef(null);
  const [homesError, setHomesError] = useState(''), [homesLoading, setHomesLoading] = useState(false);
  const route = path.split('?')[0], params = new URLSearchParams(path.split('?')[1] || '');
  const [section = '', id] = route.replace(/^\//, '').split('/');
  const home = homes.find(h => h.id === homeId) || homes[0] || null;
  activeHomeRef.current = home?.id || null;
  const publicPage = ['', 'login','register','verify','forgot','reset','privacy','terms','support'].includes(section);
  const homeDataPlan=['cameras','rooms',...(['overview'].includes(section)?['events']:[]),...(['overview','reminders'].includes(section)?['reminders']:[])].join(',');
  const needsHomeData = !publicPage && !['homes','account','invitation'].includes(section);
  function notify(message) { setToast(message); }
  function reload() { setTick(v => v + 1); }
  async function reloadAlerts(targetHome = home?.id, announce = false) {
    if (!targetHome || activeHomeRef.current !== targetHome) return;
    const session = alertSessionRef.current, request = ++alertRequestRef.current;
    try {
      const summary = await api(`/homes/${targetHome}/active-events?page_size=5`);
      if (activeHomeRef.current !== targetHome || session !== alertSessionRef.current || request !== alertRequestRef.current) return;
      const previous = knownAlertIds.current;
      if (announce && previous) {
        const incoming = summary.items.find(event => event.status === 'OPEN' && !previous.has(event.id)
          && Date.parse(event.first_observed_at || event.observed_at) > alertBaselineRef.current);
        if (incoming) { notify(`Cảnh báo mới: ${incoming.camera_name || 'camera'} · ${incoming.reason || 'cần kiểm tra'}`);alertSound.play(); }
      }
      if (!previous) alertBaselineRef.current = Date.parse(summary.as_of) || Date.now();
      const ids = previous || new Set();
      summary.items.forEach(event => ids.add(event.id));
      knownAlertIds.current = ids;
      setActiveAlerts(summary);
    } catch (error) {
      if (activeHomeRef.current !== targetHome || session !== alertSessionRef.current || request !== alertRequestRef.current) return;
      if ([401,403,404].includes(error.status)) {
        setActiveAlerts({ count: 0, items: [] });setToast('');
        setData({ ...emptyData, homeId: null });
        if (error.status === 401) { setUser(null);setCsrf(''); }
        else reloadHomes().catch(() => {});
      }
      // A network outage preserves the last authorized summary until reconnect.
    }
  }
  async function markAlertRead(eventId) {
    if (readingAlertId) return;
    const targetHome=home?.id;
    setReadingAlertId(eventId);
    try {
      await api('/events/'+eventId+'/read',{method:'POST',body:{}});
      if (activeHomeRef.current !== targetHome) return;
      setActiveAlerts(previous => {
        const wasUnread=previous.items.some(item=>item.id===eventId&&!item.is_read);
        return {...previous,unread_count:Math.max(0,(previous.unread_count??previous.count??0)-(wasUnread?1:0)),
          items:previous.items.map(item=>item.id===eventId?{...item,is_read:true}:item)};
      });
      reloadAlerts(targetHome);reload();
    } catch (error) { if (activeHomeRef.current === targetHome) notify(error.message); }
    finally { setReadingAlertId(''); }
  }
  async function markAllAlertsRead() {
    if (readingAlertId || !home) return;
    const targetHome=home.id;setReadingAlertId('all');
    try { await api('/homes/'+targetHome+'/events/read-all',{method:'POST',body:{}});if(activeHomeRef.current===targetHome){reloadAlerts(targetHome);reload();} }
    catch(error){if(activeHomeRef.current===targetHome)notify(error.message);}
    finally{setReadingAlertId('');}
  }
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
    return canCamera(camera, action);
  }
  useEffect(() => { const listener = () => { setPath(location.hash.slice(1) || '/');setMenu(false); };window.addEventListener('hashchange',listener);return () => window.removeEventListener('hashchange',listener); }, []);
  useEffect(() => { let active = true;api('/auth/me').then(result => { if (active) { setUser(result.user);setCsrf(result.csrf); } }).catch(() => {}).finally(() => { if (active) setBoot(false); });return () => { active = false; }; }, []);
  useEffect(() => { if (user) reloadHomes().catch(() => {}); }, [user?.id]);
  useEffect(() => { alertSessionRef.current++;alertRequestRef.current++;alertBaselineRef.current=null;knownAlertIds.current = null;setActiveAlerts({ count: 0, items: [] });setAlertOpen(false);setReadingAlertId('');setToast(''); }, [home?.id,user?.id]);
  useEffect(() => { const timer = setInterval(() => { if (document.visibilityState === 'visible' && !['events','event'].includes(section)) reload(); },10000);return () => clearInterval(timer); }, [section]);
  useEffect(() => { if (!toast) return;const timer = setTimeout(() => setToast(''),6000);return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    if (!boot && !user && !publicPage) { sessionStorage.setItem('annha-after-login', path);go('/login'); }
  }, [boot,user,publicPage,path]);
  useEffect(() => {
    if (!user || !home || !needsHomeData) return;
    let active = true;
    const controller = new AbortController(), received = {}, failures = {};
    const targetHomeId = home.id;
    for (const type of homeDataPlan.split(',')) {
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
  }, [user?.id,home?.id,tick,needsHomeData,homeDataPlan]);
  useEffect(() => {
    if (!user || !home) return;
    let stopped = false, socket, timer;
    const homeKey = home.id;
    const poll = setInterval(() => { if (document.visibilityState === 'visible') reloadAlerts(homeKey,true); },10000);
    function connect() {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/alerts?home_id=${encodeURIComponent(home.id)}`);
      socket.onmessage = () => { if (!stopped) { setAlertTick(v => v + 1);reloadAlerts(homeKey,true); } };
      socket.onclose = event => {
        if (stopped) return;
        if (event.code === 1008) {
          alertRequestRef.current++;setActiveAlerts({ count: 0, items: [] });setToast('');
          setData({ ...emptyData, homeId: null });reload();reloadHomes().catch(() => {});
        }
        timer = setTimeout(async () => { await reloadAlerts(homeKey,event.code !== 1008);if (!stopped) connect(); },4000);
      };
    }
    reloadAlerts(homeKey).finally(() => { if (!stopped) connect(); });
    return () => { stopped = true;clearInterval(poll);clearTimeout(timer);socket?.close(); };
  }, [user?.id,home?.id]);
  const currentData = data.homeId === home?.id ? data : emptyData;
  const unreadAlertCount=activeAlerts.unread_count??activeAlerts.count;
  const value = { user, setUser, home, homes, homeId: home?.id, selectHome, reloadHomes, ...currentData, tick, alertTick, reloadAlerts, reload, notify, confirm, can, logout };
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
      case 'events': case 'backend-alerts': return <Events initialStatus={params.get('status')||''}/>;
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
  else content = <div className="app-shell"><aside className="sidebar"><Logo href="#/overview"/><button className="home-selector" onClick={() => go('/homes')}><House/><strong>{home?.name || 'Chọn nhà'}</strong><CaretDown/></button><nav>{nav.filter(([key]) => home?.role === 'owner' || !['members','settings'].includes(key)).map(([key,label,Icon]) => <a key={key} className={section === key || (key === 'cameras' && section === 'camera') || (key === 'events' && section === 'event') ? 'active' : ''} href={'#/' + key}><Icon/><span>{label}</span></a>)}</nav><footer className="sidebar-footer"><button className="sidebar-logout" onClick={logout}><SignOut/>Đăng xuất</button><div className="sidebar-bottom"><ShieldCheck/><span>Không gian riêng của gia đình<small>{roleNames[home?.role] || 'Tài khoản đã xác minh'}</small></span></div></footer></aside><div className="app-main"><header className="topbar"><span>{nav.find(([key]) => key === section)?.[1] || 'AnNhà'}</span><div className="topbar-controls"><small>{new Date().toLocaleDateString('vi-VN')}</small><button className="icon alert-toggle" aria-label={`Thông báo${unreadAlertCount ? `, ${unreadAlertCount} chưa đọc` : ''}`} aria-expanded={alertOpen} onClick={() => setAlertOpen(value => !value)}><Bell/>{unreadAlertCount>0&&<span className="alert-count">{unreadAlertCount>99?'99+':unreadAlertCount}</span>}</button><button className="icon" title="Đăng xuất" aria-label="Đăng xuất" onClick={logout}><SignOut/></button><button className="account-button" onClick={() => setMenu(!menu)}><span className="avatar small">{user.name.slice(0,1)}</span><span>{user.name}</span><CaretDown/></button></div>{alertOpen&&<AlertPopover alerts={activeAlerts} sound={alertSound} onRead={markAlertRead} onReadAll={markAllAlertsRead} readingId={readingAlertId} onClose={() => setAlertOpen(false)}/>}{menu && <div className="account-menu"><strong>{user.name}</strong><small>{user.email}</small><a href="#/account">Tài khoản</a><a href="#/homes">Chuyển nhà</a><button className="button ghost" onClick={logout}>Đăng xuất</button></div>}</header><main className="workspace">{dataError && data.homeId === home?.id && <div className="notice error" role="status">Chưa thể cập nhật dữ liệu. Nội dung gần nhất được giữ lại.<Button kind="ghost" onClick={reload}>Thử lại</Button></div>}<ScreenBoundary key={home?.id + path} onRetry={reload}>{screen()}</ScreenBoundary></main></div><nav className="bottom-nav">{[['overview','Tổng quan',SquaresFour],['cameras','Camera',VideoCamera],['events','Sự kiện',Bell],['reminders','Lời nhắc',SpeakerHigh],['more','Thêm',DotsThree]].map(([key,label,Icon]) => <a key={key} className={section === key ? 'active' : ''} href={'#/' + key}><Icon/>{label}</a>)}</nav></div>;
  return <AppContext.Provider value={value}>{content}{dialog}{toast && <div className="toast" role="status" aria-live="polite"><CheckCircle/><span>{toast}</span><button className="icon" aria-label="Đóng thông báo" onClick={() => setToast('')}><X/></button></div>}</AppContext.Provider>;
}
