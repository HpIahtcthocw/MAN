from datetime import date
import pytest
from guardian.bill_scope import analyze
from guardian.engine import Engine,Denied
from guardian.assistant import Assistant


def ledger():
    return dict(balance_cents=900000,reserved_cents=0,bills=[
        dict(id='s1',day='2026-09-02',amount=-10000,category='餐饮',merchant='餐厅',source='bank:1'),
        dict(id='s2',day='2026-09-20',amount=-20000,category='餐饮',merchant='餐厅',source='bank:2'),
        dict(id='s3',day='2026-09-10',amount=-2900,category='订阅',merchant='云盘',source='bank:3'),
        dict(id='a1',day='2026-08-05',amount=-8000,category='餐饮',merchant='餐厅',source='bank:4'),
        dict(id='a2',day='2026-08-10',amount=-2900,category='订阅',merchant='云盘',source='bank:5')])


@pytest.mark.parametrize('text',['9月1日到9月15日花了多少','2026-09-01到2026-09-15花了多少','2026年9月1日至15日的支出'])
def test_day_range_does_not_widen_to_month(text):
    r=analyze(ledger(),text,date(2026,10,20))
    assert r['scope']==dict(start='2026-09-01',end='2026-09-15')
    assert r['expense_cents']==12900 and {b['id'] for b in r['rows']}=={'s1','s3'}


@pytest.mark.parametrize('text',['9月上半月花了多少','9月1日以前花了多少','9月15日以后','9月1日到月末','9月1日到9月15日和10月'])
def test_unhandled_range_clarifies_instead_of_broadening(text):
    r=analyze(ledger(),text,date(2026,10,20))
    assert r['needs_clarification'] and 'expense_cents' not in r


@pytest.mark.parametrize('text',['2026年2月30日到3月1日','9月20日到9月1日'])
def test_invalid_or_reverse_range_is_rejected(text):
    with pytest.raises(Denied): analyze(ledger(),text,date(2026,10,20))


def test_comparison_inherits_category_and_both_periods_survive_followup():
    today=date(2026,10,20);s=ledger()
    first=analyze(s,'上个月只看餐饮',today)
    second=analyze(s,'和八月比呢',today,first)
    assert second['filters']['category']=='餐饮'
    assert [p['period'] for p in second['comparison_periods']]==['2026-09','2026-08']
    assert second['delta_cents']==22000
    third=analyze(s,'只看订阅',today,second)
    assert third['delta_cents']==0 and len(third['comparison_periods'])==2
    fourth=analyze(s,'全部类别',today,third)
    assert fourth['filters']['category'] is None and fourth['expense_cents']==32900


def test_merchant_filter_survives_month_edit():
    first=analyze(ledger(),'9月云盘消费',date(2026,10,20))
    second=analyze(ledger(),'改看八月',date(2026,10,20),first)
    assert second['filters']['merchant_contains']=='云盘' and second['expense_cents']==2900


@pytest.fixture
def bank(tmp_path):
    e=Engine(tmp_path/'link.sqlite3');return e,Assistant(e),e.bootstrap()['owner']


def follow(a,o,t,text): return a.message(o,text,t['id'],t['revision'])


def test_runtime_persists_filter_even_after_a_clarification(bank):
    e,a,o=bank;t=a.message(o,'上个月只看餐饮')
    first_scope=t['analysis']['scope']
    t=follow(a,o,t,'上半月呢')
    assert t['status']=='CLARIFY'
    t=follow(a,o,t,'和八月比呢')
    assert t['analysis']['filters']['category']=='餐饮'
    assert t['analysis']['scope']==first_scope and len(t['analysis']['comparison_periods'])==2
    assert not e.snapshot(o)['operations']


def test_linked_query_only_exposes_matching_protocol_candidates(bank):
    e,a,o=bank;t=a.message(o,'上个月云盘消费一共多少')
    s=follow(a,o,t,'接着整理这些代扣')
    assert 'subscriptions' not in s
    s=a.reveal(o,s['id'],True)
    assert {p['name'] for p in s['subscriptions']}=={'云盘会员 A','云盘会员 B'}
    assert s['link_status']=='CANDIDATES'
    assert all(p['matched_evidence_ids'] and p['match_basis'] for p in s['subscriptions'])
    assert all(p['preference']=='unknown' for p in s['subscriptions'])
    assert not e.snapshot(o)['operations']


def test_unmatched_bill_does_not_expand_and_all_requires_new_consent(bank):
    e,a,o=bank;t=a.message(o,'上个月只看餐饮')
    s=a.reveal(o,follow(a,o,t,'接着整理这些代扣')['id'],True)
    assert s['subscriptions']==[] and s['link_status']=='NO_MATCH'
    s=follow(a,o,s,'查询全部代扣')
    assert s['status']=='CONSENT_REQUIRED' and 'subscriptions' not in s
    s=a.reveal(o,s['id'],True)
    assert len(s['subscriptions'])==4 and s['source_mode']=='all'
    assert not e.snapshot(o)['operations']


def test_duplicate_protocol_names_remain_candidates_not_auto_cancellation(bank):
    e,a,o=bank;t=a.message(o,'上个月云盘消费一共多少')
    with e.tx() as c:
        c.execute('INSERT INTO subscriptions(id,owner,name,amount,status,card) VALUES(?,?,?,?,?,?)',(o+':duplicate',o,'云盘会员 A',2900,'ACTIVE','debit-3610'))
    s=a.reveal(o,follow(a,o,t,'接着整理这些代扣')['id'],True)
    assert any(link['status']=='AMBIGUOUS' for link in s['protocol_links'])
    with pytest.raises(Denied): a.prepare_subscription(o,s['id'],o+':duplicate')
    assert not e.snapshot(o)['operations']


def test_exact_balance_query_does_not_wait_for_model(bank,monkeypatch):
    e,a,o=bank
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    def unexpected(*args): raise AssertionError('Balance query must not call the model')
    monkeypatch.setattr('guardian.assistant.model_plan',unexpected)
    t=a.message(o,'查余额')
    assert t['planner']=='deterministic_query' and t['analysis']['balance_cents']==e.snapshot(o)['balance_cents']
    assert not e.snapshot(o)['operations']


def test_explicit_year_is_inherited_by_range_end():
    s=ledger();s['bills']=[dict(b,day=b['day'].replace('2026','2025')) for b in s['bills']]
    r=analyze(s,'2025年9月1日到9月15日花了多少',date(2026,10,20))
    assert r['scope']==dict(start='2025-09-01',end='2025-09-15') and r['expense_cents']==12900


def test_category_reset_keeps_merchant_constraint():
    first=analyze(ledger(),'9月只看云盘',date(2026,10,20))
    r=analyze(ledger(),'全部类别',date(2026,10,20),first)
    assert r['filters']==dict(category=None,merchant_contains='云盘',exclude=[]) and r['expense_cents']==2900


def test_unknown_filter_does_not_silently_reuse_previous_category():
    first=analyze(ledger(),'9月只看餐饮',date(2026,10,20))
    r=analyze(ledger(),'只看医疗',date(2026,10,20),first)
    assert r['needs_clarification'] and 'expense_cents' not in r
