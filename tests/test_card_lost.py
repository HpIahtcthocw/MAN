"""Card loss flow: card disambiguation, red verification, aftermath linkage."""
import pytest

from guardian.assistant import Assistant
from guardian.engine import Engine, Denied


def approve(e, o, op):
    code = e.challenge(o, op['id'], op['binding'])['demo_code']
    return e.confirm(o, op['id'], op['binding'], True, code)


def test_card_loss_end_to_end_with_aftermath(tmp_path):
    e = Engine(tmp_path / 'card.sqlite3')
    a = Assistant(e)
    o = e.bootstrap()['owner']
    t = a.message(o, '我卡丢了')
    assert t['status'] == 'CLARIFY' and len(t['suggestions']) == 2
    t = a.message(o, '挂失工资储蓄卡', t['id'], t['revision'])
    assert t['status'] == 'READY' and t['card']['last4'] == '3610'
    result = a.prepare_card(o, t['id'], t['card']['id'], t['revision'])
    op = result['operation']
    assert op['level'] == 'RED'
    approve(e, o, op)
    e.execute(o, op['id'])
    done = a.get(o, t['id'])
    assert done['status'] == 'DONE'
    assert next(c for c in e.cards(o) if c['id'] == op['payload']['card_id'])['status'] == 'LOST'
    am = done['aftermath']
    assert len(am['subscriptions']) == 4 and '扣款失败' in am['note'] and '微信' in am['external']
    again = a.get(o, t['id'])
    assert again['aftermath'] == am


def test_relosing_a_lost_card_short_circuits(tmp_path):
    e = Engine(tmp_path / 'card2.sqlite3')
    a = Assistant(e)
    o = e.bootstrap()['owner']
    t = a.message(o, '工资卡丢了')
    result = a.prepare_card(o, t['id'], t['card']['id'], t['revision'])
    approve(e, o, result['operation'])
    e.execute(o, result['operation']['id'])
    again = a.message(o, '工资卡又丢了')
    assert again['status'] == 'DONE' and '已经挂失' in again['text']
    with pytest.raises(Denied):
        a.prepare_card(o, t['id'], t['card']['id'], again['revision'])


def test_direct_prepare_rejects_unknown_card(tmp_path):
    e = Engine(tmp_path / 'card3.sqlite3')
    o = e.bootstrap()['owner']
    with pytest.raises(Denied):
        e.prepare(o, 'report_card_lost', {'card_id': 'owner:debit-0000'}, 'cardtest01')


def test_card_prepare_mismatched_task_object_denied(tmp_path):
    e = Engine(tmp_path / 'card4.sqlite3')
    a = Assistant(e)
    o = e.bootstrap()['owner']
    t = a.message(o, '工资卡丢了')
    with pytest.raises(Denied):
        a.prepare_card(o, t['id'], o + ':credit-8817', t['revision'])
