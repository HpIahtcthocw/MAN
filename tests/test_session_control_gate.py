"""Bare pause/resume utterances skip the model without changing task semantics."""
import re

from guardian.engine import Engine
from guardian.assistant import Assistant
from guardian.task_runtime import PURE_SESSION_CONTROL


def new_task(a, o):
    t = a.message(o, '给房东转600')
    return t


def test_gate_matches_bare_control_and_rejects_slotted_text():
    match = lambda s: bool(re.fullmatch(PURE_SESSION_CONTROL, s.strip()))
    for text in ('先别转了', '先别办了', '先暂停', '暂停办理', '等等', '请继续办理', '继续', '恢复这项任务'):
        assert match(text), text
    for text in ('先别转B了', '先别停云盘', '改成周五', '继续转700，至少留3000', '别动那个600的'):
        assert not match(text), text


def test_bare_pause_and_resume_use_deterministic_path(tmp_path):
    e = Engine(tmp_path / 'gate.sqlite3')
    a = Assistant(e)
    o = e.bootstrap()['owner']
    t = new_task(a, o)
    paused = a.message(o, '先别转了', t['id'], t['revision'])
    assert paused['status'] == 'PAUSED'
    assert paused['planner'] == 'deterministic_session_control'
    assert paused['model_meta']['model_called'] is False
    assert paused['draft'].get('amount') == '600'
    resumed = a.message(o, '继续办理', paused['id'], paused['revision'])
    assert resumed['status'] == 'READY'
    assert resumed['planner'] == 'deterministic_session_control'
    assert resumed['draft'].get('amount') == '600'
