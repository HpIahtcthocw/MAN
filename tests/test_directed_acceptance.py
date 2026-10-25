"""评审跟进的 T1-T10 定向用例，开发者可见，不是盲测集。

Pytest isolates model credentials: this checks host behavior, not live NLU.
"""
from datetime import date,timedelta
import pytest
from guardian.assistant import Assistant
from guardian.bill_scope import analyze
from guardian.engine import Engine,Denied,now
from tests.test_query_context import ledger


@pytest.fixture
def bank(tmp_path):
    e=Engine(tmp_path/'directed.sqlite3');return e,Assistant(e),e.bootstrap()['owner']


def follow(a,o,t,text):return a.message(o,text,t['id'],t['revision'])
def prepare(a,o,t):
    d=t['draft'];return a.prepare_transfer(o,t['id'],d['recipient'],d['amount'],d['due_day'],t['revision'])


def test_T1_exclusion_never_becomes_inclusion():
    r=analyze(ledger(),'9月花了多少，云盘不算',date(2026,10,20))
    assert r.get('needs_clarification') or r.get('expense_cents')==30000


def test_T2_last_year_month_does_not_mean_this_year():
    r=analyze(ledger(),'去年9月花了多少',date(2026,10,20))
    assert r.get('needs_clarification') or r.get('scope',{}).get('start')=='2025-09-01'


def test_T3_unknown_merchant_never_becomes_all_expenses():
    r=analyze(ledger(),'9月外卖花了多少',date(2026,10,20))
    assert r.get('needs_clarification') or (r.get('expense_cents')==0 and r.get('filters',{}).get('merchant_contains')=='外卖')


def test_T4_business_trip_is_not_a_comparison():
    first=analyze(ledger(),'8月花了多少',date(2026,10,20))
    r=analyze(ledger(),'9月出差花了多少',date(2026,10,20),first)
    assert 'comparison_periods' not in r


def test_T5_negated_amount_correction_revokes_old_draft(bank):
    e,a,o=bank;t=a.message(o,'给房东转600');old=prepare(a,o,t)
    t=follow(a,o,old['task'],'不转600了，转500，周五')
    assert t['draft']['amount']=='500'
    due=now().date()+timedelta(days=(4-now().date().weekday())%7)
    assert t['draft']['due_day']==due.isoformat()
    assert e.get_operation(o,old['operation']['id'])['status']=='CANCELLED'
    with pytest.raises(Denied):e.confirm(o,old['operation']['id'],old['operation']['binding'],True)


def test_T6_paused_task_cannot_resume_from_date_edit(bank):
    e,a,o=bank;t=a.message(o,'给房东转600');old=prepare(a,o,t)
    t=follow(a,o,old['task'],'先别转了');assert t['status']=='PAUSED'
    t=follow(a,o,t,'改成周五');assert t['status']=='PAUSED'
    with pytest.raises(Denied):prepare(a,o,t)
    with pytest.raises(Denied):e.confirm(o,old['operation']['id'],old['operation']['binding'],True)
    t=follow(a,o,t,'继续办理');assert t['status']=='READY'
    assert prepare(a,o,t)['operation']['status']=='PREPARED'


def test_T7_range_provenance_not_called_row_selection(bank):
    e,a,o=bank;t=a.message(o,'上个月花了多少');t=follow(a,o,t,'接着整理这些代扣');t=a.reveal(o,t['id'],True)
    assert t.get('source_selection')=='query_scope' and '选中' not in t['text']
    assert t.get('source_row_count')==12 and t.get('source_merchant_count')==12
    assert all(p['matched_evidence_ids'] for p in t['subscriptions'])
    assert not e.snapshot(o)['operations']


def test_T8_duplicate_name_needs_specific_protocol_choice(bank):
    e,a,o=bank
    with e.tx() as c:c.execute('INSERT INTO subscriptions(id,owner,name,amount,status,card) VALUES(?,?,?,?,?,?)',(o+':other-a',o,'云盘会员 A',4900,'ACTIVE','debit-3610'))
    t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    t=follow(a,o,t,'云盘会员A我不用了')
    assert not e.snapshot(o)['operations']
    assert next(s for s in t['subscriptions'] if s['id']==o+':other-a').get('ambiguous_name')
    # An explicit UI selection names a concrete protocol whose amount/suffix
    # are displayed; it is no longer the ambiguous natural-language name.
    t=a.preference(o,t['id'],o+':other-a','unneeded')
    result=a.prepare_subscription(o,t['id'],o+':other-a',t['revision']);op=result['operation']
    e.confirm(o,op['id'],op['binding'],True);e.execute(o,op['id'])
    subs=e.snapshot(o)['subscriptions']
    assert next(s for s in subs if s['id']==o+':other-a')['status']=='CANCELLED'
    assert next(s for s in subs if s['name']=='云盘会员 A' and s['id']!=o+':other-a')['status']=='ACTIVE'


def test_T9_old_preference_not_fresh_intent(bank):
    e,a,o=bank;t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    b=next(s for s in t['subscriptions'] if s['name']=='云盘会员 B')
    a.preference(o,t['id'],b['id'],'unneeded')
    second=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    b=next(s for s in second['subscriptions'] if s['name']=='云盘会员 B')
    assert b['preference']=='unknown'
    with pytest.raises(Denied):a.prepare_subscription(o,second['id'],b['id'],second['revision'])


def test_T10_education_does_not_hold_but_actual_inducement_does(bank):
    e,a,o=bank;t=a.message(o,'什么是安全账户骗局？转账时要注意什么')
    assert t['kind']=='safety_info'
    t=a.message(o,'给房东转600');assert prepare(a,o,t)['operation']['status']=='PREPARED'
    a.message(o,'客服让我转到安全账户')
    with pytest.raises(Denied):prepare(a,o,a.message(o,'给房东转600'))
