import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from './api';
export const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);
export function useResource(path, refresh = 0) {
  const [state, setState] = useState({ path: null, data: null, error: '', loading: true });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    if (!path) { setState({ path, data: null, error: '', loading: false });return; }
    setState({ path, data: null, error: '', loading: true });
    api(path).then(data => { if (active) setState({ path, data, error: '', loading: false }); }).catch(error => { if (active) setState({ path, data: null, error: error.message, loading: false }); });
    return () => { active = false; };
  }, [path, refresh, version]);
  return { ...(state.path === path ? state : { data: null, error: '', loading: true }), reload: () => setVersion(v => v + 1) };
}
export function ResourceState({ resource, children }) {
  if (resource.loading) return <div className="panel" role="status">Đang tải dữ liệu…</div>;
  if (resource.error) return <div className="notice error" role="alert">{resource.error}<button className="button secondary-btn" onClick={resource.reload}>Thử lại</button></div>;
  return children;
}
