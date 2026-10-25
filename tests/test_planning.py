from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from guardian.engine import Engine,Denied,now
from guardian import planning

@pytest.fixture
def workspace(tmp_path):
    e=Engine(tmp_path/'planning.sqlite3');return e,e.bootstrap()['owner']

def item(workspace,title='房租',kind='expense',amount='500',offset=1,recipient='landlord'):
    e,o=workspace
    return planning.save(e,o,dict(title=title,kind=kind,amount=amount,day=(now().date()+timedelta(days=offset)).isoformat(),essential=True,recipient=recipient))

def approve(e,o,op):
    otp=e.challenge(o,op['id'],op['binding'])['demo_code'] if op['level']=='RED' else None
    e.confirm(o,op['id'],op['binding'],True,otp)

def test_no_examples_in_default_workspace(workspace):
    e,o=workspace;f=planning.forecast(e,o)
    assert f['items']==[] and f['expected_income_cents']==0
    assert f['lowest_cents']==e.snapshot(o)['balance_cents']

def test_explicit_example_is_atomic_idempotent_and_shows_real_arithmetic(workspace):
    e,o=workspace
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(lambda _:planning.example(e,o),range(3)))
    f=planning.forecast(e,o)
    assert len(f['items'])==4 and f['shortfall_cents']==27000 and f['lowest_cents']==173000
    assert all(i['source']=='example' for i in f['items'])
    assert f['balance_cents']==975900

def test_income_never_mints_spendable_money(workspace):
    e,o=workspace;start=e.snapshot(o)['balance_cents']
    item(workspace,'工资','income','12000',1,None)
    assert planning.forecast(e,o)['points'][1]['balance_cents']==start+1200000
    assert planning.forecast(e,o,False)['points'][1]['balance_cents']==start
    assert e.snapshot(o)['balance_cents']==start

def test_same_day_income_does_not_hide_intraday_shortfall(workspace):
    e,o=workspace
    item(workspace,'支出','expense','9000',1,None);item(workspace,'工资','income','12000',1,None)
    f=planning.forecast(e,o)
    assert f['points'][1]['balance_cents']>200000
    assert f['points'][1]['trough_cents']==75900
    assert f['shortfall_cents']==124100

def test_date_preview_has_no_side_effects(workspace):
    e,o=workspace;planning.example(e,o);before=planning.forecast(e,o)
    rent=next(i for i in before['items'] if i['title']=='房租')
    f=planning.forecast(e,o,True,{'item_id':rent['id'],'day':(now().date()+timedelta(days=6)).isoformat()})
    assert f['lowest_cents']>before['lowest_cents']
    assert f['preview_only'] and planning.forecast(e,o)==before
    assert e.snapshot(o)['operations']==[]

def test_linked_pending_transfer_is_counted_once(workspace):
    e,o=workspace;i=item(workspace);op=planning.prepare(e,o,i['id']);approve(e,o,op)
    f=planning.forecast(e,o)
    assert f['pending_expense_cents']==50000 and len(f['events'])==1
    assert planning.prepare(e,o,i['id'])['id']==op['id']
    with pytest.raises(Denied):planning.save(e,o,dict(title='新房租',kind='expense',amount='600',day=i['day'],essential=True,recipient='landlord'),i['id'])
    with pytest.raises(Denied):planning.forecast(e,o,True,{'item_id':i['id'],'day':i['day']})

def test_paid_unknown_receipt_is_not_subtracted_twice(workspace):
    e,o=workspace;i=item(workspace,offset=0);op=planning.prepare(e,o,i['id']);approve(e,o,op)
    before=planning.forecast(e,o)['lowest_cents']
    e.execute(o,op['id'],'timeout_after_accept')
    after=planning.forecast(e,o)
    assert after['lowest_cents']==before and after['pending_expense_cents']==0
    assert after['items'][0]['paid'] and after['items'][0]['operation_status']=='UNKNOWN'

def test_draft_edits_invalidate_old_approval_and_bind_new_amount(workspace):
    e,o=workspace;i=item(workspace);op=planning.prepare(e,o,i['id'])
    planning.save(e,o,dict(title='房租',kind='expense',amount='600',day=i['day'],essential=True,recipient='landlord'),i['id'])
    with pytest.raises(Denied):e.confirm(o,op['id'],op['binding'],True)
    updated=planning.prepare(e,o,i['id'])
    assert updated['id']!=op['id'] and updated['payload']['amount_cents']==60000

def test_archiving_prepared_item_cancels_draft(workspace):
    e,o=workspace;i=item(workspace);op=planning.prepare(e,o,i['id'])
    planning.archive(e,o,i['id'])
    assert planning.forecast(e,o)['items']==[] and e.get_operation(o,op['id'])['status']=='CANCELLED'

def test_no_payment_channel_means_no_fake_execution(workspace):
    e,o=workspace;i=item(workspace,'信用卡还款',recipient=None)
    with pytest.raises(Denied):planning.prepare(e,o,i['id'])
    assert e.snapshot(o)['operations']==[]

def test_manual_plan_is_separate_and_cannot_fund_or_trigger_bank_payments(workspace):
    e,o=workspace;planning.example(e,o);start=e.snapshot(o)['balance_cents']
    planning.settings(e,o,'50000','3000');f=planning.forecast(e,o)
    assert f['mode']=='manual' and f['balance_cents']==5000000 and f['items']==[]
    i=item(workspace);assert planning.forecast(e,o)['pending_expense_cents']==50000
    with pytest.raises(Denied):planning.prepare(e,o,i['id'])
    with pytest.raises(Denied):planning.example(e,o)
    assert e.snapshot(o)['balance_cents']==start
    planning.demo_mode(e,o);assert len(planning.forecast(e,o)['items'])==4
    planning.settings(e,o,'50000','3000');assert len(planning.forecast(e,o)['items'])==1

def test_csv_export_escapes_spreadsheet_formulas(workspace):
    e,o=workspace;item(workspace,'=HYPERLINK("x")',recipient=None)
    text=planning.export_csv(e,o)
    assert "'=HYPERLINK" in text and text.startswith('\ufeffdate,')

def test_missing_past_income_is_not_assumed_received_today(workspace,monkeypatch):
    e,o=workspace;item(workspace,'工资','income','12000',0,None)
    tomorrow=now()+timedelta(days=1);monkeypatch.setattr(planning,'now',lambda:tomorrow)
    f=planning.forecast(e,o)
    assert f['expected_income_cents']==0 and f['items'][0]['overdue']

def test_foreign_workspace_cannot_preview_edit_or_prepare(workspace):
    e,o=workspace;i=item(workspace);other=e.bootstrap()['owner']
    with pytest.raises(Denied):planning.prepare(e,other,i['id'])
    with pytest.raises(Denied):planning.forecast(e,other,True,{'item_id':i['id'],'day':i['day']})
    with pytest.raises(Denied):planning.archive(e,other,i['id'])
