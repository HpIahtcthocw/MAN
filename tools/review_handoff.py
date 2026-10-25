"""Sandbox operator only. No HTTP endpoint and no model tool calls this script."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.assistant import Assistant

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--database',default=str(ROOT/'data/guardian.sqlite3'))
p.add_argument('--task',required=True)
p.add_argument('--reviewer')
p.add_argument('--reason')
p.add_argument('--release',action='store_true',help='Revoke pending transfer approvals and release sandbox hold after review')
args=p.parse_args()
e=Engine(args.database);a=Assistant(e)
if args.reviewer and args.reason:
    task=a.review_handoff(args.task,args.reviewer,args.reason,args.release)
else:
    with e.tx() as c:
        row=c.execute('SELECT owner FROM assistant_tasks WHERE id=?',(args.task,)).fetchone()
    if not row: raise SystemExit('Task not found')
    task=a.get(row['owner'],args.task)
print(json.dumps(task,ensure_ascii=True,indent=2))
