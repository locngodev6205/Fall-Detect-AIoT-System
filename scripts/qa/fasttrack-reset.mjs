/** Single OTP-reset UI smoke on the isolated local fixture; no real SMTP. */
import {chromium} from 'playwright';import assert from 'node:assert/strict';
import {readFile,mkdir,writeFile} from 'node:fs/promises';import {execFileSync} from 'node:child_process';
const fixture=JSON.parse(await readFile('.secrets/fasttrack-reset-ui-fixture.json','utf8'));
const base='http://localhost:5188';await mkdir('artifacts/ui-review',{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
 const context=await browser.newContext({viewport:{width:390,height:844}});
 assert.equal((await context.request.post(base+'/api/auth/login',{data:{email:fixture.email,password:fixture.old}})).status(),200);
 const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto(base+'/#/forgot');await page.getByLabel('Email',{exact:true}).fill(fixture.email);
 await page.getByRole('button',{name:'Gửi mã đặt lại mật khẩu',exact:true}).click();await page.getByLabel('Mã đặt lại mật khẩu',{exact:true}).waitFor();
 const code=execFileSync('python3',['/private/tmp/annha_reset_read_test_code.py'],{encoding:'utf8',env:{...process.env,PYTHONPATH:'.'}}).trim();assert.match(code,/^\d{8}$/);
 await page.getByLabel('Mã đặt lại mật khẩu',{exact:true}).fill(code);await page.getByRole('button',{name:'Xác nhận mã',exact:true}).click();
 await page.getByLabel('Mật khẩu mới',{exact:true}).waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'artifacts/ui-review/fasttrack-reset-mobile.png',fullPage:true});
 await page.getByLabel('Mật khẩu mới',{exact:true}).fill(fixture.new);await page.getByLabel('Xác nhận mật khẩu mới',{exact:true}).fill(fixture.new);
 await page.getByRole('button',{name:'Lưu mật khẩu mới',exact:true}).click();await page.getByRole('button',{name:'Đăng nhập bằng mật khẩu mới',exact:true}).waitFor();
 assert.equal((await context.request.get(base+'/api/auth/me')).status(),401);
 assert.equal((await context.request.post(base+'/api/auth/login',{data:{email:fixture.email,password:fixture.old}})).status(),401);
 await page.getByRole('button',{name:'Đăng nhập bằng mật khẩu mới',exact:true}).click();
 await page.getByLabel('Email',{exact:true}).fill(fixture.email);await page.getByLabel('Mật khẩu',{exact:true}).fill(fixture.new);await page.getByRole('button',{name:'Đăng nhập',exact:true}).click();
 await page.waitForURL('**/#/homes');await page.getByRole('heading',{name:'Những ngôi nhà của bạn',exact:true}).waitFor();assert.deepEqual(errors,[]);
 const result={result:'PASS',environment:'isolated local PostgreSQL',three_step_reset:true,old_session_revoked:true,old_password_rejected:true,new_password_ui_login:true,mobile_no_overflow:true,page_errors:0,real_emails_sent:0};
 await writeFile('artifacts/ui-review/fasttrack-reset-result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}
