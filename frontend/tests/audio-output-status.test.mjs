import { test } from 'node:test';
import assert from 'node:assert/strict';
import { audioOutputLabels, audioOutputStatus } from '../src/audioOutputStatus.mjs';

test('mode labels and status distinguish desired selection from Edge confirmation', () => {
  assert.equal(audioOutputLabels.analog, 'Loa có dây (3.5 mm)');
  assert.equal(audioOutputStatus({online:true, switching:true, ready:true}), 'Đang chờ Pi áp dụng');
  assert.equal(audioOutputStatus({online:true, switching:false, ready:true}), 'Sẵn sàng');
  assert.equal(audioOutputStatus({online:false, switching:false, ready:true}), 'Thiết bị ngoại tuyến');
  assert.equal(audioOutputStatus({online:true, switching:false, ready:false,error:'Loa Bluetooth chưa sẵn sàng.'}), 'Loa Bluetooth chưa sẵn sàng.');
});
