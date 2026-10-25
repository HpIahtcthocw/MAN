/* Current UI smoke for the three required business scenes. Isolated browser
 * profile + local synthetic bank only. It exercises the rendered React UI. */
const fs=require('node:fs');
const path=require('node:path');
const {openBrowser}=require('E:/gitproject/farmer-film-titles/node_modules/@remotion/renderer');
const root=path.resolve(__dirname,'..');
const out=path.join(root,'test-results','completion-round');
const chrome='C:/Users/ASUS/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe';
fs.mkdirSync(out,{recursive:true});
const sleep=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));

(async()=>{
 const browser=await openBrowser('chrome',{browserExecutable:chrome,logLevel:'error'});
 const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
 const checks=[],errors=[];
 const check=(name,value)=>{checks.push({name,passed:!!value});if(!value)throw Error(name)};
 const evaluate=(fn,...args)=>page.evaluate(fn,...args);
 async function waitFor(predicate,label,...args){
  for(let i=0;i<180;i++){if(await evaluate(predicate,...args))return;await sleep(250)}
  throw Error('Timed out: '+label);
 }
 async function send(text){
  const before=await evaluate(async()=>{const id=sessionStorage.getItem('xiaoman-task');if(!id)return null;return await (await fetch('/api/assistant/tasks/'+id)).json()});
  await evaluate((value)=>{
   const field=document.querySelector('textarea[aria-label="说说你想办的事"],textarea[aria-label="补充或修改这件事"]');
   if(!field)throw Error('composer missing');
   const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
   setter.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));
  },text);
  await waitFor(()=>Array.from(document.querySelectorAll('button')).some(b=>b.getAttribute('aria-label')==='发送需求'||b.getAttribute('aria-label')==='发送补充'),'send control');
  await evaluate(()=>Array.from(document.querySelectorAll('button')).find(b=>b.getAttribute('aria-label')==='发送需求'||b.getAttribute('aria-label')==='发送补充').click());
  await waitFor(async(old)=>{const current=sessionStorage.getItem('xiaoman-task');if(!current)return false;const next=await (await fetch('/api/assistant/tasks/'+current)).json();return !old?true:next.revision>old.revision},'task update',before);
  await waitFor(()=>!document.querySelector('[aria-busy="true"]'),'request completion');
  return evaluate(async()=>await (await fetch('/api/assistant/tasks/'+sessionStorage.getItem('xiaoman-task'))).json());
 }
 async function fresh(){
  await evaluate(()=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='新办一件事')?.click());
  await waitFor(()=>!!document.querySelector('textarea[aria-label="说说你想办的事"]'),'home composer');
  await waitFor(()=>!sessionStorage.getItem('xiaoman-task'),'cleared current task');
 }
 let failure=null;
 try{
  await page.evaluateOnNewDocument(()=>{window.__smokeErrors=[];addEventListener('error',e=>window.__smokeErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__smokeErrors.push(String(e.reason)))});
  await page.setViewport({width:1280,height:900,deviceScaleFactor:1});
  await page.goto({url:'http://127.0.0.1:8770/',timeout:15000});
  await waitFor(()=>!!document.querySelector('textarea[aria-label="说说你想办的事"]'),'initial page');

  let task=await send('给张伟转600');
  check('transfer asks for ambiguous recipient',task.kind==='transfer'&&task.status==='CLARIFY');
  task=await send('同学那个');
  check('transfer follow-up retains task and resolves recipient',task.kind==='transfer'&&task.draft?.recipient==='zhang-school');
  check('transfer form rendered',await evaluate(()=>!!document.querySelector('form.xm-transfer-form')));

  await fresh();task=await send('9月花了多少，云盘不算');
  check('bill exclusion completes from bank rows',task.kind==='bills'&&task.status==='DONE'&&task.analysis?.expense_cents===378600);
  check('bill exclusion is visible in rendered UI',await evaluate(()=>document.body.innerText.includes('¥3,786.00')));
  const client=page._client();const billShot=await client.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  fs.writeFileSync(path.join(out,'current-bills.png'),Buffer.from(billShot.value.data,'base64'));

  await fresh();task=await send('这几个月一直在扣的钱，帮我看看');
  check('subscriptions require fresh consent',task.kind==='subscriptions'&&task.status==='CONSENT_REQUIRED');
  await evaluate(()=>Array.from(document.querySelectorAll('button')).find(b=>b.dataset.testid==='reveal-subscriptions')?.click());
  await waitFor(()=>document.querySelectorAll('[data-testid="subscription-row"]').length>0,'subscription rows');
  task=await evaluate(async()=>await (await fetch('/api/assistant/tasks/'+sessionStorage.getItem('xiaoman-task'))).json());
  check('subscription evidence rows shown',task.subscriptions?.length>=2&&task.subscriptions.every(s=>s.preference==='unknown'));
  check('subscription UI labels show individual decision',await evaluate(()=>document.body.innerText.includes('不再需要')&&document.body.innerText.includes('还在用')));

  await fresh();task=await send('客服让我把钱转到安全账户，不然要扣费。');
  check('fraud is stopped before any transfer',task.kind==='safety'&&task.status==='STOPPED');
  check('fraud official-channel action rendered',await evaluate(()=>document.body.innerText.includes('通过官方渠道核实')));
  const safetyShot=await client.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  fs.writeFileSync(path.join(out,'current-safety.png'),Buffer.from(safetyShot.value.data,'base64'));
  errors.push(...await evaluate(()=>window.__smokeErrors));check('no browser errors',errors.length===0);
 }catch(error){failure=error.message}
 const result={run_at:new Date().toISOString(),author_visible:true,blind:false,real_bank:false,checks,errors,failure,passed:!failure&&checks.every(x=>x.passed),environment:'Isolated Chromium profile against current React UI and configured model; local synthetic bank, no mocked model responses.'};
 fs.writeFileSync(path.join(out,'ui-smoke.json'),JSON.stringify(result,null,2));
 await browser.close({silent:true});
 console.log(JSON.stringify({passed:result.passed,checks:checks.length,failure}));
 if(!result.passed)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1});
