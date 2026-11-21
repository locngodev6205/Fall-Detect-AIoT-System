import React, { useEffect, useState } from 'react';
import { api, dateTime } from './api';
import { useApp, useResource } from './context';
import { Button, Field } from './ui';

import { compareVersions, compatibleReleases, labels, otaPollDelay, otaResult, terminal } from './ota-view.mjs';

const steps = ['Tải gói', 'Xác minh gói', 'Cài đặt', 'Health check', 'Hoàn tất'];

export function DeviceUpdates({ cameraId }) {
  const { tick, notify } = useApp();
  const [refresh, setRefresh] = useState(0);
  const resource = useResource(`/cameras/${cameraId}/updates`, `${tick}-${refresh}`);
  const [version, setVersion] = useState('');
  const [mode, setMode] = useState('now');
  const [schedule, setSchedule] = useState('');
  const [busy, setBusy] = useState(false);
  const data = resource.data;
  const active = data?.jobs.find(job => !terminal.has(job.status));
  const state = data?.state;
  const release = data?.releases.find(item => item.version === version);
  const compatible = compatibleReleases(data?.releases || [], state);
  const latest = compatible[0];
  const comparison = compareVersions(latest?.version, state?.current_version);
  const incompatible = release && !compatible.includes(release);
  const job = active || data?.jobs[0];
  const result = job && otaResult(job, state, data.online && !resource.error);
  const pollDelay = otaPollDelay(job, result);

  useEffect(() => {
    if (!pollDelay || resource.refreshing || resource.loading) return;
    const timer = setTimeout(() => setRefresh(value => value + 1), pollDelay);
    return () => clearTimeout(timer);
  }, [pollDelay, resource.refreshing, resource.loading, refresh, cameraId]);

  async function submit(rollback = false) {
    const when = mode === 'scheduled' && !rollback ? new Date(schedule).getTime() / 1000 : null;
    if (when !== null && (!Number.isFinite(when) || when <= Date.now() / 1000)) {
      notify('Hãy chọn thời điểm trong tương lai.');
      return;
    }
    if (rollback && !window.confirm('Quay về phiên bản trước trên thiết bị này?')) return;
    if (!rollback && mode === 'now' && !window.confirm('Ứng dụng sẽ tạm dừng giám sát trong lúc cài đặt khi thiết bị đủ điều kiện. Tiếp tục?')) return;
    setBusy(true);
    try {
      await api(`/cameras/${cameraId}/updates`, { method: 'POST', body: { version: rollback ? undefined : version, rollback, scheduled_at: when } });
      notify(rollback ? 'Đã gửi yêu cầu quay về bản trước.' : 'Đã tạo lệnh cập nhật. Thiết bị sẽ tải gói trước.');
      setRefresh(value => value + 1);
    } catch (error) { notify(error.message); }
    finally { setBusy(false); }
  }

  async function cancel() {
    setBusy(true);
    try {
      await api(`/cameras/${cameraId}/updates/${active.id}/cancel`, { method: 'POST' });
      setRefresh(value => value + 1);
    } catch (error) { notify(error.message); }
    finally { setBusy(false); }
  }

  return <section className="panel spaced device-updates">
    <header className="ota-heading">
      <h2>Cập nhật ứng dụng Raspberry Pi 4</h2>
      {data && <span className="ota-badge" data-tone={resource.error ? 'warn' : data.online ? 'good' : 'neutral'}>
        {resource.error ? 'Mất kết nối API' : data.online ? 'Updater trực tuyến' : 'Updater ngoại tuyến'}
      </span>}
    </header>
    {resource.error && <p role="alert">{resource.error} <button className="button secondary-btn" onClick={resource.reload}>Thử lại</button></p>}
    {!data && !resource.error && <p>Đang tải phiên bản…</p>}
    {data && <>
      <dl className="ota-versions">
        <div><dt>Phiên bản Pi báo</dt><dd>{state?.current_version || 'Chưa nhận thông tin'}</dd></div>
        <div><dt>Mới nhất tương thích</dt><dd>{latest?.version || 'Chưa có thông tin'} {comparison > 0 && !resource.error && !data.release_error && <span className="ota-badge" data-tone="good">Mới</span>}</dd></div>
        <div><dt>Có thể quay về</dt><dd>{state?.previous_version || 'Chưa có'}</dd></div>
      </dl>
      {!resource.error && !data.release_error && comparison === 0 && <p>Đã ở phiên bản mới nhất.</p>}
      {state && <p className="muted">Heartbeat gần nhất {dateTime(state.last_seen * 1000)}{data.online && !resource.error && !active && (state.ready ? ' · Sẵn sàng cập nhật' : ` · ${state.reason || 'Chưa sẵn sàng cập nhật'}`)}</p>}
      {job && <div className="ota-job" data-tone={result.confirmed ? 'good' : job.status === 'failed' ? 'bad' : 'neutral'}>
        <div aria-live="polite">
          <strong>{result.title}</strong>
          {result.confirmed && job.from_version && job.status !== 'rolled_back'
            ? <p>{job.from_version} → {state.current_version}</p>
            : <p>{job.rollback ? 'Yêu cầu quay về' : 'Bản được yêu cầu'} <b>{job.version}</b>{result.confirmed && ` · Pi đang chạy ${state.current_version}`}</p>}
          {['rolling_back', 'rolled_back'].includes(job.status) && <p>
            {job.rollback ? 'Khôi phục sau khi lệnh quay về gặp lỗi' : 'Khôi phục tự động'}
            {job.from_version && ` · Khôi phục về ${job.from_version}`}
          </p>}
          {job.message && <p>{job.message}</p>}
          {active && !data.online && <p>Đang chờ kết nối lại với bộ cập nhật.</p>}
        </div>
        {!['rolling_back', 'rolled_back', 'failed', 'cancelled', 'expired'].includes(job.status) &&
          <ol className="ota-timeline" aria-label="Tiến trình cập nhật">
            {steps.map((step, index) => {
              const current = index === result.phase && !['ready', 'deferred'].includes(job.status);
              return <li key={step} data-complete={index < result.phase} aria-current={current ? 'step' : undefined}>
                <span aria-hidden="true">{index < result.phase ? '✓' : index + 1}</span>{step}
              </li>;
            })}
          </ol>}
        {active && <p>Thời điểm cài đặt dự kiến {dateTime(active.scheduled_at * 1000)}</p>}
        {active && !['installing', 'health_check', 'rolling_back'].includes(active.status) &&
          <Button kind="secondary-btn" disabled={busy || !!resource.error} onClick={cancel}>Hủy lệnh cập nhật</Button>}
      </div>}
      {data.release_error && <p role="alert">{data.release_error}</p>}
      {!data.release_error && !data.releases.length && <p>Chưa có bản phát hành Pi đã xác minh.</p>}
      <div className="update-controls">
        <Field label="Phiên bản"><select value={version} disabled={busy || !!active} onChange={event => setVersion(event.target.value)}><option value="">Chọn phiên bản</option>{data.releases.filter(item => item.version !== state?.current_version).map(item => <option key={item.version} value={item.version}>{item.version}</option>)}</select></Field>
        <Field label="Thời điểm"><select value={mode} disabled={busy || !!active} onChange={event => setMode(event.target.value)}><option value="now">Cập nhật ngay</option><option value="scheduled">Hẹn giờ cập nhật</option></select></Field>
        {mode === 'scheduled' && <Field label="Giờ trên thiết bị của bạn"><input type="datetime-local" value={schedule} disabled={busy || !!active} onChange={event => setSchedule(event.target.value)}/></Field>}
        <Button disabled={busy || !!active || !!resource.error || !data.online || !release || incompatible} onClick={() => submit()}>{mode === 'scheduled' ? 'Lưu lịch' : 'Cập nhật ngay'}</Button>
        <Button kind="secondary-btn" disabled={busy || !!active || !!resource.error || !data.online || !state?.previous_version} onClick={() => submit(true)}>Quay về bản trước</Button>
      </div>
      {incompatible && <p role="alert">Phiên bản này yêu cầu model hoặc môi trường Python khác trên Pi.</p>}
      {release?.notes && <details><summary>Ghi chú phát hành {version}</summary><pre className="release-notes">{release.notes}</pre></details>}
      <p className="muted">Gói được tải trước. Khi đến giờ, thiết bị chờ cảnh báo và âm thanh kết thúc tối đa 30 phút trước khi lịch hết hạn.</p>
      {!!data.jobs.length && <div className="ota-history">
        <h3>5 lệnh gần nhất</h3>
        <ul>{data.jobs.slice(0, 5).map(item => {
          const title = item.id === job?.id ? result.title :
            item.status === 'succeeded' && item.rollback ? 'Lệnh quay về đã hoàn tất' : labels[item.status];
          return <li key={item.id}>
            <strong>{title}</strong> · {item.version}
            {item.status === 'rolled_back' && item.from_version && ` → ${item.from_version}`}
            <small>{dateTime(item.updated_at * 1000)}{item.message && ` · ${item.message}`}</small>
          </li>;
        })}</ul>
      </div>}
    </>}
  </section>;
}
