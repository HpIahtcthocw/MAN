from datetime import datetime, timezone
from guardian.assistant import bill_analysis


def data():
    return dict(balance_cents=950000, reserved_cents=10000, bills=[
        dict(id='dec-rent', day='2025-12-03', amount=-50000, category='房租', source='bank:1'),
        dict(id='dec-food', day='2025-12-05', amount=-10000, category='餐饮', source='bank:2'),
        dict(id='nov-rent', day='2025-11-03', amount=-50000, category='房租', source='bank:3'),
        dict(id='nov-food', day='2025-11-05', amount=-5000, category='餐饮', source='bank:4'),
        dict(id='jan-food', day='2026-01-05', amount=-2000, category='餐饮', source='bank:5'),
        dict(id='dec-income', day='2025-12-10', amount=300000, category='收入', source='bank:6'),
        dict(id='csv', day='2025-12-05', amount=-999999, category='餐饮', source='csv:untrusted'),
    ])


def freeze(monkeypatch):
    monkeypatch.setattr('guardian.assistant.now',lambda:datetime(2026,1,15,tzinfo=timezone.utc))


def test_last_month_crosses_year_and_excludes_csv(monkeypatch):
    freeze(monkeypatch)
    report=bill_analysis(data(),'上个月花了多少？')
    assert report['period']=='2025年12月'
    assert report['expense_cents']==60000
    assert {r['id'] for r in report['rows']}=={'dec-rent','dec-food','dec-income'}


def test_comparison_returns_signed_delta_and_both_period_sources(monkeypatch):
    freeze(monkeypatch)
    report=bill_analysis(data(),'上个月和上上个月比多花了多少？')
    assert report['delta_cents']==5000
    assert [p['period'] for p in report['comparison_periods']]==['2025-12','2025-11']
    assert report['category_deltas']=={'房租':0,'餐饮':5000}
    assert len(report['comparison_periods'][1]['rows'])==2


def test_comparison_order_is_not_silently_reversed(monkeypatch):
    freeze(monkeypatch)
    report=bill_analysis(data(),'上上个月和上个月比少花了多少？')
    assert report['delta_cents']==-5000
    assert report['comparison_periods'][0]['period']=='2025-11'


def test_current_month_never_includes_prior_month(monkeypatch):
    freeze(monkeypatch)
    report=bill_analysis(data(),'本月花了多少？')
    assert report['expense_cents']==2000
    assert [r['id'] for r in report['rows']]==['jan-food']
