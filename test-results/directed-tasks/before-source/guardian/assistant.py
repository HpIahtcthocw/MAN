"""Scoped assistant: semantic planning proposes; the existing bank authorizes.

No bank write is executable through model output. Plans and consent are persisted
per owner. Untrusted bank memo text is never placed in the model instruction.
"""
import json
import os
import re
import time
import uuid
import urllib.request
from urllib.parse import urlparse
from datetime import timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from guardian.engine import Denied, now, money
from guardian.fraud import assess
from guardian.model_config import settings
from guardian.task_runtime import TaskRuntimeMixin


class Intent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    intent: Literal['transfer', 'subscriptions', 'bills', 'safety', 'clarify', 'unsupported']
    recipient_hint: Optional[StrictStr] = Field(default=None, max_length=80)
    amount: Optional[StrictStr] = Field(default=None, max_length=14)
    due_day: Optional[StrictStr] = Field(default=None, max_length=10)
    reference_last: StrictBool = False
    subtract_amount: Optional[StrictStr] = Field(default=None, max_length=14)


def configured():
    config = settings()
    return all(config.get(k) for k in ('base_url', 'api_key', 'model'))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Do not forward a provider credential to an unexpected redirect target.
        return None


def guarded_urlopen(request, timeout):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


def model_intent(message):
    """OpenAI-compatible JSON mode; strict local validation is still mandatory."""
    config = settings()
    url = config.get('base_url', '').rstrip('/')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Model endpoint must use HTTPS')
    prompt = ('你只解析银行用户意图，输出JSON，不执行操作。今天是' + now().date().isoformat() +
        '。只允许以下schema，不能增加字段：' + json.dumps(Intent.model_json_schema(), ensure_ascii=False) +
        '。代扣/续费/订阅归subscriptions；查账、余额、分析归bills；'
        '不清楚则clarify。reference_last只在用户明确要求参考过去付款时为true。'
        '金额是元的正数字符串，不自己编造对象、金额或日期。不输出账户结果或批准。')
    body = dict(model=config['model'], temperature=0, enable_thinking=False,
        response_format={'type': 'json_object'}, max_tokens=500,
        messages=[{'role': 'system', 'content': prompt}, {'role': 'user', 'content': message}])
    request = urllib.request.Request(url + '/chat/completions',
        data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + config['api_key'],
        'Content-Type': 'application/json'})
    with guarded_urlopen(request, timeout=20) as response:
        data = json.loads(response.read(100_000))
    return Intent.model_validate_json(data['choices'][0]['message']['content'])


def model_plan(message, context):
    from guardian.task_planner import Plan, prompt, validate_nodes
    started=time.monotonic()
    config=settings()
    base=config.get('base_url','').rstrip('/')
    parsed=urlparse(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid model endpoint')
    body=dict(model=config['model'],temperature=0,enable_thinking=False,max_tokens=1600,
        response_format={'type':'json_object'},messages=[{'role':'system','content':prompt(context)},
        {'role':'user','content':message}])
    request=urllib.request.Request(base+'/chat/completions',data=json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+config['api_key'],'Content-Type':'application/json'})
    with guarded_urlopen(request,timeout=30) as response: output=json.loads(response.read(200_000))
    choice=output['choices'][0]
    if choice.get('finish_reason') not in ('stop',None): raise ValueError('Incomplete model response')
    plan=validate_nodes(Plan.model_validate_json(choice['message']['content']))
    return plan,dict(model=config['model'],latency_seconds=round(time.monotonic()-started,3),
        prompt_tokens=output.get('usage',{}).get('prompt_tokens'),
        completion_tokens=output.get('usage',{}).get('completion_tokens'),structured_output_valid=True)


def fallback_intent(message):
    """Explicit rule baseline, never described as a successful LLM call."""
    if '只看' in message and re.search(r'上个月|上月|本月|这个月|\d+月',message) and not re.search(r'转|取消|撤销|停用',message):
        return Intent(intent='bills')
    if re.search(r'花了多少|消费.*多少|花费.*差|消费.*一共|账单|流水|(?:上个月|上月|本月|这个月|\d+月).*(?:一共|总共|合计).*(?:扣|花|付)',message) and not re.search(r'取消|停用|撤销|整理.*代扣',message):
        return Intent(intent='bills')
    if re.search(r'转|汇款|打钱', message):
        amount = re.search(r'(?:转|汇|打)(?:账|款|给)?[^\d-]{0,30}(\d+(?:\.\d{1,2})?)(?:元|块)?', message)
        subtract = re.search(r'少\s*(\d+(?:\.\d{1,2})?)', message)
        reference = bool(re.search(r'上次|上回|照旧|一样', message))
        hint = next((name for name in ('张伟', '房东', '林女士') if name in message), None)
        due = now().date()
        if '后天' in message: due += timedelta(days=2)
        elif '明天' in message: due += timedelta(days=1)
        elif re.search(r'(?:星期|周)[一二三四五六日天]', message):
            day = re.search(r'(?:星期|周)([一二三四五六日天])', message).group(1)
            offset = ('一二三四五六日'.find('日' if day == '天' else day) - due.weekday()) % 7
            if '下周' in message or '下星期' in message:
                offset = 7 - due.weekday() + '一二三四五六日'.find('日' if day == '天' else day)
            due += timedelta(days=offset)
        return Intent(intent='transfer', recipient_hint=hint,
            amount=amount.group(1) if amount and not reference else None,
            reference_last=reference, subtract_amount=subtract.group(1) if subtract else None,
            due_day=due.isoformat())
    if re.search(r'代扣|续费|订阅|会员|一直.*扣|持续.*扣|云盘', message):
        return Intent(intent='subscriptions')
    if re.search(r'账|余额|花|支出|收入|扣费|扣款|多少钱', message): return Intent(intent='bills')
    if re.search(r'诈骗|被骗|安全账户', message): return Intent(intent='safety')
    return Intent(intent='clarify')


def bill_analysis(state, message, previous_scope=None):
    from guardian.bill_scope import analyze
    return analyze(state,message,now().date(),previous_scope)


def _historical_bill_analysis(state, message):
    """Periods and money are computed from bank rows, never guessed by a model."""
    rows = [b for b in state['bills'] if not b['source'].startswith('csv:')]
    today = now().date()
    words = {'本月': 0, '这个月': 0, '这月': 0,
        '上个月': -1, '上月': -1, '上上个月': -2, '上上月': -2}
    offsets = []
    for match in re.finditer(r'上上个月|上上月|上个月|上月|这个月|这月|本月', message):
        offset = words[match.group()]
        if offset not in offsets: offsets.append(offset)

    def aggregate(selected):
        categories = {}
        for b in selected:
            if b['amount'] < 0:
                categories[b['category']] = categories.get(b['category'], 0) - b['amount']
        return dict(expense_cents=sum(categories.values()), categories=categories, rows=selected)

    def period(offset):
        month = today.year * 12 + today.month - 1 + offset
        key = f'{month // 12:04d}-{month % 12 + 1:02d}'
        selected = [b for b in rows if b['day'][:7] == key]
        return dict(period=key, label=f'{key[:4]}年{int(key[5:]):02d}月', **aggregate(selected))

    result = dict(balance_cents=state['balance_cents'], reserved_cents=state['reserved_cents'])
    if not offsets:
        return dict(result, period='当前可用流水', **aggregate(rows))
    first = period(offsets[0])
    result.update(period=first['label'], **aggregate(first['rows']))
    if len(offsets) >= 2 and re.search(r'比|多花|少花|差|变化', message):
        second = period(offsets[1])
        result.update(comparison_periods=[first, second],
            delta_cents=first['expense_cents'] - second['expense_cents'],
            category_deltas={name: first['categories'].get(name, 0) - second['categories'].get(name, 0)
                for name in first['categories'].keys() | second['categories'].keys()})
    return result


class Assistant(TaskRuntimeMixin):
    def __init__(self, engine):
        self.engine = engine
        with engine.tx() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS assistant_tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL,
 kind TEXT NOT NULL,data TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS subscription_preferences(owner TEXT NOT NULL,subscription TEXT NOT NULL,
 preference TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(owner,subscription));
''')

    def save(self, owner, kind, data):
        data.setdefault('revision',1)
        data.setdefault('turns',[{'role':'user','text':data.get('message','')}])
        task = uuid.uuid4().hex
        with self.engine.tx() as c:
            c.execute('INSERT INTO assistant_tasks VALUES(?,?,?,?,?)',
                (task, owner, kind, json.dumps(data, ensure_ascii=False), time.time()))
            self.engine.audit(c, owner, 'ASSISTANT_TASK_CREATED', {'task': task, 'kind': kind,
                'planner': data.get('planner'), 'risk_signals': data.get('risk', {}).get('signals', []),
                'plan':data.get('plan'),'draft':data.get('draft'),'constraint_check':data.get('constraint_check')})
        return self.get(owner, task)

    def row(self, c, owner, task):
        row = c.execute('SELECT * FROM assistant_tasks WHERE id=? AND owner=?', (task, owner)).fetchone()
        if not row: raise Denied('找不到当前账户的办理记录', 'NOT_FOUND')
        return row, json.loads(row['data'])

    def update(self, c, task, data):
        c.execute('UPDATE assistant_tasks SET data=? WHERE id=?', (json.dumps(data, ensure_ascii=False), task))

    def get(self, owner, task):
        with self.engine.tx() as c:
            row, data = self.row(c, owner, task)
        data = dict(data, id=task, kind=row['kind'], created=row['created'])
        data['operations'] = [self.engine.get_operation(owner, op) for op in data.get('operation_ids', [])]
        if data['operations']:
            active = [o for o in data['operations'] if o['status'] != 'CANCELLED']
            if active and data.get('status') not in ('PAUSED','HANDOFF','DECLINED'):
                data['status'] = 'DONE' if all(o['status'] == 'SUCCEEDED' for o in active) else 'ACTION_PENDING'
            data['steps'][-1]['status'] = 'DONE' if data['status'] == 'DONE' else 'WAITING'
            # Read back only subscriptions named by successfully approved writes.
            # Do not silently refresh all protocol data without query consent.
            succeeded = [o['payload']['subscription_id'] for o in data['operations']
                if o['kind'] == 'cancel_subscription' and o['status'] == 'SUCCEEDED']
            with self.engine.tx() as c:
                for sub in data.get('subscriptions', []):
                    if sub['id'] in succeeded:
                        actual = c.execute('SELECT status FROM subscriptions WHERE id=? AND owner=?', (sub['id'], owner)).fetchone()
                        if actual: sub['status'] = actual[0]
        return self.decorate(data,owner)

    def history(self, owner):
        with self.engine.tx() as c:
            ids = [r[0] for r in c.execute('SELECT id FROM assistant_tasks WHERE owner=? ORDER BY created DESC LIMIT 30', (owner,))]
        return [self.get(owner, task) for task in ids]

    def message(self, owner, message, task_id=None, revision=None):
        return self.process_message(owner,message,task_id,revision)

    def _legacy_message(self, owner, message):
        risk = assess(message)
        if risk['blocked']:
            self.engine.hold_transfer(owner, risk)
            return self.save(owner, 'safety', dict(message=message, planner='deterministic_safety_gate',
                risk=risk, status='STOPPED', text=risk['title'], operation_ids=[],
                steps=[dict(label='核查用户描述', status='DONE'), dict(label='暂停资金操作，等待人工核实', status='STOPPED')]))
        # Never silently drop a user-specified financial constraint that the
        # first slice cannot enforce. It is not delegated to model discretion.
        unsupported_condition = re.search(
            r'至少留|保留|留出|不低于|低于|不够|不足|最低余额|余额底线|'
            r'(?:剩|余|留|还有|还要有|还得有).{0,12}(?:\d|[零一二三四五六七八九十百千万两]|生活费)|'
            r'余额.{0,10}(?:至少|最少|不能少|不少于)', message)
        if re.search(r'转|汇款|打钱', message) and unsupported_condition:
            return self.save(owner, 'clarify', dict(message=message, planner='deterministic_capability_gate',
                status='CLARIFY', operation_ids=[], text='这项转账带有余额条件，当前版本还不能完整执行这类条件任务，因此没有准备付款。可以先查余额，或改为你已核实的明确转账。',
                steps=[dict(label='识别转账条件', status='DONE'), dict(label='条件执行能力不足，等待补充或接管', status='WAITING')]))
        planner, unavailable = 'rule_baseline', False
        try:
            intent = model_intent(message) if configured() else fallback_intent(message)
            if configured(): planner = 'llm'
        except Exception:
            # Provider errors contain no details in the public result or audit.
            intent, unavailable = fallback_intent(message), True
        data = dict(message=message, planner=planner, model_unavailable=unavailable,
            status='READY', operation_ids=[], risk=risk)
        if intent.intent == 'subscriptions':
            data.update(status='CONSENT_REQUIRED', text='先确认查询银行代扣，再一起看看哪些还需要。',
                steps=[dict(label='确认查询银行代扣', status='WAITING'),
                    dict(label='核对扣费记录与使用意愿', status='PENDING'),
                    dict(label='确认后办理并回读', status='PENDING')])
        elif intent.intent == 'transfer':
            candidates = [c for c in self.engine.contacts() if intent.recipient_hint and
                (intent.recipient_hint in c['name'] or intent.recipient_hint == c['id'])]
            data.update(text='先核对收款人、金额与执行日期。', candidates=candidates or self.engine.contacts(),
                draft=intent.model_dump(), steps=[dict(label='明确收款人和金额', status='WAITING'),
                    dict(label='校验余额、限额与风险', status='PENDING'),
                    dict(label='确认、验证并办理', status='PENDING')])
            if len(candidates) == 1:
                data['draft']['recipient'] = candidates[0]['id']
                if intent.reference_last:
                    ops = self.engine.snapshot(owner)['operations']
                    previous = next((o for o in ops if o['kind'] == 'transfer' and o['status'] == 'SUCCEEDED'
                        and o['payload']['recipient'] == candidates[0]['id']), None)
                    if previous:
                        amount = previous['payload']['amount_cents'] - (money(intent.subtract_amount) if intent.subtract_amount else 0)
                        if amount > 0:
                            data['draft']['amount'] = f'{amount // 100}.{amount % 100:02d}'
                            data['reference_operation'] = previous['id']
                        else: data['text'] = '调整后的金额不是正数，请重新说明金额。'
                    else: data['text'] = '没有查到可引用的已完成付款，请明确本次金额。'
        elif intent.intent == 'bills':
            state = self.engine.snapshot(owner)
            analysis = bill_analysis(state, message)
            data.update(status='DONE', text='按账户流水算好了，点开可以核对每一笔。',
                analysis=analysis, steps=[dict(label='读取账户流水', status='DONE'),
                        dict(label='按分类汇总并保留来源', status='DONE')])
        else:
            data.update(status='CLARIFY', text='你想查账、转账，还是整理代扣？请再说具体一点。',
                steps=[dict(label='等待补充需求', status='WAITING')])
        return self.save(owner, intent.intent, data)

    def reveal(self, owner, task, confirmed):
        if not confirmed: raise Denied('请先确认查询银行代扣信息', 'APPROVAL')
        with self.engine.tx() as c:
            row, data = self.row(c, owner, task)
            if row['kind'] != 'subscriptions': raise Denied('不是代扣办理任务', 'STATE')
            self.engine.check_lock(c, owner)
            subs = [dict(s) for s in c.execute('SELECT * FROM subscriptions WHERE owner=?', (owner,))]
            if data.get('source_task_id') and data.get('source_mode','related')=='related':
                source_ids=set(data.get('source_evidence_ids',[]))
                # Only owner-scoped bank rows may propose protocol candidates.
                # Name equality is an explainable candidate, not a verified
                # bank protocol identifier or permission to cancel anything.
                source_rows=[dict(r) for r in c.execute("SELECT id,merchant FROM ledger WHERE owner=? AND source NOT LIKE 'csv:%'",(owner,)) if r['id'] in source_ids]
                links=[]
                for r in source_rows:
                    matches=[s['id'] for s in subs if s['name']==r['merchant']]
                    links.append(dict(evidence_id=r['id'],candidate_protocol_ids=matches,
                        status='NAME_CANDIDATE' if len(matches)==1 else 'AMBIGUOUS' if matches else 'NO_MATCH'))
                candidate_ids={sid for link in links for sid in link['candidate_protocol_ids']}
                subs=[s for s in subs if s['id'] in candidate_ids]
                for s in subs:
                    s['matched_evidence_ids']=[link['evidence_id'] for link in links if s['id'] in link['candidate_protocol_ids']]
                    s['match_basis']='所选流水的商户名称与协议名称一致；请继续核对具体协议。'
                data['protocol_links']=links
                data['link_status']='CANDIDATES' if subs else 'NO_MATCH'
            for sub in subs:
                observations = [dict(b) for b in c.execute(
                    "SELECT id,day,amount,source FROM ledger WHERE owner=? AND merchant=? AND source NOT LIKE 'csv:%' ORDER BY day DESC", (owner, sub['name']))]
                preference = c.execute('SELECT preference FROM subscription_preferences WHERE owner=? AND subscription=?', (owner, sub['id'])).fetchone()
                sub.update(observations=observations, preference=preference[0] if preference else 'unknown',
                    usage_evidence='没有应用使用记录；需要由你确认是否还在使用。')
            data.update(subscriptions=subs, consent_at=time.time(), status='REVIEW',
                text='这些是银行协议与对应扣费记录。用途可能相近，是否还需要由你决定。')
            if data.get('source_task_id') and data.get('source_mode','related')=='related':
                data['text']='已按所选扣款找到协议候选，请核对名称和扣费依据；没有自动撤销。' if subs else '所选账单没有匹配到代扣协议。没有扩大查询或执行撤销；如需查看其他项目，请明确说“查询全部代扣”。'
            before=json.loads(json.dumps(data))
            self.apply_choices(owner,data)
            self.persist_choices(c,owner,before,data,task)
            data['revision']=data.get('revision',1)+1
            data['steps'][0]['status'] = 'DONE'
            data['steps'][1]['status'] = 'WAITING'
            self.update(c, task, data)
            self.engine.audit(c, owner, 'SUBSCRIPTIONS_QUERY_CONFIRMED', {'task': task})
        return self.get(owner, task)

    def preference(self, owner, task, subscription, preference):
        with self.engine.tx() as c:
            row, data = self.row(c, owner, task)
            before=json.loads(json.dumps(data))
            if row['kind'] != 'subscriptions' or not data.get('consent_at'):
                raise Denied('尚未确认读取协议', 'APPROVAL')
            if time.time() - data['consent_at'] > 600: raise Denied('查询已过期，请重新查询', 'EXPIRED')
            sub = next((s for s in data['subscriptions'] if s['id'] == subscription), None)
            if not sub: raise Denied('只能选择本次查询的协议', 'SUBSCRIPTION')
            c.execute('INSERT OR REPLACE INTO subscription_preferences VALUES(?,?,?,?)',
                (owner, subscription, preference, time.time()))
            sub['preference'] = preference
            self.persist_choices(c,owner,before,data,task)
            data['revision']=data.get('revision',1)+1
            self.update(c, task, data)
            self.engine.audit(c, owner, 'SUBSCRIPTION_PREFERENCE_SET', {'task': task,
                'subscription': subscription, 'preference': preference, 'source': 'explicit_user_choice'})
        return self.get(owner, task)

    def prepare_subscription(self, owner, task, subscription, revision=None):
        data = self.get(owner, task)
        if revision is not None and revision!=data.get('revision',1): raise Denied('任务已更新，请刷新。','STALE_TASK')
        if data.get('status') in ('PAUSED','HANDOFF'): raise Denied('任务已暂停或交由人工处理。','TASK_PAUSED')
        sub = next((s for s in data.get('subscriptions', []) if s['id'] == subscription), None)
        if not sub or not data.get('consent_at') or time.time() - data['consent_at'] > 600:
            raise Denied('请先重新确认查询并核对协议', 'APPROVAL')
        if sub['preference'] != 'unneeded': raise Denied('请先明确标记不再需要', 'APPROVAL')
        op = self.engine.prepare(owner, 'cancel_subscription', {'subscription_id': subscription},
            'task_' + task + '_' + subscription.split(':')[-1],task_id=task,task_revision=revision)
        self.link(owner, task, op['id'])
        return dict(operation=op, subscription=sub, task=self.get(owner, task))

    def prepare_transfer(self, owner, task, recipient, amount, due_day, revision=None):
        data = self.get(owner, task)
        if revision is not None and revision!=data.get('revision',1): raise Denied('任务已更新，请刷新。','STALE_TASK')
        if data['kind'] != 'transfer': raise Denied('不是转账办理任务', 'STATE')
        if data.get('status') in ('PAUSED','HANDOFF') or any(data.get(flag) for flag in ('unresolved_constraint','unsupported_currency','unresolved_amount','unresolved_schedule')):
            raise Denied('任务仍有暂停或未明确条件，不能准备付款。','TASK_PAUSED')
        # User-editable details are newly bound by Engine.prepare; old approvals
        # cannot authorize a new amount, recipient or execution day.
        floor=data.get('draft',{}).get('minimum_balance')
        key = 'task_' + task + '_' + __import__('hashlib').sha256(
            json.dumps([recipient, amount, due_day,floor]).encode()).hexdigest()[:16]
        payload=dict(recipient=recipient,amount=amount,due_day=due_day,note=data.get('initial_message',data['message'])[:200])
        if floor: payload['minimum_balance']=floor
        op = self.engine.prepare(owner, 'transfer', payload, key, task_id=task,task_revision=revision)
        self.link(owner, task, op['id'])
        return dict(operation=op, task=self.get(owner, task))

    def link(self, owner, task, op):
        with self.engine.tx() as c:
            _, data = self.row(c, owner, task)
            ids = data.setdefault('operation_ids', [])
            if op not in ids: ids.append(op)
            self.update(c, task, data)
