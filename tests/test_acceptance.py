from datetime import datetime,timezone
import pytest
from guardian.assistant import Assistant,bill_analysis
from guardian.engine import Engine,Denied
from guardian.language import contact_hint
from guardian.task_runtime import direct_amount
from tests.test_bill_periods import data


@pytest.fixture
def bank(tmp_path):
    e=Engine(tmp_path/'award.sqlite3');return e,Assistant(e),e.bootstrap()['owner']


@pytest.mark.parametrize('text,expected',[
    ('2025年12月支出',60000),('去年一共花了多少',115000),('十二月花了多少',0),
    ('2025年11月到12月的支出',115000),('2025年12月餐饮消费',10000),
    ('最近30天支出',2000),
])
def test_explicit_and_rolling_bill_ranges(monkeypatch,text,expected):
    monkeypatch.setattr('guardian.assistant.now',lambda:datetime(2026,1,15,tzinfo=timezone.utc))
    r=bill_analysis(data(),text)
    assert r['expense_cents']==expected
    assert all(not b['source'].startswith('csv:') for b in r['rows'])
    assert r['coverage']['note'] and r['scope']


def test_bill_followup_keeps_month_not_all_data(monkeypatch):
    monkeypatch.setattr('guardian.assistant.now',lambda:datetime(2026,1,15,tzinfo=timezone.utc))
    first=bill_analysis(data(),'上个月花了多少')
    second=bill_analysis(data(),'只看餐饮',first['scope'])
    assert second['expense_cents']==10000 and second['scope']==first['scope']


@pytest.mark.parametrize('message',['最近三个月的账单','上周花了多少','从去年以来花多少'])
def test_unclear_period_is_not_silently_replaced_by_full_history(message):
    r=bill_analysis(data(),message)
    assert r.get('needs_clarification')


def test_bills_to_subscriptions_is_linked_but_reconsents(bank):
    e,a,o=bank;t=a.message(o,'上个月花了多少')
    s=a.message(o,'接着帮我整理这些代扣',t['id'],t['revision'])
    assert s['id']!=t['id'] and s['source_task_id']==t['id']
    assert s['source_scope']==t['analysis']['scope'] and s['source_evidence_ids']
    assert s['status']=='CONSENT_REQUIRED' and 'subscriptions' not in s and not s['operations']
    assert a.get(o,t['id'])['status']=='DONE'


def test_contact_resolution_uses_bank_entities_not_demo_names():
    contacts=[dict(id='a',name='王梅（姐姐）',last4='1024'),dict(id='b',name='王梅（同事）',last4='2048')]
    assert contact_hint('给王梅转600',contacts)=='王梅'
    assert contact_hint('不是同事，是姐姐那个',contacts)=='a'
    assert contact_hint('尾号2048的',contacts)=='b'
    assert contact_hint('第二位',contacts,candidates=contacts)=='b'
    assert contact_hint('转600',contacts,model_hint='a') is None


@pytest.mark.parametrize('text,expected',[('转给尾号6739的同学600元','600'),('给第二位转600元','600'),('金额换成八百块','800')])
def test_contact_digits_never_become_payment_amount(text,expected): assert direct_amount(text)==expected


@pytest.mark.parametrize('text',['给房东转三千五','给房东转600，转完留3000.001','给房东转600，余额不低于3e3'])
def test_ambiguous_money_conditions_fail_closed(bank,text):
    e,a,o=bank;t=a.message(o,text)
    assert t['status']=='CLARIFY' and not t['operations']
    with pytest.raises(Denied): a.prepare_transfer(o,t['id'],'landlord','600',t['draft']['due_day'])


def test_unquoted_warning_explanation_does_not_unlock_prior_hold(bank):
    e,a,o=bank
    quote='防诈提醒说不要把钱转到安全账户，为什么'
    assert a.message(o,quote)['kind']=='safety_info'
    a.message(o,'客服让我转到安全账户')
    assert a.message(o,quote)['kind']=='safety_info'
    with e.tx() as c: assert c.execute('SELECT 1 FROM transfer_holds WHERE owner=?',(o,)).fetchone()


def test_exact_edit_skips_model_but_keeps_approval_gate(bank,monkeypatch):
    e,a,o=bank;t=a.message(o,'给张伟转600')
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    def unexpected(*_): raise AssertionError('An exact scoped edit must not call the model')
    monkeypatch.setattr('guardian.assistant.model_plan',unexpected)
    t=a.message(o,'同学那个',t['id'],t['revision'])
    t=a.message(o,'改成周五',t['id'],t['revision'])
    assert t['planner']=='validated_edit' and t['model_meta']['model_called'] is False
    assert t['draft']['recipient']=='zhang-school' and not t['operations']


@pytest.mark.parametrize('text',['给房东转600，改成下下周五','给房东转600，明天下午三点','给房东转600，月底再办'])
def test_unsupported_time_is_not_silently_changed(bank,text):
    e,a,o=bank;t=a.message(o,text)
    assert t['status']=='CLARIFY' and t['unresolved_schedule']
    with pytest.raises(Denied): a.prepare_transfer(o,t['id'],'landlord','600',t['draft']['due_day'])


def test_multi_recipient_correction_cannot_silently_overwrite_old_recipient(bank):
    e,a,o=bank;t=a.message(o,'给房东转600')
    t=a.message(o,'房东转600，同学转500',t['id'],t['revision'])
    assert t['status']=='CLARIFY' and not t['draft'].get('recipient') and not t['operations']
