export const audioOutputLabels = {
  bluetooth: 'Loa Bluetooth',
  analog: 'Loa có dây (3.5 mm)',
};

export function audioOutputStatus(state) {
  if (!state) return 'Đang tải trạng thái';
  if (!state.online) return 'Thiết bị ngoại tuyến';
  if (state.switching) return state.switch_error || 'Đang chờ Pi áp dụng';
  return state.ready ? 'Sẵn sàng' : state.error || 'Đầu ra chưa sẵn sàng';
}
