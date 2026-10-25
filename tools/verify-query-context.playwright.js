async(page)=>{
 const dir='E:/gitproject/hackathon/cashflow-guardian/test-results/query-context';
 const c=await page.context().browser().newContext({viewport:{width:1280,height:900}});const p=await c.newPage();p.setDefaultTimeout(60000);
 const checks=[],errors=[];p.on('pageerror',e=>errors.push(e.message));
 function check(name,ok){checks.push({name,passed:!!ok});if(!ok)throw Error(name)}
 async function send(text,first=false){await p.getByLabel(first?'说说你想办的事':'补充或修改这件事',{exact:true}).fill(text);const pending=p.waitForResponse(r=>r.url().endsWith('/api/assistant/message')&&r.request().method()==='POST');await p.getByRole('button',{name:first?'发送需求':'发送补充',exact:true}).click();const res=await pending;const t=await res.json();check('accepted '+text,res.ok());await p.waitForFunction(()=>!document.querySelector('[aria-busy="true"]'));return t}
 async function reveal(){await p.getByTestId('reveal-subscriptions').click();await p.waitForFunction(()=>!document.querySelector('[aria-busy="true"]'));return p.evaluate(async()=>await(await fetch('/api/assistant/tasks/'+sessionStorage.getItem('xiaoman-task'))).json())}
 let failure=null;
 try{
  await p.goto('http://127.0.0.1:8770/');await p.getByLabel('说说你想办的事',{exact:true}).waitFor();
  let t=await send('查余额',true);check('balance bypasses model',t.planner==='deterministic_query'&&t.model_meta.model_called===false);
  await p.getByRole('button',{name:'新办一件事',exact:true}).click();
  t=await send('9月1日到9月3日花了多少',true);check('day range has no fifth-day rows',t.analysis.scope.start==='2026-09-01'&&t.analysis.scope.end==='2026-09-03'&&t.analysis.expense_cents===0);
  t=await send('上个月只看餐饮');check('food selected',t.analysis.filters.category==='餐饮'&&t.analysis.expense_cents===65000);
  t=await send('和八月比呢');check('comparison retains food and both months',t.analysis.filters.category==='餐饮'&&t.analysis.comparison_periods.length===2&&t.analysis.delta_cents===0);
  await p.screenshot({path:dir+'/comparison.png',fullPage:true});
  t=await send('全部类别，只看云盘');check('explicit reset switches to cloud',t.analysis.filters.category===null&&t.analysis.filters.merchant_contains==='云盘'&&t.analysis.expense_cents===5800);
  t=await send('接着整理这些代扣');check('linked query requires consent',t.status==='CONSENT_REQUIRED'&&t.source_mode==='related');
  t=await reveal();check('only two cloud protocols exposed',t.subscriptions.length===2&&t.subscriptions.every(s=>s.name.includes('云盘')));
  check('candidates have source evidence and no auto-selection',t.subscriptions.every(s=>s.matched_evidence_ids.length&&s.preference==='unknown'));
  await p.getByTestId('subscription-row').first().locator('summary').click();
  const matchText=p.getByTestId('subscription-row').first().locator('details[open]').getByText('所选流水的商户名称与协议名称一致；请继续核对具体协议。',{exact:false});
  await matchText.waitFor({state:'visible'});check('matching explanation visible',await matchText.isVisible());
  await p.screenshot({path:dir+'/linked-candidates.png',fullPage:true});
  await p.getByRole('button',{name:'新办一件事',exact:true}).click();t=await send('上个月餐饮花了多少',true);await send('接着整理这些代扣');t=await reveal();
  check('food has no protocol match and no expansion',t.subscriptions.length===0&&t.link_status==='NO_MATCH');
  await p.screenshot({path:dir+'/no-match.png',fullPage:true});
  t=await send('查询全部代扣');check('expansion asks fresh consent',t.status==='CONSENT_REQUIRED'&&!t.subscriptions&&t.source_mode==='all');
  t=await reveal();check('explicitly authorized all query returns three',t.subscriptions.length===3);
  const s=await p.evaluate(async()=>await(await fetch('/api/state')).json());check('no financial writes',s.operations.length===0);check('no page errors',errors.length===0);
 }catch(e){failure=e.message;await p.screenshot({path:dir+'/failure.png',fullPage:true})}
 const report={run_at:new Date().toISOString(),checks,errors,failure,passed:!failure,real_bank:false,environment:'Final UI and configured model; balance deterministic; new isolated cookie account; no response mocking'};
 const dl=p.waitForEvent('download');await p.evaluate(r=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));a.download='query-context.json';a.click()},report);await(await dl).saveAs(dir+'/browser.json');await c.close();return report;
}
