// Source artwork belongs to the UI. It never represents an observation from a device.
export function roomImage(name = '') {
  const text = name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  if (/ngu|bed|sleep/.test(text)) return '/images/bedroom.png';
  if (/cua|cong|sanh|entrance|door|san|garden/.test(text)) return '/images/entrance.png';
  return '/images/living.png';
}
export function roomEntries(cameras, rooms, includeUnpaired = false) {
  const entries = cameras.map(camera => ({ id: camera.id, name: rooms.find(room => room.id === camera.room_id)?.name || camera.name, camera }));
  if (includeUnpaired) for (const room of rooms) {
    if (!cameras.some(camera => camera.room_id === room.id)) entries.push({ id: room.id, name: room.name, camera: null });
  }
  const rank = entry => {
    const name = entry.name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    if (/khach|living/.test(name)) return 0;
    if (/ngu|bed/.test(name)) return 1;
    if (/cua|entrance/.test(name)) return 2;
    if (/san|yard/.test(name)) return 3;
    return 4;
  };
  return entries.sort((a,b) => rank(a) - rank(b) || a.name.localeCompare(b.name, 'vi'));
}
export function connectionLabel(camera) {
  if (!camera) return 'Chưa ghép nối camera';
  if (camera.online) return 'Thiết bị đang kết nối';
  return camera.last_seen ? 'Thiết bị mất kết nối' : 'Chưa kết nối thiết bị';
}
export const observationNames = { unknown: 'Chưa có quan sát', clear: 'Quan sát rõ', no_person: 'Chưa thấy người trong khung hình', occluded: 'Tầm nhìn bị che', camera_error: 'Cần kiểm tra camera' };
