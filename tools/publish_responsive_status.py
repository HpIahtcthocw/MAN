# -*- coding: utf-8 -*-
"""Publish measured responsiveness/recovery status; retain older dated results."""
import json
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
heading='### 2026-10-20 响应式与交互收尾'
entry='''
沿用原设计补齐响应式：14视口×11页面/弹窗，154/154检查通过；150%/200%强制字号压力18/18；网络故障/旧版本/键盘13/13；存储禁用、连点和意愿保存回滚额外检查通过。API前端5项Node测试、后端135项回归通过。修复窄屏强验证弹窗越界、长文本/按钮/日期/选项布局、导航不一致、无重连入口、非JSON/超时不确定结果和旧草稿提示；已完成转账不再开放准备入口，多项代扣只办一项显示部分完成。45秒请求超时不重试写入，只刷新状态；意愿保存失败回滚。

8770已加载最终版本，真实Qwen手机路径验证两项代扣分别确认后才DONE。源码包已独立解包复验135项与启动检查，旧视频仅是上一轮功能记录，最终界面以当前代码/截图为准。报告test-results/responsive/verification.md、matrix.json、font-stress.json、recovery.json、resilience.json；交付入口submission/响应式与交互验收.md。

这些是Chromium和模拟字号/视口检查，未实测物理iOS/Android键盘、Safari/WebKit或真实读屏/银发用户。没有把银行/MFA/坐席、未见任务、PPTX、公开仓库与正式提交算作响应式完成。相关外部条件仍按提交检查处理。

'''
for p in (ROOT/'PROJECT_LOG.md',ROOT.parent.parent/'artifacts/fintech-hackathons-2026/current/CURRENT_PLAN.md'):
    s=p.read_text(encoding='utf-8')
    if heading not in s:
        title,rest=s.split('\n',1);p.write_text(title+'\n\n'+heading+'\n'+entry+rest,encoding='utf-8')
readme=ROOT/'README.md';s=readme.read_text(encoding='utf-8')
notice='''> 2026-10-20 最新交互版本：135项后端回归与5项前端请求测试通过；14种视口154项响应式检查、18项字号压力、13项故障/键盘检查通过。新增弹窗内部滚动、安全区域、统一导航、连接重试、状态回查与部分完成显示。[本轮验收](submission/响应式与交互验收.md)。以下2026-10-19的133/109项为历史阶段结果。

'''
if notice not in s:
    title,rest=s.split('\n',1);readme.write_text(title+'\n\n'+notice+rest,encoding='utf-8')
p=ROOT/'submission/评审入口.md';s=p.read_text(encoding='utf-8').replace('工程回归133项','工程回归135项')
if '## 响应式最新验收' not in s:s+='\n## 响应式最新验收\n\n2026-10-20补充：154项布局、18项字号压力、13项故障/键盘通过，详见`响应式与交互验收.md`。135项后端测试与5项前端请求测试通过，不等于所有真机/浏览器已验收。\n'
p.write_text(s,encoding='utf-8')
(ROOT/'submission/响应式与交互验收.md').write_text((ROOT/'test-results/responsive/verification.md').read_text(encoding='utf-8'),encoding='utf-8')
print('Responsive handoff and canonical status updated')
