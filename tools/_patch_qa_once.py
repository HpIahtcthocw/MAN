# -*- coding: utf-8 -*-
"""一次性补丁：现场问答（生成源）补压力组改口径披露。用完即删。"""
import io

p = 'tools/build_submission.py'
s = io.open(p, encoding='utf-8').read()

anchor = """**为什么不用纯规则？**
同一冻结挑战规则正常任务11/12，系统12/12；额外作者口语集也保留对照。规则覆盖明确格式，模型补非模板表达。不是证明LLM在所有任务占优，也不把账务算法交给模型。
"""
qa = anchor + """
**压力组第一轮只有6/11，终轮11/11是因为改了判分标准吗？**
是新增了判分口径，并且证据文件里主动写明：product_stress 首轮失败永久保留（first-run/ 目录），final 的判定额外核对了收款人（EVIDENCE.json note：Final oracle additionally checks recipients for S01-S03. Inputs unchanged.）。第一轮的失败里有几笔实际是收款人错误，v1 口径没有判出来——属于第一版判分漏判，不是题目或输入变了（inputs unchanged，两轮题面可对比）。所以终轮 11/11 应读作“v2 口径下全过”，不应读作“模型从6分进步到满分”；我们也不引用 v1 口径下的终轮分数。
"""
assert anchor in s, 'anchor missing'
assert s.count(anchor) == 1
io.open(p, 'w', encoding='utf-8').write(s.replace(anchor, qa))
print('patched, new size lines:', s.count('\n') + 7)
