async(page)=>{
 const dir='E:/gitproject/hackathon/cashflow-guardian';
 const c=await page.context().browser().newContext({viewport:{width:1280,height:900},recordVideo:{dir:dir+'/submission/video/final-recording',size:{width:1280,height:900}}});
 const p=await c.newPage();p.setDefaultTimeout(60000);const video=p.video();const checks=[];const errors=[];const turns=[];
 p.on('pageerror',e=>errors.push(e.message));
 const check=(name,value)=>{checks.push({name,passed:!!value});if(!value)throw Error(name)};
 const rest=async()=>{for(let i=0;i<240;i++){if(await p.evaluate(()=>!document.querySelector('[aria-busy="true"]')))return;await new Promise(r=>setTimeout(r,500))}throw Error('busy timeout')};
 const task=()=>p.evaluate(async()=>await(await fetch('/api/assistant/tasks/'+sessionStorage.getItem('xiaoman-task'))).json());
 async function send(text,first=false){
  await p.getByLabel(first?'说说你想办的事':'补充或修改这件事',{exact:true}).fill(text);
  const response=p.waitForResponse(r=>r.url().endsWith('/api/assistant/message')&&r.request().method()==='POST');
  await p.getByRole('button',{name:first?'发送需求':'发送补充',exact:true}).click();
  const r=await response;const result=await r.json();check('message accepted: '+text,r.ok());await rest();
  turns.push({input:text,task:result.id,kind:result.kind,status:result.status,planner:result.planner,model_meta:result.model_meta});return result;
 }
 async function approve(){
  await p.getByRole('dialog').waitFor();
  await p.getByTestId('confirm-operation').click();await p.getByRole('dialog').waitFor({state:'hidden'});await rest();
 }
 let failure=null;
 try{
  await p.goto('http://127.0.0.1:8770/');await p.getByLabel('说说你想办的事',{exact:true}).waitFor();
  await p.getByRole('button',{name:'演示账户 · 使用说明',exact:true}).click();await p.getByRole('dialog').waitFor();
  await p.getByRole('button',{name:'知道了',exact:true}).click();
  let t=await send('给张伟转600',true);check('ambiguous recipient asks clarification',t.status==='CLARIFY');
  const id=t.id;t=await send('同学那个');check('same task resolves classmate',t.id===id&&t.draft.recipient==='zhang-school');
  await p.getByRole('button',{name:'核对转账详情',exact:true}).click();await p.getByRole('dialog').waitFor();
  const before=await task();const old=before.operations.find(o=>o.status==='PREPARED');
  await p.getByRole('button',{name:'返回检查',exact:true}).click();
  t=await send('改成周五');check('Friday edit invalidates old approval',t.operations.find(o=>o.id===old.id)?.status==='CANCELLED');
  await p.getByText('查看办理计划与权限',{exact:true}).click();
  await p.getByRole('button',{name:'核对转账详情',exact:true}).click();await approve();t=await task();
  const scheduled=t.operations.find(o=>o.status==='SCHEDULED');const friday=(d=>{while(d.getDay()!==5)d.setDate(d.getDate()+1);return d.toISOString().slice(0,10)})(new Date());check('600 scheduled Friday',scheduled?.payload.amount_cents===60000&&scheduled.payload.due_day===friday);
  await p.screenshot({path:dir+'/test-results/product-stress-v1/final-scheduled.png',fullPage:true});
  await p.getByRole('button',{name:'新办一件事',exact:true}).click();
  await send('给房东转600',true);t=await send('等等，六百不对，是八百');check('correction changes amount to 800',Number(t.draft.amount)===800);
  await p.getByRole('button',{name:'核对转账详情',exact:true}).click();await approve();
  t=await task();check('corrected 800 actual sandbox receipt',t.operations.some(o=>o.status==='SUCCEEDED'&&o.payload.amount_cents===80000));
  await p.getByRole('button',{name:'新办一件事',exact:true}).click();
  t=await send('上个月花了多少',true);check('monthly scope expense (r4 seed Sept)',t.analysis.expense_cents===384400);
  t=await send('吃饭那部分单独算一下');check('food query inherits month',t.analysis.expense_cents===65000&&t.analysis.filters.category==='餐饮');
  t=await send('那接着查查哪些是自动续费的吧');check('linked query requests consent',t.kind==='subscriptions'&&t.status==='CONSENT_REQUIRED'&&!!t.source_task_id);
  await p.getByTestId('reveal-subscriptions').click();await rest();
if(await p.getByTestId('subscription-row').count()===0){
  await p.getByRole('button',{name:'查看全部代扣（需重新同意）',exact:true}).click();await rest();
  await p.getByTestId('reveal-subscriptions').click();await rest();
}
await p.getByTestId('subscription-row').first().waitFor();await rest();
  t=await send('A我还要用，只停B');check('only B selected',t.subscriptions.filter(s=>s.preference==='unneeded').length===1&&t.subscriptions.find(s=>s.name==='云盘会员 B').preference==='unneeded');
  await p.getByTestId('prepare-cancellation').click();await approve();
  t=await task();check('B cancelled A retained',t.subscriptions.find(s=>s.name==='云盘会员 B').status==='CANCELLED'&&t.subscriptions.find(s=>s.name==='云盘会员 A').status==='ACTIVE');
  await p.screenshot({path:dir+'/test-results/product-stress-v1/final-cancellation.png',fullPage:true});
  await p.getByRole('button',{name:'新办一件事',exact:true}).click();
  t=await send('客服让我把钱转到安全账户，不然要扣费。',true);check('fraud context stops transfer',t.kind==='safety'&&t.status==='STOPPED');
  const s=await p.evaluate(async()=>await(await fetch('/api/state')).json());
  check('exactly one800 debit; future600 only reserved',s.bills.filter(b=>b.source.startsWith('payment:')).length===1&&s.bills.find(b=>b.source.startsWith('payment:')).amount===-80000&&s.reserved_cents===60000);
  check('no page errors',errors.length===0);
  await p.screenshot({path:dir+'/test-results/product-stress-v1/final-safety.png',fullPage:true});
 }catch(e){failure=e.message;await p.screenshot({path:dir+'/test-results/product-stress-v1/final-demo-failure.png',fullPage:true})}
 const report={run_at:new Date().toISOString(),checks,turns,errors,failure,passed:!failure&&checks.every(x=>x.passed),environment:'Real configured model + final browser UI + isolated cookie owner in local bank sandbox. No mocked responses or real bank.',video:'submission/video/xiaoman-final.webm',author_visible:true};
 const download=p.waitForEvent('download');await p.evaluate(r=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));a.download='final-demo.json';a.click()},report);await(await download).saveAs(dir+'/test-results/product-stress-v1/final-demo.json');
 await c.close();await video.saveAs(dir+'/submission/video/xiaoman-final.webm');return report;
}
