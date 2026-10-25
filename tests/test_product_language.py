import pytest
from guardian import assistant as mod
from guardian.assistant import Assistant
from guardian.engine import Engine, Denied
from guardian.language import explicit_edit_amount
from guardian.task_planner import Plan, template


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'configured', lambda: False)
    e = Engine(tmp_path / 'language.sqlite3')
    return e, Assistant(e), e.bootstrap()['owner']


@pytest.mark.parametrize('text', ['等等，六百不对，是八百', '不是六百，是八百', '600元错了，应该是800元'])
def test_corrective_amount_revokes_old_preparation(bank, text):
    e, a, o = bank
    t = a.message(o, '给房东转600')
    d = t['draft']
    r = a.prepare_transfer(o, t['id'], d['recipient'], d['amount'], d['due_day'], t['revision'])
    t = a.message(o, text, t['id'], r['task']['revision'])
    assert t['draft']['amount'] == '800' and t['status'] == 'READY'
    assert e.get_operation(o, r['operation']['id'])['status'] == 'CANCELLED'
    with pytest.raises(Denied):
        e.confirm(o, r['operation']['id'], r['operation']['binding'], True, None)


@pytest.mark.parametrize('text', ['不是600吗？', '周六不对，是周五', '不是600，是800天', '不是600，是800吗？'])
def test_questions_and_dates_not_money_corrections(text):
    assert explicit_edit_amount(text) is None


def test_ungrounded_model_amount_change_blocks_old_amount(bank, monkeypatch):
    e, a, o = bank
    t = a.message(o, '给房东转600')
    monkeypatch.setattr(mod, 'configured', lambda: True)
    monkeypatch.setattr(mod, 'model_plan', lambda *args: (Plan(intent='transfer', amount='800', nodes=template('transfer')), {}))
    t = a.message(o, '再多给一点吧', t['id'], t['revision'])
    assert t['status'] == 'CLARIFY' and t['unresolved_amount']
    with pytest.raises(Denied):
        a.prepare_transfer(o, t['id'], 'landlord', '600', t['draft']['due_day'], t['revision'])
    assert not e.snapshot(o)['operations']


def test_colloquial_floor_declines_insufficient_balance(bank):
    e, a, o = bank
    t = a.message(o, '给房东转7000，不过办完卡里至少得有三千，不够就别办')
    assert t['status'] == 'DECLINED'
    assert t['constraint_check']['requested_floor_cents'] == 300000
    assert not e.snapshot(o)['operations']


def test_food_alias_keeps_previous_month(bank):
    _, a, o = bank
    t = a.message(o, '上个月花了多少')
    scope = t['analysis']['scope']
    t = a.message(o, '吃饭那部分单独算一下', t['id'], t['revision'])
    assert t['analysis']['scope'] == scope
    assert t['analysis']['filters']['category'] == '餐饮'
    assert t['analysis']['expense_cents'] == 65000


def test_only_stop_b_keeps_a_and_does_not_execute(bank):
    e, a, o = bank
    t = a.message(o, '查询代扣')
    t = a.reveal(o, t['id'], True)
    t = a.message(o, 'A我还要用，只停B', t['id'], t['revision'])
    by_name = {s['name']: s for s in t['subscriptions']}
    assert by_name['云盘会员 A']['preference'] == 'using'
    assert by_name['云盘会员 B']['preference'] == 'unneeded'
    assert not e.snapshot(o)['operations']


def test_monthly_cloud_amount_is_a_bill_query(bank):
    _, a, o = bank
    t = a.message(o, '上个月买云盘服务一共扣了几块钱')
    assert t['kind'] == 'bills' and t['analysis']['expense_cents'] == 5800


@pytest.mark.parametrize('message,kind', [('给房东转600','transfer'), ('上个月花了多少','bills'), ('查询代扣','subscriptions')])
def test_vague_opening_accepts_clarification_in_same_task(bank, message, kind):
    e, a, o = bank
    first = a.message(o, '帮我办一下')
    assert first['kind'] == 'clarify'
    second = a.message(o, message, first['id'], first['revision'])
    assert second['id'] == first['id'] and second['kind'] == kind
    assert len(second['turns']) == 2 and not e.snapshot(o)['operations']
    assert a.get(o, first['id'])['kind'] == kind
