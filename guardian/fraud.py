"""Conservative, explainable preflight signals; not a fraud verdict service."""
import re
import unicodedata

SOURCES = [
    'https://by.china-embassy.gov.cn/lsfw/lingshibaohuyuxiezhu1/202512/P020251229757139157854.pdf',
    'https://wsb.gansu.gov.cn/wsb/c108889/202502/174076754/files/060c099184094a0ea0e7fb1b3153417e.pdf',
]


def educational_question(text):
    """Narrow read-only quotation case; never releases an existing safety hold."""
    # Education is routed to a read-only answer; it never releases a hold.
    # Actual instructions or reported inducements still dominate a question.
    asks=bool(re.search(r'什么是|如何识别|怎么识别|如何防范|怎么防范|要注意什么|怎样防骗',text))
    acts=bool(re.search(r'帮我.{0,12}(?:转|付|汇)|我要.{0,8}(?:转|付|汇)|(?:客服|公安|对方|有人|平台|贷款|银行|陌生人).{0,12}(?:让我|要求我|叫我|说|要求|指示)|执行|现在转',text))
    if asks and not acts:return True
    quotes=re.findall(r'[“「‘"]([^”」’"]+)[”」’"]',text)
    if not quotes:
        # A narrow unquoted warning/explanation path remains READ ONLY. It
        # never blesses a transfer and never clears an existing account hold.
        explanation=bool(re.search(r'为什么|什么意思|解释|科普|防诈提醒|宣传册|宣传单',text))
        negated=bool(re.search(r'(?:不要|不能|别).{0,12}(?:转|汇).{0,12}安全账户',text))
        actual=bool(re.search(r'帮我(?:把|给)?.{0,12}(?:转|付|打)|现在.{0,12}(?:转|付)|执行|先转|先付',text))
        return explanation and negated and not actual
    if not re.search(r'什么意思|是什么意思|解释|为什么|科普|宣传册|宣传单',text):
        return False
    outside=re.sub(r'[“「‘"][^”」’"]+[”」’"]','',text)
    if re.search(r'帮我转|给.{0,15}转|我要转|汇款|打钱|先转|先付|执行|验证码.{0,10}告诉',outside):
        return False
    return any(assess(quote)['blocked'] for quote in quotes) and not assess(outside)['blocked']


def assess(text):
    text = re.sub(r'[\s\u200b-\u200f\ufeff]', '', unicodedata.normalize('NFKC', text))
    signals = []
    if '安全账户' in text and re.search(r'转|汇|打款|付款|资金', text):
        signals.append('要求把资金转入所谓“安全账户”')
    if '屏幕共享' in text and re.search(r'转账|操作|验证码|银行卡', text):
        signals.append('对方要求屏幕共享并操作账户')
    if re.search(r'验证码|银行卡密码|支付密码|查询密码|取款密码', text) and re.search(r'告诉|发给|提供给|给客服|交给|发给我|发给他|发给她', text):
        signals.append('对方索取验证码或账户密码')
    if re.search(r'退款|退费|贷款|解冻', text) and re.search(r'先转|先交|先付|保证金|解冻金', text):
        signals.append('以退款、贷款或解冻为由要求先付钱')
    # 2025-2026高发新增：AI合成语音/换脸冒充亲友、假客服注销话术、
    # "老师带单"投资诱导、冒充公检法。全部要求资金语境，避免误报日常聊天。
    if re.search(r'我是你(?:孙子|孙女|儿子|女儿|外孙|外孙女|亲戚)|(?:孙子|孙女|儿子|女儿|爷爷|奶奶|外公|外婆)(?:的)?(?:视频|语音|声音)', text) and re.search(r'出事|被抓|住院|车祸|急用|急需|先.{0,4}(?:转|打|汇)|借', text):
        signals.append('疑似AI合成语音或换脸冒充亲友，以急事为由要求转账；请当面或回拨常用号码核实')
    if re.search(r'(?:客服|客户经理|工作人员|官方)', text) and re.search(r'注销|取消|关闭', text) and re.search(r'校园贷|学生贷|百万保障|保障|会员|额度|征信|扣费', text):
        signals.append('冒充客服称不注销/不取消将影响征信或继续扣费')
    if re.search(r'老师|导师|内部消息|带单|跟单|稳赚|保本|翻倍|内幕', text) and re.search(r'转|投|入金|充值', text):
        signals.append('以“老师带单”“稳赚不赔”等话术诱导转账投资')
    if re.search(r'公检法|公安|检察院|法院|警官|民警|冻结账户', text) and re.search(r'涉案|洗钱|通缉|清查|资金审查|配合调查.{0,10}(?:转|汇|付)', text):
        signals.append('冒充公检法要求配合清查资金或转账自证')
    if re.search(r'快递|包裹|电商|商家', text) and re.search(r'丢失|损毁|烧毁|下架|质量问题', text) and re.search(r'理赔|赔偿|退款', text) and re.search(r'垫付|手续费|保证金|先.{0,3}(?:交|付|转)|银行卡|验证码', text):
        signals.append('冒充快递或商家理赔，要求垫付费用或提供银行卡信息')
    return dict(blocked=bool(signals), signals=signals,
        title='先别转，这种说法需要警惕。' if signals else '未命中已配置的话术规则',
        explanation='请通过银行卡或银行官方App提供的渠道核实，拿不准时先和家里人商量，或拨打反诈专线96110。当前没有发起这笔转账。' if signals
        else '规则覆盖有限；未发现这些信号不代表交易安全。', sources=SOURCES)
