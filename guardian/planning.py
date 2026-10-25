"""Dated cash-flow arithmetic, not an income prediction or an authorization.

User-entered planned income stays hypothetical. Imported CSV cannot create funds.
An operation already debited by the provider must not be counted a second time.
"""
import csv
import io
import json
import uuid
from contextlib import closing
from datetime import datetime,timedelta
from guardian.engine import Denied,money,now


def validate(engine,body):
    day=datetime.strptime(body['day'],'%Y-%m-%d').date()
    if not now().date()<=day<=now().date()+timedelta(days=30):
        raise Denied('安排日期须为今天至未来30天','DATE')
    recipient=body.get('recipient')
    if recipient and (body['kind']!='expense' or recipient not in {c['id'] for c in engine.contacts()}):
        raise Denied('此计划不能关联该收款人','RECIPIENT')
    return dict(title=body['title'].strip(),kind=body['kind'],amount=money(body['amount']),
                day=day.isoformat(),essential=int(body['essential']),recipient=recipient)


def save(engine,owner,body,item_id=None,source='user_entered'):
    item=validate(engine,body)
    if not item['title']: raise Denied('请填写事项名称','SCHEMA')
    with engine.tx() as c:
        engine.check_lock(c,owner)
        if item_id:
            old=c.execute('SELECT * FROM commitments WHERE id=? AND owner=? AND archived=0',(item_id,owner)).fetchone()
            if not old: raise Denied('计划不存在','NOT_FOUND')
            linked=c.execute('SELECT o.* FROM plan_links l JOIN operations o ON o.id=l.op WHERE l.item=?',(item_id,)).fetchone()
            if linked and linked['status'] not in {'PREPARED','CANCELLED'}:
                raise Denied('付款已确认或状态未知，先处理原操作，不能直接改计划','PLAN_BOUND')
            if linked:
                c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(linked['id'],))
                engine.audit(c,owner,'DRAFT_INVALIDATED',dict(op=linked['id'],item=item_id))
            c.execute('UPDATE commitments SET title=?,kind=?,amount=?,day=?,essential=?,recipient=?,source=? WHERE id=?',
                tuple(item[k] for k in ['title','kind','amount','day','essential','recipient'])+(old['source'],item_id))
        else:
            if c.execute('SELECT 1 FROM planning_profiles WHERE owner=?',(owner,)).fetchone(): source='manual_plan'
            item_id=uuid.uuid4().hex
            c.execute('INSERT INTO commitments VALUES(?,?,?,?,?,?,?,?,0,?)',
                      (item_id,owner,item['title'],item['kind'],item['amount'],item['day'],item['essential'],item['recipient'],source))
        engine.audit(c,owner,'PLAN_ITEM_SAVED',dict(item=item_id,**item,source=source))
    return dict(id=item_id,**item)


def archive(engine,owner,item_id):
    with engine.tx() as c:
        engine.check_lock(c,owner)
        row=c.execute('SELECT * FROM commitments WHERE id=? AND owner=? AND archived=0',(item_id,owner)).fetchone()
        if not row: raise Denied('计划不存在','NOT_FOUND')
        linked=c.execute('SELECT o.* FROM plan_links l JOIN operations o ON o.id=l.op WHERE l.item=?',(item_id,)).fetchone()
        if linked and linked['status'] not in {'PREPARED','CANCELLED'}:
            raise Denied('已有确认／未知／完成操作，不可通过移除计划改变付款事实','PLAN_BOUND')
        if linked:
            c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(linked['id'],))
            engine.audit(c,owner,'DRAFT_INVALIDATED',dict(op=linked['id'],item=item_id))
        c.execute('UPDATE commitments SET archived=1 WHERE id=?',(item_id,))
        engine.audit(c,owner,'PLAN_ITEM_ARCHIVED',dict(item=item_id))
    return {'archived':True}


def prepare(engine,owner,item_id):
    with closing(engine.connect()) as c:
        row=c.execute('SELECT * FROM commitments WHERE id=? AND owner=? AND archived=0',(item_id,owner)).fetchone()
    if not row or row['source']=='manual_plan' or row['kind']!='expense' or not row['recipient']:
        raise Denied('此事项没有已核对的转账收款人，仅作提醒与测算','NO_PAYMENT_CHANNEL')
    return engine.prepare(owner,'transfer',dict(recipient=row['recipient'],amount=f"{row['amount']//100}.{row['amount']%100:02d}",
        due_day=row['day'],note=row['title']),'plan_'+item_id,source_item=item_id)


def forecast(engine,owner,include_income=True,changes=None):
    today=now().date();end=today+timedelta(days=30)
    with closing(engine.connect()) as c:
        # Read one SQLite snapshot so receipt/ledger/operation cannot disagree.
        c.execute('BEGIN')
        balance=engine.balance(c,owner)
        reserved=engine.reserved(c,owner)
        profile=c.execute('SELECT * FROM planning_profiles WHERE owner=?',(owner,)).fetchone()
        items=[dict(r) for r in c.execute('SELECT * FROM commitments WHERE owner=? AND archived=0 ORDER BY day,id',(owner,))]
        links={r['item']:r['op'] for r in c.execute('SELECT l.* FROM plan_links l JOIN commitments i ON i.id=l.item WHERE i.owner=?',(owner,))}
        ops={r['id']:dict(r) for r in c.execute("SELECT * FROM operations WHERE owner=? AND kind='transfer'",(owner,))}
        paid={r['op'] for r in c.execute('SELECT op FROM provider_receipts WHERE owner=?',(owner,))}
        c.rollback()
    floor=200000
    if profile:
        balance=profile['balance'];reserved=0;floor=profile['floor'];ops={};paid=set();links={}
        items=[i for i in items if i['source']=='manual_plan']
    else: items=[i for i in items if i['source']!='manual_plan']
    if changes:
        item=next((i for i in items if i['id']==changes['item_id']),None)
        if not item: raise Denied('此计划不存在','NOT_FOUND')
        op=ops.get(links.get(item['id']))
        if op and op['status'] not in {'PREPARED','CANCELLED'}: raise Denied('已批准付款不能通过试算修改','PLAN_BOUND')
        day=datetime.strptime(changes['day'],'%Y-%m-%d').date()
        if not today<=day<=end: raise Denied('试算日期须在未来30天内','DATE')
        item['day']=day.isoformat()
    events=[];represented=set()
    for item in items:
        op=ops.get(links.get(item['id']));item['operation_id']=op['id'] if op else None
        item['operation_status']=op['status'] if op else None
        item['paid']=bool(op and op['id'] in paid)
        item['overdue']=item['day']<today.isoformat() and not item['paid']
        if item['paid'] or item['kind']=='income' and item['overdue']: continue
        if op and op['status'] in {'CONFIRMED','SCHEDULED','UNKNOWN'}: represented.add(op['id'])
        events.append(dict(id=item['id'],title=item['title'],kind=item['kind'],amount_cents=item['amount'],
            day=max(item['day'],today.isoformat()),essential=bool(item['essential']),source=item['source'],
            operation_status=item['operation_status']))
    for op in ops.values():
        if op['id'] in represented or op['id'] in paid or op['status'] not in {'CONFIRMED','SCHEDULED','UNKNOWN'}: continue
        p=json.loads(op['payload'])
        events.append(dict(id=op['id'],title=p['note'] or '已确认转账',kind='expense',amount_cents=p['amount_cents'],
            day=max(p['due_day'],today.isoformat()),essential=True,source='confirmed_operation',operation_status=op['status']))
    baseline=balance;scenario=balance;points=[]
    for offset in range(31):
        day=(today+timedelta(days=offset)).isoformat()
        batch=[e for e in events if e['day']==day]
        # Income is assumed to arrive AFTER same-day expenses. Report the trough,
        # otherwise income and bills on one date can conceal an intraday shortfall.
        expenses=sum(e['amount_cents'] for e in batch if e['kind']=='expense')
        income=sum(e['amount_cents'] for e in batch if e['kind']=='income')
        baseline-=expenses;scenario-=expenses
        low=scenario
        if include_income: scenario+=income
        points.append(dict(day=day,balance_cents=scenario,trough_cents=low,without_income_cents=baseline,
                           income_cents=income,expense_cents=expenses))
    lowest=min(points,key=lambda p:p['trough_cents'])
    first=next((p for p in points if p['trough_cents']<floor),None)
    conservative=min([balance-reserved]+[p['without_income_cents'] for p in points])
    return dict(today=today.isoformat(),until=end.isoformat(),include_income=include_income,
        balance_cents=balance,reserved_cents=reserved,floor_cents=floor,items=items,events=events,points=points,
        lowest_cents=lowest['trough_cents'],lowest_day=lowest['day'],first_shortfall_day=first['day'] if first else None,
        shortfall_cents=max(0,floor-lowest['trough_cents']),unallocated_cents=max(0,conservative-floor),
        pending_expense_cents=sum(e['amount_cents'] for e in events if e['kind']=='expense'),
        expected_income_cents=sum(e['amount_cents'] for e in events if e['kind']=='income'),
        basis='user_entered_schedule_not_prediction',income_timing='after_same_day_expenses',
        mode='manual' if profile else 'sandbox',preview_only=bool(changes),
        caveat='只按已录入安排测算，不覆盖未录入支出；未来收入未到账，不是可用余额。')


def settings(engine,owner,balance,floor):
    def nonnegative(text):
        return 0 if text in {'0','0.0','0.00'} else money(text)
    b,f=nonnegative(balance),nonnegative(floor)
    with engine.tx() as c:
        engine.check_lock(c,owner)
        c.execute('INSERT OR REPLACE INTO planning_profiles VALUES(?,?,?)',(owner,b,f))
        engine.audit(c,owner,'MANUAL_PLAN_SETTINGS',dict(balance_cents=b,floor_cents=f,scope='calculation_only'))
    return {'mode':'manual','scope':'calculation_only_no_spendable_funds'}


def demo_mode(engine,owner):
    with engine.tx() as c:
        c.execute('DELETE FROM planning_profiles WHERE owner=?',(owner,))
        engine.audit(c,owner,'SANDBOX_PLAN_VIEW',{})
    return {'mode':'sandbox'}


def example(engine,owner):
    with engine.tx() as c:
        if c.execute('SELECT 1 FROM planning_profiles WHERE owner=?',(owner,)).fetchone():
            raise Denied('请先明确切回演示账户，再载入示例','EXAMPLE_SCOPE')
        if c.execute("SELECT 1 FROM commitments WHERE owner=? AND source='example'",(owner,)).fetchone():
            return {'loaded':False,'reason':'示例已加载，保留你的修改'}
        engine.check_lock(c,owner)
        for title,kind,amount,offset,recipient in [('信用卡还款','expense','4500',1,None),('云盘会员','expense','29',2,None),
            ('房租','expense','3500',3,'landlord'),('下次工资（预计）','income','12000',5,None)]:
            c.execute('INSERT INTO commitments VALUES(?,?,?,?,?,?,?,?,0,?)',
                (uuid.uuid4().hex,owner,title,kind,money(amount),(now().date()+timedelta(days=offset)).isoformat(),
                 int(kind=='expense' and title!='云盘会员'),recipient,'example'))
        engine.audit(c,owner,'EXAMPLE_PLAN_LOADED',dict(items=4,source='explicit_example'))
    return {'loaded':True,'mode':'explicit_example_not_user_data'}


def export_csv(engine,owner):
    data=forecast(engine,owner);out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['date','title','direction','amount_CNY','source','payment_status'])
    for item in data['items']:
        title=item['title']
        if title.startswith(('=','+','-','@','\t','\r')): title="'"+title
        writer.writerow([item['day'],title,item['kind'],f"{item['amount']/100:.2f}",item['source'],item['operation_status'] or 'not_executed'])
    return '\ufeff'+out.getvalue()
