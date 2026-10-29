import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
const args=process.argv.slice(2),file=args[args.indexOf('--output')+1];if(!file)throw new Error('--output required');
const account=JSON.parse(await readFile('.secrets/demo-credentials.json','utf8')).accounts.find(a=>a.role==='owner');
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
try{const context=await browser.newContext({viewport:{width:1440,height:1000}});const result=await context.request.post('http://localhost:8188/api/auth/login',{data:{email:account.email,password:account.password}});if(!result.ok())throw new Error('Login failed');const samples=[];
for(let i=0;i<3;i++){const page=await context.newPage();const start=performance.now();await page.goto('http://localhost:8188/#/overview');await page.locator('.room-row').nth(3).waitFor();const overview=Math.round(performance.now()-start);const envStart=performance.now();await page.locator('a[href="#/environment"]').first().click();await page.getByRole('heading',{name:'Lịch sử số đo'}).waitFor();samples.push({overview_ms:overview,environment_ms:Math.round(performance.now()-envStart)});console.log(samples.at(-1));await page.close();}
await writeFile(file,JSON.stringify(samples,null,2));await context.close();}finally{await browser.close();}
