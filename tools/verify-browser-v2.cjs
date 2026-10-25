const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {openBrowser}=require('E:/gitproject/farmer-film-titles/node_modules/@remotion/renderer');
const output=path.join(__dirname,'../test-results/v2');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await openBrowser('chrome',{browserExecutable:'C:/Users/ASUS/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe',logLevel:'error'});
 try{
 const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
 await page.evaluateOnNewDocument(()=>{window.__errors=[];window.__csp=[];addEventListener('error',e=>window.__errors.push(e.message));addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason)));addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective));window.__setInput=(id,value)=>{const el=document.getElementById(id);const prototype=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))}});
 await page.setViewport({width:1440,height:1120,deviceScaleFactor:1});
 await page.goto({url:'http://127.0.0.1:8770/',timeout:15000});
 async function until(fn){for(let i=0;i<80;i++){if(await page.evaluate(fn))return;await new Promise(r=>setTimeout(r,100))}await shot('failure.png');console.error(await page.evaluate(()=>({text:document.body.textContent.slice(-2500),errors:window.__errors,csp:window.__csp})));throw Error('UI wait timed out: '+fn.toString())}
 async function shot(name){const s=await page._client().send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,name),Buffer.from(s.value.data,'base64'))}
 const get=route=>page.evaluate(async path=>await(await fetch('/api'+path)).json(),route);
 async function click(selector){await page.evaluate(s=>{const node=document.querySelector(s);if(!node)throw Error('Missing '+s);node.click()},selector)}
 async function button(text){await page.evaluate(t=>{const node=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===t);if(!node)throw Error('Missing button '+t);node.click()},text)}
 async function input(id,value){await page.evaluate(({id,value})=>window.__setInput(id,value),{id,value});await new Promise(r=>setTimeout(r,70))}
 async function pointer(selector){const rect=await page.evaluate(s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}},selector);await page._client().send('Input.dispatchMouseEvent',{type:'mousePressed',...rect,button:'left',clickCount:1});await page._client().send('Input.dispatchMouseEvent',{type:'mouseReleased',...rect,button:'left',clickCount:1})}
 await until(()=>!!document.querySelector('[data-testid="load-example"]'));
 await shot('empty-desktop.png');
 await click('[data-testid="load-example"]');
 await until(()=>document.querySelectorAll('[data-plan-item]').length===4);
 const f=await get('/forecast');assert.equal(f.shortfall_cents,27000);assert.ok(f.items.every(i=>i.source==='example'));
 await until(()=>!document.querySelector('.toast'));await shot('desktop.png');
 const rent=f.items.find(i=>i.title==='房租');
 await click('[data-edit-item="'+rent.id+'"]');
 await until(()=>!!document.getElementById('item-day'));
 await input('item-day',f.points[6].day);
 await click('[data-testid="preview-date"]');
 await until(()=>!!document.querySelector('[data-testid="preview-result"]'));
 assert.equal((await get('/forecast')).items.find(i=>i.id===rent.id).day,rent.day);
 await shot('date-preview.png');
 await input('item-day',f.today);await click('[data-testid="save-item"]');
 await until(()=>!document.getElementById('item-day'));
 // Select a fault using the real Radix combobox and pointer events.
 await page.evaluate(()=>document.querySelectorAll('.nav-item')[3].click());
 await button('演示工具');await until(()=>!!document.querySelector('[role="dialog"] [role="combobox"]'));
 await pointer('[role="dialog"] [role="combobox"]');
 await until(()=>document.querySelectorAll('[role="option"]').length===3);
 await page.evaluate(()=>{const node=[...document.querySelectorAll('[role="option"]')].find(n=>n.textContent.includes('银行已受理'));node.dataset.testFault='true'});
 await pointer('[data-test-fault]');await button('保存演示设置');
 await page.evaluate(()=>document.querySelectorAll('.nav-item')[0].click());
 await click('[data-edit-item="'+rent.id+'"]');await click('[data-testid="prepare-payment"]');
 await until(()=>!!document.querySelector('[data-testid="demo-code"]'));
 const code=await page.evaluate(()=>document.querySelector('[data-testid="demo-code"]').textContent);
 await input('approval-otp',code);await click('#approval-consent');await shot('approval.png');await click('[data-testid="confirm-payment"]');
 await until(()=>document.body.textContent.includes('需要回查'));
 const s=await get('/state');assert.equal(s.balance_cents,625900);assert.equal(s.operations[0].status,'UNKNOWN');
 await page.goto({url:'http://127.0.0.1:8770/',timeout:15000});await until(()=>!!document.querySelector('[data-action="recover"]'));
 await click('[data-action="recover"]');await until(()=>!document.querySelector('[data-action="recover"]'));
 const recovered=await get('/state');assert.equal(recovered.balance_cents,625900);assert.equal(recovered.bills.filter(b=>b.source.startsWith('payment:')).length,1);
 const after=await get('/forecast');assert.ok(after.items.find(i=>i.id===rent.id).paid);assert.equal(after.pending_expense_cents,452900);
 // Manual planning is an independent, actually usable path without bank access.
 await click('.account-picker');await until(()=>!!document.getElementById('opening-balance'));
 await input('opening-balance','3000');await input('planning-floor','1000');await click('[data-testid="save-settings"]');
 await until(()=>document.body.textContent.includes('我的手动计划'));
 assert.equal((await get('/forecast')).items.length,0);
 await click('[data-testid="add-item"]');await until(()=>!!document.getElementById('item-title'));
 await input('item-title','本月房租');await input('item-amount','2500');await input('item-day',f.points[1].day);await click('[data-testid="save-item"]');
 await until(()=>document.querySelectorAll('[data-plan-item]').length===1);
 const manual=await get('/forecast');assert.equal(manual.lowest_cents,50000);assert.equal(manual.shortfall_cents,50000);assert.equal(manual.mode,'manual');
 assert.equal((await get('/state')).balance_cents,625900);
 await until(()=>!document.querySelector('.toast'));await shot('manual-desktop.png');
 // Mobile/tablet layouts and navigation are independently inspected.
 await page.setViewport({width:390,height:844,deviceScaleFactor:1});await shot('mobile.png');
 const mobile=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert.ok(mobile.document<=mobile.viewport);
 await page.setViewport({width:820,height:1050,deviceScaleFactor:1});await shot('tablet.png');
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.evaluate(()=>document.querySelectorAll('.nav-item')[2].click());await button('确认查询管理信息');await click('[data-testid="reveal-subs"]');
 await until(()=>document.querySelectorAll('[data-sub]').length===3);await click('[data-sub]');await until(()=>!!document.getElementById('approval-consent'));await click('#approval-consent');await click('[data-testid="confirm-payment"]');
 await until(()=>document.querySelectorAll('[data-sub]').length===2);
 const exported=await page.evaluate(async()=>await(await fetch('/api/planning/export')).text());assert.ok(exported.includes('本月房租')&&!exported.includes('信用卡还款'));
 await page.setViewport({width:1440,height:1120,deviceScaleFactor:1});await page.evaluate(()=>document.querySelectorAll('.nav-item')[0].click());
 const variants={};
 for(const [value,title] of [['blue','暮蓝'],['gray','岩灰'],['jade','玉绿']]){
  await until(()=>!document.querySelector('[role="dialog"]'));await click('[aria-label="风格设置"]');await until(()=>!!document.querySelector('[role="dialog"] [aria-label="视觉风格"]'));await new Promise(r=>setTimeout(r,200));await pointer('[role="dialog"] [aria-label="视觉风格"]');await until(()=>document.querySelectorAll('[role="option"]').length===3);
  await page.evaluate(t=>{[...document.querySelectorAll('[role="option"]')].find(n=>n.textContent.includes(t)).dataset.testVariant='true'},title);await pointer('[data-test-variant]');await until(()=>!document.querySelector('[role="option"]'));await button('完成');await until(()=>!document.querySelector('[role="dialog"]'));await new Promise(r=>setTimeout(r,200));
  variants[value]=await page.evaluate(()=>getComputedStyle(document.querySelector('.guardian')).getPropertyValue('--chart-color').trim());await shot('theme-'+value+'.png');
 }
 assert.equal(new Set(Object.values(variants)).size,3);
 const errors=await page.evaluate(()=>({js:window.__errors,csp:window.__csp}));assert.deepEqual(errors,{js:[],csp:[]});
 const result={checkedAt:new Date().toISOString(),library:'Radix Themes 3.3.0 / React 19.2.7',checks:['empty workspace','explicit example only','cash-flow shortfall arithmetic','date preview does not save','Radix drawer and combobox','bound red confirmation','demo OTP','accepted payment timeout','reload and reconcile original','one debit','no duplicate forecast debit','manual balance separate from bank','manual expense forecast','CSV export scoped to manual plan','mobile no overflow','tablet no overflow','subscription query and cancellation','three working visual variants','no JS or CSP errors'],mobile,variants,errors};
 fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }finally{await browser.close({silent:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
