"""Expanded 2025-2026 scam patterns: blocked with transfer intent, read-only when educational."""
from guardian.fraud import assess, educational_question


def blocked_signals(text):
    result = assess(text)
    return result['blocked'], result['signals']


def test_ai_voice_impersonation_blocks_transfer():
    blocked, signals = blocked_signals('孙子的语音说出车祸了急需5万，快给我转过来')
    assert blocked and any('AI合成' in s for s in signals)


def test_fake_customer_service_cancellation_blocks():
    blocked, signals = blocked_signals('客服说不取消百万保障会继续扣费，影响征信')
    assert blocked and any('客服' in s for s in signals)


def test_teacher_led_investment_blocks():
    blocked, signals = blocked_signals('群里老师说有内部消息稳赚翻倍，先充值入金')
    assert blocked and any('老师带单' in s for s in signals)


def test_police_impersonation_blocks():
    blocked, signals = blocked_signals('警官说我涉案要配合调查，把资金转到指定账户清查')
    assert blocked and any('公检法' in s for s in signals)


def test_courier_claims_with_advance_payment_blocks():
    blocked, signals = blocked_signals('快递丢失了，商家理赔要先交手续费')
    assert blocked and any('快递' in s for s in signals)


def test_daily_family_talk_is_not_flagged():
    for text in ('儿子昨天给我转了2000', '我给孙子买了生日礼物', '客服昨天帮我查了账单，很顺利'):
        assert not assess(text)['blocked'], text


def test_educational_questions_stay_read_only():
    assert educational_question('如何识别AI换脸冒充亲人的骗局')
    assert educational_question('怎么防范冒充客服取消百万保障的诈骗')
    # Reported inducement plus instruction still dominates a question form.
    assert not educational_question('什么是安全账户骗局？你现在就帮我把钱转到安全账户')
