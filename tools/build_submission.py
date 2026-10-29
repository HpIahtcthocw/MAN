"""Create a reviewable local submission packet; never publish or include data/."""
import hashlib,json,statistics,sys,zipfile
from pathlib import Path
from xml.etree import ElementTree
ROOT=Path(__file__).absolute().parent.parent
OUT=ROOT/'submission';OUT.mkdir(exist_ok=True)
def read(path): return json.loads((ROOT/path).read_text(encoding='utf-8'))
live=read('test-results/challenge-v2/live-results.json')
rules=read('test-results/challenge-v2/rules-results.json')
external=read('test-results/agentdojo-adapted-v1/live-results.json')
regression_path='test-results/query-context/regression.xml' if (ROOT/'test-results/query-context/regression.xml').exists() else 'test-results/challenge-v2/regression.xml'
if (ROOT/'test-results/acceptance-review/regression.xml').exists(): regression_path='test-results/acceptance-review/regression.xml'
if (ROOT/'test-results/directed-tasks/regression.xml').exists():regression_path='test-results/directed-tasks/regression.xml'
suite=ElementTree.parse(ROOT/regression_path).getroot()
tests=sum(int(e.get('tests','0')) for e in suite.iter('testsuite'))
failures=sum(int(e.get('failures','0'))+int(e.get('errors','0')) for e in suite.iter('testsuite'))
assert not failures,'Do not package failed tests'
turns=[t for c in live['cases'] for t in c.get('turns',[])]
latencies=[t['model_meta']['latency_seconds'] for t in turns if (t.get('model_meta') or {}).get('latency_seconds')]
metrics=dict(tests=tests,live=live['summary'],rules=rules['summary'],external_adapted=external['summary'],
    spec_sha256=live['spec_sha256'],model_returns=sum(t.get('planner')=='llm' for t in turns),
    exact_edits=sum(t.get('planner')=='validated_edit' for t in turns),
    fallbacks=sum(bool(t.get('model_meta')) and not t['model_meta'].get('structured_output_valid',True) for t in turns),
    median_model_seconds=round(statistics.median(latencies),3) if latencies else None,
    browser_single_exact_edit_ms=159,real_payments=False,blind=False)
current_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'guardian').rglob('*.py'))}
metrics['live_results_match_current_code']=live.get('source_hashes')==current_hashes
metrics['regression_xml']=regression_path
if (ROOT/'test-results/directed-tasks/live-results.json').exists():
    claude_live=read('test-results/directed-tasks/live-results.json')
    metrics['directed_review']={'note':'历史定向检查存档（作者可见）；对应早期代码，当前代码口径见 live 块。','regression_tests':tests,'directed_live_passed':claude_live['passed'],'directed_live_total':claude_live['total'],
        'matches_current_code':claude_live['source_hashes']==current_hashes,'blind':False,'merchant_scoring_implemented':False}
if (ROOT/'test-results/acceptance-review/after.json').exists():
    before_acceptance=read('test-results/acceptance-review/before.json');after_acceptance=read('test-results/acceptance-review/after.json')
    metrics['acceptance_review']={'before_passed':before_acceptance['passed'],'after_passed':after_acceptance['passed'],
        'total':after_acceptance['total'],'author_visible':True,'blind':False,
        'matches_current_code':after_acceptance['source_hashes']==current_hashes,
        'note':'历史验收存档（作者可见）；浏览器检查未随本轮重跑，当前代码口径见 live 块。'}
    if (ROOT/'test-results/acceptance-review/api.json').exists():
        api_acceptance=read('test-results/acceptance-review/api.json')
        metrics['acceptance_review']['live_api_passed']=api_acceptance['passed']
if (ROOT/'test-results/query-context/browser.json').exists():
    query_browser=read('test-results/query-context/browser.json')
    metrics['query_context']={'browser_passed':query_browser['passed'],'checks':len(query_browser['checks']),
        'real_bank':False,'previous_challenge_scores_are_historical':not metrics['live_results_match_current_code']}
if (ROOT/'test-results/product-stress-v1/live-results.json').exists():
    stress_live=read('test-results/product-stress-v1/live-results.json')
    stress_rules=read('test-results/product-stress-v1/rules-results.json')
    assert stress_live['spec_sha256']==stress_rules['spec_sha256']
    assert stress_live['source_hashes']==stress_rules['source_hashes']
    metrics['product_stress']={'first_live':read('test-results/product-stress-v1/first-run/live-results.json')['summary'],
        'first_rules':read('test-results/product-stress-v1/first-run/rules-results.json')['summary'],
        'final_live':stress_live['summary'],'final_rules':stress_rules['summary'],
        'author_visible':True,'blind_cases':0,'final_spec_sha256':stress_live['spec_sha256'],
        'note':'Development stress set; first failures preserved. Final oracle additionally checks recipients for S01-S03. Inputs unchanged.'}
if (ROOT/'test-results/responsive/matrix.json').exists():
    matrix=read('test-results/responsive/matrix.json');font=read('test-results/responsive/font-stress.json');recovery=read('test-results/responsive/recovery.json')
    metrics['responsive']={'layout_passed':matrix['passed'],'layout_total':matrix['total'],'viewports':len(matrix['sizes']),
        'font_stress_passed':font['passed'],'font_stress_total':font['total'],'ui_recovery_passed':recovery['passed'],'ui_recovery_total':recovery['total'],
        'physical_mobile_devices_tested':False,'cross_browser_certified':False}
if (ROOT/'test-results/blind-li-2026-10-29/run-v3-final.json').exists():
    bli=json.loads((ROOT/'test-results/blind-li-2026-10-29/run-v3-final.json').read_text(encoding='utf-8'))
    first=json.loads((ROOT/'test-results/blind-li-2026-10-29/run-v1-first-2008.json').read_text(encoding='utf-8'))
    metrics['blind_li']={'set':'blind-li-2026-10-29','author':'队友盲写（题面作者可见、执行盲跑）',
        'final':bli['summary'],'first_run_preserved':first['summary'],
        'note':'首轮3/18后修复5处确定性缺口（4类反诈话术、叮咛问答、边界拒绝、UNKNOWN对账轮误判改口）并重跑；3条未过为非模板理解边界，均安全失败（追问、不编数、不动钱）。'}
(OUT/'EVIDENCE.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
intro='小满是一款可核验的银行办理智能体，覆盖转账、账单分析与订阅代扣。用户可自然语言追问、改口和续办。模型提出意图和查询条件，宿主校验原话、权限与实际数据；理解不一致时先追问。资金操作须明确批准，支持余额底线、旧草稿作废、幂等与异常回查。扣费查证保留依据，协议候选不等于已验证归属。当前作品使用可运行银行沙箱，模型已接通；大字、朗读和逐项确认是设计原则，未验证特定人群收益。'
assert len(intro)<=200
(OUT/'作品简介.txt').write_text(intro+'\n',encoding='utf-8')
tech=f'''# 小满技术说明

## 业务目标与数据边界

面向不熟悉银行菜单、需要口语追问和明确复核的人群。银发是设计对象，尚未做代表性人群效果验证。本机合成银行提供余额、流水、已核对联系人、代扣协议、预约及回执；无需导入账单即可完成演示。真实部署依赖银行授权API，不把公开数据或LLM当成账户来源。

主线任务：查清持续扣费，用户逐项决定，再单项撤销并核实；同一助手另支持带条件转账与账单范围分析。反诈为跨场景安全能力，不另计第三类。

## 系统架构

```mermaid
flowchart LR
  U[自然语言与可访问表单] --> S[账户会话与任务版本]
  S --> F[确定性风险门禁]
  F --> R{{明确补充?}}
  R -->|是| E[原话精确校验]
  R -->|否| L[Qwen结构化提案]
  E --> V[类型与依赖校验]
  L --> V
  V --> T[受限业务计划与读取证据]
  T --> A[具体操作确认及红色验证]
  A --> B[确定性资金引擎]
  B --> P[合成银行与持久回执]
  P --> C[回读结果与原交易恢复]
  T --> H[暂停与本机接管]
  B --> G[哈希审计]
  C --> G
```

## 计划与增量办理算法

输入为本轮原话、当前草稿、最多6轮已保存补充、银行提供的联系人；协议名称/状态只来自有查询同意的任务。银行商户备注、完整snapshot、服务密钥和OTP不进模型上下文。

模型输出Plan严格schema：业务类型、动作、金额/日期/收款人提议、用户意愿与原话、最多5个白名单节点和依赖。验证拒绝额外字段、重复ID、未知工具、后向或缺失依赖、超预算。执行器按固定业务合同解释，当前并非自由生成通用DAG。

每轮按task_id与revision读取上下文，模型返回后再次核版本。金额/日期/对象须有本轮依据，日期改口不能重置已消歧的人。实体解析读取银行姓名、括号关系、尾号及已显示候选次序，不由模型虚构对象。明确的日期、金额、次序和类别补充走精确编辑路径；它仍经过风险、schema、版本与批准检查，不是自动付款捷径。

修订差异只影响关联草稿。PREPARED失效并清除挑战；CONFIRMED/SCHEDULED/UNKNOWN/SUCCEEDED须先核查或撤销，不能以新句话覆盖原资金状态。代扣按具体协议处理，改A不意味着撤销B的合法任务；对象未明确也使相关旧草稿失效。

## 确定性金融算法

金额为整数分，拒绝负数、科学计数、小数分和有歧义的三千五。最低余额判定：

`预计剩余 = 实际银行余额 − 其他未落账付款预留 − 本次金额`

`要求底线 = max(账户底线, 本次明确最低余额, 其他待付款的已批准最低余额)`

准备、确认、provider落账前均校验。未来工资不算余额，导入证据不铸造资金。日累计按计划执行日汇总已确认/预约/未知/成功金额，≤1000黄色，>1000红色。

账单期间/分类/商户筛选在后端算，支持明确年月、两个连续月范围/比较、本上上上月、年度、最近N天和同范围类别追问。无法确定范围就询问，不能自动替换成全历史。输出带原始行、范围、覆盖缺口，不用LLM计算总额。

## 授权、幂等与恢复

批准绑定账户、能力、收款人、金额、日期、币种、备注与最低余额的摘要；准备不付款，聊天确认不批准。红色操作使用单次且绑定操作的演示OTP，并非真实短信或生产MFA。失败3次锁5分钟。

先持久化UNKNOWN，再调合成银行事务。银行收据独立落账，30秒执行租约防止并发回查；响应丢失查询同一操作，无回执也不自动重付。SQLite写事务串行预留/确认，重复执行只产生一张收据。真实provider须另处理最终一致性，不能照搬本机NOT_FOUND语义。

## 评测与可复现结果

工程回归 {tests} 项通过，XML在evidence中。冻结24条挑战SHA256：`{live['spec_sha256']}`。

回归明细：`{regression_path}`。冻结挑战已于 2026-10-25 按当前代码重跑，源代码指纹一致：{metrics['live_results_match_current_code']}。

模型系统：正常任务 {live['summary']['normal']['passed']}/12、攻击边界 {live['summary']['attack']['passed']}/8、故障 {live['summary']['fault']['passed']}/4。规则系统：正常 {rules['summary']['normal']['passed']}/12、攻击 {rules['summary']['attack']['passed']}/8、故障 {rules['summary']['fault']['passed']}/4。正常组除明确拒绝/追问任务外，断言真实操作终态；不把安全拒绝当成功付款。

最终挑战共有 {metrics['model_returns']} 次真实模型返回、{metrics['exact_edits']} 次精确编辑。模型请求中位耗时约 {metrics['median_model_seconds']} 秒；手机浏览器某次精确类别补充159毫秒，是单次本机观察，不是普遍延迟承诺。两项不能混为一个平均数。

外部任务：参考AgentDojo银行任务UserTask1/8/9/10的结构，中文重写并替换数据/日期/批准策略，4/4通过。没有运行原AgentDojo环境或评分器，不与公开成绩比较。所有集合作者可见，没有真实用户、盲测或官方成绩。

## 技术贡献与边界

贡献在于面向口语改口的可追溯执行：把用户原话、具体对象、批准版本和银行回执连接，明确哪些变化撤销旧批准，UNKNOWN如何恢复。采用的是成熟工程与领域约束方法，不主张新基础模型、通用规划或原创密码协议。

真实银行接口口径、代码预带/模拟许可、模型来源限制待组委会确认。本机接管不是银行坐席；真实身份、生产MFA、全量反诈和银发试用没有完成。没有生成任意代码，因此不声称通用代码沙箱已实现。

## 来源

- 本届题面与40/30/30评审规则：https://fintechathon.g-ican.com/#/rule （2026-10-19真实浏览器重读）
- AgentDojo：https://github.com/ethz-spylab/agentdojo （仅概念改编；MIT）
- Qwen结构输出：https://help.aliyun.com/en/model-studio/qwen-structured-output
- 往届获奖参照：https://www.hkust-gz.edu.cn/zh/?p=13630%2F%2F 与 https://github.com/CUEB-QF-ZQS/YiJinJing
'''
(OUT/'技术说明.md').write_text(tech,encoding='utf-8')
speech='''# 10分钟答辩逐页稿

这是可直接排版的12页内容与讲稿，不是已导出的PPTX。总时长约9分30秒，留30秒机动。数字以同目录EVIDENCE.json为准。每个结果同时带样本性质与环境。

## 1 小满（30秒）
屏幕只写：小满／银发银行办事助手。配实际运行截图。
讲：我们解决的不是让模型回答银行知识，而是让用户说完需求后，能核对、改口、办成，并知道结果。下面所有账户是银行沙箱，模型是真实调用。

## 2 一件完整的事（45秒）
屏幕：这几个月一直在扣钱，帮我查清楚；B不用了，A留着。
讲：在不同菜单之间查流水、找协议、决定停哪项、再核实结果，用户要自己维护上下文。我们的流程保留这些依赖。账单不证明是否使用，所以最后决定仍由本人作出。银发是设计人群，尚无代表性用户试验，不能把设计目标说成已验证收益。

## 3 三类业务与共同办理方式（35秒）
屏幕用三个业务标题和实际截图：带条件转账、账单分析、代扣整理。
讲：三类独立满足题面覆盖。反诈贯穿执行，不凑第四类。差异在同一任务的补充、改口和回读，而不是换一层菜单名称。

## 4 账单接着代扣办理（65秒）
演示：九月花了多少；只看餐饮；继续整理持续扣费；同意查询；B不用了A留着；只撤销B；核实结果。
讲：来源行和范围保留，协议查询仍单独同意。不能从账单推断使用频率，也不能把银行协议撤销说成商户退款。演示采用实际运行视频或现场，不能播放预置成功动画。

## 5 转账中的改口（60秒）
演示：给张伟600；同学那个；改成周五；核对预约。另展示“转7000至少留3000”的明确拒绝。
讲：这里考验对象、金额、日期和批准的一致性。改日期不重置人，改金额使旧草稿失效。未来工资和其他资金预留都不能被模型忽略。

## 6 模型和资金权限（50秒）
屏幕放技术说明中的架构图，拆成一张清楚的图，不堆功能卡。
讲：模型提供受限提案，后端校验依赖。模型不能批准、发验证码、执行或解除安全暂停。白名单和事务控制资金，LLM不负责算余额。

## 7 只重办受影响的部分（45秒）
屏幕：原话、任务版本、差异、旧批准失效、新批准五项对应关系，注明工程方法。
讲：我们采用成熟的版本控制与绑定方法。明确补充直接校验，复杂口语仍走模型。既降低无谓等待，也避免把“模型生成了新答案”当成“旧批准仍有效”。

## 8 诱导转账与误报（40秒）
屏幕：安全账户诱导暂停；宣传册解释只读。
讲：未命中规则不代表安全。解释反诈宣传不能锁死正常账户，也不能解除已有风险暂停。普通继续不放行，资料可交本机操作员核实；当前没有银行坐席接入。

## 9 银行已扣款，回答丢了（50秒）
屏幕放真实UNKNOWN回查截图和一笔ledger记录。
讲：最危险的是把超时理解为失败再付一次。我们先记录UNKNOWN，再查同一交易的回执。只恢复原交易，不再建第二笔；结果来自银行沙箱，不来自模型描述。

## 10 结果与对照（50秒）
屏幕放EVIDENCE.json的正常/攻击/故障三组结果，作者可见标识与工程测试数分开。
讲：不要把工程用例数当任务完成率。规则仍能完成绝大多数固定表达，模型价值出现在非模板口语。冻结挑战不是盲测；AgentDojo概念改编也不是原公开基准成绩。

## 11 与往届获奖作品的比较（35秒）
屏幕只放可比的机制：完整任务、具体技术模块、可复查结果。
讲：灵操盘和易金经各有明确技术链和成果，我们借鉴完整交付的标准，不靠多Agent或图谱数量追概念。本届重点是银行任务、权限与交互，因此我们的技术贡献必须由改口、授权和故障结果证明。

## 12 能力边界与下一步（25秒）
屏幕：银行API／正式身份认证／独立银发试用。
讲：当前完成的是可运行、可复测的银行沙箱。真实合作和用户收益不能用包装代替。交付包含源码、测试、技术说明、安全自评与原始结果，欢迎评委自行写任务复查。
'''
(OUT/'答辩逐页稿.md').write_text(speech,encoding='utf-8')
qa='''# 现场追问与证据入口

**和普通银行菜单相比有什么用？**
对单一步骤、对象明确的业务，按钮可能更快。我们的目标是有范围、指代、改口和跨页面依赖的任务。展示同一任务的原话、版本与回执，不能声称已经量化证明银发用户节省时间。演示保留直接表单作为降级入口。

**为什么不用纯规则？**
同一冻结挑战规则正常任务11/12，系统12/12；额外作者口语集也保留对照。规则覆盖明确格式，模型补非模板表达。不是证明LLM在所有任务占优，也不把账务算法交给模型。

**有没有新算法？**
没有训练新基础模型。技术贡献是领域约束计划、原话/版本/批准/回执之间的绑定和恢复实现。类型、幂等、状态机是成熟方法，不冒充原创算法。

**DAG是不是只是画图？**
当前是最多5节点的受限业务链，依赖顺序严格校验，节点对应实际读取、验证、等待批准与回读。它不是可任意生成工具的通用规划器。复杂跨业务任务以带来源的后继任务续接，写权限重新征求，不合并旧批准。

**拒绝所有操作是不是也能安全满分？**
所以正常、攻击、故障分开统计，正常组确有真实确认后的资金终态。拒绝正确只在任务本身要求底线检查、信息不足或模糊范围时计为完成声明目标。

**验证码在页面上，算强验证吗？**
不算生产第二因子。演示码只能验证操作绑定、过期、单次和错误熔断逻辑。正式提交应披露，若评委要求真实MFA或指定环境，必须接认证服务，不能称已满足生产级强验证。

**没有银行API，数据怎么拿？**
本机合成银行提供同构查询/操作接口，不需要用户导入账单来演示。真实部署必须获得银行接口。尚未取得官方模拟许可的明确口径，不能把沙箱当银行合作。

**怎么知道订阅没用？**
不知道。流水只能给出周期扣费证据，用户明确意愿后才撤销。没有使用频次、商户合同或退款接口，不能声称自动识别闲置、自动省钱或退款。

**引用诈骗宣传会不会把账户锁死？**
有高精度只读解释分支，并测试不新建hold、不清旧hold。真正的诱导信号依旧暂停；规则覆盖有限，不能声称识别所有骗局。

**普通“继续”能解除风控吗？**
不能。接管状态聊天不可解除，只有本机操作员可记录复核，先解决UNKNOWN并撤销旧授权再解除沙箱hold。真实银行审核服务未接。

**模型报错或网络断了怎么办？**
明确显示规则降级，仍校验业务参数和批准。付款超时进入UNKNOWN查原交易，不用新模型答案重付。真实provider的最终一致性另需适配。

**这些成绩有没有盲测？**
没有。作者可见的开发/挑战集合均有冻结输入、哈希、原始输出与数据库。队友真正独立写题、真实银发可用性和官方评测仍缺，不能改名成盲测。

**怎么处理提示注入？**
不把商户备注作为模型指令或上下文，工具白名单不含任意代码/付款批准；参数仍需原话和具体用户确认。所测攻击只能证明声明边界，不是通用防注入认证。

**源代码可复现吗？**
包里有启动说明、依赖、测试、冻结题、runner和结果JSON。真实推理需自行配置HTTPS兼容服务密钥；离线测试不需要密钥。包不含本机data和API密钥，未代用户发布GitHub。
'''
(OUT/'现场问答.md').write_text((ROOT/'submission/现场问答.md').read_text(encoding='utf-8'),encoding='utf-8')
check='''# 提交检查与剩余外部条件

## 已形成的本地交付

- 200字内作品简介、技术说明和架构Mermaid、源代码与部署说明、测试、冻结任务和原始结果。
- SECURITY.md安全自评、现场问答、约9分30秒答辩逐页稿。
- 真实界面操作视频MP4/WebM（无配音原始录屏，非五分钟完整剪辑）。
- 源码ZIP采用白名单打包，不含data、环境密钥、账户数据库或node_modules。ZIP不是已经发布的GitHub仓库。

## 仍不能勾成完成

- 队伍真实成员/全日制与高校资格、报名状态：用户自行办理；没有代填或确认成功。
- 官方业务API/自建模拟许可、代码预带边界、模型来源要求：未得到组委会明确口径。不凭赛题未写禁止就宣称允许。
- 真实银行身份、短信/生物验证和银行人工坐席：未接，演示OTP必须如实披露。
- 真正由队友独立编写且开发者事前未见的任务、真实银发用户试用：未完成，不编造。
- 必交答辩PPTX：已完成逐页内容和讲稿，尚未导出PPTX。当前没有可用的Artifact导出运行时或已连接PowerPoint会话，不能把Markdown当PPT交。
- 公开GitHub地址与正式赛事提交：尚未发布或上传。

## 赛程核对

2026-10-19真实浏览器读取官网：报名至11/01，作品11/02截止，11/03–08评审，11/10公布十强，11/21–22深圳黑客松与答辩，11/23颁奖。按官网说明，视频不超过5分钟为可选；题面作品资料仍列演示视频，准备好更稳妥。没有具体截止时刻就不要自行写23:59。

来源：https://fintechathon.g-ican.com/#/rule

## 内部放行建议

代码与演示达到可供独立评审的候选状态。正式提交仍为条件放行：完成PPTX、真实队伍信息、公开仓库与赛事口径确认。不能把作者小样本或测试总数换算获奖概率。
'''
(OUT/'提交检查.md').write_text(check,encoding='utf-8')
notice='''# 外部资源与复用声明

## 原有资产

Personal Investment OS：门禁、审计、幂等与恢复的设计经验；Capability POC：白名单能力注册的设计经验。此目录资金账本与原项目独立，未对真实投资账户操作。没有复用开放任意工具执行器、炒股多Agent辩论或x402资金通道。

## 开源与外部评测

AgentDojo银行任务结构用于4条中文概念改编，源任务UserTask1/8/9/10。未复制执行器或评分器，未运行原始fixture，不提供原基准成绩。上游MIT许可，版权归原作者。
https://github.com/ethz-spylab/agentdojo/blob/main/src/agentdojo/default_suites/v1/banking/user_tasks.py
https://github.com/ethz-spylab/agentdojo/blob/main/LICENSE

前端使用React、Radix Themes、Lucide和Vite，后端使用FastAPI、Pydantic、Uvicorn；第三方软件保留各自许可证，具体依赖见锁文件。本文不授予整个原创项目新的对外开源许可证，作品知识产权由参赛者保留。

往届《灵操盘》《FinAgent》参照获奖报道，《易金经》参照公开技术目录；未复制其模型、训练数据、图谱或获奖代码，没有同条件复现，不能声称性能超过。
'''
(OUT/'复用与来源.md').write_text(notice,encoding='utf-8')

# A separate source archive, with an allowlist rather than a broad directory zip.
# Public-repo exclusions (agreed 2026-10-25): test-results/blind-agent-* stays local-only;
# if published to GitHub later, do NOT git-add that directory — its authorship notes are
# internal provenance, and materials must not cite its numbers without the honest label.
files=[]
for name in ('README.md','SECURITY.md','requirements.txt','requirements-dev.txt','package.json','package-lock.json','vite.config.js','frontend/index.html','run.py','model.local.example.json','.gitignore'):
    p=ROOT/name
    if p.is_file(): files.append(p)
for folder,patterns in [('guardian',['*.py']),('frontend/src',['*.js','*.jsx','*.css']),('tests',['*.py','*.mjs']),('evaluation',['*.json'])]:
    for pattern in patterns: files.extend((ROOT/folder).rglob(pattern))
for name in ('README.md','SECURITY.md','run.py','requirements.txt','requirements-dev.txt','package.json','package-lock.json'):
    pth=ROOT/name
    if pth.is_file(): files.append(pth)
files.extend([ROOT/'frontend/index.html'])
for name in ('evaluation/blind-li-2026-10-29.txt','evaluation/blind-li-2026-10-29.sha256','tools/run_blind_li.py'):
    pth=ROOT/name
    if pth.is_file(): files.append(pth)
for p in (ROOT/'test-results/blind-li-2026-10-29').glob('*.json'): files.append(p)
for name in ('evaluate_task_baseline.py','evaluate_paraphrases.py','run_challenge.py','review_handoff.py','build_submission.py','preflight_submission.py','serve_ui_test.py','verify-responsive.playwright.js','verify-ui-recovery.playwright.js','verify_priority_milestone.py','record-final-demo.playwright.js','verify-query-context.playwright.js','run_acceptance_review.py','verify_acceptance_api.py','verify-acceptance-review.playwright.js','run_directed_live.py'):
    p=ROOT/'tools'/name
    if p.is_file(): files.append(p)
for name in ('技术说明.md','一镜到底演示脚本.md','答辩逐页稿.md','现场问答.md','复用与来源.md','评审入口.md','独立试用记录模板.md'):
    pth=OUT/name
    if pth.is_file(): files.append(pth)
files.extend([OUT/'作品简介.txt',OUT/'EVIDENCE.json'])
for p in (ROOT/'test-results/challenge-v2').glob('*results.json'): files.append(p)
files.extend([ROOT/'test-results/challenge-v2/regression.xml',ROOT/'test-results/agentdojo-adapted-v1/live-results.json'])
for p in (ROOT/'test-results/challenge-v2/browser').glob('*.png'): files.append(p)
for folder in ('test-results/product-stress-v1','test-results/product-stress-v1/first-run','test-results/priority-milestone'):
    for p in (ROOT/folder).glob('*.json'): files.append(p)
for p in (ROOT/'test-results/product-stress-v1').glob('final-*.png'): files.append(p)
for p in (ROOT/'test-results/query-context').glob('*'):
    if p.is_file() and p.suffix in ('.json','.xml','.png'): files.append(p)
for p in (ROOT/'test-results/acceptance-review').glob('*'):
    if p.is_file() and p.suffix in ('.json','.xml','.png'): files.append(p)
files.append(ROOT/'test-results/acceptance-review/before-source/guardian/bill_scope.py')
for p in (ROOT/'test-results/directed-tasks').glob('*'):
    if p.is_file() and p.suffix in ('.json','.xml'):files.append(p)
for name in ('matrix.json','recovery.json','font-stress.json','resilience.json','dropdown.json','frontend.xml','verification.md'):
    p=ROOT/'test-results/responsive'/name
    if p.is_file(): files.append(p)
for name in ('approval-320x568.png','subscriptions-320x568.png','home-1440x900.png','final-live-360.png'):
    p=ROOT/'test-results/responsive'/name
    if p.is_file(): files.append(p)
for p in (ROOT/'web/dist').rglob('*'):
    if p.is_file() and p.suffix in ('.html','.js','.css'): files.append(p)
zip_path=OUT/'xiaoman-source-candidate.zip'
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(set(files)):
        rel=p.relative_to(ROOT)
        assert not set(rel.parts)&{'data','node_modules','.git','__pycache__'}
        z.write(p,str(rel).replace('\\','/'))
manifest={'files':[str(p.relative_to(ROOT)).replace('\\','/') for p in sorted(set(files))],
    'zip':zip_path.name,'sha256':hashlib.sha256(zip_path.read_bytes()).hexdigest(),'real_payments':False}
(OUT/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'tests':tests,'metrics':metrics,'source_zip':str(zip_path),'intro_characters':len(intro)},ensure_ascii=True))
