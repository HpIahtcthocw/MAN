"""今日叮咛 speaks first from ledger facts: anomaly, upcoming charges, income, watch hits."""
from datetime import timedelta

from guardian.briefing import build
from guardian.engine import Engine, now


def kinds(briefing):
    return [item['kind'] for item in briefing['items']]


def test_first_open_briefing_has_anomaly_upcoming_and_income(tmp_path):
    e = Engine(tmp_path / 'brief.sqlite3')
    o = e.bootstrap()['owner']
    briefing = build(e, o)
    kinds_found = kinds(briefing)
    assert 'anomaly' in kinds_found and 'upcoming' in kinds_found and 'income' in kinds_found
    anomaly = next(i for i in briefing['items'] if i['kind'] == 'anomaly')
    assert anomaly['merchant'] == '迅捷数码专营店' and '599' in anomaly['text']
    upcoming = next(i for i in briefing['items'] if i['kind'] == 'upcoming')
    assert '3笔' in upcoming['text'] and '97' in upcoming['text']
    assert briefing['spoken'].startswith(briefing['items'][0]['text'][:6])


def test_watch_then_new_charge_trips_the_watch(tmp_path):
    e = Engine(tmp_path / 'watch.sqlite3')
    o = e.bootstrap()['owner']
    e.watch(o, '迅捷数码专营店', 59900)
    quiet = build(e, o)
    assert 'watch_hit' not in kinds(quiet)
    watching = next(i for i in quiet['items'] if i['kind'] == 'watching')
    assert '599' in watching['text'] and watching['evidence'] and '本人' in watching['text'] and '争议' in watching['text']
    today = now().date().isoformat()
    with e.tx() as c:
        c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',
                  ('watchhit', o, -39900, '迅捷数码专营店', '购物', today, 'watch:demo'))
    hit = build(e, o)
    assert 'watch_hit' in kinds(hit)
    hit_item = next(i for i in hit['items'] if i['kind'] == 'watch_hit')
    assert '399' in hit_item['text']
    # The user answers, not the system: hit stays until they resolve it.
    assert 'watch_hit' in kinds(build(e, o))
    e.resolve_watch(o, '迅捷数码专营店', 'mine')
    assert 'watch_hit' not in kinds(build(e, o)) and 'watching' not in kinds(build(e, o))


def test_lost_card_surfaces_in_briefing(tmp_path):
    e = Engine(tmp_path / 'briefcard.sqlite3')
    from guardian.assistant import Assistant as A
    assistant = A(e)
    o = e.bootstrap()['owner']
    t = assistant.message(o, '工资卡丢了')
    result = assistant.prepare_card(o, t['id'], t['card']['id'], t['revision'])
    code = e.challenge(o, result['operation']['id'], result['operation']['binding'])['demo_code']
    e.confirm(o, result['operation']['id'], result['operation']['binding'], True, code)
    e.execute(o, result['operation']['id'])
    briefing = build(e, o)
    assert 'aftermath' in kinds(briefing)
    item = next(i for i in briefing['items'] if i['kind'] == 'aftermath')
    assert '4笔' in item['text'] or '3笔' in item['text']


def test_calm_day_gets_a_calm_line(tmp_path):
    e = Engine(tmp_path / 'calm.sqlite3')
    o = e.bootstrap()['owner']
    with e.tx() as c:
        c.execute("DELETE FROM ledger WHERE owner=? AND day>=? AND source NOT LIKE 'seed:%'", (o, now().date().replace(day=1).isoformat()))
        c.execute("UPDATE subscriptions SET status='CANCELLED' WHERE owner=?", (o,))
    briefing = build(e, o)
    assert kinds(briefing) == ['calm'] and '没什么要紧事' in briefing['items'][0]['text']


def _approve(e, o, op):
    code = e.challenge(o, op['id'], op['binding'])['demo_code']
    return e.confirm(o, op['id'], op['binding'], True, code)


def test_scheduled_reminder_and_receipt_announcement(tmp_path):
    from datetime import timedelta as td
    from guardian.assistant import Assistant as A
    e = Engine(tmp_path / 'sched.sqlite3')
    a = A(e)
    o = e.bootstrap()['owner']
    op = e.prepare(o, 'transfer', dict(recipient='landlord', amount='600',
        due_day=(now().date() + td(days=1)).isoformat(), note='房租'), 'sched-0001')
    e.confirm(o, op['id'], op['binding'], True)
    kinds_found = kinds(build(e, o))
    assert 'scheduled' in kinds_found
    assert '明天' in next(i for i in build(e, o)['items'] if i['kind'] == 'scheduled')['text']
    today_op = e.prepare(o, 'transfer', dict(recipient='zhang-school', amount='200',
        due_day=now().date().isoformat(), note='午饭'), 'sched-0002')
    e.confirm(o, today_op['id'], today_op['binding'], True)
    e.execute(o, today_op['id'])
    receipt_item = next(i for i in build(e, o)['items'] if i['kind'] == 'receipt')
    assert '200' in receipt_item['text'] and '回执' in receipt_item['text']


def test_cancelled_subscription_charged_again_alerts(tmp_path):
    from guardian.assistant import Assistant as A
    e = Engine(tmp_path / 'chrg.sqlite3')
    a = A(e)
    o = e.bootstrap()['owner']
    t = a.message(o, '查询代扣')
    revealed = a.reveal(o, t['id'], True)
    sub = next(s for s in revealed['subscriptions'] if s['name'] == '云盘会员 A')
    after_pref = a.preference(o, t['id'], sub['id'], 'unneeded')
    result = a.prepare_subscription(o, t['id'], sub['id'], after_pref['revision'])
    e.confirm(o, result['operation']['id'], result['operation']['binding'], True)
    e.execute(o, result['operation']['id'])
    today = now().date().isoformat()
    with e.tx() as c:
        c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',
                  ('still', o, -2900, '云盘会员 A', '订阅', today, 'still-charging'))
    briefing = build(e, o)
    assert 'cancelled_charge' in kinds(briefing)
    item = next(i for i in briefing['items'] if i['kind'] == 'cancelled_charge')
    assert '已经撤销' in item['text'] and '29' in item['text']


def test_aa_split_next_share_surfaces_after_first_done(tmp_path):
    from guardian.assistant import Assistant as A
    e = Engine(tmp_path / 'aanext.sqlite3')
    a = A(e)
    o = e.bootstrap()['owner']
    t = a.message(o, '给同学张伟和房东AA，一共600元')
    t = a.message(o, '给张伟（同学）转300', t['id'], t['revision'])
    result = a.prepare_transfer(o, t['id'], t['draft']['recipient'], t['draft']['amount'], t['draft']['due_day'], t['revision'])
    e.confirm(o, result['operation']['id'], result['operation']['binding'], True)
    e.execute(o, result['operation']['id'])
    item = next(i for i in build(e, o)['items'] if i['kind'] == 'aa_next')
    assert '林女士' in item['text'] and item['message'] == '给林女士（房东）转300'
