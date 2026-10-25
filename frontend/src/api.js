let csrf='';
export class ApiError extends Error{
 constructor(message,code,status=0){super(message);this.name='ApiError';this.code=code;this.status=status}
}
export async function api(path,body){
 const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),45000);
 try{
  const response=await fetch('/api'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  let result;try{result=await response.json()}catch{throw new ApiError('暂时无法读取服务器响应。请先刷新办理状态，涉及付款时不要重复提交。','RESPONSE',response.status)}
  if(!response.ok)throw new ApiError(typeof result.detail==='string'?result.detail:'请检查输入内容',result.code||'HTTP',response.status);
  return result;
 }catch(error){
  if(error instanceof ApiError)throw error;
  throw new ApiError(error.name==='AbortError'?'等待响应超时，结果尚未确认。请先刷新办理状态，不要重复付款。':'连接暂时中断。请检查网络后刷新办理状态，不要重复付款。',error.name==='AbortError'?'TIMEOUT':'NETWORK');
 }finally{clearTimeout(timeout)}
}
export async function connect(){const session=await api('/session',{});csrf=session.csrf}
export const money=n=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',minimumFractionDigits:2}).format(n/100);
export const shortDay=d=>d?`${Number(d.slice(5,7))}月${Number(d.slice(8,10))}日`:'—';
export const dateNow=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export const dateAfter=days=>new Date(Date.parse(dateNow()+'T00:00:00Z')+days*86400000).toISOString().slice(0,10);
