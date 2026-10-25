from datetime import date
import pytest
from pydantic import ValidationError
from guardian.bill_scope import analyze
from guardian.task_planner import BillQuery,Plan,template
from guardian.assistant import Assistant
from guardian.engine import Engine,Denied
from tests.test_query_context import ledger


def test_model_period_disagreement_never_emits_amount():
    q=BillQuery(period_start='2025-09-01',period_end='2025-09-30',period_evidence='9月')
    r=analyze(ledger(),'9月花了多少',date(2026,10,20),proposal=q)
    assert r['needs_clarification'] and 'expense_cents' not in r


def test_model_unknown_merchant_never_falls_back_to_all():
    q=BillQuery(merchant='外卖',merchant_evidence='外卖')
    r=analyze(ledger(),'我的外卖开支呢',date(2026,10,20),proposal=q)
    assert r['needs_clarification'] and 'expense_cents' not in r


def test_model_evidence_must_be_verbatim():
    r=analyze(ledger(),'9月花了多少',date(2026,10,20),proposal=BillQuery(category='餐饮',category_evidence='只看餐饮'))
    assert r['needs_clarification'] and 'expense_cents' not in r


def test_agreed_query_uses_bank_rows_not_model_amounts():
    q=BillQuery(period_start='2026-09-01',period_end='2026-09-30',period_evidence='9月',merchant='云盘',merchant_evidence='云盘')
    r=analyze(ledger(),'9月云盘花了多少',date(2026,10,20),proposal=q)
    assert r['query_verification']=='model_host_agreement' and r['expense_cents']==2900


def test_query_cannot_include_sql_or_totals():
    with pytest.raises(ValidationError):BillQuery.model_validate({'sql':'DELETE FROM ledger'})
    with pytest.raises(ValidationError):BillQuery.model_validate({'expense_cents':100})


@pytest.mark.parametrize('text',['9月花了多少，云盘不含在内','9月不含云盘花了多少','9月云盘除外','9月不是餐饮那部分','9月花了多少，云盘不算'])
def test_exclusion_is_not_silently_reversed(text):
    r=analyze(ledger(),text,date(2026,10,20))
    assert not r.get('needs_clarification')
    assert r['expense_cents']==(2900 if '餐饮' in text else 30000)
    assert r['filters']['merchant_contains'] is None and r['filters']['category'] is None


@pytest.mark.parametrize('text',['9月不含外卖花了多少','9月不含云盘和外卖花了多少','9月除了餐饮还看云盘'])
def test_unknown_or_compound_exclusion_does_not_emit_total(text):
    r=analyze(ledger(),text,date(2026,10,20))
    assert r.get('needs_clarification') and 'expense_cents' not in r


def test_exclusion_persists_across_period_edits_and_can_be_reset():
    r=analyze(ledger(),'9月云盘不算',date(2026,10,20))
    r=analyze(ledger(),'改看8月',date(2026,10,20),r)
    assert r['expense_cents']==8000 and r['filters']['exclude']
    r=analyze(ledger(),'清除排除',date(2026,10,20),r)
    assert r['expense_cents']==10900 and not r['filters']['exclude']


def test_exclusion_proposal_must_match_account_vocabulary_and_original_request():
    text='9月花了多少，云盘不算'
    r=analyze(ledger(),text,date(2026,10,20),proposal=BillQuery(exclude=['云盘']))
    assert r['expense_cents']==30000 and r['query_verification']=='model_host_agreement'
    r=analyze(ledger(),text,date(2026,10,20),proposal=BillQuery(exclude=['餐饮']))
    assert r.get('needs_clarification') and 'expense_cents' not in r


def test_wire_contract_does_not_let_model_supply_tools_or_approval():
    from guardian.task_planner import parse_semantic_plan,semantic_schema
    assert 'nodes' not in semantic_schema()['properties']
    assert parse_semantic_plan('{"intent":"transfer","amount":"600"}').nodes==template('transfer')
    for content in ('{"intent":"transfer","nodes":[]}','{"intent":"transfer","approved":true}'):
        with pytest.raises(ValueError):parse_semantic_plan(content)


@pytest.mark.parametrize('text',['9月外卖花了多少','9月医疗花了多少','9月出差花了多少'])
def test_unknown_subject_clarifies(text):
    r=analyze(ledger(),text,date(2026,10,20))
    assert r['needs_clarification'] and 'expense_cents' not in r


def test_merchant_candidates_come_from_bank_not_demo_names():
    s=ledger();s['bills'].append(dict(id='new-brand',day='2026-09-04',amount=-9900,category='订阅',merchant='星河云备份服务',source='bank:new'))
    r=analyze(s,'9月星河云备份花了多少',date(2026,10,20))
    assert r['expense_cents']==9900 and [b['id'] for b in r['rows']]==['new-brand']


@pytest.mark.parametrize('text',[
    '什么是安全账户骗局？转账时要注意什么','如何识别安全账户转账诈骗','怎么防范安全账户转账诈骗',
    '什么是屏幕共享骗局，操作银行卡时要注意什么','如何识别索取验证码诈骗，告诉别人安全吗',
    '怎么识别先付保证金的贷款诈骗','如何防范先付款再退款诈骗','什么是解冻资金要先转账的骗局',
    '如何识别银行卡密码被索取的骗局，告诉别人安全吗','转账时要注意什么，如何识别安全账户骗局',
])
def test_ten_education_queries_do_not_freeze_account(tmp_path,text):
    e=Engine(tmp_path/'education.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    t=a.message(o,text)
    assert t['kind'] in ('safety_info','clarify')
    with e.tx() as c:assert not c.execute('SELECT 1 FROM transfer_holds WHERE owner=?',(o,)).fetchone()


@pytest.mark.parametrize('text',['客服让我转到安全账户','公安要求我转账到安全账户','对方让我屏幕共享操作银行卡','客服让我把验证码发给他','贷款让我先付保证金','客服说必须转到安全账户，什么是这个流程'])
def test_actual_inducements_still_hold_account(tmp_path,text):
    e=Engine(tmp_path/'inducement.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    assert a.message(o,text)['kind']=='safety'
    with e.tx() as c:assert c.execute('SELECT 1 FROM transfer_holds WHERE owner=?',(o,)).fetchone()


def test_model_and_host_money_disagreement_blocks_old_draft(tmp_path,monkeypatch):
    e=Engine(tmp_path/'money-disagreement.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    t=a.message(o,'给房东转600');d=t['draft'];old=a.prepare_transfer(o,t['id'],d['recipient'],d['amount'],d['due_day'],t['revision'])
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    monkeypatch.setattr('guardian.assistant.model_plan',lambda *_:(Plan(intent='transfer',amount='500',nodes=template('transfer')),{}))
    t=a.message(o,'不是转600，是转500',t['id'],old['task']['revision'])
    assert t['status']=='CLARIFY' and t['unresolved_amount']
    assert e.get_operation(o,old['operation']['id'])['status']=='CANCELLED'
    with pytest.raises(Denied):a.prepare_transfer(o,t['id'],'landlord','600',t['draft']['due_day'],t['revision'])


def test_model_cannot_resume_without_explicit_user_resume(tmp_path,monkeypatch):
    e=Engine(tmp_path/'paused.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    t=a.message(o,'给房东转600');t=a.message(o,'先别转了',t['id'],t['revision'])
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    monkeypatch.setattr('guardian.assistant.model_plan',lambda *_:(Plan(intent='transfer',action='resume',nodes=template('transfer')),{}))
    t=a.message(o,'我想把时间换一下',t['id'],t['revision'])
    assert t['status']=='PAUSED'
