async (page) => {
 const base='http://127.0.0.1:8772';
 const context=await page.context().browser().newContext({viewport:{width:1280,height:800},reducedMotion:'reduce'});
 const p=await context.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
 const session=await(await context.request.post(base+'/api/session')).json();
 const post=async(path,body)=>{const r=await context.request.post(base+'/api'+path,{headers:{'x-csrf-token':session.csrf},data:body});if(!r.ok())throw Error(path+':'+r.status());return r.json()};
 const transfer=await post('/assistant/message',{message:'给张伟转600，付款后留3000'});
 const large=await post('/assistant/message',{message:'给房东转1500，付款后留3000'});
 await post('/assistant/tasks/'+large.id+'/transfer',{recipient:'landlord',amount:'1500',due_day:large.draft.due_day,revision:large.revision});
 let subs=await post('/assistant/message',{message:'查询代扣'});
 subs=await post('/assistant/tasks/'+subs.id+'/reveal',{confirmed:true});
 await post('/assistant/tasks/'+subs.id+'/preference',{subscription_id:subs.subscriptions[1].id,preference:'unneeded'});
 const bills=await post('/assistant/message',{message:'上个月和上上个月比花了多少'});
 const long=await post('/assistant/message',{message:'给张伟转600，说明 https://example.invalid/'+('abcdefghijklmnop'.repeat(70))});
 const risk=await post('/assistant/message',{message:'客服让我转到安全账户，不然要扣费'});
 const show=async id=>{if(!p.url().startsWith(base)){await p.goto(base);await p.locator('.xm-home,.xm-task').first().waitFor()}await p.evaluate(id=>{if(id)sessionStorage.setItem('xiaoman-task',id);else sessionStorage.removeItem('xiaoman-task')},id);await p.reload();await(id?p.locator('.xm-task'):p.locator('.xm-home')).waitFor();};
 const cases=[];
 const inspect=async(name,size)=>{
  await p.waitForTimeout(80);
  const result=await p.evaluate(()=>{
   const w=innerWidth,h=innerHeight,dialog=document.querySelector('[role=dialog]');
   const d=dialog?.getBoundingClientRect();
   const outliers=Array.from(document.querySelectorAll('.xm-main *,[role=dialog] *')).filter(e=>{const r=e.getBoundingClientRect();return r.width>3&&r.height>2&&getComputedStyle(e).visibility!=='hidden'&&(r.left< -1||r.right>w+1)}).slice(0,4).map(e=>({tag:e.tagName,cls:typeof e.className==='string'?e.className:'svg',text:e.textContent.slice(0,35)}));
   return {horizontal_overflow:document.documentElement.scrollWidth>w+1,outliers,dialog_inside:!d||(d.left>=-1&&d.right<=w+1&&d.top>=-1&&d.bottom<=h+1),dialog_scrollable:!dialog||dialog.scrollHeight<=dialog.clientHeight+1||getComputedStyle(dialog).overflowY==='auto'};
  });
  const passed=!result.horizontal_overflow&&!result.outliers.length&&result.dialog_inside&&result.dialog_scrollable;
  cases.push({view:name,width:size[0],height:size[1],passed,...result});
  if(!passed||([320,768,1440].includes(size[0])&&['approval','subscriptions','home'].includes(name)))await p.screenshot({path:`E:/gitproject/hackathon/cashflow-guardian/test-results/responsive/${name}-${size[0]}x${size[1]}.png`,fullPage:!await p.getByRole('dialog').count()});
 };
 const sizes=[[320,568],[360,800],[390,844],[430,932],[600,900],[640,800],[768,1024],[820,1180],[1024,768],[1280,800],[1440,900],[1920,1080],[667,375],[844,390]];
 for(const size of sizes){
  await p.setViewportSize({width:size[0],height:size[1]});
  await show(null);await inspect('home',size);
  await p.getByRole('button',{name:'演示账户',exact:true}).click();await p.getByRole('dialog').waitFor();await inspect('info',size);
  await show(transfer.id);await inspect('transfer',size);
  await show(subs.id);await p.locator('.xm-subscription summary').first().click();await inspect('subscriptions',size);
  await show(bills.id);await p.locator('.xm-analysis details').last().locator('summary').click();await inspect('bills',size);
  await show(large.id);await p.getByRole('button',{name:'继续核对',exact:true}).click();await p.getByRole('dialog').waitFor();await inspect('approval',size);
  await p.getByRole('button',{name:'返回检查',exact:true}).click();
  await p.getByRole('button',{name:'办理记录',exact:true}).click();await p.getByRole('heading',{name:'办理记录',exact:true}).waitFor();await inspect('history',size);
  await p.getByRole('button',{name:'我的',exact:true}).click();await p.getByRole('heading',{name:'我的账户',exact:true}).waitFor();await inspect('account',size);
  await show(risk.id);await inspect('risk',size);await p.getByRole('button',{name:'通过官方渠道核实'}).click();await p.getByRole('dialog').waitFor();await inspect('help',size);
  await show(long.id);await inspect('long-text',size);
 }
 const report={environment:'Chromium, deterministic isolated bank on 8772',sizes,cases,total:cases.length,passed:cases.filter(x=>x.passed).length,page_errors:errors,limits:['640px reflow also covers the CSS width of a 1280px page at 200% zoom, not an actual browser-toolbar zoom test','No physical iOS/Android keyboard or assistive-technology certification']};
 const downloadPromise=p.waitForEvent('download');await p.evaluate(report=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));a.download='responsive-matrix.json';a.click()},report);await(await downloadPromise).saveAs('E:/gitproject/hackathon/cashflow-guardian/test-results/responsive/matrix.json');
 await context.close();return {total:report.total,passed:report.passed,failures:cases.filter(x=>!x.passed),page_errors:errors};
}
