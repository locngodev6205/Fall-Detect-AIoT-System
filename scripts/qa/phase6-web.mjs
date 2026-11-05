/** One focused Phase 6 browser smoke, isolated local API/Postgres only; no providers. */
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
const fixture=JSON.parse(await readFile('.secrets/phase6-ui.json','utf8'));
const base='http://127.0.0.1:5188';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const resume=process.env.PHASE6_FROM||'';
const previous=resume?JSON.parse(await readFile('artifacts/ui-review/phase6-web-result.json','utf8')):null;
const results={environment:'isolated local PostgreSQL; real API; no SMTP/Telegram/Cloudinary',checks:previous?.checks||[],page_errors:[]};
await mkdir('artifacts/ui-review',{recursive:true});
try{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const login=await context.request.post(base+'/api/auth/login',{data:{email:fixture.email,password:fixture.password}});assert.equal(login.status(),200);
 const page=await context.newPage();page.on('pageerror',e=>results.page_errors.push(e.message));
 await page.goto(base);await page.evaluate(id=>sessionStorage.setItem('annha-active-home',id),fixture.home);
 async function open(route){await page.goto(base+'/#/'+route);await page.waitForLoadState('networkidle');}
 async function shot(name){assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal page overflow: '+name);await page.screenshot({path:'artifacts/ui-review/phase6-'+name+'.png',fullPage:true});}
 if(!resume){
 await open('environment');await page.getByText('605 mẫu trong toàn khoảng',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Trang sau',exact:true}).click();await page.getByText('11–20 / 605 kết quả',{exact:true}).waitFor();
 await page.getByLabel('Khoảng thời gian',{exact:true}).selectOption('custom');
 await page.getByLabel('Từ ngày giờ',{exact:true}).fill('2026-01-01T00:00');await page.getByLabel('Đến trước ngày giờ',{exact:true}).fill('2027-01-01T00:00');await page.getByRole('button',{name:'Áp dụng',exact:true}).click();await page.getByText('605 mẫu trong toàn khoảng',{exact:true}).waitFor();await shot('environment-desktop');results.checks.push('summary covers 605 samples, custom range and server detail page 2');
 await open('events');await page.getByLabel('Mức cảnh báo',{exact:true}).selectOption('critical');await page.getByLabel('Từ ngày giờ',{exact:true}).fill('2026-01-01T00:00');await page.getByLabel('Đến trước ngày giờ',{exact:true}).fill('2027-01-01T00:00');await page.locator('a.event-live-row').first().waitFor();await shot('events-desktop');
 }
 await open('event/'+fixture.event);await page.getByRole('heading',{name:'Diễn biến quan sát'}).waitFor();await page.getByText('Bằng chứng đã hết hạn',{exact:true}).waitFor();await page.getByText('Bằng chứng đã được xóa',{exact:true}).waitFor();await page.getByText('Không thể tải bằng chứng',{exact:true}).waitFor();await page.getByRole('button',{name:'Trang sau',exact:true}).click();await page.getByText('11–13 / 13 kết quả',{exact:true}).waitFor();await shot('event-detail-desktop');results.checks.push('event range/severity, update timeline page 2, expired/deleted/failed evidence');
 await open('reminders');await page.getByRole('button',{name:'Thư viện âm thanh',exact:true}).click();await page.getByRole('button',{name:'Trang sau',exact:true}).click();await page.getByText('11–20 / 23 kết quả',{exact:true}).waitFor();
 await page.getByLabel('Tìm âm thanh',{exact:true}).fill('Đã đổi tên');await page.locator('.audio-library-card').filter({hasText:'Đã đổi tên'}).waitFor();const card=page.locator('.audio-library-card').filter({hasText:'Đã đổi tên'});assert(await card.getByRole('button',{name:'Xóa Đã đổi tên'}).isDisabled());await card.getByRole('button',{name:'Đổi tên',exact:true}).click();await page.getByLabel('Tên âm thanh',{exact:true}).fill('Âm thanh browser');await page.getByRole('button',{name:'Lưu tên',exact:true}).click();await page.getByLabel('Tìm âm thanh',{exact:true}).fill('Âm thanh browser');await page.locator('.audio-library-card').filter({hasText:'Âm thanh browser'}).waitFor();results.checks.push('audio server pages/search, rename and in-use delete disabled');
 await page.getByRole('button',{name:'Lịch nhắc',exact:true}).click();await page.getByRole('button',{name:'Chỉnh sửa',exact:true}).click();assert(await page.getByLabel('Camera/loa đích',{exact:true}).isDisabled());await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'Tạo lời nhắc',exact:true}).click();await page.getByLabel('Tên lịch',{exact:true}).fill('Lịch upload browser');await page.getByLabel('Nguồn âm thanh',{exact:true}).selectOption('audio');
 const wav=Buffer.alloc(44+1600);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(8000,24);wav.writeUInt32LE(16000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(1600,40);
 await page.getByLabel('Hoặc tải âm thanh mới',{exact:true}).setInputFiles({name:'Ghi âm browser.wav',mimeType:'audio/wav',buffer:wav});await page.getByRole('button',{name:'Lưu lời nhắc',exact:true}).waitFor();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Lưu lời nhắc')?.disabled);
 await page.setViewportSize({width:390,height:844});await shot('reminder-upload-mobile');await page.getByRole('button',{name:'Lưu lời nhắc',exact:true}).click();await page.getByRole('heading',{name:'07:00 · Lịch upload browser',exact:true}).waitFor();results.checks.push('camera locked on edit; inline real local upload selected ready and saved reminder');
 await page.getByRole('button',{name:'Lịch sử phát',exact:true}).click();await page.getByLabel('Kết quả phát',{exact:true}).selectOption('failed');await shot('playback-mobile');
 await page.setViewportSize({width:1440,height:1000});await open('settings');await page.getByText('Lịch sử thông báo',{exact:true}).click();await page.getByLabel('Kênh gửi',{exact:true}).selectOption('email');await page.getByLabel('Trạng thái gửi',{exact:true}).selectOption('accepted');await page.getByText('Hoạt động trong nhà',{exact:true}).click();await page.getByRole('button',{name:'Trang sau',exact:true}).click();await shot('settings-desktop');results.checks.push('notification channel/status controls and audit page 2');
 await page.setViewportSize({width:390,height:844});await shot('settings-mobile');assert.deepEqual(results.page_errors,[]);results.result='PASS';console.log(JSON.stringify(results));
}finally{await writeFile('artifacts/ui-review/phase6-web-result.json',JSON.stringify(results,null,2));await browser.close();}
