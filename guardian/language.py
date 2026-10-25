"""Ground semantic edits in user text, independently of model suggestions."""
import re
import unicodedata
from guardian.task_planner import cn_number

NUM=r'[0-9零一二三四五六七八九十百千万两]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'


def contact_hint(message,contacts,model_hint=None,candidates=None):
    text=unicodedata.normalize('NFKC',message)
    # Prefer relation qualifiers over a shared name; reject explicitly negated
    # alternatives rather than guessing which similarly named person was meant.
    aliases={}
    for contact in contacts:
        for alias in re.split(r'[()（）]',contact['name']):
            if alias: aliases.setdefault(alias,set()).add(contact['id'])
    positive=[]
    for alias,ids in aliases.items():
        for match in re.finditer(re.escape(alias),text):
            if not re.search(r'不是|别选|不要选|不转给|别给',text[max(0,match.start()-5):match.start()]):
                positive.append(ids)
    if positive:
        selected=set.intersection(*positive)
        if len(selected)==1: return next(iter(selected))
        # Keep a known shared name ambiguous, never choose the first match.
        return next((a for a,ids in aliases.items() if a in text and len(ids)>1),'__multiple_contacts__')
    phone=re.search(r'1[3-9][0-9]{9}',text)
    if phone:
        matches=[c for c in contacts if c.get('phone')==phone.group()]
        if len(matches)==1 and not re.search(r'不是|别选|不要选|不转给|别给',text[max(0,phone.start()-5):phone.start()]):
            return matches[0]['id']
    phone_tail=re.search(r'手机(?:尾号|号尾)?\s*([0-9]{4})',text)
    if phone_tail:
        matches=[c for c in contacts if str(c.get('phone',''))[-4:]==phone_tail.group(1)]
        return matches[0]['id'] if len(matches)==1 else None
    last4=re.search(r'尾号\s*([0-9]{4})',text)
    if last4:
        matches=[c for c in contacts if c['last4']==last4.group(1)]
        return matches[0]['id'] if len(matches)==1 else None
    ordinal=re.search(r'第([一二三123])(?:个|位)',text)
    if ordinal and candidates:
        index=('一二三'.index(ordinal.group(1)) if ordinal.group(1) in '一二三' else int(ordinal.group(1))-1)
        if index<len(candidates): return candidates[index]['id']
    if model_hint and model_hint in text: return model_hint
    return None


def explicit_edit_amount(message):
    corrected=re.search(r'(?:不转|别转|不要转)\s*('+NUM+r')(?:元|块)?了?[，,\s]+(?:而是|改为|改成)?\s*(?:转|付)\s*('+NUM+r')(?:元|块)?(?=$|[，,。！!\s])',message)
    if corrected:return cn_number(corrected.group(2))
    match=re.search(r'(?:金额(?:换成|换为|改成|改为|是)|改成|改为|换成|换为)\s*('+NUM+r')',message)
    if match: return cn_number(match.group(1))
    # A corrective contrast grounds the replacement, never the negated amount.
    # Exclude questions and non-money units so a date/edit cannot become money.
    contrast=re.search(r'('+NUM+r')(?:元|块)?\s*(?:不对|错了|不算|说错了)[，,\s]*(?:应该|应当|实际)?(?:是|要)\s*('+NUM+r')(?:元|块)?(?=$|[，,。！!\s])',message)
    if not contrast:
        contrast=re.search(r'不是\s*('+NUM+r')(?:元|块)?[，,\s]*(?:而)?是\s*('+NUM+r')(?:元|块)?(?=$|[，,。！!\s])',message)
    return cn_number(contrast.group(2)) if contrast else None


def ambiguous_amount(message):
    if re.search(r'(?:转|汇|打|金额|改成|改为|换成|换为).{0,24}(?:-\d|\d+[eE][+-]?\d|\d+\.\d{3,})',message): return True
    for match in re.finditer(r'(?:转|汇|打|金额|改成|改为|换成|换为)[^，。；;0-9零一二三四五六七八九十百千万两-]{0,20}('+NUM+r')',message):
        if cn_number(match.group(1)) is None: return True
    return False


def deterministic_edit(message,kind):
    """Only fully matched, scoped edits bypass a redundant paid model call.

    This is not a classifier for a new task. Safety gates and revision checks
    still run before/after it. Anything outside this narrow grammar uses LLM.
    """
    text=message.strip().rstrip('。.!！')
    if kind=='transfer':
        return bool(re.fullmatch(r'(?:(?:金额)?(?:改成|改为|换成|换为)\s*(?:'+NUM+r')(?:元|块)?|'
            r'(?:改成|改为)(?:今天|明天|后天|(?:下|本)?(?:周|星期)[一二三四五六日天])|'
            r'第[一二三123](?:个|位)|尾号\s*[0-9]{4}(?:的)?|(?:同学|同事|房东)(?:那个|那位))',text))
    if kind=='bills': return bool(re.fullmatch(r'只看[\u4e00-\u9fff]{2,8}',text))
    return False


def mentioned_contacts(message,contacts):
    """Contacts named in the message, in first-mention order, or None when a
    shared name stays ambiguous. Relation qualifiers disambiguate shared names
    ("同学张伟"); negated mentions ("别给张伟") are ignored.
    """
    text=re.sub(r'\s|[（）()·]|会员|服务','',unicodedata.normalize('NFKC',message)).lower()
    alias_map={}
    for contact in contacts:
        for alias in re.split(r'[()（）]',contact['name']):
            if not alias: continue
            key=re.sub(r'\s|[（）()·]|会员|服务','',unicodedata.normalize('NFKC',alias)).lower()
            alias_map.setdefault(key,set()).add(contact['id'])
    hits=[]
    for alias,ids in alias_map.items():
        match=re.search(re.escape(alias),text)
        if match and not re.search(r'不是|别选|不要选|不转给|别给',text[max(0,match.start()-5):match.start()]):
            hits.append((match.start(),alias,ids))
    hits.sort()
    resolved={}
    for position,alias,ids in hits:
        if len(ids)==1:
            resolved.setdefault(next(iter(ids)),position)
    ambiguous=None
    for position,alias,ids in hits:
        if len(ids)>1:
            covered=[i for i in ids if i in resolved]
            if covered: continue
            ambiguous=alias;break
    if ambiguous is not None: return None
    by_id={c['id']:c for c in contacts}
    return [by_id[i] for i in sorted(resolved,key=resolved.get)]


def split_request(message,contacts):
    """Deterministic AA-split advice from an explicit keyword, total and named contacts.

    Returns None when this is not a split request; a 'clarify' dict when the
    request is incomplete or names are ambiguous; otherwise a 'plan' dict with
    per-person integer-cent amounts. No operation is created here.
    """
    if not re.search(r'AA|aa|ａａ|平分|拆分',message): return None
    total=re.search(r'(?:一共|总共|合计)?\s*('+NUM+r')(?:元|块)',message)
    if not total:
        return {'state':'clarify','text':'想按AA拆分可以。请说明总金额和参与的人，例如“给同学张伟和房东AA，一共600元”。'}
    named=mentioned_contacts(message,contacts)
    if named is None:
        return {'state':'clarify','text':'提到的名字对应多位联系人，AA拆分前请先说明各是哪一位（同学/同事/房东或尾号）。'}
    if len(named)<2:
        return {'state':'clarify','text':'AA拆分至少需要两位已核对的联系人。请说明参与的人，例如“给同学张伟和房东AA，一共600元”。'}
    if len(named)>5:
        return {'state':'clarify','text':'一次最多拆分给5位联系人。'}
    from guardian.engine import money
    try:
        total_cents=money(total.group(1))
    except Exception:
        return {'state':'clarify','text':'总金额要大于0、最多两位小数，请再说一次金额。'}
    count=len(named)
    per,remainder=divmod(total_cents,count)
    if per<=0:
        return {'state':'clarify','text':'总金额太少，无法在'+str(count)+'人之间拆分。'}
    shares=[]
    for index,contact in enumerate(named):
        amount=per+(1 if index<remainder else 0)
        shares.append(dict(recipient_id=contact['id'],name=contact['name'],amount_cents=amount))
    def yuan(cents):
        value=cents/100
        return str(int(value)) if cents%100==0 else format(value,'.2f')
    parts='、'.join(s['name']+' '+yuan(s['amount_cents'])+'元' for s in shares)
    text=('AA拆分建议（按提及顺序）：'+parts+'，合计'+yuan(total_cents)+'元。'
        '本账户只能转出、不能代收；请逐笔发起，每笔仍走各自的核对与批准，例如先说“给'
        +named[0]['name']+'转'+yuan(shares[0]['amount_cents'])+'”。当前不会自动拆成多笔。')
    if remainder: text+='（'+str(remainder)+'分尾差已按提及顺序加在前'+str(remainder)+'位。）'
    return {'state':'plan','text':text,'shares':shares,'total_cents':total_cents}
