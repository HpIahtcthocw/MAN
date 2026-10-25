# -*- coding: utf-8 -*-
"""Live configured-model API smoke test, isolated synthetic bank, not browser QA."""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from guardian.app import create_app
from guardian.engine import now
out=ROOT/'test-results/acceptance-review'
run=Path(tempfile.mkdtemp(prefix='api-',dir=str(out)))
client=TestClient(create_app(run/'bank.sqlite3'))
headers={'x-csrf-token':client.post('/api/session').json()['csrf']}
checks=[];turns=[];t=None
def check(name,value):
    checks.append(dict(name=name,passed=bool(value)))
    if not value: raise AssertionError(name)
def send(message,new=False):
    global t
    payload={'message':message}
    if t and not new:payload.update(task_id=t['id'],revision=t['revision'])
    r=client.post('/api/assistant/message',headers=headers,json=payload)
    check('API accepts '+message,r.status_code==200)
    t=r.json();turns.append(dict(input=message,status=t['status'],planner=t['planner'],model_meta=t.get('model_meta'),query=t.get('analysis',{}).get('query')))
    return t
failure=None
try:
    x=send('2025年9月1日到9月15日花了多少',True)
    check('explicit end-year inherited',x['analysis']['scope']['end']=='2025-09-15' and x['analysis']['expense_cents']==0)
    x=send('上个月云盘消费一共多少',True)
    check('cloud total58',x['analysis']['expense_cents']==5800)
    x=send('全部类别')
    check('merchant survives category reset',x['analysis']['filters']['merchant_contains']=='云盘' and x['analysis']['expense_cents']==5800)
    x=send('只看医疗')
    check('unknown filter clarifies without stale total',x['status']=='CLARIFY' and 'analysis' not in x)
    check('financial operations remain zero',client.get('/api/state').json()['operations']==[])
    check('state does not bypass protocol consent','subscriptions' not in client.get('/api/state').json())
    check('mutation without csrf rejected',client.post('/api/assistant/message',json={'message':'查余额'}).status_code==403)
except Exception as e:failure=type(e).__name__+': '+str(e)
report=dict(run_at=now().isoformat(),passed=failure is None,checks=checks,turns=turns,failure=failure,
    real_bank=False,blind=False,environment='FastAPI TestClient + real configured model + isolated synthetic bank; not a browser or user trial')
(out/'api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(passed=report['passed'],checks=len(checks),failure=failure),ensure_ascii=True))
if failure:raise SystemExit(1)
