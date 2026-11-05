import test from 'node:test';
import assert from 'node:assert/strict';
import {roomImage,roomEntries,connectionLabel} from '../src/cameraState.js';
import {canCamera} from '../src/cameraPermissions.js';
test('source photos cover Vietnamese room names and arbitrary new rooms',()=>{
  assert.equal(roomImage('Phòng ngủ'),'/images/bedroom.png');
  assert.equal(roomImage('Cửa chính'),'/images/entrance.png');
  assert.equal(roomImage('Sân sau'),'/images/entrance.png');
  assert.equal(roomImage('Phòng đọc sách mới'),'/images/living.png');
});
test('new unpaired rooms remain visible only when requested by the owner view',()=>{
  const cameras=[{id:'c1',room_id:'r1',name:'Camera 1'}], rooms=[{id:'r1',name:'Phòng khách'},{id:'r2',name:'Phòng đọc sách'}];
  assert.equal(roomEntries(cameras,rooms,true).length,2);
  assert.equal(roomEntries(cameras,rooms,false).length,1);
  assert.equal(roomEntries(cameras,rooms,true)[1].camera,null);
});
test('an unavailable feed never gets labelled live or online',()=>{
  assert.equal(connectionLabel(null),'Chưa ghép nối camera');
  assert.equal(connectionLabel({online:false,last_seen:null}),'Chưa kết nối thiết bị');
  assert.equal(connectionLabel({online:false,last_seen:'2026-10-28'}),'Thiết bị mất kết nối');
});
test('actions use the selected camera permissions and reflect a revocation on the next state',()=>{
  const scheduleOnly={id:'c1',permissions:{view:true,events:true,audio:false,schedules:true,manage:false}};
  const audioOnly={id:'c2',permissions:{view:true,events:true,audio:true,schedules:false,manage:false}};
  assert.equal(canCamera(scheduleOnly,'schedules'),true);
  assert.equal(canCamera(scheduleOnly,'audio'),false);
  assert.equal(canCamera(audioOnly,'audio'),true);
  assert.equal(canCamera(audioOnly,'schedules'),false);
  assert.equal(canCamera({id:'c3',permissions:{view:true}},'audio'),false);
  const refreshed={...scheduleOnly,permissions:{...scheduleOnly.permissions,schedules:false}};
  assert.equal(canCamera(refreshed,'schedules'),false);
});
