# -*- coding: utf-8 -*-
"""一次性补丁：盲写李集暴露的5处确定性缺口。幂等，用完即删。"""
import io

# ── 1) fraud.py：补 4 类话术
p = 'guardian/fraud.py'
s = io.open(p, encoding='utf-8').read()
if '念给' not in s:
    old = "    if re.search(r'验证码|银行卡密码|支付密码|查询密码|取款密码', text) and re.search(r'告诉|发给|提供给|给客服|交给|发给我|发给他|发给她', text):"
    new = ("    if re.search(r'验证码|银行卡密码|支付密码|查询密码|取款密码|六位数字|六位数', text) "
           "and re.search(r'告诉|发给|提供给|给客服|交给|发给我|发给他|发给她|念给|读给|报给|念一下|读一下', text):")
    assert old in s, 'fraud anchor 1'
    s = s.replace(old, new)
if '验一验' not in s:
    old2 = "    if re.search(r'快递|包裹|电商|商家', text)"
    new2 = ("    if re.search(r'验一验|验资|资金验证|安全验证', text) and re.search(r'新户头|新账户|转到|转入|另一张卡', text):\n"
            "        signals.append('冒充客服要求“验资”把钱转到所谓新账户')\n"
            "    if re.search(r'出事|车祸|住院|急救|急用|急需', text) and re.search(r'别告诉|不要告诉|保密|别声张|先别声张', text) and re.search(r'转|汇|打', text):\n"
            "        signals.append('冒充熟人急事借钱并要求保密，请当面或回拨常用号码核实')\n"
            "    if re.search(r'医保|社保|补贴|补助|养老金发放', text) and re.search(r'停|冻结|失效|作废|过期', text) and re.search(r'转|打|汇', text) and re.search(r'今天|下午|小时|马上|立即|赶紧|之前|以前', text):\n"
            "        signals.append('冒充机构称待遇即将停用，限时催转到指定账户')\n"
            "    if re.search(r'快递|包裹|电商|商家', text)")
    assert old2 in s, 'fraud anchor 2'
    s = s.replace(old2, new2, 1)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('fraud ok')

# ── 2) task_runtime.py
p = 'guardian/task_runtime.py'
s = io.open(p, encoding='utf-8').read()
if '出去没有' not in s:
    old3 = "        if old and kind=='transfer' and re.search(r'转了|转出去|到账|结果|成功|扣了',message):"
    new3 = "        if old and kind=='transfer' and re.search(r'转了|转出去|到账|结果|成功|扣了|出去没有|再转|没动静|失败了',message):"
    assert old3 in s, 'runtime anchor 1'
    s = s.replace(old3, new3)

line_a = "            elif configured():"
line_b = "                plan,meta=model_plan(message,context);mode='llm'"
line_c = "            else: plan=self.rule_plan(message,context)"
anchor4 = line_a + "\n" + line_b + "\n" + line_c
if 'deterministic_briefing' not in s:
    add4 = ("            elif not old and re.search(r'养老金|叮咛|快到期|这两天要交',message):\n"
            "                from guardian.briefing import build as _briefing\n"
            "                _b=_briefing(self.engine,owner)\n"
            "                _text=_b.get('spoken') or '；'.join(i['text'] for i in _b['items'])\n"
            "                return self.save(owner,'bills',dict(message=message,initial_message=message,revision=1,\n"
            "                    turns=[{'role':'user','text':message}],status='DONE',planner='deterministic_briefing',\n"
            "                    text=_text,operation_ids=[],plan=[n.model_dump() for n in template('bills')],\n"
            "                    steps=[{'label':'汇总账户当前事实','status':'DONE'}]))\n"
            "            elif not old and re.search(r'买.{0,8}(?:理财|基金|股票)|利息高.{0,8}(?:来点|买|理)',message):\n"
            "                return self.save(owner,'clarify',dict(message=message,initial_message=message,revision=1,\n"
            "                    turns=[{'role':'user','text':message}],status='DONE',planner='deterministic_boundary',\n"
            "                    text='买理财这类投资它办不了，也不会替你估收益。请到银行柜台或银行官方App咨询，别信“利息高”的来路不明推荐。',\n"
            "                    operation_ids=[],plan=[n.model_dump() for n in template('safety_info')],\n"
            "                    steps=[{'label':'说明能力边界','status':'DONE'}]))\n"
            "            elif not old and re.search(r'退.{0,12}(?:回来|回|款)',message) and re.search(r'别的银行|其他银行|他行|连.{0,6}卡',message):\n"
            "                return self.save(owner,'clarify',dict(message=message,initial_message=message,revision=1,\n"
            "                    turns=[{'role':'user','text':message}],status='DONE',planner='deterministic_boundary',\n"
            "                    text='已经扣掉的钱它退不了：撤销银行代扣不等于退款，退款要找商户或官方客服。别的银行的卡也连不上，它只办理本行授权的账户。本账户的自动扣费可以帮你逐项整理。',\n"
            "                    operation_ids=[],plan=[n.model_dump() for n in template('safety_info')],\n"
            "                    steps=[{'label':'说明能力边界','status':'DONE'}]))\n"
            + anchor4)
    assert anchor4 in s, 'runtime anchor 2'
    s = s.replace(anchor4, add4)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('runtime ok')
