/** Focused Phase 3 browser regression; all API/WS data is synthetic. */
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.UI_BASE_URL||'http://127.0.0.1:5188';
const browser=await chromium.launch({headless:true,args:['--mute-audio'],executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const passed=[],errors=[];
const baseline=Date.now()-10000;
const event=(id,time=Date.now())=>({id,home_id:'a',camera_id:'camera-'+id,camera_name:'Camera '+id,kind:'fall',status:'OPEN',severity:'critical',observed_at:new Date(time).toISOString(),first_observed_at:new Date(time).toISOString(),reason:'Cần kiểm tra '+id,sequence:1,payload:{},actions:[],evidence:[]});
const summary=items=>({count:items.length,items,as_of:new Date(baseline).toISOString()});
const settle=page=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
async function fixture({mockAudio=false}={}){
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  await context.addInitScript(({mockAudio})=>{
    const stats=window.__qaAudio={contexts:[],oscillators:0,blocked:false,hanging:false};
    if(mockAudio){
      window.AudioContext=class {
        constructor(){this.state='suspended';this.currentTime=0;this.destination={};stats.contexts.push(this);}
        async resume(){if(stats.blocked)throw new DOMException('fixture autoplay denied','NotAllowedError');if(stats.hanging)return new Promise(()=>{});this.state='running';}
        async close(){this.state='closed';}
        createOscillator(){stats.oscillators++;return {frequency:{setValueAtTime(){}},connect(){},start(){},stop(){}};}
        createGain(){return {gain:{setValueAtTime(){},linearRampToValueAtTime(){}},connect(){}};}
      };
    }else{
      const Native=window.AudioContext;
      window.AudioContext=class extends Native {
        constructor(...args){super(...args);stats.contexts.push(this);}
        createOscillator(){stats.oscillators++;return super.createOscillator();}
      };
    }
  },{mockAudio});
  await context.addInitScript(()=>{
    const Native=window.WebSocket;
    window.__qaSockets=[];
    window.WebSocket=class {
      static OPEN=1;static CONNECTING=0;static CLOSING=2;static CLOSED=3;
      constructor(url,...args){if(!String(url).includes('/ws/alerts?'))return new Native(url,...args);this.url=url;this.readyState=1;window.__qaSockets.push(this);}
      close(){if(this.readyState===3)return;this.readyState=3;this.onclose?.({code:1000});}
      serverClose(code){this.readyState=3;this.onclose?.({code});}
      message(){this.onmessage?.({data:'{}'});}
    };
  });
  const state={summaries:{a:summary([event('old',baseline-60000)]),b:summary([])},hold:null};
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/auth/me')return route.fulfill({json:{csrf:'fixture',user:{id:'owner',name:'Chủ nhà',email:'owner@example.test'}}});
    if(path==='/api/auth/logout')return route.fulfill({json:{}});
    if(path==='/api/homes')return route.fulfill({json:['a','b'].map(id=>({id,name:'Nhà '+id.toUpperCase(),role:'owner',timezone:'Asia/Ho_Chi_Minh',room_count:0,camera_count:0}))});
    const active=path.match(/^\/api\/homes\/([^/]+)\/active-events$/);
    if(active){
      const home=active[1],body=structuredClone(state.summaries[home]);
      if(state.hold?.home===home){const hold=state.hold;state.hold=null;hold.seen();await hold.wait;return route.fulfill({json:body,headers:{'X-QA-Held':'1'}});}
      return route.fulfill({json:body});
    }
    if(path.startsWith('/api/events/'))return route.fulfill({json:event(path.split('/').at(-1))});
    if(/^\/api\/homes\/[^/]+\/(cameras|rooms|events|reminders)$/.test(path))return route.fulfill({json:[]});
    throw new Error('Unexpected API fixture: '+path);
  });
  await page.goto(base+'/#/account');await page.getByRole('heading',{name:'Tài khoản của bạn'}).waitFor();
  await page.waitForFunction(()=>window.__qaSockets.length===1);await settle(page);
  const holdNext=home=>{
    let seen,release;
    const started=new Promise(resolve=>seen=resolve),wait=new Promise(resolve=>release=resolve);
    const finished=page.waitForResponse(response=>response.headers()['x-qa-held']==='1');
    state.hold={home,seen,wait};return {started,release,finished};
  };
  const message=async()=>{
    const response=page.waitForResponse(response=>response.url().includes('/active-events?'));
    await page.evaluate(()=>window.__qaSockets.at(-1).message());await response;await settle(page);
  };
  const switchHome=async id=>{
    await page.locator('.home-selector').click();
    await page.locator('.home-tile').filter({has:page.getByRole('heading',{name:'Nhà '+id.toUpperCase(),exact:true})}).getByRole('button',{name:'Mở nhà',exact:true}).click();
    await page.waitForFunction(id=>window.__qaSockets.at(-1)?.url.includes('home_id='+id),id);await settle(page);
  };
  return {page,context,state,message,holdNext,switchHome};
}
async function check(name,run,options){const f=await fixture(options);try{await run(f);passed.push(name);console.log('PASS '+name);}finally{await f.context.close();}}
try{
  if(!process.argv.includes('--sound-only')){
  await check('Reconnect announces an event created while disconnected; duplicate/update stays quiet',async({page,state,message})=>{
    assert.equal(await page.locator('.toast').count(),0);
    await page.evaluate(()=>window.__qaSockets.at(-1).serverClose(1006));
    state.summaries.a=summary([event('new'),...state.summaries.a.items]);
    await page.waitForFunction(()=>window.__qaSockets.length===2);
    await page.locator('.toast').filter({hasText:'Camera new'}).waitFor();
    await page.getByRole('button',{name:'Đóng thông báo',exact:true}).click();
    state.summaries.a.items[0].sequence=2;await message();
    assert.equal(await page.locator('.toast').count(),0);assert.equal(await page.locator('.alert-count').innerText(),'2');
  });
  await check('Historical replay updates count without toast; refresh baseline remains silent',async({page,state,message})=>{
    state.summaries.a=summary([event('historical',baseline-86400000),...state.summaries.a.items]);await message();
    assert.equal(await page.locator('.toast').count(),0);assert.equal(await page.locator('.alert-count').innerText(),'2');
    await page.reload();await page.waitForFunction(()=>window.__qaSockets.length===1);await settle(page);
    assert.equal(await page.locator('.toast').count(),0);assert.equal(await page.locator('.alert-count').innerText(),'2');
  });
  await check('Camera revocation clears stale summary/toast and rejects an in-flight pre-revocation response',async({page,state,holdNext})=>{
    const hold=holdNext('a');const response=page.waitForResponse(r=>r.url().includes('/active-events?'));
    await page.evaluate(()=>window.__qaSockets.at(-1).message());await hold.started;
    state.summaries.a=summary([]);await page.evaluate(()=>window.__qaSockets.at(-1).serverClose(1008));
    hold.release();await response;await hold.finished;await settle(page);
    assert.equal(await page.locator('.alert-count').count(),0);assert.equal(await page.locator('.toast').count(),0);
    await page.waitForFunction(()=>window.__qaSockets.length===2);await page.getByRole('button',{name:'Thông báo',exact:true}).click();
    await page.getByText('Không có cảnh báo đang mở.',{exact:true}).waitFor();
  });
  await check('Switching A to B ignores unfinished A response',async({page,state,holdNext,switchHome})=>{
    state.summaries.a={...summary([event('stale')]),count:99};
    const hold=holdNext('a');await page.evaluate(()=>window.__qaSockets.at(-1).message());await hold.started;
    state.summaries.b=summary([event('b-one'),event('b-two')]);await switchHome('b');
    hold.release();await hold.finished;await settle(page);
    assert.equal(await page.locator('.home-selector').innerText(),'Nhà B');assert.equal(await page.locator('.alert-count').innerText(),'2');
    assert.equal(await page.locator('.toast').count(),0);
  });
  await check('A to B to A rejects a response from the earlier A session',async({page,state,holdNext,switchHome})=>{
    state.summaries.a={...summary([event('stale')]),count:99};
    const hold=holdNext('a');await page.evaluate(()=>window.__qaSockets.at(-1).message());await hold.started;
    await switchHome('b');state.summaries.a=summary([event('current',baseline-1000)]);await switchHome('a');
    hold.release();await hold.finished;await settle(page);assert.equal(await page.locator('.alert-count').innerText(),'1');assert.equal(await page.locator('.toast').count(),0);
  });
  await check('Out-of-order same-home requests preserve latest summary; popover opens exact event',async({page,state,holdNext,message})=>{
    const hold=holdNext('a');await page.evaluate(()=>window.__qaSockets.at(-1).message());await hold.started;
    state.summaries.a=summary([event('latest'),event('second')]);await message();
    hold.release();await hold.finished;await settle(page);assert.equal(await page.locator('.alert-count').innerText(),'2');
    await page.locator('.alert-toggle').click();
    await page.locator('.alert-popover-row').filter({hasText:'Camera latest'}).click();
    await page.waitForURL('**/#/event/latest');assert(page.url().endsWith('/#/event/latest'));
  });
  }
  await check('Sound defaults off; native Web Audio only starts after opt-in, deduplicates, stops on off/logout and resets on refresh',async({page,state,message})=>{
    await page.locator('.alert-toggle').click();
    const toggle=page.getByRole('switch',{name:'Âm báo cảnh báo mới'});
    assert.equal(await toggle.isChecked(),false);assert.equal(await page.evaluate(()=>window.__qaAudio.contexts.length),0);
    state.summaries.a=summary([event('silent')]);await message();
    assert.equal(await page.evaluate(()=>window.__qaAudio.contexts.length),0);
    await toggle.click();await page.waitForFunction(()=>window.__qaAudio.contexts.at(-1)?.state==='running'&&document.querySelector('[role=switch]')?.checked);
    state.summaries.a=summary([event('audible')]);await message();assert.equal(await page.evaluate(()=>window.__qaAudio.oscillators),1);
    state.summaries.a.items[0].sequence=2;await message();assert.equal(await page.evaluate(()=>window.__qaAudio.oscillators),1);
    await toggle.click();state.summaries.a=summary([event('off-again')]);await message();
    assert.equal(await page.evaluate(()=>window.__qaAudio.oscillators),1);assert.equal(await toggle.isChecked(),false);
    await page.reload();await page.waitForFunction(()=>window.__qaSockets.length===1);await page.locator('.alert-toggle').click();
    assert.equal(await toggle.isChecked(),false);assert.equal(await page.evaluate(()=>window.__qaAudio.contexts.length),0);
    await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await toggle.click();await page.waitForFunction(()=>window.__qaAudio.contexts.at(-1)?.state==='running');
    await page.locator('.topbar').getByRole('button',{name:'Đăng xuất',exact:true}).click();
    await page.waitForFunction(()=>window.__qaAudio.contexts.at(-1)?.state==='closed');
  });
  await check('Autoplay rejection and pending resume time out safely; visual alerts remain available',async({page,state,message})=>{
    await page.locator('.alert-toggle').click();const toggle=page.getByRole('switch',{name:'Âm báo cảnh báo mới'});
    await page.evaluate(()=>window.__qaAudio.blocked=true);await toggle.click();
    await page.locator('.alert-sound-control [role=status]').filter({hasText:'Chưa bật được âm báo'}).waitFor();
    assert.equal(await toggle.isChecked(),false);
    await page.evaluate(()=>{window.__qaAudio.blocked=false;window.__qaAudio.hanging=true;});await toggle.click();
    await page.locator('.alert-sound-control [role=status]').filter({hasText:'Chưa bật được âm báo'}).waitFor();
    assert.equal(await toggle.isDisabled(),false);assert.equal(await toggle.isChecked(),false);
    state.summaries.a=summary([event('blocked')]);await message();await page.locator('.toast').filter({hasText:'Camera blocked'}).waitFor();
    assert.equal(await page.evaluate(()=>window.__qaAudio.oscillators),0);assert(await page.evaluate(()=>window.__qaAudio.contexts.every(context=>context.state==='closed')));
  },{mockAudio:true});
  await check('A suspended context disables sound with recovery guidance; re-enable requires another user click',async({page,state,message})=>{
    await page.locator('.alert-toggle').click();const toggle=page.getByRole('switch',{name:'Âm báo cảnh báo mới'});
    await toggle.click();await page.waitForFunction(()=>document.querySelector('[role=switch]')?.checked);
    await page.evaluate(()=>window.__qaAudio.contexts.at(-1).state='suspended');
    state.summaries.a=summary([event('suspended')]);await message();
    await page.locator('.alert-sound-control [role=status]').filter({hasText:'Trình duyệt đã tạm dừng âm báo'}).waitFor();
    assert.equal(await toggle.isChecked(),false);assert.equal(await page.evaluate(()=>window.__qaAudio.oscillators),0);
    state.summaries.a=summary([event('still-silent')]);await message();assert.equal(await page.evaluate(()=>window.__qaAudio.contexts.length),1);
    await toggle.click();await page.waitForFunction(()=>document.querySelector('[role=switch]')?.checked);
    state.summaries.a=summary([event('re-enabled')]);await message();assert.equal(await page.evaluate(()=>window.__qaAudio.oscillators),1);
  },{mockAudio:true});
  assert.deepEqual(errors,[]);console.log(`ALL ${passed.length} PHASE 3 REALTIME CHECKS PASSED`);
  if(process.env.UI_OUTPUT_DIR){await mkdir(process.env.UI_OUTPUT_DIR,{recursive:true});await writeFile(process.env.UI_OUTPUT_DIR+'/phase3-realtime-checks.json',JSON.stringify({passed,errors},null,2));}
}finally{await browser.close();}
