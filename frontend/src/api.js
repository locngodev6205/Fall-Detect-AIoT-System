let csrf = '';
export function setCsrf(value) { csrf = value || ''; }
export async function api(path, options = {}) {
  const { body, ...rest } = options;
  const headers = { ...options.headers };
  if (body !== undefined && !(body instanceof Blob)) headers['Content-Type'] = 'application/json';
  if ((options.method || 'GET') !== 'GET') headers['X-CSRF-Token'] = csrf;
  const response = await fetch('/api' + path, { ...rest, credentials: 'same-origin', headers, body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body) });
  if (!response.ok) {
    let data; try { data = await response.json(); } catch { data = {}; }
    const message = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('; ') : data.detail;
    const error = new Error(message || `Yêu cầu thất bại (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
export const go = path => { location.hash = path; window.scrollTo(0, 0); };
export const roleNames = { owner: 'Chủ nhà', caregiver: 'Người chăm sóc', viewer: 'Người xem' };
export const dateTime = value => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa cập nhật';
export const eventNames = { fall: 'Nghi ngờ té ngã', immobility: 'Bất động kéo dài', environment: 'Môi trường bất thường', device: 'Lỗi giám sát' };
export const statusNames = { OPEN: 'Đang mở', ACKNOWLEDGED: 'Đã tiếp nhận', RESOLVED: 'Đã xử lý / an toàn', FALSE_ALARM: 'Báo động giả', pending: 'Đang chờ', applied: 'Đã áp dụng', ready: 'File sẵn sàng', failed: 'Thất bại', expired: 'Đã hết hạn', accepted: 'Thiết bị đã nhận', executing: 'Đang thực thi', executed: 'Thiết bị đã thực thi', sent: 'Đã gửi', played: 'Đã phát', skipped: 'Đã bỏ qua' };
