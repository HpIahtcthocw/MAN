"""Synthetic-only transport probe. Never log request headers or local config."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
sys.path.insert(0,str(ROOT))
from guardian import assistant as mod
from guardian.engine import Engine
original=mod.guarded_urlopen
captured=[]
class Response:
    def __init__(self,data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def read(self,_): return self.data
def fetch(request,timeout):
    with original(request,timeout) as r: data=r.read(200000)
    response=json.loads(data)
    captured.append(response['choices'][0]['message']['content'])
    return Response(data)
mod.guarded_urlopen=fetch
for message in ['查询代扣','这几个月一直在扣的钱，帮我看看。']:
    try:
        plan,meta=mod.model_plan(message,{'kind':None,'draft':{},'contacts':Engine.contacts(None),'turns':[],'subscriptions':[]})
        print(json.dumps({'ok':True,'plan':plan.model_dump(),'meta':meta},ensure_ascii=True))
    except Exception as err:
        print(json.dumps({'ok':False,'category':type(err).__name__,'reason':str(err) if isinstance(err,ValueError) else 'transport','synthetic_response':captured[-1] if captured else None},ensure_ascii=True))
