/** Isolated invitation-code UI smoke. Requires private synthetic fixture, API 8018 and Vite 5188. */
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
const fixture=JSON.parse(await readFile('.secrets/invitation-code-ui-fixture.json','utf8'));
const base=process.env.UI_BASE_URL||'http://localhost:5188';
await mkdir('artifacts/ui-review',{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[];
try {
 const owner=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
 assert.equal((await owner.request.post(base+'/api/auth/login',{data:{email:fixture.owner,password:fixture.password}})).status(),200);
 const homes=await(await owner.request.get(base+'/api/homes')).json();const home=homes.find(h=>h.camera_count>0);assert(home);
 const page=await owner.newPage();page.on('pageerror',e=>errors.push(e.message));await page.addInitScript(id=>sessionStorage.setItem('annha-active-home',id),home.id);
 await page.goto(base+'/#/members');await page.getByRole('button',{name:'Tạo mã mời',exact:true}).click();
 const codeInput=page.getByLabel('Mã mời vừa tạo',{exact:true});await codeInput.waitFor();const code=await codeInput.inputValue();
 assert.match(code,/^[A-Z2-9]{4}(-[A-Z2-9]{4}){3}$/);
 await page.getByRole('button',{name:'Sao chép mã',exact:true}).click();await page.getByRole('button',{name:'Đã sao chép',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),code);
 await page.screenshot({path:'artifacts/ui-review/invitation-code-owner.png',fullPage:true,mask:[codeInput]});
 await page.getByRole('button',{name:'Đóng',exact:true}).last().click();
 const member=await browser.newContext({viewport:{width:390,height:844}});
 assert.equal((await member.request.post(base+'/api/auth/login',{data:{email:fixture.member,password:fixture.password}})).status(),200);
 const mobile=await member.newPage();mobile.on('pageerror',e=>errors.push(e.message));
 await mobile.goto(base+'/#/homes');await mobile.getByRole('button',{name:'Tham gia nhà bằng mã',exact:true}).click();
 const input=mobile.getByLabel('Mã mời',{exact:true});await input.fill(code.toLowerCase());
 assert(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await mobile.screenshot({path:'artifacts/ui-review/invitation-code-member-mobile.png',fullPage:true,mask:[input]});
 await mobile.getByRole('button',{name:'Tham gia nhà',exact:true}).click();await mobile.waitForURL('**/#/overview');await mobile.getByRole('heading',{name:/Xin chào/}).waitFor();
 const joined=(await(await member.request.get(base+'/api/homes')).json()).find(h=>h.id===home.id);assert.equal(joined.role,'member');
 const cameras=await(await member.request.get(base+`/api/homes/${home.id}/cameras`)).json();assert(cameras.length>0);assert(cameras.every(c=>c.permissions.view&&!c.permissions.audio&&!c.permissions.schedules));
 await page.reload();const row=page.locator('.member-row').filter({hasText:fixture.member});await row.getByText('Thành viên',{exact:true}).waitFor();
 await row.getByRole('button',{name:'Sửa quyền',exact:true}).click();await page.getByLabel('Vai trò',{exact:true}).selectOption('member');await page.getByRole('button',{name:'Lưu quyền',exact:true}).click();
 await page.getByText('Đã cập nhật quyền theo từng camera.',{exact:true}).waitFor();
 await page.locator('.invitation-code-row').first().getByText('Đã sử dụng',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 const result={result:'PASS',environment:'isolated PostgreSQL 16',owner_create_and_copy:true,member_mobile_join:true,role:'member',immediate_home_camera_access:true,owner_edit_member:true,used_status:true,page_errors:0,real_emails_sent:0};
 await writeFile('artifacts/ui-review/invitation-code-result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}
