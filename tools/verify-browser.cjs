const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {openBrowser}=require('E:/gitproject/farmer-film-titles/node_modules/@remotion/renderer');
const output=path.join(__dirname,'../test-results');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await openBrowser('chrome',{browserExecutable:'C:/Users/ASUS/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe',logLevel:'error'});
 try{
 const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
 await page.evaluateOnNewDocument(()=>{window.__errors=[];window.__csp=[];window.__confirmations=[];window.confirm=text=>{window.__confirmations.push(text);return true};addEventListener('error',e=>window.__errors.push(e.message));addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason)));addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective))});
 await page.setViewport({width:1440,height:1100,deviceScaleFactor:1});
 await page.goto({url:'http://127.0.0.1:8770/',timeout:15000});
 async function until(fn){for(let i=0;i<60;i++){if(await page.evaluate(fn))return;await new Promise(r=>setTimeout(r,100))}console.error(await page.evaluate(()=>({forms:[...document.querySelectorAll('input,select')].map(x=>({id:x.id,value:x.value,valid:x.validity.valid,error:x.validationMessage})),errors:window.__errors,toast:document.getElementById('toast').textContent})));throw new Error('UI wait timed out: '+fn.toString())}
 const snapshot=()=>page.evaluate(async()=>await(await fetch('/api/state')).json());
 async function screenshot(name){const shot=await page._client().send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,name),Buffer.from(shot.value.data,'base64'))}
 await until(()=>document.getElementById('connection').textContent==='沙箱已连接');
 const initial=await snapshot();assert.equal(initial.operations.length,0);
 await screenshot('desktop.png');
 await page.evaluate(()=>document.querySelector('[data-prompt]').click());
 await until(()=>document.getElementById('amount').value==='3500');
 assert.ok(await page.evaluate(()=>document.querySelectorAll('.dag-node').length===3));
 await page.evaluate(()=>{document.getElementById('fault').value='timeout_after_accept';document.getElementById('transfer-form').requestSubmit()});
 await until(()=>!!document.querySelector('[data-action="approve"]'));
 await page.evaluate(()=>document.querySelector('[data-action="approve"]').click());
 await until(()=>document.getElementById('approval-dialog').open);
 await screenshot('approval.png');
 await page.evaluate(()=>{document.getElementById('otp').value=document.getElementById('demo-code').textContent;document.getElementById('consent').checked=true;document.getElementById('approval-form').requestSubmit()});
 await until(()=>!!document.querySelector('.state.UNKNOWN'));
 const unknown=await snapshot();assert.equal(unknown.balance_cents,initial.balance_cents-350000);assert.equal(unknown.reserved_cents,0);
 assert.equal(await page.evaluate(()=>document.querySelectorAll('[data-action="execute"]').length),0);
 await screenshot('timeout.png');
 await page.goto({url:'http://127.0.0.1:8770/',timeout:15000});
 await until(()=>!!document.querySelector('[data-action="recover"]'));
 await page.evaluate(()=>document.querySelector('[data-action="recover"]').click());
 await until(()=>!!document.querySelector('.state.SUCCEEDED'));
 const recovered=await snapshot();assert.equal(recovered.balance_cents,initial.balance_cents-350000);
 assert.equal(recovered.bills.filter(x=>x.source.startsWith('payment:')).length,1);
 // Query requires an explicit click + browser confirmation; allow only this dialog.
 await page.evaluate(()=>{document.getElementById('fault').value='none';document.getElementById('reveal').click()});
 await until(()=>document.querySelectorAll('[data-sub]').length===3);
 await page.evaluate(()=>document.querySelector('[data-sub]').click());
 await until(()=>!!document.querySelector('[data-action="approve"]'));
 await page.evaluate(()=>document.querySelector('[data-action="approve"]').click());
 await until(()=>document.getElementById('approval-dialog').open);
 await page.evaluate(()=>{document.getElementById('consent').checked=true;document.getElementById('approval-form').requestSubmit()});
 await until(()=>document.querySelectorAll('[data-sub]').length===2);
 // Imported hostile text must render as text, with no executable DOM nodes.
 await page.evaluate(()=>{const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());document.getElementById('csv').value='id,date,merchant,amount,category\nweb-xss,'+day+',<img src=x onerror=alert(1)>,-1,其他\n';document.getElementById('import').click()});
 await until(()=>document.getElementById('bills').textContent.includes('<img'));
 assert.equal(await page.evaluate(()=>document.querySelectorAll('#bills img').length),0);
 await page.setViewport({width:390,height:844,deviceScaleFactor:1});
 const mobile=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert.ok(mobile.document<=mobile.viewport);
 await screenshot('mobile.png');
 const final=await snapshot();assert.ok(final.audit_valid);assert.equal(final.balance_cents,initial.balance_cents-350000);
 const errors=await page.evaluate(()=>({js:window.__errors,csp:window.__csp}));assert.deepEqual(errors,{js:[],csp:[]});
 const result={checkedAt:new Date().toISOString(),checks:['browser session','rule plan draft','red confirmation','sandbox OTP','timeout after bank accept','reload persists state','original payment reconciliation','one debit only','subscription query confirmation','subscription cancellation','imported XSS remains text','mobile no overflow','audit chain','no JS or CSP errors'],initial_balance_cents:initial.balance_cents,final_balance_cents:final.balance_cents,mobile,errors};
 fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
 }finally{await browser.close({silent:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
