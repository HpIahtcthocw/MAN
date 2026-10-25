"""Transfer notes (chat-parsed and API) and phone-number recipient resolution."""
from guardian.assistant import Assistant
from guardian.engine import Engine, now
from guardian.language import contact_hint


def task(tmp_path):
    e = Engine(tmp_path / 'note-phone.sqlite3')
    a = Assistant(e)
    return e, a, e.bootstrap()['owner']


def test_note_parsed_from_chat_binds_into_operation(tmp_path):
    e, a, o = task(tmp_path)
    t = a.message(o, '给房东转600，备注房租')
    assert t['draft'].get('user_note') == '房租'
    result = a.prepare_transfer(o, t['id'], t['draft']['recipient'], t['draft']['amount'], t['draft']['due_day'], t['revision'])
    assert result['operation']['payload']['note'] == '房租'


def test_api_note_overrides_and_removal_falls_back_to_message(tmp_path):
    e, a, o = task(tmp_path)
    t = a.message(o, '给房东转600，备注房租')
    d = t['draft']
    result = a.prepare_transfer(o, t['id'], d['recipient'], d['amount'], d['due_day'], t['revision'], '十一月房租')
    assert result['operation']['payload']['note'] == '十一月房租'
    cleared = a.message(o, '去掉备注', t['id'], result['task']['revision'])
    assert 'user_note' not in cleared['draft']
    d = cleared['draft']
    fallback = a.prepare_transfer(o, cleared['id'], d['recipient'], d['amount'], d['due_day'], cleared['revision'])
    assert fallback['operation']['payload']['note'] == '给房东转600，备注房租'


def test_note_change_creates_new_operation_binding(tmp_path):
    e, a, o = task(tmp_path)
    t = a.message(o, '给房东转600，备注房租')
    d = t['draft']
    first = a.prepare_transfer(o, t['id'], d['recipient'], d['amount'], d['due_day'], t['revision'])
    e.cancel(o, first['operation']['id'])
    second = a.prepare_transfer(o, t['id'], d['recipient'], d['amount'], d['due_day'], first['task']['revision'], '押金')
    assert second['operation']['payload']['note'] == '押金'


def test_full_phone_number_resolves_recipient(tmp_path):
    e, a, o = task(tmp_path)
    assert contact_hint('给13800008026转600', e.contacts()) == 'landlord'
    t = a.message(o, '给13700006739转600')
    assert t['draft'].get('recipient') == 'zhang-school'
    assert t['draft'].get('amount') == '600'


def test_phone_tail_and_unknown_phone(tmp_path):
    e, a, o = task(tmp_path)
    assert contact_hint('手机尾号1218那位', e.contacts()) == 'zhang-work'
    t = a.message(o, '给13500000000转600')
    assert t['draft'].get('recipient') is None and t.get('candidates')
