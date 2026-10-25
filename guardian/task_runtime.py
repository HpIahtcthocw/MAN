"""Persistent, revisioned execution of a bounded bank task plan.

Only read nodes run automatically. Drafts, approvals and dispatch remain separate
bank endpoints. Model output cannot call them, clear a hold, or mint consent.
"""
import copy
import json
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta

from guardian.engine import Denied, money, now
from guardian.fraud import assess, educational_question
from guardian.task_planner import Plan, Choice, template, validate_nodes, LABELS, floor_from_text, has_floor_condition, cn_number
from guardian.language import contact_hint, explicit_edit_amount, ambiguous_amount, deterministic_edit

# Bare session-control utterances that carry no business slot: the model adds no
# information over the deterministic action, so they skip the model round trip.
PURE_SESSION_CONTROL=(r'(?:请)?(?:先别(?:再)?(?:转|办|付|扣|动|弄)?了?|先不办了?|先暂停(?:一下)?|'
    r'暂停(?:一下|先)?(?:办理|转账|付款|扣款|这件事|这项任务)?|等等?|(?:继续|恢复)(?:办理|这件事|这项任务|转账|付款)?)[。！!？?\s]*')


def normalized(text):
    return re.sub(r'\s|[（）()·]|会员|服务','',unicodedata.normalize('NFKC',text)).lower()


def direct_amount(message):
    message=re.sub(r'尾号\s*[0-9]{4}|第[一二三123](?:个|位)|1[3-9][0-9]{9}|\d{4}-\d{2}-\d{2}','',message)
    found=re.search(r'(?:转|汇|打)(?:账|款|给)?[^0-9零一二三四五六七八九十百千万两-]{0,24}'
        r'([0-9零一二三四五六七八九十百千万两]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)',message)
    if not found:
        found=re.search(r'(?:金额改成|金额改为|改成|改为)\s*([0-9零一二三四五六七八九十百千万两]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)',message)
    return explicit_edit_amount(message) or (cn_number(found.group(1)) if found else None)


def preference_word(clause):
    if re.search(r'不要取消|别取消|别停|不要停|先不停|继续用|还在用|仍在用|还要用|保留|留着',clause): return 'using'
    if re.search(r'不用|不需要|不再|停掉|停止|撤销|取消|(?:只|就)停\s*[A-Za-z\u4e00-\u9fff]',clause): return 'unneeded'
    if re.search(r'不确定|不知道|没想好',clause): return 'unknown'
    return None


class TaskRuntimeMixin:
    def safe_context(self, owner, row_kind, data):
        return dict(kind=row_kind, draft=data.get('draft',{}),bill_query=data.get('bill_query'), contacts=self.engine.contacts(),
            turns=data.get('turns',[])[-6:], subscriptions=[
                {'name':s['name'],'preference':s.get('preference'),'status':s['status']}
                for s in data.get('subscriptions',[])])

    def rule_plan(self, message, context):
        from guardian.assistant import fallback_intent
        intent=fallback_intent(message)
        current=context.get('kind')
        update=bool(current and (intent.intent=='clarify' or re.search(r'改成|改为|那个|那位|留着|先别|暂停|继续|人工|不用了|还在用',message)))
        kind=current if update else intent.intent
        if kind not in ('transfer','subscriptions','bills','safety_info','card'): kind='clarify'
        pause=bool(re.search(r'先别|暂停|先不办',message) or ('等等' in message and explicit_edit_amount(message) is None))
        action='handoff' if re.search(r'转人工|找人工|人工接管|人工核实',message) else 'pause' if pause else 'resume' if re.search(r'继续',message) else 'update'
        hint=intent.recipient_hint
        if current=='transfer':
            hint=next((v for v in ('同学','同事','房东','林女士','张伟') if v in message),hint)
        due=None
        if re.search(r'今天|明天|后天|(?:周|星期)[一二三四五六日天]',message):
            due=fallback_intent('转1，'+message).due_day
        amount=direct_amount(message)
        choices=[]
        if kind=='subscriptions':
            for clause in re.split(r'[，,。；;！!?？\n]',message):
                pref=preference_word(clause)
                if pref:
                    target=next((v for v in ('云盘A','云盘B','视频','A','B') if v.lower() in normalized(clause)),None)
                    if target: choices.append(Choice(target=target,preference=pref,evidence=clause.strip()))
        return Plan(intent=kind,action=action,recipient_hint=hint,amount=amount,due_day=due,
            minimum_balance=floor_from_text(message),reference_last=intent.reference_last,
            subtract_amount=intent.subtract_amount,choices=choices,nodes=template(kind))

    def process_message(self, owner, message, task_id=None, revision=None):
        from guardian.assistant import configured, model_plan, bill_analysis
        old=None;kind=None
        if task_id:
            with self.engine.tx() as c:
                row,old=self.row(c,owner,task_id);kind=row['kind']
            expected=old.get('revision',1)
            if revision is not None and revision!=expected: raise Denied('任务已更新，请先刷新当前内容。','STALE_TASK')
            if len(old.get('turns',[]))>=20: raise Denied('本任务已达到20轮，请在核对现有操作后新建任务。','TURN_LIMIT')
            if old.get('status')=='HANDOFF': raise Denied('接管资料待人工核实，聊天不能解除接管状态。','TASK_PAUSED')
        else: expected=0

        risk=assess(message)
        if risk['blocked'] and educational_question(message):
            # A read-only quotation explanation cannot create a transfer task or
            # release a previous account hold, irrespective of model output.
            return self.save(owner,'safety_info',dict(message=message,initial_message=message,revision=1,
                turns=[{'role':'user','text':message}],status='DONE',planner='deterministic_context_gate',
                text='这段宣传是在提醒：不要按陌生人的要求把钱转到所谓“安全账户”。这是解释性查询，没有发起转账，也不会解除已有安全暂停。',
                operation_ids=[],plan=[n.model_dump() for n in template('safety_info')],steps=[{'label':'解释引用的反诈提醒','status':'DONE'}]))
        if risk['blocked']:
            self.engine.hold_transfer(owner,risk)
            return self.save(owner,'safety',dict(message=message,initial_message=message,revision=1,
                turns=[{'role':'user','text':message}],status='STOPPED',planner='deterministic_safety_gate',
                risk=risk,text=risk['title']+'（'+'；'.join(risk['signals'])+'）',operation_ids=[],plan=[],steps=[{'label':'核查用户描述','status':'DONE'},
                {'label':'暂停资金操作，等待人工核实','status':'STOPPED'}]))

        context=self.safe_context(owner,kind,old or {})
        mode='rule_baseline';meta=None;unavailable=False
        try:
            if not old and re.fullmatch(r'(?:请)?(?:帮我)?(?:查余额|查询余额|余额多少|余额还有多少|可用余额|账户余额)[？?。！!\s]*',message):
                plan=Plan(intent='bills',nodes=template('bills'));mode='deterministic_query'
                meta={'model_called':False,'reason':'exact_read_only_balance_query','structured_output_valid':True}
            elif old and deterministic_edit(message,kind):
                plan=self.rule_plan(message,context);mode='validated_edit'
                meta={'model_called':False,'reason':'exact_scoped_edit','structured_output_valid':True}
            elif old and re.fullmatch(PURE_SESSION_CONTROL,message.strip()):
                # A bare pause/resume carries no new semantic slot; the rule plan
                # already sets the action and keeps every draft field unchanged.
                plan=self.rule_plan(message,context);mode='deterministic_session_control'
                meta={'model_called':False,'reason':'pure_pause_or_resume','structured_output_valid':True}
            elif configured():
                plan,meta=model_plan(message,context);mode='llm'
            else: plan=self.rule_plan(message,context)
        except Exception as error:
            plan=self.rule_plan(message,context);unavailable=True
            meta={'structured_output_valid':False,'failure_category':type(error).__name__}
        validate_nodes(plan)
        if old and kind=='transfer' and re.search(r'转了|转出去|到账|结果|成功|扣了',message):
            unknown_ids=[op_id for op_id in old.get('operation_ids',[])
                         if self.engine.get_operation(owner,op_id)['status']=='UNKNOWN']
            if unknown_ids:
                plan=Plan(intent='transfer',action='resume',nodes=template('transfer'))
                mode='deterministic_reconcile_inquiry'
                meta={'model_called':False,'reason':'unknown_reconcile_inquiry','structured_output_valid':True}
        source=None
        clarified_kind=None
        if old and kind in ('clarify','unsupported') and not old.get('operation_ids') and plan.intent in ('transfer','bills','subscriptions'):
            # A clarification is the beginning of the same task, not a reason
            # to force the user to restart after supplying the missing intent.
            clarified_kind=plan.intent
            kind=plan.intent
        if old and plan.intent not in (kind,'clarify','unsupported'):
            if kind=='bills' and plan.intent=='subscriptions':
                source={'source_task_id':task_id,'source_mode':'related','source_scope':old.get('analysis',{}).get('scope'),
                    'source_evidence_ids':[r['id'] for r in old.get('analysis',{}).get('rows',[])]}
                old=None;kind=None;task_id=None;expected=0
            else:
                raise Denied('这是另一类业务，请点“新办一件事”；原任务和批准不会被合并。','NEW_TASK_REQUIRED')
        task_kind=kind or plan.intent
        data=copy.deepcopy(old) if old else {'operation_ids':[],'initial_message':message}
        if source: data.update(source)
        data.update(message=message,revision=expected+1,planner=mode,model_meta=meta,
            model_unavailable=unavailable,risk=risk,status='READY')
        data['query_proposal']=plan.bill_query.model_dump() if plan.bill_query else None
        was_paused=bool(old and old.get('status')=='PAUSED')
        explicit_resume=bool(re.fullmatch(r'(?:请)?(?:继续|恢复)(?:办理|这项任务|转账)?[。！!\s]*',message.strip()))
        data.setdefault('turns',[]).append({'role':'user','text':message})
        data['plan']=[n.model_dump() for n in (plan.nodes if plan.intent==task_kind else template(task_kind))]
        data['steps']=[{'label':LABELS[n['tool']],'status':'PENDING'} for n in data['plan']]
        if not data['steps']: data['steps']=[{'label':'补充明确的业务需求','status':'WAITING'}]

        if task_kind=='transfer':
            from guardian.language import split_request
            split=split_request(message,self.engine.contacts())
            if split:
                # A split request replaces the single-recipient draft; the old
                # draft is dropped so it cannot be prepared alongside new intent.
                data['draft']={}
                data.update(status='CLARIFY',text=split['text'],
                    steps=[{'label':'计算拆分金额','status':'DONE'},
                           {'label':'按提示逐笔发起，每笔单独核对批准','status':'WAITING'}])
                if split['state']=='plan':
                    data['split_plan']=dict(total_cents=split['total_cents'],shares=split['shares'],
                        note='只读拆分建议；不会自动创建或执行多笔转账。')
                    first=split['shares'][0]
                    first_amount=first['amount_cents']/100
                    first_text=str(int(first_amount)) if first['amount_cents']%100==0 else f'{first_amount:.2f}'
                    data['suggestions']=[{'label':f'先办：给{first["name"]}转{first_text}','message':f'给{first["name"]}转{first_text}'}]
                return self.save(owner,task_kind,data)
            d=data.setdefault('draft',{})
            original_reference=(d.get('recipient'),d.get('subtract_amount'))
            grounded=direct_amount(message)
            for field in ('amount','due_day','minimum_balance','subtract_amount'):
                value=getattr(plan,field)
                if field=='minimum_balance': continue  # Only an explicit host-parsed condition binds money.
                if old and field=='amount' and grounded is None: continue
                if old and field=='due_day' and not re.search(r'今天|明天|后天|周|星期|\d{4}-\d{2}-\d{2}',message): continue
                if value is not None: d[field]=value
            if grounded is not None and not plan.reference_last: d['amount']=grounded
            # Host-parsed explicit conditions outrank model interpretation.
            floor=floor_from_text(message)
            if floor is not None: d['minimum_balance']=floor
            if has_floor_condition(message) and floor is None:
                data.update(status='CLARIFY',text='需要保留多少钱？请明确金额，当前没有准备付款。')
                data['unresolved_constraint']=True
            elif floor is not None: data.pop('unresolved_constraint',None)
            if ambiguous_amount(message):
                data.update(status='CLARIFY',text='金额表达有歧义，请使用正数、最多两位小数的元金额。当前没有准备付款。',unresolved_amount=True)
            elif mode=='llm' and grounded is not None and plan.amount is not None and money(grounded)!=money(plan.amount):
                data.update(status='CLARIFY',text='对这次金额的理解不一致，请明确说“金额改为多少元”；当前不会准备付款。',unresolved_amount=True)
            elif old and grounded is None and plan.amount is not None and money(plan.amount)!=money(d.get('amount') or '0'):
                # Never silently retain the old amount after an ungrounded
                # correction. A model proposal alone cannot overwrite money.
                data.update(status='CLARIFY',text='你似乎修改了金额，请明确说“金额改为多少元”。确认前不会沿用旧金额付款。',unresolved_amount=True)
            elif grounded is not None: data.pop('unresolved_amount',None)
            if re.search(r'美元|美金|港币|USD|HKD',message,re.I):
                data.update(status='CLARIFY',text='当前只支持人民币，请核对币种。');data['unsupported_currency']=True
            elif '人民币' in message: data.pop('unsupported_currency',None)
            if re.search(r'下下周|下下星期|月底|月末|\d{1,2}[点时]|上午|下午|晚上|明早|明晚',message):
                data.update(status='CLARIFY',text='当前预约支持未来30天内的日期，不支持具体时刻或“月底”等范围。请明确哪天发起。',unresolved_schedule=True)
            elif re.search(r'今天|明天|后天|周|星期|\d{4}-\d{2}-\d{2}',message): data.pop('unresolved_schedule',None)
            # A date-only edit cannot undo an already resolved recipient even
            # when the model redundantly emits the old ambiguous full name.
            hint=contact_hint(message,self.engine.contacts(),plan.recipient_hint,(old or {}).get('candidates'))
            if hint:
                matches=[c for c in self.engine.contacts() if normalized(hint) in normalized(c['name']) or hint==c['id'] or hint==c.get('phone')]
                data['candidates']=matches or self.engine.contacts()
                d['recipient']=matches[0]['id'] if len(matches)==1 else None
                d['recipient_hint']=hint
            else: data.setdefault('candidates',self.engine.contacts())
            if 'due_day' not in d or not d['due_day']: d['due_day']=now().date().isoformat()
            if re.search(r'今天|明天|后天|(?:周|星期)[一二三四五六日天]',message):
                from guardian.assistant import fallback_intent
                d['due_day']=fallback_intent('转1，'+message).due_day
            if plan.reference_last: d.update(reference_last=True,subtract_amount=plan.subtract_amount)
            if original_reference!=(d.get('recipient'),d.get('subtract_amount')) and d.get('reference_last'):
                d.pop('reference_resolved',None);d.pop('amount',None);data.pop('reference_operation',None)
            if grounded is not None and not plan.reference_last:
                d.update(amount=grounded,reference_last=False);d.pop('reference_resolved',None);data.pop('reference_operation',None)
            note_match=re.search(r'(?:备注|附言|留言)[:：]?\s*([^\s，,。；;！!？?<>"]{1,30})',message)
            if note_match: d['user_note']=note_match.group(1)[:30]
            if re.search(r'(?:不要|去掉|取消)(?:备注|附言|留言)',message): d.pop('user_note',None)
            self.resolve_transfer(owner,data)
        elif task_kind=='subscriptions':
            if data.get('source_task_id') and re.search(r'(?:全部|所有).{0,8}(?:代扣|订阅|协议)|(?:代扣|订阅|协议).{0,8}(?:全部|所有)',message):
                data['source_mode']='all'
                data.pop('protocol_links',None);data.pop('link_status',None)
                data.pop('consent_at',None);data.pop('subscriptions',None)
            snapshot=self.engine.snapshot(owner)
            data['bill_evidence_ids']=[b['id'] for b in snapshot['bills']]
            data.setdefault('pending_choices',[])
            for choice in plan.choices:
                if choice.evidence not in message: raise Denied('项目选择缺少本轮原话依据，请重新核对。','EVIDENCE')
                data['pending_choices'].append(choice.model_dump())
            if not data.get('consent_at') or time.time()-data['consent_at']>600:
                data.update(status='CONSENT_REQUIRED',text='先确认查询银行代扣，再核对哪些仍然需要。')
                # Expired protocol data cannot be used for new choices.
                data.pop('subscriptions',None)
            else:
                self.apply_choices(owner,data,message)
                data.update(status='REVIEW',text='已按你这轮的话更新选择，请核对具体协议；没有执行撤销。')
        elif task_kind=='bills':
            analysis=bill_analysis(self.engine.snapshot(owner),message,(old or {}).get('bill_query') or (old or {}).get('analysis'),plan.bill_query)
            if mode=='llm' and plan.bill_query is None:
                analysis={'needs_clarification':True,'question':'这次查询缺少可核对的范围提案，请明确期间、分类或商户；当前没有给出金额。'}
            if analysis.get('needs_clarification'):
                data.pop('analysis',None)
                clarify_update=dict(status='CLARIFY',text=analysis['question'])
                if analysis.get('suggestions'): clarify_update['suggestions']=analysis['suggestions']
                data.update(clarify_update)
            else:
                data['bill_query']=analysis['query']
                anomalies=analysis.get('anomalies') or []
                text=('账单范围和金额已按银行流水计算，下面保留原始依据。' if not anomalies else
                    f'账单范围和金额已按银行流水计算；其中 {len(anomalies)} 笔被标记为异常候选（金额突增或首次大额），依据在下方，只作核对提示，不会自动处理。')
                data.update(status='DONE',text=text,analysis=analysis)
        elif task_kind=='card':
            cards=self.engine.cards(owner)
            d=data.setdefault('draft',{});d.setdefault('action','report_lost')
            active=[c for c in cards if c['status']=='ACTIVE']
            if not d.get('card_id'):
                tail=re.search(r'尾号\s*([0-9]{4})',message)
                qualifier=re.search(r'(工资|储蓄|信用)(?:卡)?',message)
                all_matched=[c for c in cards if (tail and c['last4']==tail.group(1)) or (qualifier and qualifier.group(1) in c['name'])]
                active=[c for c in cards if c['status']=='ACTIVE']
                if len(all_matched)==1: d['card_id']=all_matched[0]['id']
                elif len(active)==1 and not qualifier and not tail: d['card_id']=active[0]['id']
                else:
                    data.update(status='CLARIFY',text='哪张卡丢了？请说明是哪一张，挂失只针对选中的这张。',
                        suggestions=[{'label':'挂失'+c['name'],'message':'挂失'+c['name']} for c in active])
                    return self.save(owner,task_kind,data)
            card=next((c for c in cards if c['id']==d['card_id']),None)
            if card is None:
                data.update(status='CLARIFY',text='这张卡不在你的名下，请重新说明。');return self.save(owner,task_kind,data)
            if card['status']!='ACTIVE':
                data.update(status='DONE',text=card['name']+'已经挂失，不用重复办理。补卡请到柜台或银行App办理。',
                    steps=[{'label':'核对卡片状态','status':'DONE'}])
                return self.save(owner,task_kind,data)
            data['card']=dict(id=card['id'],name=card['name'],last4=card['last4'],status=card['status'])
            data.update(status='READY',text='要挂失的是：'+card['name']+'。挂失后这张卡不能再付款，绑在卡上的自动扣费也会扣款失败；挂失之后我会把要处理的事列给你。挂失是重要操作，需要短信验证。')
        else:
            data.update(status='CLARIFY',text='你想查账、转账，还是整理代扣？请再说具体一点。',
                suggestions=[{'label':'查账单','message':'这个月花了多少'},{'label':'办转账','message':'我要转账'},{'label':'整理代扣','message':'这几个月一直在扣的钱，帮我看看'},{'label':'卡丢了','message':'我的卡丢了'}])

        if plan.action=='pause' and task_kind=='subscriptions' and plan.choices:
            # A concrete preference clause (“视频会员不用了”) is an instruction,
            # not a pause request; the model's pause reading is overridden.
            plan.action='update'
        if plan.action=='pause': data.update(status='PAUSED',text='已暂停，没有转出任何钱。未执行的草稿会失效，已付款不会被撤回。')
        elif plan.action=='resume':
            for op_id in data.get('operation_ids',[]):
                op=self.engine.get_operation(owner,op_id)
                if op['status']=='UNKNOWN': self.engine.recover(owner,op_id)
        # An anxious "did the money go out?" after a lost response must trigger
        # reconciliation on its own — waiting for the word 继续 is not senior-safe.
        if old and task_kind=='transfer' and re.search(r'转了|转出去|到账|结果|成功|扣了',message):
            unknown_ops=[op_id for op_id in data.get('operation_ids',[]) if self.engine.get_operation(owner,op_id)['status']=='UNKNOWN']
            if unknown_ops:
                for op_id in unknown_ops: self.engine.recover(owner,op_id)
                recovered=self.engine.get_operation(owner,unknown_ops[0])
                if recovered['status']=='SUCCEEDED':
                    data.update(status='DONE',text='查过了：钱已经转出去，回执在下面，只动了这一笔。')
        if plan.action=='handoff': data.update(status='HANDOFF',text='已准备人工接管资料；这不是银行坐席已接单。')
        if was_paused and not explicit_resume and plan.action!='handoff':
            data.update(status='PAUSED',text='补充已保留，这项任务仍然暂停；只有明确说“继续办理”后才会重新核对。')
        material=task_kind=='transfer' and ((old or {}).get('draft',{})!=data.get('draft',{}) or
            any(data.get(flag) for flag in ('unresolved_constraint','unresolved_amount','unsupported_currency','unresolved_schedule')))
        if task_id:
            with self.engine.tx() as c:
                _,current=self.row(c,owner,task_id)
                if current.get('revision',1)!=expected: raise Denied('任务已更新，请刷新再补充。','STALE_TASK')
                if material or plan.action=='pause': self.invalidate_drafts(c,owner,current,task_id)
                if plan.action=='handoff':
                    for op_id in current.get('operation_ids',[]):
                        if self.engine.operation(c,owner,op_id)['status'] in ('CONFIRMED','SCHEDULED'):
                            raise Denied('请先撤销已确认但未执行的操作，再提交接管。','TASK_IN_FLIGHT')
                if task_kind=='subscriptions':
                    self.persist_choices(c,owner,current,data,task_id)
                    if data.get('pending_choices'):
                        self.invalidate_drafts(c,owner,current,task_id)
                        data.update(status='CLARIFY',text='这次保留或停用的对象还需核对，旧草稿已失效。请逐项选择，当前没有执行撤销。')
                self.update(c,task_id,data)
                if clarified_kind:
                    c.execute('UPDATE assistant_tasks SET kind=? WHERE id=? AND owner=?',(clarified_kind,task_id,owner))
                self.engine.audit(c,owner,'TASK_REVISED',{'task':task_id,'revision':data['revision'],'planner':mode,
                    'material':material,'plan':data['plan'],'draft':data.get('draft'),
                    'constraint_check':data.get('constraint_check'),'pending_choices':data.get('pending_choices')})
            result=self.get(owner,task_id)
        else: result=self.save(owner,task_kind,data)
        if plan.action=='handoff': self.create_handoff(owner,result['id'])
        return self.get(owner,result['id'])

    def resolve_transfer(self,owner,data):
        d=data['draft']
        if d.get('reference_last') and d.get('recipient') and not d.get('reference_resolved'):
            previous=next((o for o in self.engine.snapshot(owner)['operations'] if o['kind']=='transfer'
                and o['status']=='SUCCEEDED' and o['payload']['recipient']==d['recipient']),None)
            if previous:
                value=previous['payload']['amount_cents']-(money(d['subtract_amount']) if d.get('subtract_amount') else 0)
                if value>0:
                    d['amount']=f'{value//100}.{value%100:02d}';d['reference_resolved']=True
                    data['reference_operation']=previous['id']
        if not d.get('recipient'):
            data.update(status='CLARIFY',text='你要转给哪位？请在候选中核对，或者接着告诉我。',
                suggestions=[{'label':'转给'+c['name'],'message':'就转给'+c['name']} for c in data.get('candidates',[])][:4]);return
        if not d.get('amount'):
            data.update(status='CLARIFY',text='本次转多少元？没有可引用的付款时，需要你明确金额。');return
        amount=money(d['amount'])
        try: datetime.strptime(d['due_day'],'%Y-%m-%d')
        except ValueError: raise Denied('日期无法识别，请使用有效的年月日。','DATE')
        if not now().date().isoformat()<=d['due_day']<=(now().date()+timedelta(days=30)).isoformat():
            raise Denied('执行日期须在今天至未来30天内。','DATE')
        if any(data.get(flag) for flag in ('unresolved_constraint','unsupported_currency','unresolved_amount','unresolved_schedule')): return
        with self.engine.tx() as c:
            balance=self.engine.balance(c,owner);reserved=self.engine.reserved(c,owner)
            floor=self.engine.required_floor(c,owner)
        requested=money(d['minimum_balance']) if d.get('minimum_balance') else 0
        required=max(floor,requested)
        projected=balance-reserved-amount
        data['constraint_check']=dict(balance_cents=balance,reserved_cents=reserved,
            amount_cents=amount,requested_floor_cents=requested,required_floor_cents=required,
            projected_balance_cents=projected,decision='INSUFFICIENT_AFTER_FLOOR' if projected<required else 'PASS')
        data['text']='对象、金额、日期和余额条件已核对；下一步仍由你批准。'
        if projected<required:
            data.update(status='DECLINED',text=f'当前可用余额不足以满足这笔付款及保留条件：预计剩{projected/100:.2f}元，需要保留{required/100:.2f}元，没有准备付款。')

    def invalidate_drafts(self,c,owner,current,task):
        for op_id in current.get('operation_ids',[]):
            row=self.engine.operation(c,owner,op_id)
            if row['status']=='CANCELLED': continue
            if row['status']!='PREPARED': raise Denied('原操作已确认、已付款或状态未知，先核查/撤销原操作，不能用改口覆盖。','TASK_IN_FLIGHT')
            c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(op_id,))
            c.execute('DELETE FROM challenges WHERE op=?',(op_id,))
            self.engine.audit(c,owner,'DRAFT_SUPERSEDED',{'task':task,'op':op_id})

    def apply_choices(self,owner,data,message=None):
        if not data.get('subscriptions'): return
        remaining=[]
        for choice in data.get('pending_choices',[]):
            evidence=choice['evidence'];target=normalized(choice['target'])
            # A claim must be in one original user clause, not in bank text or
            # a model-generated instruction. Human approval still follows.
            source=next((t['text'] for t in reversed(data['turns']) if evidence in t['text']),None)
            clauses=re.split(r'[，,。；;！!?？\n]',source or '')
            pref=choice['preference']
            candidates=[s for s in data['subscriptions'] if target in normalized(s['name'])]
            alias=re.search(r'\b([A-Za-z]{1,4})$',candidates[0]['name']) if len(candidates)==1 else None
            valid_clause=any((evidence in clause or clause.strip() in evidence) and
                (target in normalized(clause) or (alias and re.search(r'(?<![A-Za-z])'+re.escape(alias.group(1))+r'(?![A-Za-z])',clause,re.I)))
                and preference_word(clause)==pref for clause in clauses if clause.strip())
            if not valid_clause or len(candidates)!=1:
                remaining.append(choice);continue
            candidates[0]['preference']=pref
        data['pending_choices']=remaining

    def persist_choices(self,c,owner,previous,data,task):
        before={s['id']:s for s in previous.get('subscriptions',[])}
        for s in data.get('subscriptions',[]):
            if s.get('preference')==before.get(s['id'],{}).get('preference'): continue
            for op_id in previous.get('operation_ids',[]):
                row=self.engine.operation(c,owner,op_id)
                if row['kind']=='cancel_subscription' and json.loads(row['payload'])['subscription_id']==s['id']:
                    if row['status']=='PREPARED':
                        c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(op_id,))
                        self.engine.audit(c,owner,'DRAFT_SUPERSEDED',{'task':task,'op':op_id})
                    elif row['status'] not in ('CANCELLED',):
                        raise Denied('该协议已有确认或完成操作，改口不能恢复已经撤销的协议。','TASK_IN_FLIGHT')
            c.execute('INSERT OR REPLACE INTO subscription_preferences VALUES(?,?,?,?)',
                (owner,s['id'],s.get('preference','unknown'),time.time()))
            self.engine.audit(c,owner,'SUBSCRIPTION_PREFERENCE_SET',{'task':task,'subscription':s['id'],
                'preference':s['preference'],'source':'user_clause_validated'})

    def create_handoff(self,owner,task):
        with self.engine.tx() as c:
            _,data=self.row(c,owner,task)
            for op_id in data.get('operation_ids',[]):
                op=self.engine.operation(c,owner,op_id)
                if op['status'] in ('CONFIRMED','SCHEDULED'):
                    raise Denied('已有确认或预约操作，请先撤销未执行操作，再提交接管资料。','TASK_IN_FLIGHT')
                if op['status']=='PREPARED':
                    c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(op_id,))
                    c.execute('DELETE FROM challenges WHERE op=?',(op_id,))
                    self.engine.audit(c,owner,'DRAFT_SUPERSEDED',{'task':task,'op':op_id,'reason':'handoff'})
            ticket=data.get('handoff_id') or uuid.uuid4().hex
            data.update(handoff_id=ticket,status='HANDOFF',revision=data.get('revision',1)+1)
            self.update(c,task,data)
            self.engine.audit(c,owner,'HUMAN_HANDOFF_REQUESTED',{'task':task,'ticket':ticket,'revision':data.get('revision')})
        return self.get(owner,task)

    def review_handoff(self,task,reviewer,reason,release=False):
        """LOCAL operator boundary, intentionally absent from HTTP/model tools.

        Filesystem access is the sandbox operator privilege. This is not a bank
        identity verification service. Release revokes ALL pending authorizations
        so the user must begin a fresh task and approve new exact terms.
        """
        if not reviewer.strip() or len(reason.strip())<8:
            raise Denied('须填写核实人及至少8字的核实依据。','REVIEW')
        with self.engine.tx() as c:
            row=c.execute('SELECT owner FROM assistant_tasks WHERE id=?',(task,)).fetchone()
            if not row: raise Denied('接管任务不存在。','NOT_FOUND')
            owner=row['owner'];_,data=self.row(c,owner,task)
            if data.get('status')!='HANDOFF': raise Denied('任务不在待人工接管状态。','STATE')
            if release:
                if c.execute("SELECT 1 FROM operations WHERE owner=? AND status='UNKNOWN'",(owner,)).fetchone():
                    raise Denied('仍有未知结果，先查询银行回执再核实解除。','UNKNOWN')
                for op in c.execute("SELECT id FROM operations WHERE owner=? AND kind='transfer' AND status IN ('PREPARED','CONFIRMED','SCHEDULED')",(owner,)).fetchall():
                    c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(op['id'],))
                    c.execute('DELETE FROM challenges WHERE op=?',(op['id'],))
                    self.engine.audit(c,owner,'AUTHORIZATION_REVOKED_BY_REVIEW',{'op':op['id'],'task':task})
                c.execute('DELETE FROM transfer_holds WHERE owner=?',(owner,))
            data.update(status='REVIEWED',revision=data.get('revision',1)+1,
                human_review={'reviewer':reviewer,'reason':reason,'released':release,'at':time.time()},
                text='本机核实已记录。旧批准已撤销，重新办理须新建任务并重新核对。' if release else '本机核实已记录，安全暂停仍保留。')
            self.update(c,task,data)
            self.engine.audit(c,owner,'LOCAL_HUMAN_REVIEW',{'task':task,'reviewer':reviewer,'reason':reason,'released':release})
        return self.get(owner,task)

    def decorate(self,data,owner):
        if data.get('kind')=='subscriptions':
            data['consent_expired']=bool(data.get('subscriptions')) and time.time()-data.get('consent_at',0)>=600
        if not data.get('plan'): return data
        active=[o for o in data.get('operations',[]) if o['status']!='CANCELLED']
        if data.get('status') not in ('PAUSED','HANDOFF','DECLINED') and active:
            data['status']='DONE' if all(o['status']=='SUCCEEDED' for o in active) else 'SCHEDULED' if all(o['status'] in ('SCHEDULED','SUCCEEDED') for o in active) else 'ACTION_PENDING'
            if any(o['status']=='UNKNOWN' for o in active): data['text']='付款结果待核实，请先查询原交易。'
            elif data['status']=='SCHEDULED': data['text']='预约已受理，尚未扣款。执行日期与后续结果可在下方核对。'
            elif data['status']=='DONE':
                completed={o['payload']['subscription_id'] for o in active if o['kind']=='cancel_subscription' and o['status']=='SUCCEEDED'}
                names=[s['name'] for s in data.get('subscriptions',[]) if s['id'] in completed]
                done_amount=next((o['payload']['amount_cents'] for o in active if o['kind']=='transfer' and o['status']=='SUCCEEDED'),None)
                data['text']=(f'查过了：{done_amount/100:.0f}元已经转出成功，回执在下面，只动了这一笔。' if done_amount is not None else '已收到这笔转账的完成回执。') if data['kind']=='transfer' else ('挂失已完成，这张卡现在不能付款；要处理的事一条条列在下面。' if data['kind']=='card' else (names[0]+'的银行代扣已撤销。' if len(names)==1 else f'已核实 {len(completed)} 项银行代扣撤销结果。'))
        completed_ids={o['payload']['subscription_id'] for o in active if o['kind']=='cancel_subscription' and o['status']=='SUCCEEDED'}
        remaining=[s for s in data.get('subscriptions',[]) if s.get('preference')=='unneeded' and s['status']=='ACTIVE' and s['id'] not in completed_ids]
        if completed_ids and remaining and data.get('status')=='DONE':
            data.update(status='REVIEW',text=f'已核实 {len(completed_ids)} 项撤销，还有 {len(remaining)} 项等你逐项确认。')
        statuses=[];blocked=False
        for node in data['plan']:
            tool=node['tool'];status='PENDING'
            level='YELLOW' if tool in ('read_subscriptions','prepare_subscription','prepare_transfer') else 'GREEN'
            if tool=='prepare_transfer' and data.get('draft',{}).get('amount'):
                with self.engine.tx() as c:
                    level=self.engine.tier(c,owner,{'amount_cents':money(data['draft']['amount']),'due_day':data['draft']['due_day']},exclude=active[0]['id'] if active else None)
            if data['status'] in ('PAUSED','HANDOFF'): status='PAUSED'
            elif blocked: status='PENDING'
            elif tool=='resolve_recipient': status='DONE' if data.get('draft',{}).get('recipient') else 'WAITING'
            elif tool=='read_transfer_evidence': status='DONE' if data.get('constraint_check') else 'WAITING'
            elif tool=='validate_transfer': status='STOPPED' if data['status']=='DECLINED' else 'DONE' if data.get('constraint_check',{}).get('decision')=='PASS' else 'WAITING'
            elif tool=='read_bills': status='DONE' if 'bill_evidence_ids' in data or data.get('analysis') else 'WAITING'
            elif tool=='summarize_bills': status='DONE' if data.get('analysis') else 'WAITING'
            elif tool=='read_subscriptions':
                level='YELLOW';status='DONE' if data.get('subscriptions') and time.time()-data.get('consent_at',0)<600 else 'WAITING'
            elif tool=='choose_subscriptions': status='DONE' if any(s.get('preference')!='unknown' for s in data.get('subscriptions',[])) else 'WAITING'
            elif tool in ('prepare_transfer','prepare_subscription'):
                status='WAITING' if tool=='prepare_subscription' and remaining and all(o['status']=='SUCCEEDED' for o in active) else 'DONE' if active else 'WAITING'
            elif tool=='readback_operation': status='DONE' if active and all(o['status'] in ('SUCCEEDED','SCHEDULED') for o in active) else 'WAITING'
            elif tool=='explain_safety': status='DONE'
            statuses.append(dict(**node,label=LABELS[tool],status=status,level=level,
                access='WRITE_DRAFT' if tool.startswith('prepare_') else 'READ',strong_verification=level=='RED'))
            if status!='DONE': blocked=True
        data['plan_nodes']=statuses;data['steps']=[{'label':n['label'],'status':n['status']} for n in statuses]
        return data
