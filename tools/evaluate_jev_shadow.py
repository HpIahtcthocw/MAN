"""Author-visible intent experiment; does not create accounts or execute tools."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent;sys.path.insert(0,str(ROOT))
from guardian.jev_shadow import configured,classify
from guardian.engine import now

cases=[('给房东转600','transfer'),('帮我约到周五再转五百元','transfer'),
    ('9月花了多少，云盘不算','bills'),('去年九月餐饮花了多少','bills'),
    ('这几个月一直在扣的钱，帮我看看','subscriptions'),('视频会员我不用了，别续费','subscriptions'),
    ('什么是安全账户骗局，转账时要注意什么','safety_info'),('如何识别索取验证码的诈骗','safety_info'),
    ('帮我弄一下','clarify'),('那个钱处理了吗','clarify'),('帮我写一首诗','unsupported'),('我要申请房贷','unsupported')]
report={'run_at':now().isoformat(),'author_visible':True,'blind':False,'shadow_only':True,
    'configured':configured(),'records':[],'metric_note':'Intent-only correctness, not banking task completion. Confidence is not measured Chinese accuracy.'}
if not configured():report.update(status='NOT_RUN_MISSING_CREDENTIAL',requests=0)
else:
    for text,expected in cases:
        try:
            result=classify(text);report['records'].append({'input':text,'expected':expected,'result':result,'correct':result['intent']==expected})
        except Exception as error:
            # Never write provider error bodies, headers or secret-bearing objects.
            report['records'].append({'input':text,'expected':expected,'error_type':type(error).__name__,'correct':False})
    report.update(status='RAN',requests=len(cases),correct=sum(r['correct'] for r in report['records']))
out=ROOT/'test-results/completion-round/jev-shadow.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='records'}))
