"""Publish verified local implementation status, preserving prior dated claims."""
import json,shutil,statistics
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
out=ROOT/'test-results/agent-completion'
live=json.loads((ROOT/'test-results/task-baseline-2026-10-19/live-results.json').read_text(encoding='utf-8'))
para=json.loads((out/'paraphrases.json').read_text(encoding='utf-8'))
archive=ROOT/'docs/archive/2026-10-19-before-agent-completion'
archive.mkdir(parents=True,exist_ok=True)
for name in ('README.md','SECURITY.md'):
    if not (archive/name).exists(): shutil.copyfile(ROOT/name,archive/name)

readme='''# 小满 · 银发银行办事助手

在同一个任务里说清需求、核对对象与条件、确认办理，并回查银行状态。当前是独立可运行的**银行沙箱原型**；没有接真实银行卡，不操作真实资金。

## 当前三类业务

- **智能转账**：同名消歧、多轮补充/改口、今日或未来30天预约、指定付款后最低余额。对象、金额、日期或余额条件变化，旧草稿失效；已确认/付款/未知操作不能被改口覆盖。
- **账单分析**：本账户流水分类、本月/上月/上上月及跨月比较，金额由整数账本计算，保留原始记录。无需用户导入账单即可演示；实际银行数据接口尚未获得。
- **订阅/代扣整理**：先同意查询银行协议，保留扣费依据，再由用户说明是否需要；支持“B不用了，A还在用”及改口。每个撤销单独确认、执行后回读。没有应用使用数据，不能判断实际使用频率；撤销银行代扣不等于终止商户合同或退款。

反诈贯穿三类业务，不独立凑题面场景。配置的话术规则可持久暂停转账；教育性引用有窄范围的只读解释分支。未命中不代表安全，普通“继续”不能解除风险暂停。

## Agent与安全边界

实际接通 `qwen3.8-flash`，服务器HTTPS兼容接口的配置按用户授权从geo项目读取，密钥保存在被忽略的 `data/model.local.json`，不进前端或日志。geo原文件未修改。环境变量 `GUARDIAN_LLM_BASE_URL`、`GUARDIAN_LLM_API_KEY`、`GUARDIAN_LLM_MODEL` 可覆盖本机文件。

模型输出严格类型计划，固定工具、最多5节点，依赖校验后由后端解释；不是任意工具或通用DAG框架。只读自动进行，协议查询需同意，所有写入需明确确认，红色操作另需操作绑定的**演示验证码**。模型不掌握批准、签名、执行或解除暂停权限；无任意代码执行。

任务按账户、task_id、revision持久化。刷新恢复当前任务，20轮上限；失效版本被拒。余额条件在准备、确认和落账前重复校验，其他已预约付款的预留与底线一起计入。UNKNOWN只能查原交易，不自动重付。

人工接管可保存本机任务资料和编号。无银行坐席接入；只有具备本机文件权限的沙箱操作员可用 `tools/review_handoff.py` 记录核实。解除前要求先解决UNKNOWN，撤销旧转账批准，重新办理须新建任务并重新确认。这不是生产身份核验服务。

## 已验证结果（2026-10-19）

- 109项离线工程回归通过：`test-results/agent-completion/offline.xml`。测试隔离本机凭据，不意外调用付费模型。
- 作者可见12条开发任务：真实模型版12/12、规则版12/12，通过各条声明的状态/字段断言。真实模型13次返回均通过结构/依赖校验；不能据此证明优于规则或称盲测成绩。
- 额外10条作者编写口语/攻击输入：规则8/10、模型10/10。此处评的是意图/字段及无未授权写入，**不是10条业务全部端到端付款**；金额按整数分比较。小样本不代表泛化准确率。
- 实际Chromium手机视口完成四条完整路径：多轮预约及刷新恢复、代扣改口后旧草稿失效再单项撤销、反诈解释/暂停与接管、付款响应丢失后刷新回查仅扣一次。截图与记录见 `test-results/xiaoman-browser/agent-completion.json`。
- 生产前端构建通过。详细证据与限制见 [验收记录](docs/AGENT_COMPLETION_2026-10-19.md) 与 [安全自评](SECURITY.md)。

这些结果不等于官方评测、真实银发用户试用、生产可用或获奖证明。

## 启动和复验

推荐Python3.9–3.12，在本目录执行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
npm run build
.venv/Scripts/python.exe run.py
```

打开 http://127.0.0.1:8770/ 。无模型配置时明确显示规则模式。首访创建合成账户，会话24小时；数据库默认 `data/guardian.sqlite3`，可用 `GUARDIAN_DB` 指定。

```powershell
.venv/Scripts/python.exe -m pytest -q tests
.venv/Scripts/python.exe tools/evaluate_task_baseline.py
.venv/Scripts/python.exe tools/evaluate_task_baseline.py --live
.venv/Scripts/python.exe tools/evaluate_paraphrases.py
```

后两项会调用本机已配置的模型、产生API用量，输入均为合成账户任务。所有评测集明确为作者可见，不能改称盲测。请勿把data目录发布出去。

本轮实际使用现有 `E:/gitproject/hackathon/agent-hack/personal-investment-os/.venv/Scripts/python.exe`，没有修改geo或原资产依赖；全新环境安装未另行复验。

## 实现与复用

`guardian/task_planner.py`：类型计划、白名单和依赖合同；`task_runtime.py`：同任务多轮、证据核对、修订/暂停/接管；`assistant.py`：真实模型适配、账单汇总和业务入口；`engine.py`：资金、授权、预留、幂等、预约、回查及审计的最终权威。`frontend/src/Xiaoman.jsx`沿用已审阅设计，使用React、Radix Themes与Lucide，构建至`web/dist`，FastAPI同源提供。

借鉴现有Personal Investment OS的门禁、审计和恢复设计，Capability POC的白名单能力思路；本目录未复制开放执行器、炒股辩论或x402资金通道。`guardian/core`的金额和绑定组件可复用。没有为六个比赛另建六套项目，海外平台API尚未接入。

旧预算界面源码与历史结果保留，但不是正常入口。之前README、安全说明已备份至 `docs/archive/2026-10-19-before-agent-completion/`；研究与当前主线见 `E:/gitproject/artifacts/fintech-hackathons-2026/current/CURRENT_PLAN.md`。
'''
(ROOT/'README.md').write_text(readme,encoding='utf-8')

security='''# 小满安全自评 · 2026-10-19

## 实现与信任边界

1. **模型只提案。** HTTPS兼容服务、禁重定向；不提供凭据或任意工具/代码执行能力。严格schema、额外字段拒绝、最多5节点、白名单顺序及依赖验证。错误/超时明确降级，不伪称LLM完成。
2. **模型上下文最小化。** 当前用户请求、最多6轮用户补充、当前草稿和候选联系人；有查询同意的任务可提供协议名称/状态/用户意愿。不会发送本机密钥、OTP、完整snapshot或银行商户备注。这里仍含金融个人信息的潜在处理路径，生产必须落实用户授权、合规及模型服务约定。
3. **不编造执行结果。** 金额/月份计算来自整数账本；模型不能声明付款成功。任务状态从engine操作和provider回执回读，关键执行参数与约束保留审计记录。
4. **分级权限。** 纯余额/流水/分析自动读取；代扣查询先同意，10分钟有效；取消代扣逐项明确确认。转账同执行日已确认/预约/未知/成功累计≤1000黄色，>1000红色强验证。红色当前为操作绑定的一次性演示码，非真实MFA。
5. **批准绑定与任务版本。** 绑定账户、类型及全部清洗参数。自然语言补充task_id/revision，异步模型返回后再次核对版本。对象/金额/日期/底线变化撤销旧PREPARED及挑战；已确认/预约/未知/成功不能被改口覆盖。待确认10分钟过期；验证码2分钟、一次性，连续失败3次锁5分钟。
6. **余额与并发。** 金额最多两位小数，整数分；拒绝负数、科学计数及小数分。明确最低余额在准备/确认/provider落账前再查，连同其他待付预留底线计算。SQLite写事务串行；同任务并发准备去重；CSV分析证据不增加资金。
7. **可恢复执行。** 执行前持久UNKNOWN，银行沙箱独立事务落账和收据；执行租约30秒，UNKNOWN只回查原操作，不能以重付解决超时。已接收后响应丢失的浏览器路径验证仅一笔扣款。预约每2秒扫描；错过执行日不自动补付。
8. **有限反诈门禁。** 安全账户、屏幕共享操作账户、索要验证凭证、先付费退款/解冻规则触发持久hold，在prepare/confirm/execute/落账检查。教育性引用只走只读解释，不能清已有hold；引用外的付款意图仍阻断。不是全场景反诈模型，未命中不是安全证明。
9. **订阅证据与否定。** 扣费不等于未使用。用户选择须引用原话，并在同一子句内核对对象与肯定/否定，不能把A保留和B停用串起来。对象未明确时撤销旧草稿并追问。新意愿改口撤销旧PREPARED；完成撤销不能靠聊天恢复商户协议。
10. **人工接管。** 本机资料编号与状态持久化，聊天不能解除HANDOFF。沙箱操作员通过CLI复核；release要求无UNKNOWN，撤销所有旧待付转账批准后再解除hold，必须新建任务重新确认。CLI没有HTTP或模型入口，本机文件权限是当前操作员边界，不是银行正式审核系统。
11. **Web边界。** 仅监听127.0.0.1，Host/Origin/跨站检查，写入CSRF，会话cookie HttpOnly/SameSite Strict。静态只暴露构建assets，data/.env/源码不挂载；CSP脚本同源、不允许eval，Radix动态样式允许inline CSS。会话为合成账户隔离，不是客户实名鉴权。
12. **审计。** 关键操作、计划/修订、约束决策、确认/失败、回执、接管/核实进入哈希链；无模型私有思维链。没有外部锚定/签名或防截断存储，不能声称管理员不可重写整个库。

## 已知风险与不可宣称事项

- 所有银行账户和资金为合成；单币种单账户，不是双重记账核心系统。真实银行API、生产客户身份、短信/生物验证、银行人工坐席未接入。
- 模型可能误解、超时或给出合法但错误的结构。白名单和批准阻止直接写入，不证明任何口语都正确理解。当前主要日期为今天/明天/后天/周几、30天内；账单主要本/上/上上月与现有流水；新表达仍需扩展独立任务验证。
- 模拟银行与应用共用SQLite。真实provider存在最终一致性，不能照搬沙箱NOT_FOUND可重新确认语义。
- 本地HTTP演示，不具备生产TLS、身份生命周期、会话撤销后台、全局容量限制或设备校验。
- 银行协议撤销不能保证商户不通过别的协议再扣、不代表合同终止或退款。周期线索不代表重复消费或已验证节省。
- 没有任意代码生成功能，因此不声称已经实现通用生成代码沙箱。若比赛要求必做该能力，须另行澄清或补独立隔离实现。
- 普通聊天触发暂停可以导致拒绝服务；有限规则误报/漏报尚未在代表性人群/诈骗样本上验证。真实模型请求含用户业务语句，上线需按实际数据和法律条件重新评估。

## 证据

109项离线回归：`test-results/agent-completion/offline.xml`。模型开发任务12/12（13次结构合法返回）、额外口语/攻击10/10，仅为作者可见小样本；同一规则对照分别12/12和8/10。四条浏览器纵向路径见 `test-results/xiaoman-browser/agent-completion.json`。无第三方审计、官方成绩、银发用户研究或生产安全认证。
'''
(ROOT/'SECURITY.md').write_text(security,encoding='utf-8')

browser=dict(date='2026-10-19',environment='real Chromium, 430x950, synthetic bank, live qwen3.8-flash',
    method='Tool-orchestrated Playwright assertions; browser traces also recorded in Codex tool calls',
    journeys=[
      dict(name='多轮预约',passed=True,same_task=True,refresh_restored=True,recipient='zhang-school',amount_cents=60000,minimum_balance_cents=300000,status='SCHEDULED',screenshot='live-multiturn.png'),
      dict(name='代扣改口再办理',passed=True,A='using',old_draft='CANCELLED',bank_cancelled_count=1,screenshot='live-subscription.png'),
      dict(name='反诈解释与接管',passed=True,quote_kind='safety_info',held_status='HANDOFF',ticket_persisted=True,operations=0,screenshot='live-handoff.png'),
      dict(name='响应丢失后回查',passed=True,execute_requests=1,payment_rows=1,payment_amount_cents=-60000,balance_cents=915900,refresh_restored=True,screenshot='live-recovery.png')],
    limitations=['Synthetic bank receipts only','No real MFA, bank seat or microphone trial','Not a blind usability study'])
(ROOT/'test-results/xiaoman-browser/agent-completion.json').write_text(json.dumps(browser,ensure_ascii=False,indent=2),encoding='utf-8')

report='''# Agent闭环验收记录 · 2026-10-19

本轮完成真实模型、多轮办理、余额条件、受限计划与恢复验证。可运行开发版本不等于最终比赛提交就绪；真实银行环境口径、材料及用户验证仍需独立完成。

## 实现

- 接口配置按用户授权复用geo的DASHSCOPE兼容服务，实际模型qwen3.8-flash；本机私有data配置，不展示或提交密钥。
- 固定三类：转账、账单分析、订阅代扣。反诈为横切能力，不能自行当作官方第三类。
- 计划严格类型、最多5节点、依赖和工具白名单；后端解释固定业务链，不提供自由代码执行。模型不掌握写入批准权。
- 同任务20轮内保留指代/金额/日期/最低余额，task_id+revision并发校验；修改使旧草稿失效。确认/付款/未知状态须先核查或撤销，不能覆盖。
- 用户最低余额在准备、确认、落账三处结合真实账本与预留校验；不明确金额、币种或不支持表达要追问。科学计数/负数/小数分不得截断成付款。
- 代扣查询确认、原始扣费证据、用户原话逐子句匹配、保留/停用改口、每协议单项确认和结果回读。
- 教育性反诈引用不锁新账户、不清旧hold；真实风险持久暂停；接管资料和本机操作员复核有审计。没有银行人工坐席。
- UI沿用原审阅设计，仅补同任务输入、计划/权限、约束预览及接管入口，非另一版整体设计。

## 验收结果与解释

1. **109项离线回归通过**，保留XML。单元测试隔离模型配置，覆盖原资金执行、安全、导入、预约、故障恢复，及多轮修订、过期版本、模型字段幻觉、节点篡改、负数/小数分、否定子句与本机审核。
2. **12条作者可见开发任务**：真实模型和规则各12/12，通过每条声明的字段和最终状态断言。真实模型13次结构/依赖全部合法，最终运行无降级；中位模型请求约7.45秒。该组已经用于开发，不能称盲测或用来证明模型提升。
3. **额外10条作者编写口语/攻击输入**：规则8/10、模型10/10。这里评的是意图/字段及无未授权写入，不是付款任务完成率。规则未理解两条倒装口语，模型给出正确收款人和600元。最初评分脚本把“600.00”和“600”误判不同，已改用整数分；原推理输出与更正前报告保留。无重新推理或手工修改模型输出。
4. **四条实际浏览器路径通过**：多轮消歧→改日期→刷新→确认预约；代扣B停用→改口保留→旧批准失效→重新选择并仅撤销B；教育性引用→实际诱导暂停→保存接管→刷新；付款已接收但响应丢失→UNKNOWN→刷新回查→一笔扣款。
5. **前端生产构建通过**；模型和银行数据仍然走服务端，data路径不可通过Web读取。

## 本轮发现并修复的问题

- 模型在仅改日期时重复输出“张伟”，会覆盖已消歧对象：字段修改必须有本轮原话依据，日期修改不动对象/金额。
- 模型把代扣查询当成仅两个节点：提示明确“完整计划含等待节点”，保持校验严格，不以自动补齐掩盖非法输出。
- 模型返回完整产品名但用户只说B：仅在已同意查询的唯一协议中，以原话独立A/B别名消歧。
- 模型把“B不要取消，先留着”整句作为证据：目标和肯否定必须在同一子句核对；未明确的修订也要使旧草稿失效。
- 类型版本与并发幂等相互干扰：UI显式版本检查保留；无版本的同绑定幂等重试仍原子去重，不能制造第二笔。
- 待执行节点曾因前序未完成而显示绿色：权限级别独立于节点是否已执行，不把待办写入标成只读。

## 可复查文件

- `test-results/agent-completion/offline.xml`
- `test-results/task-baseline-2026-10-19/live-results.json`
- `test-results/task-baseline-2026-10-19/completed-rule-results.json`
- `test-results/agent-completion/paraphrases.json`
- `test-results/agent-completion/paraphrases-before-scoring-correction.json`
- `test-results/xiaoman-browser/agent-completion.json`及四张live-*.png
- 任务runner创建的独立SQLite证据保留在各结果里的database_dir，不是线上账户。

## 本机人工核实

普通用户只能保存资料，不能解除暂停。本机操作员有数据库文件权限，以下仅为沙箱审核工具：

```powershell
python tools/review_handoff.py --task TASK_ID
python tools/review_handoff.py --task TASK_ID --reviewer 核实员 --reason 已通过独立渠道核对并撤销旧转账批准 --release
```

release遇UNKNOWN先拒绝，要求先核实回执；记录理由和审核人，取消旧待付款批准，再解除沙箱hold。必须新建任务、重新确认。无release参数时保留暂停。这个流程不能替代真实银行身份验证、坐席权限和机构审批。

## 仍然不能声称完成的外部条件

真实银行API/账户、生产短信/生物验证、银行人工坐席、代表性银发用户试用、官方未见任务评测、第三方渗透测试均没有证据。模型理解仍可能出错，有限规则反诈有漏报/误报。没有应用使用数据、商户合同/退款API，不承诺自动省钱、退费或关闭所有平台扣费。受限业务链不是通用自主规划器。

下一阶段应使用队友独立编写且开发者未见的任务做一次冻结验收，再完成比赛文档/答辩/视频。不能以本记录宣称获奖水平或全部题面满分。
'''
(ROOT/'docs/AGENT_COMPLETION_2026-10-19.md').write_text(report,encoding='utf-8')
summary='''### 2026-10-19 真实模型与Agent闭环完成

已按用户授权从geo复用兼容服务配置，qwen3.8-flash真实推理成功；密钥只在被忽略的本机data文件，geo源文件未修改。类型计划最多5节点、依赖与工具白名单；同任务多轮指代/改口/暂停、修订并发检查、旧批准失效、最低余额三阶段校验、代扣原话证据与否定、教育性反诈引用、持久hold、本机接管/操作员核实已实现。模型无批准或资金执行权限。

验证：109项离线工程回归通过；作者可见12条任务规则和真实模型各12/12，模型13次结构合法且最终运行无降级；额外10条作者编写口语/攻击规则8/10、模型10/10（意图/字段与无未授权操作，不是业务全流程完成率）；实际手机浏览器四条路径通过，含刷新预约、代扣改口、反诈接管、UNKNOWN仅扣一次。前端构建通过。工程docs/AGENT_COMPLETION_2026-10-19.md为完整证据入口。

保持三类为转账/账单分析/订阅代扣，反诈横切。当前仍是本机银行沙箱：真实银行/MFA/坐席未接，未有队友盲写集、真实银发试用或获奖证据；受限业务计划不是通用规划器。本文以下为历史进度，缺凭据/未多轮等描述已被本节替代。下一阶段是冻结后独立任务验收与提交材料，不再扩项目或换UI。

'''
plan=ROOT.parent.parent/'artifacts/fintech-hackathons-2026/current/CURRENT_PLAN.md'
old=plan.read_text(encoding='utf-8')
if '### 2026-10-19 真实模型与Agent闭环完成' not in old:
    title,body=old.split('\n',1)
    plan.write_text('# 当前工作计划：小满银行办事助手\n\n'+summary+body,encoding='utf-8')
log=ROOT/'PROJECT_LOG.md'
old=log.read_text(encoding='utf-8')
if '### 2026-10-19 真实模型与Agent闭环完成' not in old:
    title,body=old.split('\n',1)
    log.write_text(title+'\n\n'+summary+body,encoding='utf-8')
print(json.dumps({'updated':['README.md','SECURITY.md','docs/AGENT_COMPLETION_2026-10-19.md','PROJECT_LOG.md',str(plan)],'live_completed':live['completed'],'additional':para['summary']},ensure_ascii=True))
