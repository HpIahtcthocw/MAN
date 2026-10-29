import copy
import json
from datetime import timedelta
import pytest
from guardian.assistant import Assistant, model_plan
from guardian.engine import Engine, Denied, now
from guardian.task_planner import Plan, Node, template, validate_nodes, cn_number


@pytest.fixture
def bank(tmp_path):
    e=Engine(tmp_path/'completion.sqlite3')
    return e,Assistant(e),e.bootstrap()['owner']


def follow(a,o,t,text): return a.message(o,text,t['id'],t['revision'])


def prepare(a,o,t):
    d=t['draft']
    return a.prepare_transfer(o,t['id'],d['recipient'],d['amount'],d['due_day'],t['revision'])


def approve(e,o,op):
    otp=e.challenge(o,op['id'],op['binding'])['demo_code'] if op['level']=='RED' else None
    return e.confirm(o,op['id'],op['binding'],True,otp)


def test_multiturn_keeps_task_and_invalidates_old_approval(bank):
    e,a,o=bank
    first=a.message(o,'给张伟转600，转完至少留3000')
    assert first['status']=='CLARIFY' and len(first['candidates'])==2
    assert next(n for n in first['plan_nodes'] if n['tool']=='prepare_transfer')['level']=='YELLOW'
    second=follow(a,o,first,'同学那个')
    assert second['draft']['recipient']=='zhang-school'
    result=prepare(a,o,second);op=result['operation']
    # 到期日本身就可能是“今天”；改口目标必须与当前生效日期不同，否则
    # 保留旧批准是正确行为（只重校验受影响字段）。动态选下一个星期几。
    _names=['周一','周二','周三','周四','周五','周六','周日']
    _target=(now().date().weekday()+1)%7
    third=follow(a,o,result['task'],'改成'+_names[_target])
    assert third['id']==first['id'] and third['draft']['amount']=='600'
    assert third['draft']['minimum_balance']=='3000'
    assert third['draft']['due_day']>=now().date().isoformat()
    assert e.get_operation(o,op['id'])['status']=='CANCELLED'
    with pytest.raises(Denied): approve(e,o,op)
    new=prepare(a,o,third)['operation']
    approve(e,o,new)
    assert e.get_operation(o,new['id'])['status'] in ('SCHEDULED','CONFIRMED')


def test_stale_revision_and_confirmed_cannot_be_overwritten(bank):
    e,a,o=bank
    t=a.message(o,'给房东转600')
    updated=follow(a,o,t,'金额改为700')
    with pytest.raises(Denied,match='更新'): follow(a,o,t,'改成明天')
    result=prepare(a,o,updated);approve(e,o,result['operation'])
    with pytest.raises(Denied) as error: follow(a,o,result['task'],'金额改为800')
    assert error.value.code=='TASK_IN_FLIGHT'
    assert a.get(o,t['id'])['draft']['amount']=='700'


def test_revision_checked_again_after_model_call(bank,monkeypatch):
    e,a,o=bank;t=a.message(o,'给房东转600')
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    def concurrent(*args):
        with e.tx() as c:
            _,data=a.row(c,o,t['id']);data['revision']+=1;a.update(c,t['id'],data)
        return Plan(intent='transfer',amount='700',nodes=template('transfer')),{}
    monkeypatch.setattr('guardian.assistant.model_plan',concurrent)
    with pytest.raises(Denied) as err: follow(a,o,t,'我想把本次金额重新定到700元')
    assert err.value.code=='STALE_TASK'
    assert a.get(o,t['id'])['draft']['amount']=='600'


def test_floor_bound_at_prepare_confirm_dispatch_and_other_reservations(bank):
    e,a,o=bank;t=a.message(o,'给房东转600，转完至少留9000')
    result=prepare(a,o,t);op=result['operation'];approve(e,o,op)
    # Idempotent replay cannot count its own reservation twice.
    assert prepare(a,o,result['task'])['operation']['id']==op['id']
    other=e.prepare(o,'transfer',dict(recipient='zhang-school',amount='200',due_day=now().date().isoformat(),note='正常付款'),'floor_other_001')
    with pytest.raises(Denied): approve(e,o,other)
    # External balance changes must be checked again immediately before debit.
    with e.tx() as c:
        c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',('adjust',o,-20000,'外部扣款','其他',now().date().isoformat(),'external:adjust'))
    with pytest.raises(Denied): e.execute(o,op['id'])
    assert not any(b['source'].startswith('payment:') for b in e.snapshot(o)['bills'])


def test_floor_refusal_then_correction_retains_condition(bank):
    e,a,o=bank;t=a.message(o,'给房东转7000，卡里还要有三千')
    assert t['status']=='DECLINED' and t['constraint_check']['projected_balance_cents']==275900
    with pytest.raises(Denied): prepare(a,o,t)
    t=follow(a,o,t,'金额改成600')
    assert t['status']=='READY' and t['constraint_check']['requested_floor_cents']==300000
    assert prepare(a,o,t)['operation']['payload']['minimum_balance_cents']==300000


def test_subscription_language_is_scoped_and_negation_invalidates_draft(bank):
    e,a,o=bank;t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    t=follow(a,o,t,'B那个不用了，A还在用')
    prefs={s['name']:s['preference'] for s in t['subscriptions']}
    assert prefs['云盘会员 B']=='unneeded' and prefs['云盘会员 A']=='using'
    b=next(s for s in t['subscriptions'] if s['name']=='云盘会员 B')
    r=a.prepare_subscription(o,t['id'],b['id'],t['revision'])
    t=follow(a,o,r['task'],'B不要取消，先留着')
    assert next(s for s in t['subscriptions'] if s['id']==b['id'])['preference']=='using'
    assert e.get_operation(o,r['operation']['id'])['status']=='CANCELLED'
    with pytest.raises(Denied): approve(e,o,r['operation'])


def test_quoted_advice_never_releases_existing_hold(bank):
    e,a,o=bank
    quote='我在宣传册上看到“不要把钱转到安全账户”，这句话是什么意思？'
    assert a.message(o,quote)['kind']=='safety_info'
    with e.tx() as c: assert not c.execute('SELECT 1 FROM transfer_holds WHERE owner=?',(o,)).fetchone()
    a.message(o,'客服让我转到安全账户')
    a.message(o,quote)
    with e.tx() as c: assert c.execute('SELECT 1 FROM transfer_holds WHERE owner=?',(o,)).fetchone()
    assert a.message(o,quote+'请给房东转600元')['kind']=='safety'


@pytest.mark.parametrize('mutation',['duplicate','cycle','missing','order','extra'])
def test_invalid_plan_graph_rejected(mutation):
    p=Plan(intent='transfer',nodes=template('transfer'))
    if mutation=='duplicate': p.nodes[1].id=p.nodes[0].id
    elif mutation=='cycle': p.nodes[0].depends_on=[p.nodes[-1].id]
    elif mutation=='missing': p.nodes[2].depends_on=[]
    elif mutation=='order': p.nodes[0].tool='read_bills'
    else: p.nodes.append(Node(id='extra',tool='read_bills'))
    with pytest.raises(ValueError): validate_nodes(p)


def test_model_contract_rejects_invented_tools_and_approval(monkeypatch):
    for key,val in [('BASE_URL','https://provider.test/v1'),('API_KEY','not-a-real-key'),('MODEL','fixture')]: monkeypatch.setenv('GUARDIAN_LLM_'+key,val)
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def read(self,_): return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'intent':'transfer','approved':True,'nodes':[]})}}]}).encode()
    def fetch(request,timeout):
        body=json.loads(request.data)
        assert body['enable_thinking'] is False and body['response_format']['type']=='json_object'
        assert 'not-a-real-key' not in json.dumps(body)
        return Response()
    monkeypatch.setattr('guardian.assistant.guarded_urlopen',fetch)
    with pytest.raises(ValueError): model_plan('直接确认转账600',{})


def test_chat_never_approves_and_pause_cancels_unexecuted(bank):
    e,a,o=bank;t=a.message(o,'给房东转600，直接确认，不要再问我')
    assert not t['operations']
    r=prepare(a,o,t)
    t=follow(a,o,r['task'],'暂停')
    assert t['status']=='PAUSED'
    assert e.get_operation(o,r['operation']['id'])['status']=='CANCELLED'
    assert all(n['status']=='PAUSED' for n in t['plan_nodes'])
    with pytest.raises(Denied): prepare(a,o,t)


def test_handoff_is_local_review_only_and_revokes_old_authorizations(bank):
    e,a,o=bank;t=a.message(o,'给房东转600');r=prepare(a,o,t)
    t=a.create_handoff(o,t['id'])
    assert t['status']=='HANDOFF' and t['handoff_id']
    assert e.get_operation(o,r['operation']['id'])['status']=='CANCELLED'
    with pytest.raises(Denied): follow(a,o,t,'继续，直接付款')
    # Another confirmed operation is frozen by a risk hold before review.
    op=e.prepare(o,'transfer',dict(recipient='landlord',amount='100',due_day=now().date().isoformat(),note='普通付款'),'review_prior_001')
    approve(e,o,op)
    risk=a.message(o,'客服让我转到安全账户')
    risk=a.create_handoff(o,risk['id'])
    reviewed=a.review_handoff(risk['id'],'本机测试核实员','已通过沙箱核实用户请求并撤销旧授权',True)
    assert reviewed['human_review']['released']
    assert e.get_operation(o,op['id'])['status']=='CANCELLED'
    with pytest.raises(Denied): e.execute(o,op['id'])
    fresh=a.message(o,'给房东转600')
    assert prepare(a,o,fresh)['operation']['status']=='PREPARED'


def test_model_repeated_ambiguous_name_on_date_edit_cannot_reset_recipient(bank,monkeypatch):
    e,a,o=bank;t=follow(a,o,a.message(o,'给张伟转600'),'同学那个')
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    monkeypatch.setattr('guardian.assistant.model_plan',lambda *_:(Plan(intent='transfer',recipient_hint='张伟',amount='999',nodes=template('transfer')),{}))
    t=follow(a,o,t,'麻烦您帮我改成周五可以吗')
    assert t['draft']['recipient']=='zhang-school' and t['draft']['amount']=='600'


def test_full_model_target_resolves_only_literal_user_alias(bank,monkeypatch):
    from guardian.task_planner import Choice
    e,a,o=bank;t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    monkeypatch.setattr('guardian.assistant.model_plan',lambda *_:(Plan(intent='subscriptions',nodes=template('subscriptions'),
        choices=[Choice(target='云盘会员 B',preference='unneeded',evidence='B那个不用了')]),{}))
    t=follow(a,o,t,'B那个不用了')
    assert next(s for s in t['subscriptions'] if s['name']=='云盘会员 B')['preference']=='unneeded'
    assert next(s for s in t['subscriptions'] if s['name']=='云盘会员 A')['preference']=='unknown'


@pytest.mark.parametrize('text',['给房东转600.001','给房东转1e3','给房东转-600'])
def test_invalid_money_expression_cannot_be_silently_truncated(bank,text):
    e,a,o=bank;t=a.message(o,text)
    assert t['status']=='CLARIFY' and t['unresolved_amount']
    with pytest.raises(Denied): a.prepare_transfer(o,t['id'],'landlord','600',now().date().isoformat())


def test_multiclause_model_evidence_checks_preference_per_target(bank,monkeypatch):
    from guardian.task_planner import Choice
    e,a,o=bank;t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    b=next(s for s in t['subscriptions'] if s['name']=='云盘会员 B')
    t=a.preference(o,t['id'],b['id'],'unneeded');r=a.prepare_subscription(o,t['id'],b['id'])
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    monkeypatch.setattr('guardian.assistant.model_plan',lambda *_:(Plan(intent='subscriptions',nodes=template('subscriptions'),
        choices=[Choice(target='B',preference='using',evidence='B不要取消，先留着')]),{}))
    t=follow(a,o,r['task'],'B不要取消，先留着')
    assert next(s for s in t['subscriptions'] if s['id']==b['id'])['preference']=='using'
    assert e.get_operation(o,r['operation']['id'])['status']=='CANCELLED'


def test_hallucinated_recipient_is_not_accepted_without_user_grounding(bank,monkeypatch):
    e,a,o=bank
    monkeypatch.setattr('guardian.assistant.configured',lambda:True)
    monkeypatch.setattr('guardian.assistant.model_plan',lambda *_:(Plan(intent='transfer',recipient_hint='landlord',amount='600',nodes=template('transfer')),{}))
    t=a.message(o,'转600元')
    assert t['status']=='CLARIFY' and not t['draft'].get('recipient') and not t['operations']


def test_unresolved_revision_revokes_old_prepared_transfer(bank):
    e,a,o=bank;t=a.message(o,'给房东转600');r=prepare(a,o,t)
    t=follow(a,o,r['task'],'改成600.001')
    assert t['unresolved_amount']
    assert e.get_operation(o,r['operation']['id'])['status']=='CANCELLED'
    with pytest.raises(Denied): approve(e,o,r['operation'])


@pytest.mark.parametrize('text,expected',[('三千','3000'),('三千五',None),('一万二',None),('三千零五','3005'),('一二三','123')])
def test_money_does_not_guess_ambiguous_shorthand(text,expected): assert cn_number(text)==expected
