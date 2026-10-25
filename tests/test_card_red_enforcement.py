"""P0 regression: card loss keeps RED at confirm; transfer tier logic unchanged."""
from datetime import timedelta

import pytest

from guardian.assistant import Assistant
from guardian.engine import Denied, Engine, now


def test_card_confirm_without_otp_is_rejected(tmp_path):
    e = Engine(tmp_path / 'redcard.sqlite3')
    a = Assistant(e)
    o = e.bootstrap()['owner']
    t = a.message(o, '工资卡丢了')
    result = a.prepare_card(o, t['id'], t['card']['id'], t['revision'])
    assert result['operation']['level'] == 'RED'
    with pytest.raises(Denied) as err:
        e.confirm(o, result['operation']['id'], result['operation']['binding'], True)
    assert err.value.code == 'MFA_REQUIRED'
    assert e.get_operation(o, result['operation']['id'])['status'] == 'PREPARED'
    assert e.get_operation(o, result['operation']['id'])['level'] == 'RED'
    code = e.challenge(o, result['operation']['id'], result['operation']['binding'])['demo_code']
    e.confirm(o, result['operation']['id'], result['operation']['binding'], True, code)
    e.execute(o, result['operation']['id'])
    assert next(c for c in e.cards(o) if c['id'] == result['operation']['payload']['card_id'])['status'] == 'LOST'


def test_transfer_yellow_confirm_still_needs_no_otp(tmp_path):
    e = Engine(tmp_path / 'yellow.sqlite3')
    o = e.bootstrap()['owner']
    op = e.prepare(o, 'transfer', dict(recipient='landlord', amount='300',
        due_day=(now().date() + timedelta(days=1)).isoformat(), note='房租'), 'yel-low-001')
    assert op['level'] == 'YELLOW'
    confirmed = e.confirm(o, op['id'], op['binding'], True)
    assert confirmed['status'] == 'SCHEDULED'  # future-dated: scheduled, not confirmed
