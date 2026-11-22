export const terminal = new Set(['succeeded', 'failed', 'rolled_back', 'cancelled', 'expired']);
export const labels = {
  pending: 'Đang chờ tải', downloading: 'Pi đang tải gói',
  ready: 'Đã xác minh gói, chờ cài đặt', deferred: 'Đang hoãn cài đặt',
  installing: 'Đang cài đặt ứng dụng Edge', health_check: 'Đang kiểm tra camera và AI',
  rolling_back: 'Đang khôi phục phiên bản trước', succeeded: 'Hoàn tất cài đặt',
  failed: 'Thất bại', rolled_back: 'Hoàn tất khôi phục', cancelled: 'Đã hủy', expired: 'Hết hạn',
};
const phases = { downloading: 0, ready: 2, deferred: 2, installing: 2, health_check: 3 };
const keys = ['model_sha256', 'runtime_sha256', 'target'];

export function compareVersions(a, b) {
  if (![a, b].every(value => /^\d{1,6}\.\d{1,6}\.\d{1,6}$/.test(value))) return null;
  const left = a.split('.').map(Number);
  const right = b.split('.').map(Number);
  return left.map((part, index) => part - right[index]).find(Boolean) || 0;
}

export function compatibleReleases(releases, state) {
  return releases.filter(release => keys.every(key => state?.[key] && state[key] === release[key]))
    .sort((a, b) => compareVersions(b.version, a.version));
}

export function otaResult(job, state, online) {
  const restored = job.status === 'rolled_back';
  const target = restored ? job.from_version : job.version;
  const complete = restored || job.status === 'succeeded';
  const confirmed = Boolean(complete && online && target && state?.current_version === target &&
    (restored ? state.last_seen >= job.updated_at : state.last_seen >= job.created_at));
  const waiting = complete && !confirmed;
  return {
    target, confirmed, waiting,
    title: confirmed ? (restored || job.rollback ? 'Khôi phục thành công' : 'Cập nhật thành công')
      : waiting ? (restored && !target ? 'Đã báo khôi phục, thiếu phiên bản gốc để đối chiếu' : 'Đang chờ thiết bị xác nhận')
      : labels[job.status],
    phase: complete ? (confirmed ? 5 : 4) : phases[job.status] ?? -1,
  };
}

export function otaPollDelay(job, result) {
  return job && (!terminal.has(job.status) || (result.waiting && result.target)) ? 2500 : null;
}
