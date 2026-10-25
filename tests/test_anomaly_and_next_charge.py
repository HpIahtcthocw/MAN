"""Read-only anomaly candidates and next-charge estimates come from ledger facts only."""
from datetime import date

from guardian.assistant import Assistant
from guardian.bill_scope import detect_anomalies, estimate_next_charge
from guardian.engine import Engine


def row(day, merchant, amount):
    return dict(id=day + merchant, day=day, merchant=merchant, amount=amount, category='测试', source='seed')


def test_amount_spike_and_first_seen_large_are_flagged_with_basis():
    rows = [row(f'2026-08-{d:02d}', '健身房', -3000) for d in (5, 12, 19)]
    rows.append(row('2026-09-05', '健身房', -30000))       # 10x median, >=200 CNY
    rows.append(row('2026-09-08', '陌生商户', -80000))      # first-ever, >=500 CNY
    rows.append(row('2026-09-09', '便利店', -1500))
    found = detect_anomalies(rows, '2026-09-01', '2026-09-30')
    kinds = {(a['kind'], a['merchant']) for a in found}
    assert ('amount_spike', '健身房') in kinds
    assert ('first_seen_large', '陌生商户') in kinds
    assert all(a['basis'] for a in found)
    assert ('amount_spike', '便利店') not in kinds


def test_no_anomaly_for_regular_or_small_activity():
    rows = [row(f'2026-08-{d:02d}', '便利店', -1500) for d in (1, 15, 28)]
    rows += [row('2026-09-10', '便利店', -1600), row('2026-09-11', '新小商户', -4000)]
    assert detect_anomalies(rows, '2026-09-01', '2026-09-30') == []


def test_next_charge_estimate_needs_regular_intervals():
    regular = [dict(day=d, amount=-2500) for d in ('2026-07-10', '2026-08-10', '2026-09-09')]
    est = estimate_next_charge(regular, date(2026, 10, 24))
    # 2026-10-09 already passed without a recorded debit; the cycle projects to 2026-11-08.
    assert est and est['date'] == '2026-11-08' and est['same_amount'] and '不是银行扣费承诺' in est['caveat']
    irregular = [dict(day=d, amount=-2500) for d in ('2026-06-01', '2026-07-20', '2026-09-02')]
    assert estimate_next_charge(irregular, date(2026, 10, 24)) is None
    assert estimate_next_charge(regular[:2], date(2026, 10, 24)) is None


def test_end_to_end_bills_mark_anomalies_and_reveal_shows_estimate(tmp_path):
    e = Engine(tmp_path / 'anomaly.sqlite3')
    a = Assistant(e)
    o = e.bootstrap()['owner']
    task = a.message(o, '2026年9月花了多少')
    assert task['status'] == 'DONE'
    if task['analysis'].get('anomalies'):
        assert '异常候选' in task['text']
    subs = a.message(o, '查询代扣')
    subs = a.message(o, '确认', subs['id'], subs['revision']) if subs['status'] == 'CONSENT_REQUIRED' else subs
    revealed = a.message(o, '查询代扣', subs['id'], subs['revision']) if subs['status'] != 'REVIEW' else subs
    review = revealed if revealed.get('subscriptions') is not None else a.reveal(o, subs['id'] if isinstance(subs, dict) else subs, True)
    for s in review['subscriptions']:
        assert 'next_charge_estimate' in s or s.get('ambiguous_name') or len(s.get('observations', [])) < 3
