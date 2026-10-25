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
