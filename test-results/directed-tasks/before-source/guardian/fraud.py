"""Conservative, explainable preflight signals; not a fraud verdict service."""
import re
import unicodedata

SOURCES = [
    'https://by.china-embassy.gov.cn/lsfw/lingshibaohuyuxiezhu1/202512/P020251229757139157854.pdf',
    'https://wsb.gansu.gov.cn/wsb/c108889/202502/174076754/files/060c099184094a0ea0e7fb1b3153417e.pdf',
]


def educational_question(text):
    """Narrow read-only quotation case; never releases an existing safety hold."""
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
    if re.search(r'验证码|银行卡密码|支付密码', text) and re.search(r'告诉|发给|提供给|给客服|交给', text):
        signals.append('对方索取验证码或账户密码')
    if re.search(r'退款|退费|贷款|解冻', text) and re.search(r'先转|先交|先付|保证金|解冻金', text):
        signals.append('以退款、贷款或解冻为由要求先付钱')
    return dict(blocked=bool(signals), signals=signals,
        title='先别转，这种说法需要警惕。' if signals else '未命中已配置的话术规则',
        explanation='请通过银行卡或银行官方App提供的渠道核实。当前没有发起这笔转账。' if signals
        else '规则覆盖有限；未发现这些信号不代表交易安全。', sources=SOURCES)
