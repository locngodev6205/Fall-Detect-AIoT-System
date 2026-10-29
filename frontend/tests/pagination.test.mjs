import test from 'node:test';
import assert from 'node:assert/strict';
import {paginate} from '../src/pagination.js';
import {chartPoints} from '../src/chartData.js';
test('pages are disjoint, clamp after deletion, and handle empty lists',()=>{
 const rows=Array.from({length:23},(_,id)=>({id}));
 assert.deepEqual(paginate(rows,2,10).items.map(row=>row.id),[10,11,12,13,14,15,16,17,18,19]);
 assert.equal(paginate(rows,99,10).page,3);
 assert.equal(paginate(rows.slice(0,8),3,10).page,1);
 assert.deepEqual(paginate([],2,10).items,[]);
});
test('chart sorts readings and never converts invalid or mixed-unit samples to zero',()=>{
 const row=(time,value,quality='valid',unit='C')=>({observed_at:new Date(time).toISOString(),payload:{readings:{temperature:{value,quality,unit}}}});
 const points=chartPoints([row(180000,25),row(0,24),row(60000,null,'error'),row(120000,70,'valid','%')],'temperature','C');
 assert.deepEqual(points.map(point=>point.y),[24,null,null,25]);
});

import {activityLabel,deliveryLabel} from '../src/activityLabels.js';
test('settings use plain activity and notification-specific labels',()=>{
 assert.equal(activityLabel('event.safe'),'Xác nhận người thân an toàn');
 assert(!activityLabel('new.internal.action').includes('.'));
 assert.equal(deliveryLabel('accepted').label,'Dịch vụ đã tiếp nhận');
 assert(!deliveryLabel('accepted').label.includes('Thiết bị'));
 assert.equal(deliveryLabel('cancelled').tone,'gray');
});
