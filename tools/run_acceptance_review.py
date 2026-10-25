# -*- coding: utf-8 -*-
"""Author-visible boundary acceptance, not independent users or blind tasks."""
import argparse
import hashlib
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
sys.path.insert(0,str(ROOT))
from guardian.bill_scope import analyze
from guardian.assistant import Assistant
from guardian import assistant as mod
from guardian.engine import Engine

parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
out=ROOT/'test-results/acceptance-review';out.mkdir(exist_ok=True)
target=out/(args.label+'.json')
if target.exists(): raise SystemExit('Refusing to overwrite an acceptance run')
run=Path(tempfile.mkdtemp(prefix=args.label+'-',dir=str(out)))
mod.configured=lambda:False
state=dict(balance_cents=900000,reserved_cents=0,bills=[
    dict(id='old-early',day='2025-09-02',amount=-10000,category='餐饮',merchant='餐厅',source='bank:1'),
    dict(id='old-late',day='2025-09-20',amount=-20000,category='餐饮',merchant='餐厅',source='bank:2'),
    dict(id='current-food',day='2026-09-02',amount=-30000,category='餐饮',merchant='餐厅',source='bank:3'),
    dict(id='current-cloud',day='2026-09-05',amount=-2900,category='订阅',merchant='云盘',source='bank:4'),
    dict(id='last-food',day='2026-08-02',amount=-8000,category='餐饮',merchant='餐厅',source='bank:5'),
    dict(id='last-cloud',day='2026-08-05',amount=-2900,category='订阅',merchant='云盘',source='bank:6')])
today=date(2026,10,20);records=[]
def record(identifier,prompt,expected,fn):
    try:
        passed,observed=fn()
        records.append(dict(id=identifier,input=prompt,expected=expected,passed=bool(passed),observed=observed))
    except Exception as error:
        records.append(dict(id=identifier,input=prompt,expected=expected,passed=False,error_type=type(error).__name__,error_code=getattr(error,'code',None)))
def summary(r):
    return {k:r.get(k) for k in ('scope','filters','expense_cents','needs_clarification','delta_cents')}
def year_range():
    r=analyze(state,'2025年9月1日到9月15日花了多少',today)
    return r.get('scope')==dict(start='2025-09-01',end='2025-09-15') and r.get('expense_cents')==10000,summary(r)
record('A01','2025年9月1日到9月15日花了多少','End date inherits explicitly stated 2025, not today.year',year_range)
def reset_category():
    first=analyze(state,'9月只看云盘',today)
    r=analyze(state,'全部类别',today,first)
    return r.get('filters',{}).get('merchant_contains')=='云盘' and r.get('expense_cents')==2900,summary(r)
record('A02','9月只看云盘 → 全部类别','Reset category only; merchant filter remains cloud',reset_category)
def unknown_filter():
    first=analyze(state,'9月只看餐饮',today)
    r=analyze(state,'只看医疗',today,first)
    safe=r.get('needs_clarification') or (r.get('filters',{}).get('category')=='医疗' and r.get('expense_cents')==0)
    return safe,summary(r)
record('A03','9月只看餐饮 → 只看医疗','Clarify unknown category or return explicit medical zero; never old food',unknown_filter)
def exact_days():
    r=analyze(state,'9月1日至3日花了多少',today)
    return r.get('scope')==dict(start='2026-09-01',end='2026-09-03') and r.get('expense_cents')==30000,summary(r)
record('A04','9月1日至3日花了多少','Exact days; no fifth-day cloud charge',exact_days)
def comparison():
    first=analyze(state,'9月只看餐饮',today)
    r=analyze(state,'和八月比呢',today,first)
    return r.get('delta_cents')==22000 and r['filters']['category']=='餐饮',summary(r)
record('A05','9月只看餐饮 → 和八月比呢','Food remains selected; September minus August =220CNY',comparison)
def no_match():
    e=Engine(run/'no-match.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    t=a.message(o,'上个月餐饮花了多少');t=a.message(o,'接着整理这些代扣',t['id'],t['revision']);t=a.reveal(o,t['id'],True)
    return t['subscriptions']==[] and t['link_status']=='NO_MATCH' and not e.snapshot(o)['operations'],dict(protocol_count=len(t['subscriptions']),link_status=t['link_status'],operation_count=len(e.snapshot(o)['operations']))
record('A06','Food bills → related subscription query','No candidate, no expansion and no financial operation',no_match)
def foreign_evidence():
    e=Engine(run/'foreign.sqlite3');a=Assistant(e);o=e.bootstrap()['owner'];other=e.bootstrap()['owner']
    t=a.message(o,'上个月云盘消费一共多少');t=a.message(o,'接着整理这些代扣',t['id'],t['revision'])
    with e.tx() as c:
        _,d=a.row(c,o,t['id']);d['source_evidence_ids']=[b['id'] for b in e.snapshot(other)['bills']];a.update(c,t['id'],d)
    t=a.reveal(o,t['id'],True)
    return t['subscriptions']==[] and not e.snapshot(o)['operations'],dict(protocol_count=len(t['subscriptions']),operation_count=len(e.snapshot(o)['operations']))
record('A07','Corrupted provenance references another owner bank rows','Owner filter rejects foreign evidence even with internal metadata corruption',foreign_evidence)
report=dict(label=args.label,author_visible=True,blind=False,real_bank=False,model_calls=0,
    source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'guardian').rglob('*.py'))},
    records=records,passed=sum(r['passed'] for r in records),total=len(records),database_dir=str(run))
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(label=args.label,passed=report['passed'],total=len(records),failures=[r['id'] for r in records if not r['passed']]),ensure_ascii=True))
if report['passed']!=len(records): raise SystemExit(1)
