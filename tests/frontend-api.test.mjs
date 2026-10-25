import test from 'node:test';
import assert from 'node:assert/strict';
import {api,connect,ApiError} from '../frontend/src/api.js';

test('transport sends same-origin CSRF and exact payload without retry',async()=>{
 const original=globalThis.fetch;const calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>url.endsWith('/session')?{csrf:'fixture-csrf'}:{status:'PREPARED'}}};
 try{await connect();await api('/operations',{kind:'transfer',amount:'600'});assert.equal(calls.length,2);assert.equal(calls[1].options.credentials,'same-origin');assert.equal(calls[1].options.headers['X-CSRF-Token'],'fixture-csrf');assert.equal(JSON.parse(calls[1].options.body).amount,'600');assert.ok(calls[1].options.signal instanceof AbortSignal)}finally{globalThis.fetch=original}
});
test('connection loss never automatically repeats a financial POST',async()=>{
 const original=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;throw new TypeError('private proxy text')};
 try{await assert.rejects(api('/operations/example/execute',{}),e=>e instanceof ApiError&&e.code==='NETWORK'&&!e.message.includes('private proxy'));assert.equal(calls,1)}finally{globalThis.fetch=original}
});
test('non-JSON gateway error is recoverable and does not leak its body',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>({ok:false,status:502,json:async()=>{throw new SyntaxError('<html>internal server details</html>')}});
 try{await assert.rejects(api('/state'),e=>e.code==='RESPONSE'&&e.status===502&&!e.message.includes('internal server'))}finally{globalThis.fetch=original}
});
test('stale authorization version preserves typed error for refresh only',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({detail:'任务已更新',code:'STALE_TASK'})});
 try{await assert.rejects(api('/assistant/tasks/example/transfer',{}),e=>e.code==='STALE_TASK'&&e.status===409)}finally{globalThis.fetch=original}
});
test('aborted request reports uncertain outcome rather than failed payment',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>{const error=new Error('aborted');error.name='AbortError';throw error};
 try{await assert.rejects(api('/operations/example/execute',{}),e=>e.code==='TIMEOUT'&&e.message.includes('结果尚未确认'))}finally{globalThis.fetch=original}
});
