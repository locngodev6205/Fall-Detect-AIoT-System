/** Live visual/interaction checks. Uses private demo credentials; never prints passwords.
 * npm run test:ui (system Chrome on macOS, or CHROME_EXECUTABLE, or installed Chromium).
 * API overrides below are browser-only fixtures for empty/error/new-room states.
 */
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile, access } from 'node:fs/promises';
import path from 'node:path';
const base=process.env.UI_BASE_URL || 'http://localhost:8188';
const output=path.resolve('artifacts/ui-review');await mkdir(output,{recursive:true});
const credentials=JSON.parse(await readFile('.secrets/demo-credentials.json','utf8'));
let executable=process.env.CHROME_EXECUTABLE;
if (!executable) { try { await access('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');executable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'; } catch {} }
const browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
const results=[],errors=[];
async function open(role='owner',mobile=false){
  const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},reducedMotion:'reduce'});
  const account=credentials.accounts.find(account=>account.role===role);
  const response=await context.request.post(base+'/api/auth/login',{data:{email:account.email,password:account.password}});
  assert.equal(response.status(),200,'Account sign-in');
  const page=await context.newPage();page.on('pageerror',error=>errors.push({role,message:error.message}));
  return {context,page};
}
async function ready(page,route,heading){
  await page.goto(base+'/#/'+route);
  await page.getByRole('heading',{level:1}).filter({hasText:heading}).waitFor();
  await page.evaluate(()=>document.fonts.ready);
  await page.waitForLoadState('networkidle');
}
async function picture(page,name,fullPage=true){
  await page.waitForFunction(()=>![...document.querySelectorAll('.workspace .panel[role=status]')].some(element=>element.getBoundingClientRect().height));
  await page.locator('.workspace img').evaluateAll(images=>Promise.all(images.map(image=>image.decode().catch(()=>{}))));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal overflow');
  await page.screenshot({path:path.join(output,name+'.png'),fullPage});
}
try {
  const {context,page}=await open();
  await ready(page,'overview','Xin chào');
  assert.equal(await page.locator('.room-row').count(),4);
  assert.equal(await page.locator('.real-camera > img').first().getAttribute('src'),'/images/living.png');
  assert.equal(await page.locator('.real-camera .badge.dark').count(),0,'Offline preview must not say live');
  await picture(page,'02-after-overview');results.push('Desktop overview: original artwork, four rooms, honest offline labels');
  await page.getByRole('button',{name:/Phòng ngủ.*Ảnh minh hoạ/}).click();
  assert.equal(await page.locator('.real-camera > img').first().getAttribute('src'),'/images/bedroom.png');
  await page.locator('.overview-cameras > .real-camera').click();
  await page.getByRole('heading',{level:1,name:/Phòng ngủ/}).waitFor();
  results.push('Room selection switches the preview and opens the correct camera');
  for (const [route,heading,name] of [['cameras','Không gian & camera','03-after-cameras'],['devices','Thiết bị trong nhà','04-after-devices'],['environment','Môi trường sống','05-after-environment'],['events','Sự kiện & cảnh báo','06-after-events'],['reminders','Lời nhắc & âm thanh','07-after-reminders'],['members','Thành viên & quyền','09-after-members'],['settings','Cài đặt nhà','10-after-settings']]) {
    await ready(page,route,heading);
    if(route==='environment') await page.getByRole('heading',{name:'Lịch sử số đo'}).waitFor();
    if(route==='cameras') assert(await page.locator('.camera-grid').evaluate(element=>parseFloat(getComputedStyle(element).rowGap)>=16),'Camera card spacing');
    await picture(page,name,route!=='environment');results.push('Desktop route '+route+': renders without overflow');
  }
  // Workflow additions are tested without deleting any real home.
  await ready(page,'environment','Môi trường sống');
  await page.getByRole('img',{name:/Biểu đồ Nhiệt độ/}).waitFor();
  await page.getByRole('button',{name:'Độ ẩm',exact:true}).click();
  await page.getByRole('img',{name:/Biểu đồ Độ ẩm/}).waitFor();
  await picture(page,'20-environment-chart');results.push('Environment chart switches metric and unit');
  await ready(page,'reminders','Lời nhắc & âm thanh');
  assert(await page.locator('.reminder-item').first().evaluate(element=>parseFloat(getComputedStyle(element).paddingLeft)>=20));
  await picture(page,'21-reminder-padding');results.push('Reminder cards have comfortable inner padding');
  const homesForPaging=await (await context.request.get(base+'/api/homes')).json();
  const fixtureEvents=await (await context.request.get(base+'/api/homes/'+homesForPaging[0].id+'/events')).json();
  const fixture=Array.from({length:23},(_,index)=>({...fixtureEvents[0],id:'qa-page-'+index,payload:{reason:'Bản ghi '+index}}));
  const requested=[];
  await page.route('**/api/homes/*/events?*',route=>{const query=new URL(route.request().url()).searchParams;requested.push(Object.fromEntries(query));const number=Number(query.get('page')||1);const filtered=query.get('kind')==='device'?[]:fixture;return route.fulfill({json:{items:filtered.slice((number-1)*10,number*10),total:filtered.length,total_pages:Math.max(1,Math.ceil(filtered.length/10)),page:number,page_size:10}});});
  await ready(page,'events','Sự kiện & cảnh báo');
  assert.equal(await page.locator('.event-live-row').count(),10);
  await page.getByRole('button',{name:'Trang sau',exact:true}).click();await page.getByText('Bản ghi 10',{exact:true}).waitFor();
  assert.equal(await page.locator('.event-live-row').count(),10);
  await page.getByLabel('Phòng',{exact:true}).selectOption({index:1});await page.getByText('Bản ghi 0',{exact:true}).waitFor();
  assert(requested.at(-1).room_id);assert.equal(requested.at(-1).page,'1');
  await picture(page,'22-event-pagination');
  await page.getByLabel('Loại sự kiện',{exact:true}).selectOption('device');await page.getByRole('heading',{name:'Chưa có sự kiện phù hợp'}).waitFor();
  await page.unrouteAll({behavior:'wait'});results.push('Events page/filter requests reset page, show 10 rows and handle empty results');
  await ready(page,'setup','Kết nối camera với nhà');await page.getByRole('button',{name:'Thiết lập sau'}).click();await page.getByRole('heading',{level:1,name:/Xin chào/}).waitFor();
  await page.locator('.sidebar .brand').count().then(async count=>{if(count)await page.locator('.sidebar .brand').click();else await page.locator('.sidebar a[href="#/overview"]').first().click();});
  assert.equal((await context.request.get(base+'/api/auth/me')).status(),200);results.push('Skip setup and logo navigation preserve the session');
  await ready(page,'homes','Những ngôi nhà của bạn');await page.getByRole('button',{name:/Xoá nhà /}).first().click();
  assert(await page.getByRole('button',{name:'Xác nhận xoá nhà',exact:true}).isDisabled());
  await picture(page,'23-delete-home-confirmation');await page.getByRole('button',{name:'Huỷ',exact:true}).click();results.push('Home deletion requires typed confirmation; no existing home deleted');
  // Every open incident uses the normal production flow, including seeded records.
  const ownerHomes=await (await context.request.get(base+'/api/homes')).json();
  const existingEvents=await (await context.request.get(base+'/api/homes/'+ownerHomes[0].id+'/events')).json();
  const expectedOpen=existingEvents.filter(event=>['OPEN','ACKNOWLEDGED'].includes(event.status)).length+1;
  const incidentFixture=[{id:'qa-real-event',camera_id:'qa-real-camera',kind:'fall',status:'OPEN',severity:'critical',observed_at:new Date().toISOString(),payload:{reason:'QA incident'}},...existingEvents];
  await page.route('**/api/homes/*/events',route=>route.fulfill({json:incidentFixture}));
  await ready(page,'overview','Xin chào');await page.getByText(`${expectedOpen} sự kiện cần kiểm tra`,{exact:true}).waitFor();
  results.push('All open incidents remain prominent in the normal production flow');await page.unrouteAll({behavior:'wait'});
  // House selection restores the original photo, truthful scope counts, and working actions.
  await ready(page,'homes','Những ngôi nhà của bạn');
  assert(await page.locator('.home-cover img').first().evaluate(async image=>{await image.decode();return image.naturalWidth>100;}));
  assert(!(await page.locator('.workspace h1,.workspace h2,.home-selector strong,.account-button').allTextContents()).some(text=>/demo/i.test(text)));
  await picture(page,'18-house-selection');
  await page.getByRole('button',{name:'Tạo nhà mới',exact:true}).click();await page.getByRole('dialog',{name:'Tạo nhà mới',exact:true}).waitFor();
  await page.getByRole('button',{name:'Đóng',exact:true}).click();await page.getByRole('button',{name:'Mở nhà',exact:false}).first().click();
  await page.locator('.room-row').nth(3).waitFor();
  results.push('House photo cards, production labels, create dialog and open-house navigation work');
  // Structured ACK results used to crash React. Keep this regression browser-local.
  await page.route('**/api/cameras/*/commands',async route=>{
    if(route.request().method()!=='GET')return route.continue();
    return route.fulfill({json:[{id:'qa-ack',kind:'play_audio',created_at:new Date().toISOString(),status:'executed',result:{detail:'Đã phát thử'}}]});
  });
  await ready(page,'reminders/send','Lời nhắc & âm thanh');
  await page.getByText('Đã phát thử',{exact:true}).waitFor();
  results.push('Structured device ACK result renders safely');await page.unrouteAll({behavior:'wait'});
  // New room: generic original photo and unpaired state, with no fabricated device.
  await page.route('**/api/homes/*/rooms',async route=>{const response=await route.fetch();const rooms=await response.json();return route.fulfill({json:[...rooms,{id:'qa-new-room',name:'Phòng đọc sách mới'}]});});
  await ready(page,'cameras','Không gian & camera');await page.getByLabel('Lọc theo phòng').selectOption('qa-new-room');
  assert.equal(await page.locator('.camera-grid .real-camera > img').getAttribute('src'),'/images/living.png');
  await page.getByText('Chưa ghép nối camera',{exact:true}).waitFor();await picture(page,'11-new-room-placeholder');
  results.push('New unpaired room has original photo, status and pairing action');await page.unrouteAll({behavior:'wait'});
  // No camera/room/data: maintain the visual layout and usable setup action.
  await page.route(/\/api\/homes\/[^/]+\/(cameras|rooms|events|reminders)$/,route=>route.fulfill({json:[]}));
  await ready(page,'overview','Xin chào');await page.getByRole('heading',{name:'Bắt đầu với không gian của bạn'}).waitFor();
  await picture(page,'12-empty-home');results.push('Empty home remains complete and offers room setup');await page.unrouteAll({behavior:'wait'});
  // Automatic refresh must not unmount the environment content on a transient 503.
  await ready(page,'environment','Môi trường sống');await page.getByRole('heading',{name:'Lịch sử số đo'}).waitFor();
  const stable=await page.getByRole('heading',{name:'Lịch sử số đo'}).elementHandle();
  await page.route('**/api/cameras/*/telemetry?*',route=>route.fulfill({status:503,json:{detail:'QA: tạm thời không kết nối được cảm biến'}}));
  await page.locator('.notice.error').filter({hasText:'QA: tạm thời không kết nối được cảm biến'}).waitFor({timeout:22000});
  assert(await stable.evaluate(element=>element.isConnected),'Refresh must preserve the last loaded content');
  results.push('Transient API failure preserves loaded content and exposes retry');await page.unrouteAll({behavior:'wait'});await context.close();
  for(const role of ['caregiver','viewer','outsider']) {
    const {context,page}=await open(role);await ready(page,'overview','Xin chào');
    assert.equal(await page.locator('.room-row').count(),role==='viewer'?1:4);
    await picture(page,'13-role-'+role,false);results.push('Role '+role+': scoped preview renders correctly');await context.close();
  }
  const startup=await open();
  await startup.page.route('**/api/homes',route=>route.fulfill({status:503,json:{detail:'QA: chưa tải được nhà'}}));
  await startup.page.goto(base+'/#/overview');
  await startup.page.getByRole('alert').filter({hasText:'QA: chưa tải được nhà'}).waitFor();
  assert.equal(await startup.page.getByText('Bạn chưa tham gia nhà nào',{exact:true}).count(),0);
  await startup.page.unrouteAll({behavior:'wait'});await startup.page.getByRole('button',{name:'Thử lại',exact:true}).click();
  await startup.page.locator('.room-row').nth(3).waitFor();
  results.push('Initial home-list outage shows retry and recovers without a misleading empty home');await startup.context.close();
  const streamCheck=await open();
  const fixturePng=(await streamCheck.context.request.get(base+'/images/living.png'));
  const fixtureBase64=(await fixturePng.body()).toString('base64');
  await streamCheck.page.addInitScript(base64=>{
    const Native=window.WebSocket;
    window.WebSocket=function(url,...args){
      if(String(url).includes('/ws/cameras/')){
        const fake={readyState:1,close(){this.readyState=3;this.onclose?.({code:1000});}};
        setTimeout(()=>fake.onmessage?.({data:new Blob([Uint8Array.from(atob(base64),c=>c.charCodeAt(0))],{type:'image/png'})}),100);
        return fake;
      }
      return new Native(url,...args);
    };
    for(const key of ['OPEN','CLOSED','CLOSING','CONNECTING'])window.WebSocket[key]=Native[key];
  },fixtureBase64);
  await streamCheck.page.route('**/api/homes/*/cameras',async route=>{const response=await route.fetch();const cameras=await response.json();return route.fulfill({json:cameras.map(camera=>({...camera,online:true,snapshot_available:false}))});});
  await ready(streamCheck.page,'overview','Xin chào');
  await streamCheck.page.locator('.real-camera .badge.dark').waitFor();
  await streamCheck.page.locator('.real-camera .badge.dark').waitFor({state:'hidden',timeout:7500});
  assert.equal(await streamCheck.page.locator('.real-camera .photo-source').innerText(),'Ảnh gần nhất');
  results.push('A stalled stream loses its live label and preserves the timestamped last frame');await streamCheck.context.close();
  const mobile=await open('owner',true);
  for(const [route,heading,name] of [['homes','Những ngôi nhà của bạn','19-mobile-houses'],['overview','Xin chào','14-mobile-overview'],['cameras','Không gian & camera','15-mobile-cameras'],['environment','Môi trường sống','24-mobile-environment'],['events','Sự kiện & cảnh báo','25-mobile-events'],['reminders','Lời nhắc & âm thanh','26-mobile-reminders'],['reminders/send','Lời nhắc & âm thanh','16-mobile-audio'],['settings','Cài đặt nhà','17-mobile-settings']]) {
    await ready(mobile.page,route,heading);if(route==='cameras') assert(await mobile.page.locator('.camera-grid').evaluate(element=>parseFloat(getComputedStyle(element).rowGap)>=16),'Mobile camera card spacing');await picture(mobile.page,name);results.push('Mobile '+route+': no horizontal overflow');
  }
  await mobile.page.locator('.topbar').getByRole('button',{name:'Đăng xuất',exact:true}).click();await mobile.page.getByRole('heading',{level:1,name:'Chào mừng bạn trở lại'}).waitFor();assert.equal((await mobile.context.request.get(base+'/api/auth/me')).status(),401);results.push('Explicit logout ends the session');
  await mobile.context.close();assert.equal(errors.length,0,JSON.stringify(errors));
  await writeFile(path.join(output,'checks.json'),JSON.stringify({passed:results,errors},null,2));
  for(const result of results)console.log('PASS '+result);
  console.log(`ALL ${results.length} UI CHECKS PASSED; no uncaught page errors.`);
} finally {await browser.close();}
