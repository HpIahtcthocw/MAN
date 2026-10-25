# -*- coding: utf-8 -*-
"""Publish only measured outcomes; keep first-run evidence and missing work."""
import json
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
def read(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
live=read('test-results/product-stress-v1/live-results.json')
rules=read('test-results/product-stress-v1/rules-results.json')
demo=read('test-results/product-stress-v1/final-demo.json')
assert live['source_hashes']==rules['source_hashes'] and demo['passed']
text='''
### 2026-10-20 产品任务修复与最终实录

停止扩展UI。新12条作者可见压力题首轮模型正常6/11、规则4/11，精度攻击均1/1，原始失败已保留。修复金额对比改口被忽略、无法校验时沿用旧金额、口语余额条件、餐饮续问、只停B、月度云盘统计及模糊开场无法续办。最终同输入正常模型11/11、规则8/11；前三题补强收款人断言，不能称评测JSON完全相同。最终两组代码指纹一致，非盲测。

最终原24条挑战模型12/12、规则11/12；攻击8/8、故障4/4均通过。后端150项回归通过。最终界面真实模型实录24项检查通过：同学消歧、周五预约、600改800、账单餐饮续问、代扣B撤销A保留、反诈暂停；仅一笔800元扣款与600元预约预留。新实录submission/video/xiaoman-final-2026-10-20.mp4，原始WebM同目录，无伪造响应。

结果是开发回归，盲写0条、真实银发0人、菜单效率未测；不能宣称获奖已被证明。PPTX、公开仓库、官方口径与正式提交仍未完成。详见submission/本轮产品改进与实测.md。

'''
heading='### 2026-10-20 产品任务修复与最终实录'
for p in (ROOT/'PROJECT_LOG.md',ROOT.parent.parent/'artifacts/fintech-hackathons-2026/current/CURRENT_PLAN.md'):
    s=p.read_text(encoding='utf-8')
    if heading not in s:
        title,rest=s.split('\n',1);p.write_text(title+'\n'+text+rest,encoding='utf-8')
p=ROOT/'README.md';s=p.read_text(encoding='utf-8')
note='> 最新产品进展：金额改口等实际办理缺陷已修复，150项回归通过；新表达模型11/11、规则8/11（开发回归，非盲测）。[任务证据与最终实录](submission/本轮产品改进与实测.md)。以下历史视口结果不是产品竞争力证明。\n\n'
if note not in s:
    title,rest=s.split('\n',1);p.write_text(title+'\n\n'+note+rest,encoding='utf-8')
p=ROOT/'submission/评审入口.md';s=p.read_text(encoding='utf-8')
notice='''## 最新任务证据与最终演示

2026-10-20：先阅读[本轮产品改进与实测](本轮产品改进与实测.md)，包含首轮失败与修复后对照，不能将旧12/12或界面检查当泛化证明。最终[演示MP4](video/xiaoman-final-2026-10-20.mp4)已经重录，24项浏览器/银行状态断言通过；实际模型调用与合成银行，没有伪造响应。150项回归通过；盲写与用户效率测量仍缺。

'''
if '## 最新任务证据与最终演示' not in s:
    title,rest=s.split('\n',1);p.write_text(title+'\n\n'+notice+rest,encoding='utf-8')
print('Product status and reviewer entry updated from measured evidence')
