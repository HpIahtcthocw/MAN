async(page)=>{
 const dir='E:/gitproject/hackathon/cashflow-guardian/test-results/acceptance-review';
 const c=await page.context().browser().newContext({viewport:{width:1280,height:900}});const p=await c.newPage();p.setDefaultTimeout(60000);
 const checks=[],errors=[],turns=[];p.on('pageerror',e=>errors.push(e.message));
 function check(name,ok){checks.push({name,passed:!!ok});if(!ok)throw Error(name)}
 async function send(text,first=false){await p.getByLabel(first?'说说你想办的事':'补充或修改这件事',{exact:true}).fill(text);const pending=p.waitForResponse(r=>r.url().endsWith('/api/assistant/message')&&r.request().method()==='POST');await p.getByRole('button',{name:first?'发送需求':'发送补充',exact:true}).click();const res=await pending;const t=await res.json();check('accepted '+text,res.ok());await p.waitForFunction(()=>!document.querySelector('[aria-busy="true"]'));turns.push({input:text,planner:t.planner,status:t.status,query:t.analysis?.query,model_meta:t.model_meta});return t}
 let failure=null;
 try{
  await p.goto('http://127.0.0.1:8770/');await p.getByLabel('说说你想办的事',{exact:true}).waitFor();
  let t=await send('2025年9月1日到9月15日花了多少',true);
  check('explicit year inherited; no2026 rows',t.analysis.scope.end==='2025-09-15'&&t.analysis.expense_cents===0);
  await p.getByRole('button',{name:'新办一件事',exact:true}).click();
  t=await send('上个月云盘消费一共多少',true);check('cloud total58',t.analysis.expense_cents===5800);
  t=await send('全部类别');check('category reset keeps cloud filter',t.analysis.filters.merchant_contains==='云盘'&&t.analysis.expense_cents===5800);
  await p.screenshot({path:dir+'/filter-reset.png',fullPage:true});
  t=await send('只看医疗');check('unknown category clarifies without old total',t.status==='CLARIFY'&&!t.analysis);
  await p.screenshot({path:dir+'/unknown-filter.png',fullPage:true});
  const s=await p.evaluate(async()=>await(await fetch('/api/state')).json());check('no financial operations',s.operations.length===0);check('no page errors',errors.length===0);
 }catch(e){failure=e.message;await p.screenshot({path:dir+'/browser-failure.png',fullPage:true})}
 const report={checks,turns,errors,failure,passed:!failure,author_visible:true,blind:false,real_bank:false,environment:'Final UI with configured model plus validated edits; isolated cookie owner; no response mocking'};
 const dl=p.waitForEvent('download');await p.evaluate(r=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));a.download='acceptance-browser.json';a.click()},report);await(await dl).saveAs(dir+'/browser.json');await c.close();return report;
}
