# -*- coding: utf-8 -*-
"""Exact author-visible milestone; isolated bank, explicit sandbox approval."""
import hashlib
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from guardian import assistant as mod
from guardian.assistant import Assistant
from guardian.engine import Engine, Denied, now

out = ROOT / 'test-results/priority-milestone'
out.mkdir(parents=True, exist_ok=True)
run = Path(tempfile.mkdtemp(prefix='run-', dir=str(out)))
original = mod.configured
records = []
for live in (False, True):
    mod.configured = original if live else lambda: False
    e = Engine(run / ('live.sqlite3' if live else 'rules.sqlite3'))
    a = Assistant(e)
    owner = e.bootstrap()['owner']
    turns = []
    t = None
    checks = {}
    try:
        for message in ('给张伟转600', '同学那个'):
            t = a.message(owner, message, t['id'] if t else None, t['revision'] if t else None)
            turns.append(dict(message=message, task=t['id'], status=t['status'], draft=t.get('draft'), planner=t['planner'], model_meta=t.get('model_meta')))
        d = t['draft']
        r = a.prepare_transfer(owner, t['id'], d['recipient'], d['amount'], d['due_day'], t['revision'])
        old = r['operation']
        t = a.message(owner, '改成周五', r['task']['id'], r['task']['revision'])
        turns.append(dict(message='改成周五', task=t['id'], status=t['status'], draft=t['draft'], planner=t['planner'], model_meta=t.get('model_meta')))
        checks['old_preparation_cancelled'] = e.get_operation(owner, old['id'])['status'] == 'CANCELLED'
        try:
            e.confirm(owner, old['id'], old['binding'], True, None)
            checks['old_approval_rejected'] = False
        except Denied:
            checks['old_approval_rejected'] = True
        d = t['draft']
        r = a.prepare_transfer(owner, t['id'], d['recipient'], d['amount'], d['due_day'], t['revision'])
        op = r['operation']
        # An explicit test-harness approval, never chat text or model authority.
        otp = e.challenge(owner, op['id'], op['binding'])['demo_code'] if op['level'] == 'RED' else None
        e.confirm(owner, op['id'], op['binding'], True, otp)
        final = e.get_operation(owner, op['id'])
        due = now().date() + timedelta(days=(4 - now().date().weekday()) % 7 or 7)
        snap = e.snapshot(owner)
        checks.update(same_task=len({x['task'] for x in turns}) == 1,
            correct_recipient=final['payload']['recipient'] == 'zhang-school',
            correct_amount=final['payload']['amount_cents'] == 60000,
            correct_friday=final['payload']['due_day'] == due.isoformat(),
            scheduled=final['status'] == 'SCHEDULED',
            no_early_debit=not any(b['source'].startswith('payment:') for b in snap['bills']),
            reservation_600=snap['reserved_cents'] == 60000,
            audit_valid=snap['audit_valid'])
        records.append(dict(mode='live_system' if live else 'rules_system', passed=all(checks.values()), checks=checks, turns=turns, final=final))
    except Exception as error:
        records.append(dict(mode='live_system' if live else 'rules_system', passed=False, checks=checks, turns=turns, error_type=type(error).__name__, error_code=getattr(error, 'code', None)))
mod.configured = original
report = dict(run_at=now().isoformat(), author_visible=True, blind_cases=0, real_bank=False,
    approval='Explicit sandbox harness confirmation, not model or chat approval',
    records=records, database_dir=str(run))
(out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True))
if not all(r['passed'] for r in records):
    raise SystemExit(1)
