"""Update canonical local status from actual evidence, without touching secrets."""
import json
from pathlib import Path
ROOT=Path(__file__).absolute().parent.parent
stamp='### 2026-10-19 提交候选：冻结挑战与外部任务复核'
entry='''
本轮已将账单扩展至明确年月/年度/最近N天/类别与范围续问；账单→代扣以来源关联的后继任务续办，查询权限重新征求。联系人解析使用银行返回的姓名/关系/尾号/候选，不再依赖主路径中的三个演示名字。精确改日期/金额/次序/类别走确定性增量校验，复杂语句仍真实调用qwen3.8-flash，资金批准权不变。收据结果现在直接显示最终事实；金额/最低余额/时刻有歧义不能静默截断。

验证：133项工程回归通过；冻结24条作者可见挑战，模型系统正常12/12、攻击8/8、故障4/4，规则系统正常11/12、攻击8/8、故障4/4；最终挑战23次模型返回、6次精确编辑、0次降级。AgentDojo银行UserTask1/8/9/10的中文概念改编4/4，未跑原环境，不能称原公开基准成绩。手机跨场景实际录屏、桌面三场景/改口旧批准失效/预约/反诈实际录屏通过；所测视口无脚本错误或横向溢出，某次精确补充159ms仅为本机单次观察。

本地submission目录已形成155字简介、技术说明/架构、约9分30秒答辩逐页稿、现场问答、复用来源、结果、源码候选ZIP和真实MP4/WebM。vibe-preflight定向11项通过，无实际密钥或数据库入包。尚未发布GitHub或正式提交。PPTX仅有逐页稿未导出：当前缺Artifact导出运行时及已连接PowerPoint会话；真实团队信息/赛事模拟与预带码许可/正式MFA和银行坐席/真正未见任务/银发用户试用仍缺。可独立评审的沙箱候选，不宣称获奖水平已被证明。

最新入口：工程submission/提交检查.md、submission/技术说明.md、submission/EVIDENCE.json、test-results/challenge-v2/{live-results.json,rules-results.json,regression.xml,preflight.json}。以下旧进度保持历史性质，不覆盖当前状态。

'''
for p in (ROOT/'PROJECT_LOG.md',ROOT.parent.parent/'artifacts/fintech-hackathons-2026/current/CURRENT_PLAN.md'):
    s=p.read_text(encoding='utf-8')
    if stamp not in s:
        title,body=s.split('\n',1);p.write_text(title+'\n\n'+stamp+'\n'+entry+body,encoding='utf-8')
readme=ROOT/'README.md';s=readme.read_text(encoding='utf-8')
notice='''> 2026-10-19 最新候选：133项回归通过，冻结挑战正常12/12、攻击8/8、故障4/4；规则对照正常11/12。新增明确年月/年度/最近N天、同范围筛选、账单接代扣、通用联系人消歧与精确编辑。所有集合作者可见。完整交付见 [提交检查](submission/提交检查.md)、[技术说明](submission/技术说明.md) 和 [证据](submission/EVIDENCE.json)。[三场景真实录屏](submission/video/xiaoman-three-scenes.mp4)为实际沙箱操作、无配音，非剪辑后的最终答辩视频。PPTX、公开仓库、正式提交及外部许可/用户验证未完成。以下109项记录是上一阶段历史，不能代替最新证据。

'''
if notice not in s:
    title,body=s.split('\n',1);readme.write_text(title+'\n\n'+notice+body,encoding='utf-8')
security=ROOT/'SECURITY.md';s=security.read_text(encoding='utf-8')
note='''> 最新候选追加：工程133项回归、冻结挑战8条攻击及4条故障通过，见test-results/challenge-v2；它们仍是作者可见样本，不代表通用拦截率。明确补充的确定性快路径同样经过风险、类型、任务版本及批准检查。下下周/具体时刻/月底、三千五及小数分底线会要求澄清，不能静默改成另一日期/金额。提交ZIP经实际本机密钥字节比对和敏感路径检查；正式银行身份、MFA、坐席仍未接入。

'''
if note not in s:
    title,body=s.split('\n',1);security.write_text(title+'\n\n'+note+body,encoding='utf-8')
browser={'mobile':{'viewport':[430,950],'linked_bill_to_subscription':True,'edit_ms_observed':159,'bank_cancelled_count':1,'script_errors':[],'horizontal_overflow':False},
    'desktop':{'viewport':[1280,800],'three_scenes':True,'old_approval_cancelled':True,'scheduled':True,'scam_hold':True,'script_errors':[],'horizontal_overflow':False},
    'method':'Actual Playwright interaction with live Qwen and synthetic bank; videos recorded by browser, MP4 transcoded only, no result frames fabricated',
    'blind':False,'real_bank':False,'videos':['submission/video/xiaoman-bills-to-cancellation.mp4','submission/video/xiaoman-three-scenes.mp4']}
(ROOT/'test-results/challenge-v2/browser/results.json').write_text(json.dumps(browser,ensure_ascii=False,indent=2),encoding='utf-8')
print('Canonical status and browser evidence updated')
