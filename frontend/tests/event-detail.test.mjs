import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

// Render the actual JSX and exercise handlers without browser or external services.
const stubs={
  react:`const h=globalThis.harness;
    export const useState=initial=>h.useState(initial);
    export const useEffect=(effect,deps)=>h.useEffect(effect,deps);
    export default {Fragment:'Fragment',createElement:(type,props,...children)=>typeof type==='function'
      ?h.invoke(type,{...props,children:children.flat(Infinity)})
      :({type,props:{...props,children:children.flat(Infinity)}})};`,
  '@phosphor-icons/react':`export const WarningCircle='Icon',PersonSimple='Icon',Leaf='Icon',VideoCamera='Icon',ImageSquare='Icon';`,
  './api':`const h=globalThis.harness;export const api=(path,options)=>h.api(path,options);
    export const go=path=>h.navigations.push(path),dateTime=value=>value||'',
      eventNames={fall:'Fall',immobility:'Immobility',environment:'Environment',device:'Device'},
      statusNames={OPEN:'Đang mở',ACKNOWLEDGED:'Đã tiếp nhận',RESOLVED:'Đã xử lý',FALSE_ALARM:'Báo động giả'};`,
  './context':`export const useApp=()=>globalThis.harness.app;
    export const useResource=path=>{const h=globalThis.harness;h.paths.push(path);return {data:h.component==='Events'?h.feed:h.event,reload:()=>h.reloads++};};
    export const ResourceState='ResourceState';`,
  './serverPaging':`export const useServerPage=()=>({items:globalThis.harness.updates,reload:()=>globalThis.harness.reloads++});export const ServerPager='ServerPager';`,
  './ui':`export const Badge='Badge',Button='Button',Empty='Empty',Field='Field',Heading='Heading',Pagination='Pagination';`,
};
const result=await build({entryPoints:[fileURLToPath(new URL('../src/EventScreens.jsx',import.meta.url))],bundle:true,write:false,
  format:'iife',globalName:'EventScreenTest',plugins:[{name:'event-test-imports',setup(builder){
    builder.onResolve({filter:/.*/},args=>Object.hasOwn(stubs,args.path)?{path:args.path,namespace:'fixture'}:undefined);
    builder.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:stubs[args.path],loader:'js'}));
  }}]});
function render(options={}){
  const h={component:options.component||'EventDetail',effects:[],calls:[],messages:[],reloads:0,selected:[],paths:[],navigations:[],stores:new Map(),scope:'',cursor:0,
    event:{id:'event-id',home_id:'home',camera_id:'camera',kind:'fall',status:'OPEN',observation:'abnormal',payload:{},evidence:[],is_read:false,...options.event},
    feed:options.feed||{items:[],total:0,total_pages:1},updates:options.updates||[]};
  h.app={home:{id:'home'},homes:[{id:'home'},{id:'other-home'}],cameras:[{id:'camera',room_id:'room'},{id:'other-camera',room_id:'other-room'}],rooms:[{id:'room'},{id:'other-room'}],
    can:()=>options.allowed!==false,notify:message=>h.messages.push(message),
    reloadAlerts:()=>h.reloads++,reload:()=>h.reloads++,selectHome:id=>{h.selected.push(id);h.app.home={id};}};
  h.invoke=(fn,props)=>{
    const oldScope=h.scope,oldCursor=h.cursor;h.scope=fn.name+':'+(props.asset?.id||props.id||props.key||'');h.cursor=0;
    if(!h.stores.has(h.scope))h.stores.set(h.scope,[]);
    try{return fn(props);}finally{h.scope=oldScope;h.cursor=oldCursor;}
  };
  h.useState=initial=>{
    const store=h.stores.get(h.scope),slot=h.cursor++;
    if(!(slot in store))store[slot]=typeof initial==='function'?initial():initial;
    return [store[slot],value=>{store[slot]=typeof value==='function'?value(store[slot]):value;h.dirty=true;}];
  };
  h.useEffect=(effect,deps)=>{
    const store=h.stores.get(h.scope),slot=h.cursor++,previous=store[slot];
    if(!previous||deps.some((dep,index)=>!Object.is(dep,previous[index]))){store[slot]=deps;h.effects.push(effect);}
  };
  h.api=async(path,options)=>{
    h.calls.push({path,...options});if(h.fail)throw Error('Permission revoked');
    if(path.endsWith('/read-all'))return {read_count:2};
    if(path.endsWith('/actions'))return {...h.event,status:options.body.action==='acknowledge'?'ACKNOWLEDGED':options.body.action==='false_alarm'?'FALSE_ALARM':'RESOLVED'};
    return {};
  };
  const context={harness:h,URLSearchParams};vm.runInNewContext(result.outputFiles[0].text,context);
  h.render=()=>{
    let retries=0;
    do{h.dirty=false;h.effects=[];h.tree=h.invoke(context.EventScreenTest[h.component],{id:'event-id',initialStatus:options.initialStatus||''});h.effects.forEach(effect=>effect());}
    while(h.dirty&&++retries<5);
    h.nodes=[];const walk=node=>{if(!node||typeof node!=='object')return;h.nodes.push(node);node.props?.children?.forEach(walk);};walk(h.tree);
    return h;
  };
  h.button=label=>h.nodes.find(node=>node.type==='Button'&&node.props.children.includes(label));
  h.text=()=>h.nodes.flatMap(node=>node.props.children.filter(child=>typeof child==='string')).join(' ');
  h.submit=async()=>{const form=h.nodes.find(node=>node.type==='form');await form.props.onSubmit({preventDefault(){}});h.render();};
  h.fillNote=text=>{h.nodes.find(node=>node.type==='textarea').props.onChange({target:{value:text}});h.render();};
  h.confirm=()=>{h.nodes.find(node=>node.type==='input'&&node.props.type==='checkbox').props.onChange({target:{checked:true}});h.render();};
  h.filter=(label,value)=>{const field=h.nodes.find(node=>node.type==='Field'&&node.props.label===label);field.props.children[0].props.onChange({target:{value}});h.render();};
  return h.render();
}
test('opening a notification link performs no read or acknowledge request',()=>{
  const view=render();assert.equal(view.calls.length,0);assert.ok(view.button('Đánh dấu đã đọc'));
});
test('read immediately updates status while preserving explicit acknowledgement for read open events',async()=>{
  let view=render();await view.button('Đánh dấu đã đọc').props.onClick();view.render();
  assert.equal(view.calls[0].path,'/events/event-id/read');assert.equal(view.button('Đánh dấu đã đọc'),undefined);
  assert.ok(view.text().includes('Đã tiếp nhận'));assert.equal(view.reloads,4);
  view=render({event:{is_read:true}});await view.button('Tiếp nhận sự kiện').props.onClick();view.render();
  assert.equal(view.calls[0].path,'/events/event-id/actions');assert.equal(view.calls[0].body.action,'acknowledge');
  assert.equal(view.button('Tiếp nhận sự kiện'),undefined);
});
test('safe and false alarm submit upstream actions with trimmed note and explicit confirmation',async()=>{
  for(const [label,action] of [['Xác nhận đã an toàn','safe'],['Xác nhận báo động giả','false_alarm']]){
    const view=render();view.button(label).props.onClick();view.render();view.fillNote(' Đã kiểm tra tại phòng ');view.confirm();await view.submit();
    assert.equal(view.calls[0].body.action,action);assert.equal(view.calls[0].body.note,'Đã kiểm tra tại phòng');
    assert.equal(view.calls[0].body.confirm_abnormal,true);assert.equal(view.reloads,4);assert.equal(view.button(label),undefined);
  }
});
test('abnormal closure needs a note and confirmation; cancellation never mutates',async()=>{
  const view=render();view.button('Xác nhận đã an toàn').props.onClick();view.render();await view.submit();
  assert.equal(view.calls.length,0);view.fillNote('Checked');await view.submit();assert.equal(view.calls.length,0);
  view.button('Hủy').props.onClick();view.render();assert.equal(view.calls.length,0);assert.ok(view.button('Xác nhận đã an toàn'));
});
test('recovered event may close without an abnormal override',async()=>{
  const view=render({event:{observation:'recovered'}});view.button('Xác nhận đã an toàn').props.onClick();view.render();await view.submit();
  assert.equal(view.calls[0].body.confirm_abnormal,false);
});
test('view-only users and closed events have no handling buttons',()=>{
  for(const options of [{allowed:false},{event:{status:'RESOLVED'}},{event:{status:'FALSE_ALARM'}}]){
    const view=render(options);assert.equal(view.button('Xác nhận đã an toàn'),undefined);assert.equal(view.button('Xác nhận báo động giả'),undefined);
  }
});
test('viewer read does not show acknowledgement',async()=>{
  const view=render({allowed:false});await view.button('Đánh dấu đã đọc').props.onClick();view.render();assert.ok(!view.text().includes('Đã tiếp nhận'));
});
test('cross-home link selects the authorized event home without accepting or reading',()=>{
  const view=render({event:{home_id:'other-home'}});assert.deepEqual(view.selected,['other-home']);assert.equal(view.calls.length,0);
});
test('server permission errors remain visible and do not report success',async()=>{
  const view=render();view.button('Xác nhận đã an toàn').props.onClick();view.render();view.fillNote('Checked');view.confirm();view.fail=true;await view.submit();
  assert.deepEqual(view.messages,[]);assert.ok(view.text().includes('Permission revoked'));
});
test('detail image, unavailable evidence, observation text and action history remain event scoped',()=>{
  const view=render({event:{evidence:[{id:'photo-of-event',status:'ready',mime:'image/jpeg'},{id:'expired',status:'expired',name:'Expired photo'}],
    actions:[{id:'action',action:'acknowledge',note:'Checked by handler'}]},updates:[{sequence:2,payload:{reason:'Second observation'},severity:'warning',observation:'abnormal'}]});
  assert.ok(view.nodes.some(node=>node.type==='img'&&node.props.src==='/api/assets/photo-of-event'));
  assert.ok(view.text().includes('Bằng chứng đã hết hạn'));assert.ok(view.text().includes('Second observation'));assert.ok(view.text().includes('Checked by handler'));
});
test('all event filters reach server query and any filter change resets pagination',()=>{
  const view=render({component:'Events',feed:{items:[],total:20,total_pages:2}});
  for(const [label,value] of [['Phòng','room'],['Camera','camera'],['Trạng thái','OPEN'],['Loại sự kiện','fall'],['Mức cảnh báo','critical'],['Thời gian','24']])view.filter(label,value);
  view.nodes.find(node=>node.type==='Pagination').props.onChange(2);view.render();
  let query=new URLSearchParams(view.paths.at(-1).split('?')[1]);assert.equal(query.get('page'),'2');
  for(const [key,value] of Object.entries({room_id:'room',camera_id:'camera',status:'OPEN',kind:'fall',severity:'critical',hours:'24'}))assert.equal(query.get(key),value);
  view.filter('Từ ngày giờ','2026-11-21T10:00');query=new URLSearchParams(view.paths.at(-1).split('?')[1]);
  assert.equal(query.get('page'),'1');assert.equal(query.has('hours'),false);assert.equal(query.get('start'),new Date('2026-11-21T10:00').toISOString());
  view.filter('Phòng','other-room');query=new URLSearchParams(view.paths.at(-1).split('?')[1]);assert.equal(query.has('camera_id'),false);
});
test('clear filters and OTA blocker filter preserve upstream query semantics only',()=>{
  const view=render({component:'Events'});assert.equal(view.button('Cảnh báo đang chặn OTA').props.disabled,true);
  view.filter('Camera','camera');view.filter('Trạng thái','RESOLVED');view.filter('Loại sự kiện','fall');
  view.button('Cảnh báo đang chặn OTA').props.onClick();view.render();
  let query=new URLSearchParams(view.paths.at(-1).split('?')[1]);assert.equal(query.get('active_only'),'true');assert.equal(query.get('camera_id'),'camera');assert.equal(query.has('status'),false);assert.equal(query.has('kind'),false);
  view.button('Xóa bộ lọc').props.onClick();view.render();query=new URLSearchParams(view.paths.at(-1).split('?')[1]);assert.equal([...query].length,2);
});
test('list links and read-all retain exact event and home endpoints',async()=>{
  const event={id:'row-event',kind:'fall',payload:{},camera_id:'camera',observed_at:'now',status:'OPEN'};
  const view=render({component:'Events',feed:{items:[event],total:12,total_pages:2}});
  assert.ok(view.nodes.some(node=>node.type==='a'&&node.props.href==='#/event/row-event'));
  await view.button('Đánh dấu đã đọc').props.onClick();assert.equal(view.calls[0].path,'/events/row-event/read');
  await view.nodes.find(node=>node.type==='Heading').props.action.props.onClick();assert.equal(view.calls[1].path,'/homes/home/events/read-all');
});
