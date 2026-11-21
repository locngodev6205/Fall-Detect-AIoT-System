import React, { useState } from 'react';
import { api, dateTime } from './api';
import { useApp, useResource } from './context';
import { Button, Field } from './ui';

const terminal = new Set(['succeeded', 'failed', 'rolled_back', 'cancelled', 'expired']);
const labels = { pending: 'Đang chờ tải', downloading: 'Đang tải gói', ready: 'Đã tải, chờ lịch', deferred: 'Đang hoãn', installing: 'Đang cài', health_check: 'Kiểm tra ứng dụng', rolling_back: 'Đang phục hồi', succeeded: 'Thành công', failed: 'Thất bại', rolled_back: 'Đã phục hồi', cancelled: 'Đã hủy', expired: 'Hết hạn' };

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
  const incompatible = release && state && ['model_sha256', 'runtime_sha256', 'target'].some(key => release[key] !== state[key]);

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
    <h2>Cập nhật ứng dụng Pi</h2>
    {resource.error && <p role="alert">{resource.error || 'Không tải được trạng thái cập nhật.'}</p>}
    {!data && !resource.error && <p>Đang tải phiên bản…</p>}
    {data && <>
      <p>Phiên bản hiện tại <strong>{state?.current_version || 'Chưa nhận thông tin'}</strong> · {data.online ? 'Bộ cập nhật trực tuyến' : 'Bộ cập nhật ngoại tuyến'}</p>
      {data.release_error && <p role="alert">{data.release_error}</p>}
      {!data.release_error && !data.releases.length && <p>Chưa có bản phát hành Pi đã xác minh.</p>}
      <div className="update-controls">
        <Field label="Phiên bản"><select value={version} disabled={busy || !!active} onChange={event => setVersion(event.target.value)}><option value="">Chọn phiên bản</option>{data.releases.filter(item => item.version !== state?.current_version).map(item => <option key={item.version} value={item.version}>{item.version}</option>)}</select></Field>
        <Field label="Thời điểm"><select value={mode} disabled={busy || !!active} onChange={event => setMode(event.target.value)}><option value="now">Cập nhật ngay</option><option value="scheduled">Hẹn giờ cập nhật</option></select></Field>
        {mode === 'scheduled' && <Field label="Giờ trên thiết bị của bạn"><input type="datetime-local" value={schedule} disabled={busy || !!active} onChange={event => setSchedule(event.target.value)}/></Field>}
        <Button disabled={busy || !!active || !data.online || !release || incompatible} onClick={() => submit()}>{mode === 'scheduled' ? 'Lưu lịch' : 'Cập nhật ngay'}</Button>
        <Button kind="secondary-btn" disabled={busy || !!active || !data.online || !state?.previous_version} onClick={() => submit(true)}>Quay về bản trước</Button>
      </div>
      {incompatible && <p role="alert">Phiên bản này yêu cầu model hoặc môi trường Python khác trên Pi.</p>}
      {release?.notes && <details><summary>Ghi chú phát hành {version}</summary><pre className="release-notes">{release.notes}</pre></details>}
      {active && <div role="status"><p><strong>{labels[active.status]}</strong> · Hẹn {dateTime(active.scheduled_at * 1000)}</p><p>{active.message}</p>{!['installing', 'health_check', 'rolling_back'].includes(active.status) && <Button kind="secondary-btn" disabled={busy} onClick={cancel}>Hủy lịch để chọn lại</Button>}</div>}
      <p className="muted">Gói được tải trước. Khi đến giờ, thiết bị chờ cảnh báo và âm thanh kết thúc tối đa 30 phút trước khi lịch hết hạn.</p>
      {!!data.jobs.length && <details><summary>Lịch sử cập nhật</summary><ul>{data.jobs.map(job => <li key={job.id}>{job.version} · {labels[job.status]} · {dateTime(job.updated_at * 1000)}{job.message && ` — ${job.message}`}</li>)}</ul></details>}
    </>}
  </section>;
}
