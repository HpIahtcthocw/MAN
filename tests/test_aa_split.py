"""Deterministic AA-split advice: read-only calculation, never auto-executed."""
from guardian.assistant import Assistant
from guardian.engine import Engine
from guardian.language import split_request


def task(tmp_path):
    e = Engine(tmp_path / 'aa.sqlite3')
    a = Assistant(e)
    return e, a, e.bootstrap()['owner']


def test_even_split_lists_shares_in_mention_order(tmp_path):
    e, a, o = task(tmp_path)
    t = a.message(o, '给同学张伟和房东AA，一共600元')
    assert t['status'] == 'CLARIFY'
    plan = t['split_plan']
    assert [s['recipient_id'] for s in plan['shares']] == ['zhang-school', 'landlord']
    assert all(s['amount_cents'] == 30000 for s in plan['shares'])
    assert plan['total_cents'] == 60000
    assert '不会自动拆成多笔' in t['text'] and '不能代收' in t['text']


def test_odd_amount_remainder_goes_to_first_mentioned(tmp_path):
    e, a, o = task(tmp_path)
    t = a.message(o, '500元 平分 给同学张伟和房东')
    shares = t['split_plan']['shares']
    assert [s['amount_cents'] for s in shares] == [25000, 25000]
    t = a.message(o, '给同学张伟和房东AA一共500.01元')
    assert [s['amount_cents'] for s in t['split_plan']['shares']] == [25001, 25000]
    assert '尾差' in t['text']


def test_ambiguous_shared_name_blocks_split(tmp_path):
    e, a, o = task(tmp_path)
    t = a.message(o, '给张伟和房东AA，一共600元')
    assert t['status'] == 'CLARIFY' and '多位联系人' in t['text'] and not t.get('split_plan')


def test_incomplete_split_requests_clarify(tmp_path):
    e, a, o = task(tmp_path)
    assert '总金额' in a.message(o, '给同学张伟和房东AA')['text']
    assert '至少需要两位' in a.message(o, 'AA拆分600元')['text']


def test_non_split_messages_unaffected_and_split_creates_no_operation(tmp_path):
    e, a, o = task(tmp_path)
    normal = a.message(o, '给房东转600')
    assert normal['status'] == 'READY' and normal['draft'].get('recipient') == 'landlord'
    t = a.message(o, '给同学张伟和房东AA，一共600元', normal['id'], normal['revision'])
    assert t['status'] == 'CLARIFY' and not t['draft']
    assert not e.snapshot(o)['operations']
    assert split_request('给房东转600', e.contacts()) is None
