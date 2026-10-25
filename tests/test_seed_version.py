"""Returning browsers with pre-update accounts must get a freshly seeded owner."""
from guardian.engine import Engine


def test_stale_owner_session_is_retired(tmp_path):
    e = Engine(tmp_path / 'seedv.sqlite3')
    state = e.bootstrap()
    fresh = e.session(state['token'])
    assert fresh['owner'] == state['owner']
    with e.tx() as c:
        c.execute("DELETE FROM ledger WHERE owner=? AND source=?", (state['owner'], e.SEED_VERSION))
    try:
        e.session(state['token'])
        raise AssertionError('stale owner session must be denied')
    except Exception as error:
        assert getattr(error, 'code', '') == 'SESSION'
    new_state = e.bootstrap()
    assert new_state['owner'] != state['owner']
    assert e.session(new_state['token'])['owner'] == new_state['owner']
