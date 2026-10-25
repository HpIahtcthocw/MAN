"""Loopback-only demo API. A browser cookie isolates each synthetic account.

This is not customer authentication or bank MFA. No arbitrary origin may create
sessions or perform mutations, and no directory-wide static mount exposes data.
"""
import hmac
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Dict, Optional, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, Field

from guardian.engine import Engine, Denied, now
from guardian import planning
from guardian.assistant import Assistant, configured

ROOT=Path(__file__).absolute().parent.parent


class Body(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Prepare(Body):
    kind: Literal['transfer','cancel_subscription']
    payload: Dict[StrictStr,StrictStr]
    idempotency_key: StrictStr=Field(min_length=8,max_length=100)


class Approval(Body):
    binding: StrictStr=Field(min_length=64,max_length=64)
    approved: StrictBool
    otp: Optional[StrictStr]=Field(default=None,max_length=6)


class Challenge(Body):
    binding: StrictStr=Field(min_length=64,max_length=64)


class Execute(Body):
    fault: Literal['none','timeout_after_accept','timeout_before_accept']='none'


class Chat(Body):
    message: StrictStr=Field(min_length=1,max_length=2000)
    task_id: Optional[StrictStr]=Field(default=None,min_length=1,max_length=80)
    revision: Optional[int]=Field(default=None,ge=1)


class Import(Body):
    csv: StrictStr=Field(min_length=1,max_length=300000)


class Reveal(Body):
    confirmed: StrictBool


class Preference(Body):
    subscription_id: StrictStr=Field(min_length=1,max_length=100)
    preference: Literal['using','unneeded','unknown']


class SubscriptionChoice(Body):
    subscription_id: StrictStr=Field(min_length=1,max_length=100)
    revision: Optional[int]=Field(default=None,ge=1)


class TransferChoice(Body):
    recipient: StrictStr=Field(min_length=1,max_length=80)
    amount: StrictStr=Field(min_length=1,max_length=14)
    due_day: StrictStr=Field(min_length=10,max_length=10)
    note: Optional[StrictStr]=Field(default=None,max_length=30)
    revision: Optional[int]=Field(default=None,ge=1)


class CardChoice(Body):
    card_id: StrictStr=Field(min_length=1,max_length=80)
    revision: Optional[int]=Field(default=None,ge=1)


class WatchRequest(Body):
    merchant: StrictStr=Field(min_length=1,max_length=80)
    amount_cents: Optional[int]=Field(default=None,ge=0,le=10**12)


class WatchResolve(Body):
    merchant: StrictStr=Field(min_length=1,max_length=80)
    outcome: Literal['mine','refunded','pending']


class Commitment(Body):
    title: StrictStr=Field(min_length=1,max_length=80)
    kind: Literal['income','expense']
    amount: StrictStr=Field(max_length=14)
    day: StrictStr=Field(max_length=10)
    essential: StrictBool=True
    recipient: Optional[StrictStr]=None


class Preview(Body):
    item_id: StrictStr
    day: StrictStr=Field(max_length=10)
    include_income: StrictBool=True


class Settings(Body):
    balance: StrictStr=Field(max_length=14)
    floor: StrictStr=Field(max_length=14)


def create_app(db_path=None):
    engine=Engine(db_path or os.environ.get('GUARDIAN_DB',str(ROOT/'data'/'guardian.sqlite3')))
    assistant=Assistant(engine)
    @asynccontextmanager
    async def lifespan(app):
        async def scheduler():
            while True:
                await asyncio.sleep(2)
                await asyncio.to_thread(engine.run_due)
        task=asyncio.create_task(scheduler())
        try: yield
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    app=FastAPI(title='小满 · 银行办事助手',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.engine=engine
    app.state.assistant=assistant

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        host=request.url.hostname
        if host not in {'127.0.0.1','localhost','testserver'}:
            return JSONResponse({'detail':'仅允许本机Host','code':'HOST'},status_code=403)
        origin=request.headers.get('origin')
        expected=f'{request.url.scheme}://{request.headers.get("host","")}'
        if origin and origin!=expected:
            return JSONResponse({'detail':'跨来源请求被拒绝','code':'ORIGIN'},status_code=403)
        if request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'跨站请求被拒绝','code':'ORIGIN'},status_code=403)
        if request.headers.get('content-length','').isdigit() and int(request.headers['content-length'])>350000:
            return JSONResponse({'detail':'请求过大'},status_code=413)
        response=await call_next(request)
        response.headers.update({
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
            # Radix uses dynamic styles for portal/focus/scroll management. Permit
            # inline CSS only; scripts remain self-only, without eval or inline JS.
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            'Permissions-Policy':'camera=(), microphone=(self), geolocation=()'})
        return response

    @app.exception_handler(Denied)
    async def denied(request, exc):
        return JSONResponse({'detail':exc.message,'code':exc.code},status_code=403 if exc.code in {'SESSION','BINDING','LOCKED','MFA_REQUIRED'} else 409)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail':'日期或参数格式无效','code':'SCHEMA'},status_code=422)

    def session(request:Request):
        result=engine.session(request.cookies.get('guardian_session',''))
        if request.method!='GET' and not hmac.compare_digest(request.headers.get('x-csrf-token',''),result['csrf']):
            raise Denied('请求缺少当前会话的CSRF令牌','SESSION')
        return result

    @app.get('/')
    def index():
        built=ROOT/'web'/'dist'/'index.html'
        return FileResponse(built if built.exists() else ROOT/'web'/'index.html')

    if (ROOT/'web'/'dist'/'assets').exists():
        app.mount('/assets',StaticFiles(directory=ROOT/'web'/'dist'/'assets'),name='ui-assets')

    @app.get('/app.js')
    def javascript(): return FileResponse(ROOT/'web'/'app.js',media_type='text/javascript')

    @app.get('/styles.css')
    def stylesheet(): return FileResponse(ROOT/'web'/'styles.css',media_type='text/css')

    @app.get('/favicon.ico')
    def favicon(): return Response(status_code=204)

    @app.get('/api/health')
    def health(): return {'status':'ok','environment':'local-bank-sandbox','real_payments':False,
                         'planner':'llm_configured' if configured() else 'rule_baseline'}

    @app.post('/api/session')
    def bootstrap(request:Request):
        # Reuse the active session so a refresh/restart preserves operations.
        try:
            old=engine.session(request.cookies.get('guardian_session',''))
            return {'csrf':old['csrf'],'mode':'sandbox','identity':'isolated_browser_demo'}
        except Denied:
            state=engine.bootstrap()
            response=JSONResponse({'csrf':state['csrf'],'mode':'sandbox','identity':'isolated_browser_demo'})
            response.set_cookie('guardian_session',state['token'],httponly=True,samesite='strict',max_age=86400)
            return response

    @app.get('/api/state')
    def snapshot(s=Depends(session)):
        state=engine.snapshot(s['owner'])
        # Subscription management query is explicitly confirmed separately.
        state.pop('subscriptions')
        return state

    @app.post('/api/subscriptions/reveal')
    def subscriptions(body:Reveal,s=Depends(session)):
        if not body.confirmed: raise Denied('请明确确认查询订阅管理信息','APPROVAL')
        with engine.tx() as c:
            engine.check_lock(c,s['owner'])
            engine.audit(c,s['owner'],'SUBSCRIPTIONS_QUERY_CONFIRMED',{})
        return {'subscriptions':engine.snapshot(s['owner'])['subscriptions']}

    @app.post('/api/chat')
    def chat(body:Chat,s=Depends(session)): return assistant.message(s['owner'],body.message,body.task_id,body.revision)

    @app.post('/api/assistant/message')
    def assistant_message(body:Chat,s=Depends(session)):
        return assistant.message(s['owner'],body.message,body.task_id,body.revision)

    @app.get('/api/assistant/tasks')
    def assistant_history(s=Depends(session)):
        return {'tasks':assistant.history(s['owner'])}

    @app.get('/api/assistant/tasks/{task}')
    def assistant_task(task:str,s=Depends(session)):
        return assistant.get(s['owner'],task)

    @app.post('/api/assistant/tasks/{task}/reveal')
    def assistant_reveal(task:str,body:Reveal,s=Depends(session)):
        return assistant.reveal(s['owner'],task,body.confirmed)

    @app.post('/api/assistant/tasks/{task}/preference')
    def assistant_preference(task:str,body:Preference,s=Depends(session)):
        return assistant.preference(s['owner'],task,body.subscription_id,body.preference)

    @app.post('/api/assistant/tasks/{task}/subscription')
    def assistant_subscription(task:str,body:SubscriptionChoice,s=Depends(session)):
        return assistant.prepare_subscription(s['owner'],task,body.subscription_id,body.revision)

    @app.post('/api/assistant/tasks/{task}/card')
    def assistant_card(task:str,body:CardChoice,s=Depends(session)):
        return assistant.prepare_card(s['owner'],task,body.card_id,body.revision)

    @app.get('/api/briefing')
    def briefing(s=Depends(session)):
        from guardian.briefing import build
        return build(engine,s['owner'])

    @app.post('/api/watch')
    def watch(body:WatchRequest,s=Depends(session)):
        return engine.watch(s['owner'],body.merchant,body.amount_cents)

    @app.post('/api/watch/resolve')
    def watch_resolve(body:WatchResolve,s=Depends(session)):
        closed=engine.resolve_watch(s['owner'],body.merchant,body.outcome)
        return dict(resolved=bool(closed),merchant=body.merchant,outcome=body.outcome)

    @app.post('/api/assistant/tasks/{task}/transfer')
    def assistant_transfer(task:str,body:TransferChoice,s=Depends(session)):
        return assistant.prepare_transfer(s['owner'],task,body.recipient,body.amount,body.due_day,body.revision,body.note)

    @app.post('/api/assistant/tasks/{task}/handoff')
    def assistant_handoff(task:str,s=Depends(session)):
        return assistant.create_handoff(s['owner'],task)

    @app.get('/api/forecast')
    def forecast(include_income:bool=True,s=Depends(session)):
        return planning.forecast(engine,s['owner'],include_income)

    @app.post('/api/forecast/preview')
    def preview(body:Preview,s=Depends(session)):
        return planning.forecast(engine,s['owner'],body.include_income,dict(item_id=body.item_id,day=body.day))

    @app.post('/api/commitments')
    def save_item(body:Commitment,s=Depends(session)):
        return planning.save(engine,s['owner'],body.model_dump())

    @app.post('/api/commitments/{item_id}/update')
    def update_item(item_id:str,body:Commitment,s=Depends(session)):
        return planning.save(engine,s['owner'],body.model_dump(),item_id)

    @app.post('/api/commitments/{item_id}/archive')
    def archive_item(item_id:str,s=Depends(session)):
        return planning.archive(engine,s['owner'],item_id)

    @app.post('/api/commitments/{item_id}/prepare')
    def prepare_item(item_id:str,s=Depends(session)):
        return planning.prepare(engine,s['owner'],item_id)

    @app.post('/api/planning/settings')
    def plan_settings(body:Settings,s=Depends(session)):
        return planning.settings(engine,s['owner'],body.balance,body.floor)

    @app.post('/api/planning/demo')
    def plan_demo(s=Depends(session)):
        return planning.demo_mode(engine,s['owner'])

    @app.post('/api/planning/example')
    def plan_example(body:Reveal,s=Depends(session)):
        if not body.confirmed: raise Denied('请明确选择加载示例','APPROVAL')
        return planning.example(engine,s['owner'])

    @app.get('/api/planning/export')
    def plan_export(s=Depends(session)):
        return Response(planning.export_csv(engine,s['owner']),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="cashflow-plan.csv"'})

    @app.post('/api/import')
    def import_csv(body:Import,s=Depends(session)): return engine.import_csv(s['owner'],body.csv)

    @app.post('/api/operations')
    def prepare(body:Prepare,s=Depends(session)): return engine.prepare(s['owner'],body.kind,body.payload,body.idempotency_key)

    @app.post('/api/operations/{op}/challenge')
    def challenge(op:str,body:Challenge,s=Depends(session)): return engine.challenge(s['owner'],op,body.binding)

    @app.post('/api/operations/{op}/confirm')
    def confirm(op:str,body:Approval,s=Depends(session)): return engine.confirm(s['owner'],op,body.binding,body.approved,body.otp)

    @app.post('/api/operations/{op}/execute')
    def execute(op:str,body:Execute,s=Depends(session)): return engine.execute(s['owner'],op,body.fault)

    @app.post('/api/operations/{op}/recover')
    def recover(op:str,s=Depends(session)): return engine.recover(s['owner'],op)

    @app.post('/api/operations/{op}/cancel')
    def cancel(op:str,s=Depends(session)): return engine.cancel(s['owner'],op)

    return app
