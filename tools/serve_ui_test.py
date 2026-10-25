"""Isolated deterministic bank for repeatable UI checks; not the user's preview."""
import sys
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
sys.path.insert(0,str(ROOT))
from guardian.app import create_app
import uvicorn
if __name__=='__main__':
    from guardian import assistant
    assistant.configured=lambda:False
    uvicorn.run(create_app(ROOT/'test-results/responsive/ui-bank.sqlite3'),host='127.0.0.1',port=8772)
