/** Live visual/interaction checks. Uses private demo credentials; never prints passwords.
 * npm run test:ui (system Chrome on macOS, or CHROME_EXECUTABLE, or installed Chromium).
 * API overrides below are browser-only fixtures for empty/error/new-room states.
 */
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile, access } from 'node:fs/promises';
import path from 'node:path';
const base=process.env.UI_BASE_URL || 'http://localhost:8188';
const output=path.resolve(process.env.UI_OUTPUT_DIR||'artifacts/ui-review');await mkdir(output,{recursive:true});
const credentialsPath=process.env.UI_CREDENTIALS_FILE || '.secrets/demo-credentials.json';
const credentials=JSON.parse(await readFile(credentialsPath,'utf8'));
const QA_SENSOR_EPOCH=Date.parse('2026-11-04T08:00:00.000Z');
let executable=process.env.CHROME_EXECUTABLE;
if (!executable) { try { await access('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');executable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'; } catch {} }
const browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
const results=[],errors=[];
function wavFixture(){
  const samples=800,body=Buffer.alloc(44+samples*2);body.write('RIFF',0);body.writeUInt32LE(body.length-8,4);body.write('WAVEfmt ',8);body.writeUInt32LE(16,16);body.writeUInt16LE(1,20);body.writeUInt16LE(1,22);body.writeUInt32LE(8000,24);body.writeUInt32LE(16000,28);body.writeUInt16LE(2,32);body.writeUInt16LE(16,34);body.write('data',36);body.writeUInt32LE(samples*2,40);return body;
}
const qaWav=wavFixture(),qaMp3=Buffer.concat(Array.from({length:5},()=>Buffer.concat([Buffer.from('fffb9000','hex'),Buffer.alloc(413)])));
async function open(role='owner',mobile=false){
  const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},reducedMotion:'reduce'});
  await context.route('**/api/cameras/*/telemetry?*',route=>{
    const cameraId=new URL(route.request().url()).pathname.split('/')[3];
    const rows=Array.from({length:18},(_,index)=>{const observed_at=new Date(QA_SENSOR_EPOCH-index*5*60_000).toISOString();return {id:'qa-reading-'+index,camera_id:cameraId,observed_at,received_at:observed_at,payload:{observed_at,readings:{temperature:{value:25+index/10,unit:'C',quality:'valid'},humidity:{value:55+index/5,unit:'%',quality:'valid'},gas:{value:160+index,unit:'ADC',quality:'valid'}}}};});
    return route.fulfill({json:rows});
  });
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
  let alertSummary={count:3,items:[{id:'qa-active-alert',camera_id:'qa-camera',camera_name:'Camera phòng khách',room_name:'Phòng khách',kind:'fall',status:'OPEN',severity:'critical',reason:'Cần kiểm tra ngay',observed_at:new Date().toISOString(),payload:{reason:'Cần kiểm tra ngay'}}]};
  await page.addInitScript(()=>{const Native=window.WebSocket;window.__qaAlertSockets=[];window.WebSocket=function(url,...args){if(String(url).includes('/ws/alerts?')){const socket={readyState:1,close(){this.readyState=3;this.onclose?.({code:1000});}};window.__qaAlertSockets.push(socket);return socket;}return new Native(url,...args);};for(const key of ['OPEN','CLOSED','CLOSING','CONNECTING'])window.WebSocket[key]=Native[key];});
  await page.route('**/api/homes/*/active-events*',route=>route.fulfill({json:alertSummary}));
  await ready(page,'overview','Xin chào');
  await page.getByRole('button',{name:/3 sự kiện đang mở/}).click();
  await page.locator('.alert-popover').getByText('Camera phòng khách').waitFor();
  await page.locator('.alert-popover').getByText('Cần kiểm tra ngay').waitFor();
  await picture(page,'01-global-alerts');
  await page.waitForFunction(()=>window.__qaAlertSockets?.length===1);
  const newAlert={id:'qa-new-alert',camera_id:'qa-camera-2',camera_name:'Camera cửa chính',status:'OPEN',kind:'fall',severity:'critical',reason:'Cần hỗ trợ',observed_at:new Date().toISOString()};
  alertSummary={count:4,items:[newAlert,...alertSummary.items]};
  await page.evaluate(event=>window.__qaAlertSockets[0].onmessage?.({data:JSON.stringify(event)}),newAlert);
  await page.locator('.toast').getByText(/Cảnh báo mới: Camera cửa chính/).waitFor();
  await page.evaluate(event=>window.__qaAlertSockets[0].onmessage?.({data:JSON.stringify(event)}),newAlert);
  await page.waitForTimeout(150);assert.equal(await page.locator('.toast').count(),1,'One toast per new active event');
  results.push('Global alert badge/menu render and WebSocket alerts toast once per event');
  await page.getByRole('button',{name:/Thông báo/}).click();await page.unroute('**/api/homes/*/active-events*');
  assert.equal(await page.locator('.room-row').count(),4);
  assert.equal(await page.locator('.real-camera > img').first().getAttribute('src'),'/images/living.png');
  assert.equal(await page.locator('.real-camera .badge.dark').count(),0,'Offline preview must not say live');
  await picture(page,'02-after-overview');results.push('Desktop overview: original artwork, four rooms, honest offline labels');
  const liveHome=(await (await context.request.get(base+'/api/homes')).json())[0];
  const liveCameras=await (await context.request.get(base+'/api/homes/'+liveHome.id+'/cameras')).json();
  const snapshotBytes=await (await context.request.get(base+'/images/living.png')).body();
  await page.route('**/api/homes/*/cameras',async route=>{const response=await route.fetch(),cameras=await response.json();return route.fulfill({json:cameras.map(camera=>({...camera,snapshot_available:true,online:false}))});});
  await page.route('**/api/cameras/*/snapshot',route=>route.fulfill({status:200,body:snapshotBytes,headers:{'content-type':'image/png','X-Captured-At':new Date().toISOString()}}));
  await ready(page,'overview','Xin chào');await page.getByText('Ảnh gần nhất',{exact:true}).first().waitFor();
  assert.match(await page.locator('.real-camera img').first().getAttribute('alt'),/^Ảnh nhận từ /);
  results.push('Stored camera snapshot replaces the placeholder and is labeled as the latest image');
  await page.unroute('**/api/homes/*/cameras');await page.unroute('**/api/cameras/*/snapshot');
  await page.getByRole('button',{name:/Phòng ngủ.*Ảnh minh hoạ/}).click();
  assert.equal(await page.locator('.real-camera > img').first().getAttribute('src'),'/images/bedroom.png');
  await page.locator('.overview-cameras > .real-camera').click();
  await page.getByRole('heading',{level:1,name:/Phòng ngủ/}).waitFor();
  results.push('Room selection switches the preview and opens the correct camera');
  for (const [route,heading,name] of [['cameras','Không gian & camera','03-after-cameras'],['devices','Thiết bị trong nhà','04-after-devices'],['environment','Môi trường sống','05-after-environment'],['events','Sự kiện & cảnh báo','06-after-events'],['reminders','Lời nhắc & âm thanh','07-after-reminders'],['members','Thành viên & quyền','09-after-members'],['settings','Cài đặt nhà','10-after-settings']]) {
    await ready(page,route,heading);
    if(route==='environment') await page.getByRole('heading',{name:'Lịch sử số đo'}).waitFor();
    if(route==='settings') await page.getByRole('heading',{name:'Dung lượng lưu trữ'}).waitFor();
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
  await ready(page,'settings','Cài đặt nhà');
  await page.getByRole('progressbar',{name:'Dung lượng lưu trữ đã dùng'}).waitFor();
  assert(await page.getByText(/đã dùng nhiều|sắp đầy|đang ổn định/i).count());
  results.push('Owner storage page shows quota, reservation, warning and retention state');
  const qaHome=(await context.request.get(base+'/api/homes')).json();
  const homeForEvidence=(await qaHome)[0],cameraForEvidence=(await (await context.request.get(base+'/api/homes/'+homeForEvidence.id+'/cameras')).json())[0];
  await page.route('**/api/events/qa-available-image',route=>route.fulfill({json:{id:'qa-available-image',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,kind:'fall',status:'OPEN',severity:'warning',observation:'suspected',first_observed_at:new Date().toISOString(),received_at:new Date().toISOString(),payload:{reason:'Ảnh tổng hợp'},actions:[],evidence:[{id:'qa-available-image-asset',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,event_id:'qa-available-image',kind:'event_image',name:'Evidence fixture',status:'ready',created_at:new Date().toISOString(),mime:'image/png',size:snapshotBytes.length,error:null}]}}));
  await page.route('**/api/assets/qa-available-image-asset',route=>route.fulfill({status:200,body:snapshotBytes,headers:{'content-type':'image/png'}}));
  await ready(page,'event/qa-available-image','Nghi ngờ té ngã');await page.getByRole('img',{name:'Ảnh bằng chứng sự kiện'}).waitFor();
  assert(await page.getByRole('img',{name:'Ảnh bằng chứng sự kiện'}).evaluate(image=>image.naturalWidth>0));
  results.push('Stored event evidence image loads and decodes');
  await page.unroute('**/api/events/qa-available-image');await page.unroute('**/api/assets/qa-available-image-asset');
  await page.route('**/api/events/qa-unavailable-image',route=>route.fulfill({json:{id:'qa-unavailable-image',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,kind:'fall',status:'OPEN',severity:'warning',observation:'suspected',first_observed_at:new Date().toISOString(),received_at:new Date().toISOString(),payload:{reason:'Browser fixture'},actions:[],evidence:[{id:'qa-expired-image',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,event_id:'qa-unavailable-image',kind:'event_image',name:'Synthetic evidence',status:'ready',created_at:new Date().toISOString(),mime:'image/jpeg',size:123,error:null}]}}));
  await page.route('**/api/assets/qa-expired-image',route=>route.fulfill({status:404,body:'Not found'}));
  await ready(page,'event/qa-unavailable-image','Nghi ngờ té ngã');
  await page.getByText('Ảnh không khả dụng',{exact:true}).waitFor();
  await page.getByText('Thông tin sự kiện vẫn được lưu.',{exact:true}).waitFor();
  results.push('Unavailable event evidence preserves the event and shows a calm fallback');
  await page.unroute('**/api/events/qa-unavailable-image');await page.unroute('**/api/assets/qa-expired-image');
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
  // Verify the WAV/MP3 library controls and local TTS preview without saving a schedule.
  await page.route('**/api/homes/*/assets',route=>route.fulfill({json:[
    {id:'qa-audio-wav',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,kind:'audio',name:'WAV tổng hợp',status:'ready',created_at:new Date().toISOString(),mime:'audio/wav',size:qaWav.length,error:null},
    {id:'qa-audio-mp3',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,kind:'audio',name:'MP3 tổng hợp',status:'ready',created_at:new Date().toISOString(),mime:'audio/mpeg',size:qaMp3.length,error:null},
    {id:'qa-audio-failed',home_id:homeForEvidence.id,camera_id:cameraForEvidence.id,kind:'tts',name:'Lời nhắc chưa tạo được',status:'failed',created_at:new Date().toISOString(),mime:'audio/wav',size:0,error:'TTSFailed'}
  ]}));
  await page.route('**/api/assets/qa-audio-wav',route=>route.fulfill({status:200,body:qaWav,headers:{'content-type':'audio/wav','accept-ranges':'bytes'}}));
  await page.route('**/api/assets/qa-audio-mp3',route=>route.fulfill({status:200,body:qaMp3,headers:{'content-type':'audio/mpeg','accept-ranges':'bytes'}}));
  const audioRequests=[];page.on('request',request=>{if(request.url().includes('/api/assets/qa-audio-'))audioRequests.push(request.url());});
  await ready(page,'reminders','Lời nhắc & âm thanh');await page.getByRole('button',{name:'Thư viện âm thanh',exact:true}).click();
  const audioPlayers=page.locator('.audio-library-card audio');await audioPlayers.first().waitFor();assert.equal(await audioPlayers.count(),2);
  const wavResponse=page.waitForResponse(response=>response.url().endsWith('/api/assets/qa-audio-wav')&&response.status()===200);
  await audioPlayers.nth(0).evaluate(audio=>audio.load());await wavResponse;
  const mp3Response=page.waitForResponse(response=>response.url().endsWith('/api/assets/qa-audio-mp3')&&response.status()===200);
  await audioPlayers.nth(1).evaluate(audio=>audio.load());await mp3Response;
  assert((await audioPlayers.nth(0).getAttribute('src')).endsWith('/qa-audio-wav'));
  assert((await audioPlayers.nth(1).getAttribute('src')).endsWith('/qa-audio-mp3'));
  assert(audioRequests.some(url=>url.endsWith('/api/assets/qa-audio-wav'))&&audioRequests.some(url=>url.endsWith('/api/assets/qa-audio-mp3')));
  for(const player of [audioPlayers.nth(0),audioPlayers.nth(1)]){
    await player.evaluate(async audio=>{audio.muted=true;await audio.play();});
    await player.evaluate(audio=>audio.pause());
    assert(await player.evaluate(audio=>audio.readyState>=2),'Audio source must reach a playable state');
  }
  const retryResponse=page.waitForResponse(response=>response.url().endsWith('/api/assets/qa-audio-failed/retry')&&response.status()===202);
  await page.route('**/api/assets/qa-audio-failed/retry',route=>route.fulfill({status:202,json:{id:'qa-audio-failed',status:'processing'}}));
  await page.getByRole('button',{name:'Thử tạo lại',exact:true}).click();await retryResponse;
  await page.getByRole('button',{name:'Lịch nhắc',exact:true}).click();await page.getByRole('button',{name:'Tạo lời nhắc',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Tạo lời nhắc',exact:true});await dialog.waitFor();
  await dialog.getByLabel('Tên lịch').fill('Lời nhắc tổng hợp');await dialog.getByLabel('Nội dung lời nhắc').fill('Nhớ uống nước nhé.');
  const previewRequests=[];await page.route('**/api/cameras/*/tts-preview',async route=>{previewRequests.push(route.request().postDataJSON());return route.fulfill({status:200,body:qaWav,headers:{'content-type':'audio/wav'}});});
  await dialog.getByRole('button',{name:'Phát thử lời nhắc'}).click();await dialog.locator('.reminder-preview audio').waitFor();
  assert.equal(previewRequests.at(-1)?.text,'Nhớ uống nước nhé.');
  let savedReminder=null;await page.route('**/api/homes/*/reminders',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    savedReminder=route.request().postDataJSON();return route.fulfill({status:201,json:{id:'qa-saved-reminder',status:'pending',asset_id:'qa-created-tts'}});
  });
  await dialog.getByRole('button',{name:'Lưu lời nhắc'}).click();await dialog.waitFor({state:'detached'});
  assert.equal(savedReminder?.source,'tts');assert.equal(savedReminder?.text,'Nhớ uống nước nhé.');
  results.push('WAV/MP3 players decode, TTS preview plays, and the reminder form submits TTS data');
  await page.unroute('**/api/cameras/*/tts-preview');await page.unroute('**/api/homes/*/assets');await page.unroute('**/api/assets/qa-audio-wav');await page.unroute('**/api/assets/qa-audio-mp3');await page.unroute('**/api/assets/qa-audio-failed/retry');await page.unroute('**/api/homes/*/reminders');
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
  await page.reload();
  await ready(page,'cameras','Không gian & camera');await page.getByLabel('Lọc theo phòng').selectOption('qa-new-room');
  assert.equal(await page.locator('.camera-grid .real-camera > img').getAttribute('src'),'/images/living.png');
  await page.getByText('Chưa ghép nối camera',{exact:true}).waitFor();await picture(page,'11-new-room-placeholder');
  results.push('New unpaired room has original photo, status and pairing action');await page.unrouteAll({behavior:'wait'});
  // No camera/room/data: maintain the visual layout and usable setup action.
  await page.route(/\/api\/homes\/[^/]+\/(cameras|rooms|events|reminders)$/,route=>route.fulfill({json:[]}));
  await page.reload();
  await ready(page,'overview','Xin chào');await page.getByRole('heading',{name:'Bắt đầu với không gian của bạn'}).waitFor();
  await picture(page,'12-empty-home');results.push('Empty home remains complete and offers room setup');await page.unrouteAll({behavior:'wait'});await page.reload();
  // Automatic refresh must not unmount the environment content on a transient 503.
  await ready(page,'environment','Môi trường sống');await page.getByRole('heading',{name:'Lịch sử số đo'}).waitFor();
  const stable=await page.getByRole('heading',{name:'Lịch sử số đo'}).elementHandle();
  await page.route('**/api/cameras/*/telemetry?*',route=>route.fulfill({status:503,json:{detail:'QA: tạm thời không kết nối được cảm biến'}}));
  await page.locator('.notice.error').filter({hasText:'QA: tạm thời không kết nối được cảm biến'}).waitFor({timeout:35000});
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
