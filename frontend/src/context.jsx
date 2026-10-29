import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from './api';
export const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);
export function useResource(path, refresh = 0) {
  const [state, setState] = useState({ path: null, data: null, error: '', loading: true });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    if (!path) { setState({ path, data: null, error: '', loading: false, refreshing: false });return; }
    setState(previous => previous.path === path && previous.data !== null ? { ...previous, refreshing: true } : { path, data: null, error: '', loading: true, refreshing: false });
    api(path, { signal: controller.signal }).then(data => {
      if (active) setState({ path, data, error: '', loading: false, refreshing: false });
    }).catch(error => {
      if (active) setState(previous => ({ path, data: previous.path === path && ![401,403,404].includes(error.status) ? previous.data : null, error: error.message, loading: false, refreshing: false }));
    });
    return () => { active = false;controller.abort(); };
  }, [path, refresh, version]);
  return { ...(state.path === path ? state : { data: null, error: '', loading: true }), reload: () => setVersion(v => v + 1) };
}
export function ResourceState({ resource, children }) {
  return <>
    {resource.error && <div className="notice error" role="alert">{resource.error}<button className="button secondary-btn" onClick={resource.reload}>Thử lại</button></div>}
    {resource.loading ? <div className="panel" role="status">Đang tải dữ liệu…</div> : (!resource.error || resource.data !== null) && children}
  </>;
}
