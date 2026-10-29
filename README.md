# 小满 · 银行办事助手

小满把一句口语需求变成可核对、可改口、可回读的银行办理任务。当前是独立可运行的本机银行沙箱，模型真实调用，不连接真实银行卡、不操作真实资金。

它针对的场景很具体：老人在手机银行上办不了事、看不懂账单、遇到可疑扣费没人管。小满每天打开先开口（叮咛），把口语接成任务后逐项核对再执行，办完给回执，办不到的如实说明。

## 三类业务

- **转账**：同名消歧、多轮补充与改口、预约日期、付款后最低余额。对象、金额、日期或余额条件变化后，旧批准作废；金额、日期、备注的明确补充只重校验受影响的字段。
- **账单分析**：分类汇总与跨月比较，金额由整数账本计算，保留来源行与查询范围；现金与第三方支付看不到，会如实说明。
- **代扣整理**：先单独同意查询银行代扣协议，用户逐项标记是否还需要，每项撤销分别确认，执行后以银行回读为准。账单不能证明使用，撤销不等于商户退款。

反诈规则贯穿执行全程：安全账户、AI 语音冒充亲友、假客服注销、老师带单、冒充公检法等话术命中资金语境即暂停；解释类提问只读科普，不拦。未命中不代表安全。红色操作（挂失、日累计超 1000 元转账）强制验证——当前为页面明确标注的演示验证码，非真实短信；验证级别落库后不可被对话改写。

## 运行

需要 Python 3.9–3.12 与 Node.js：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
npm run build
.venv/Scripts/python.exe run.py
```

打开 http://127.0.0.1:8770/ 。首次访问自动创建合成账户。

模型配置（可选）：环境变量 `GUARDIAN_LLM_BASE_URL`、`GUARDIAN_LLM_API_KEY`、`GUARDIAN_LLM_MODEL`，或本机 `data/model.local.json`（不随代码分发）。未配置时界面明确显示规则模式，全部功能仍可运行。

## 复验

```powershell
.venv/Scripts/python.exe -m pytest -q tests          # 264 项回归
.venv/Scripts/python.exe tools/run_challenge.py      # 冻结挑战（需模型配置）
```

结果汇总在 [submission/EVIDENCE.json](submission/EVIDENCE.json)：冻结挑战正常 12/12、攻击 8/8、故障 4/4，纯规则对照 23/24；挑战为作者可见成绩（非盲测），已于 2026-10-25 按当前代码重跑，源代码指纹一致。回归 264 项对应当前代码。

## 实现结构

- `guardian/engine.py`：账户、余额、授权、幂等、预约、回查与审计的最终权威。
- `guardian/task_planner.py`：模型输出的类型计划与白名单合同（固定工具、最多 5 节点、依赖校验）。
- `guardian/task_runtime.py`：任务版本、改口作废、暂停恢复、UNKNOWN 回查。
- `guardian/assistant.py`：模型适配、账单汇总与业务入口；`fraud.py`：反诈话术规则。
- `frontend/src/Xiaoman.jsx`：React + Radix 大字界面，构建至 `web/dist`，FastAPI 同源提供。

## 边界

- 银行数据为本机合成，真实部署依赖银行授权 API；演示验证码是明确标注的演示实现，正式方案需短信或生物认证。
- 无银行人工坐席接入；安全暂停不会被聊天指令解除，资料可保留给本机操作员核实。
- 面向银发群体的实际收益尚未做真人试用验证，不能宣称普遍节省时间。
- 安全设计详见 [SECURITY.md](SECURITY.md) 与 [submission/portal/安全自评报告-小满.docx](submission/portal/安全自评报告-小满.docx)。

## 提交材料

技术文档、答辩 PPT、安全自评报告见 [submission/portal/](submission/portal/)；答辩讲稿见 [submission/答辩逐页稿.md](submission/答辩逐页稿.md)；评审复查指引见 [submission/评审入口.md](submission/评审入口.md)。
