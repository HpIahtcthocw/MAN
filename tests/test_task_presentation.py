from guardian.assistant import Assistant
from guardian.engine import Engine


def test_multiple_cancellations_are_not_done_after_only_one(tmp_path):
    e=Engine(tmp_path/'presentation.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    first,second=t['subscriptions'][:2]
    a.preference(o,t['id'],first['id'],'unneeded')
    a.preference(o,t['id'],second['id'],'unneeded')
    op=a.prepare_subscription(o,t['id'],first['id'])['operation']
    e.confirm(o,op['id'],op['binding'],True);e.execute(o,op['id'])
    t=a.get(o,t['id'])
    assert t['status']=='REVIEW' and '还有 1 项' in t['text']
    assert next(n for n in t['plan_nodes'] if n['tool']=='prepare_subscription')['status']=='WAITING'
    op=a.prepare_subscription(o,t['id'],second['id'])['operation']
    e.confirm(o,op['id'],op['binding'],True);e.execute(o,op['id'])
    assert a.get(o,t['id'])['status']=='DONE'


def test_expired_protocol_query_is_marked_but_does_not_refresh(tmp_path):
    e=Engine(tmp_path/'expiry.sqlite3');a=Assistant(e);o=e.bootstrap()['owner']
    t=a.reveal(o,a.message(o,'查询代扣')['id'],True)
    with e.tx() as c:
        _,d=a.row(c,o,t['id']);d['consent_at']=1;a.update(c,t['id'],d)
    expired=a.get(o,t['id'])
    assert expired['consent_expired']
    assert next(n for n in expired['plan_nodes'] if n['tool']=='read_subscriptions')['status']=='WAITING'
    assert not a.reveal(o,t['id'],True)['consent_expired']
