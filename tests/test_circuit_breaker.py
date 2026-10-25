"""Consecutive refused executions trip the same breaker as OTP failures."""
import uuid
from datetime import timedelta

import pytest

from guardian.engine import Denied, Engine, now


def bank(tmp_path):
    e = Engine(tmp_path / 'breaker.sqlite3')
    return e, e.bootstrap()['owner']


def refused_operation(e, o):
    """A confirmed future-dated transfer: every dispatch is refused with NOT_DUE."""
    op = e.prepare(o, 'transfer', dict(recipient='landlord', amount='500',
        due_day=(now().date() + timedelta(days=1)).isoformat(), note='预约'), uuid.uuid4().hex)
    e.confirm(o, op['id'], op['binding'], True)
    return op


def test_third_refused_execution_locks_and_audits(tmp_path):
    e, o = bank(tmp_path)
    op = refused_operation(e, o)
    for _ in range(2):
        with pytest.raises(Denied) as err:
            e.execute(o, op['id'])
        assert err.value.code == 'NOT_DUE'
    with pytest.raises(Denied) as third:
        e.execute(o, op['id'])
    assert third.value.code == 'NOT_DUE'
    with pytest.raises(Denied, match='熔断'):
        e.execute(o, op['id'])
    events = [row['event'] for row in e.snapshot(o)['audit_rows']] if 'audit_rows' in e.snapshot(o) else []
    assert events or True  # audit presence asserted via fresh query below
    with e.tx() as c:
        tripped = c.execute("SELECT payload FROM audit WHERE owner=? AND event='CIRCUIT_BREAKER_TRIPPED'", (o,)).fetchall()
    assert tripped and 'NOT_DUE' in tripped[0][0]


def test_successful_dispatch_resets_the_counter(tmp_path):
    e, o = bank(tmp_path)
    future = refused_operation(e, o)
    today = e.prepare(o, 'transfer', dict(recipient='landlord', amount='300',
        due_day=now().date().isoformat(), note='房租'), uuid.uuid4().hex)
    e.confirm(o, today['id'], today['binding'], True)
    for _ in range(2):
        with pytest.raises(Denied):
            e.execute(o, future['id'])
    assert e.execute(o, today['id'])['status'] == 'SUCCEEDED'
    with pytest.raises(Denied):
        e.execute(o, future['id'])
    with pytest.raises(Denied):
        e.execute(o, future['id'])  # counter restarted, still below the threshold
    with e.tx() as c:
        row = c.execute('SELECT failures FROM locks WHERE owner=?', (o,)).fetchone()
    assert row['failures'] == 2
