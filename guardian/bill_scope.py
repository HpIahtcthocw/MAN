"""Deterministic bank-ledger queries. No prose or amount comes from the model."""
import calendar
import re
import unicodedata
from datetime import date,timedelta
from statistics import median
from guardian.engine import Denied
from guardian.task_planner import cn_number


def detect_anomalies(rows,start,end):
    """Read-only anomaly candidates inside the analyzed period, from ledger facts only.

    Two conservative, explainable rules: an expense at least 3x the same
    merchant's earlier median (>=200 CNY, >=3 prior rows), or a first-ever
    merchant with a single expense >=500 CNY. Marking never blocks or moves money.
    """
    ordered=sorted(rows,key=lambda r:r['day'])
    period=[r for r in ordered if start<=r['day']<=end and r['amount']<0 and r.get('merchant')]
    prior={}
    first_seen={}
    for r in ordered:
        if not r.get('merchant'): continue
        first_seen.setdefault(r['merchant'],r['day'])
        if r['day']<start and r['amount']<0: prior.setdefault(r['merchant'],[]).append(-r['amount'])
    anomalies=[]
    for r in period:
        amount=-r['amount'];history=prior.get(r['merchant'],[])
        if len(history)>=3:
            base=median(history)
            if base>0 and amount>=20000 and amount>=3*base:
                anomalies.append(dict(kind='amount_spike',day=r['day'],merchant=r['merchant'],amount_cents=r['amount'],
                    prior_count=len(history),prior_median_cents=int(base),
                    basis=f'单笔{amount/100:.2f}元，约为此前{len(history)}笔中位数{base/100:.2f}元的{amount/base:.1f}倍'))
        elif not history and first_seen.get(r['merchant'])>=start and amount>=50000:
            anomalies.append(dict(kind='first_seen_large',day=r['day'],merchant=r['merchant'],amount_cents=r['amount'],
                basis=f'首次出现的商户，单笔{amount/100:.2f}元，请核对是否本人操作'))
    return anomalies[:5]


def estimate_next_charge(observations,today):
    """Projected next debit date from consistent ledger intervals; an estimate only.

    Requires >=3 debits whose consecutive intervals stay within 40% of the
    median. Returns None whenever the pattern is not regular enough to explain.
    """
    days=sorted({o['day'] for o in observations})
    if len(days)<3: return None
    gaps=[(date.fromisoformat(b)-date.fromisoformat(a)).days for a,b in zip(days,days[1:])]
    if not gaps or any(g<=0 for g in gaps): return None
    ordered=sorted(gaps);n=len(ordered)
    median_gap=ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2
    # Two gaps are always symmetric around their median, so regularity is judged by spread.
    if not 6<=median_gap<=370 or max(gaps)-min(gaps)>max(2,0.1*median_gap): return None
    interval=int(median_gap)
    projected=date.fromisoformat(days[-1])+timedelta(days=interval)
    steps=0
    while projected<today and steps<6: projected+=timedelta(days=interval);steps+=1
    if projected<today: return None
    amounts={abs(o['amount']) for o in observations}
    return dict(date=projected.isoformat(),interval_days=interval,observations=len(days),same_amount=len(amounts)==1,
        basis=f'按最近{len(days)}笔扣费间隔约{interval}天推断',
        caveat='推断值，不是银行扣费承诺；实际以协议执行为准')


def analyze(state,message,today,previous_scope=None,proposal=None):
    def norm(text):return re.sub(r'\s|会员|服务','',unicodedata.normalize('NFKC',text)).lower()
    previous=previous_scope or {}
    previous=previous.get('query',previous)
    old_scope=previous.get('scope',previous if 'start' in previous else {})
    old_filters=previous.get('filters',{})
    rows=[b for b in state['bills'] if not b['source'].startswith('csv:')]
    category_names=sorted({b['category'] for b in rows},key=len,reverse=True)
    # Resolve exclusions against this account's vocabulary before detecting
    # positive filters: “云盘不算” must never become “只看云盘”.
    merchant_names={norm(b.get('merchant','')) for b in rows if b.get('merchant')}
    terms={name[:i] for name in merchant_names for i in range(2,len(name)+1)}
    terms-=set(category_names)|{'会员','服务','支付','消费','银行'}
    vocabulary=sorted(set(category_names)|terms,key=lambda s:(-len(s),s))
    alternatives='|'.join(re.escape(s) for s in vocabulary) or r'(?!)'
    exclusion_pattern=(r'(?:除了|排除|不包括|不含|不看|不是)\s*('+alternatives+r')(?:那部分|以外|除外)?(?=$|[，,。！？?；;\s]|花了|消费|支出|花费|扣了)'
        r'|('+alternatives+r')\s*(?:不含在内|不算|除外|以外)')
    exclusions=[]
    def remove_exclusion(match):
        value=match.group(1) or match.group(2)
        item={'kind':'category' if value in category_names else 'merchant','value':value}
        if item not in exclusions:exclusions.append(item)
        return ' '
    filter_message=re.sub(exclusion_pattern,remove_exclusion,norm(message),flags=re.IGNORECASE)
    unsupported_exclusion=bool(re.search(r'以外|除外|排除|不包括|不含|不算|不是|除了|不看',filter_message))
    # Compound “除了A还看B” does not have a safe set-difference interpretation.
    unsupported_exclusion=unsupported_exclusion or bool(exclusions and re.search(r'还看|也看|而是|或者|或是|^\s*(?:和|及|、)|\s+(?:和|及|、)',filter_message))
    if not exclusions:exclusions=list(old_filters.get('exclude',[]))
    reset_exclusions=bool(re.search(r'清除排除|取消排除',message))
    if reset_exclusions:exclusions=[];unsupported_exclusion=False;filter_message=re.sub(r'清除排除|取消排除','',filter_message)
    original_message=message
    message=filter_message
    category=next((c for c in category_names if c in message),None)
    if category is None:
        # Bank categories remain authoritative; aliases only select an existing
        # category and cannot invent rows, amounts or a different time scope.
        aliases={'餐饮':r'吃饭|饭钱|下馆子|餐费','交通':r'坐车|打车|通勤','购物':r'买东西|网购'}
        category=next((c for c,pattern in aliases.items() if c in category_names and re.search(pattern,message)),None)
    # Literal candidate prefixes come from bank rows, not seed-specific names.
    aliases={norm(b.get('merchant','')) for b in rows if b.get('merchant')}
    tokens={name[:i] for name in aliases for i in range(2,len(name)+1)}
    tokens-=set(category_names)|{'会员','服务','支付','消费','银行'}
    merchant_token=next((token for token in sorted(tokens,key=lambda x:(-len(x),x)) if token in norm(message)),None)
    mentioned_filter=bool(category or merchant_token)
    unknown_filter=bool(re.fullmatch(r'只看.+?[。.!！?？]*',message.strip())) and category is None and merchant_token is None
    reset_category=bool(re.search(r'(?:全部|所有|不限)(?:类别|分类)|去掉分类|清除分类',message))
    reset_merchant=bool(re.search(r'(?:全部|所有|不限)商户|去掉商户|清除商户',message))
    reset_all=bool(re.search(r'全部|所有|不限|不分|清除筛选|去掉筛选',message)) and not (reset_category or reset_merchant)
    if reset_all:exclusions=[]
    if not (reset_all or reset_category): category=category or old_filters.get('category')
    if not (reset_all or reset_merchant): merchant_token=merchant_token or old_filters.get('merchant_contains')
    def aggregate(selected):
        categories={}
        for b in selected:
            if b['amount']<0: categories[b['category']]=categories.get(b['category'],0)-b['amount']
        return dict(expense_cents=sum(categories.values()),income_cents=sum(b['amount'] for b in selected if b['amount']>0),categories=categories,rows=selected)
    def select(start,end):
        return [b for b in rows if start<=b['day']<=end and (not category or b['category']==category) and
            (not merchant_token or merchant_token in norm(b.get('merchant',''))) and not any(
                b['category']==x['value'] if x['kind']=='category' else x['value'] in norm(b.get('merchant','')) for x in exclusions)]
    spans=[]
    # Parse day precision before month precision. Unhandled day expressions
    # must clarify, never silently widen a half-month to a whole month.
    explicit_days=[]
    day_pattern=r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]|(\d{4})-(\d{2})-(\d{2})'
    day_matches=list(re.finditer(day_pattern,message))
    inherited_day_year=today.year-(1 if '去年' in message else 2 if '前年' in message else 0)
    for match in day_matches:
        year=int(match.group(1) or match.group(4) or inherited_day_year)
        inherited_day_year=year
        month=int(match.group(2) or match.group(5))
        day=int(match.group(3) or match.group(6))
        try: explicit_days.append(date(year,month,day))
        except ValueError: raise Denied('日期无效，请核对年月日。','BILL_SCOPE')
    if len(day_matches)==1:
        short=re.search(r'^\s*(?:到|至|—|~|～|-)\s*(\d{1,2})[日号]',message[day_matches[0].end():])
        if short:
            try: explicit_days.append(explicit_days[0].replace(day=int(short.group(1))))
            except ValueError: raise Denied('日期无效，请核对年月日。','BILL_SCOPE')
    relative={'本月':0,'这个月':0,'这月':0,'上个月':-1,'上月':-1,'上上个月':-2,'上上月':-2}
    pattern=r'上上个月|上上月|上个月|上月|这个月|这月|本月|(?:(\d{4})年)?([0-9一二三四五六七八九十]{1,3})月'
    inherited_year=today.year-(1 if '去年' in message else 2 if '前年' in message else 0)
    for match in ([] if explicit_days else re.finditer(pattern,message)):
        if match.group() in relative:
            index=today.year*12+today.month-1+relative[match.group()]
            year,month=index//12,index%12+1
        else:
            year=int(match.group(1)) if match.group(1) else inherited_year
            value=cn_number(match.group(2));month=int(value) if value else 0
            if not 1<=month<=12: raise Denied('月份须在1至12月之间，请重新说明范围。','BILL_SCOPE')
            inherited_year=year
        start=date(year,month,1);end=date(year,month,calendar.monthrange(year,month)[1])
        if (start,end) not in spans: spans.append((start,end))
    result=dict(balance_cents=state['balance_cents'],reserved_cents=state['reserved_cents'],
        available_cents=state['balance_cents']-state['reserved_cents'],filters={'category':category,'merchant_contains':merchant_token,'exclude':exclusions},
        coverage={'first_day':min((b['day'] for b in rows),default=None),'last_day':max((b['day'] for b in rows),default=None),
            'note':'我只能看到这个银行账户里已有的记录；现金、微信、支付宝里的花销我看不到。'})
    def clarify(suggestions=None):
        payload=dict(result,needs_clarification=True,question='日期、筛选或排除条件尚未核对一致，请说明具体范围；当前不会返回其他范围的金额。')
        if suggestions: payload['suggestions']=suggestions
        return payload
    if unsupported_exclusion:return clarify()
    requested=re.findall(r'(?:上上个月|上个月|上月|本月|这个月|[0-9一二三四五六七八九十]+月)\s*([\u4e00-\u9fffA-Za-z]{1,16}?)(?:花了|消费|支出|花费|扣了)',message)
    def comparison_phrase(text):
        return bool(re.fullmatch(r'(?:和|跟)(?:上上个月|上个月|上月|本月|这个月|[0-9一二三四五六七八九十]+月)(?:比(?:多|少)?)?',text))
    if not mentioned_filter and any(x not in ('一共','总共','合计','总','的','总计','全部','所有') and not comparison_phrase(x) for x in requested):
        return clarify([{'label':'只看'+c,'message':'只看'+c} for c in category_names[:4]])
    if unknown_filter:
        return clarify([{'label':'只看'+c,'message':'只看'+c} for c in category_names[:4]])
    def scope_entry(start,end):
        monthly=start.day==1 and end==date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
        label=f'{start.year:04d}年{start.month:02d}月' if monthly else f'{start.isoformat()} 至 {end.isoformat()}'
        return dict(period=start.strftime('%Y-%m') if monthly else label,label=label,
            start=start.isoformat(),end=end.isoformat(),**aggregate(select(start.isoformat(),end.isoformat())))
    def plain_summary(cats,anoms,total_cents):
        if not cats: return '这个范围没有支出记录；可能钱走了别的渠道，比如现金或微信支付。'
        top=sorted(cats.items(),key=lambda kv:-kv[1])[:3]
        parts='、'.join(f'{name} {value/100:.0f}元' for name,value in top)
        tail='。'
        if anoms: tail='。另外有一笔'+f"{-anoms[0]['amount_cents']/100:.0f}"+'元的“'+anoms[0]['merchant']+'”，之前没见过——要不要我帮你查查这笔？'
        return '钱主要花在：'+parts+tail
    def finish(periods,all_rows=False):
        first=periods[0]
        scope={k:first[k] for k in ('start','end')}
        query=dict(scope=scope,filters=result['filters'],comparison_scopes=[{k:p[k] for k in ('start','end')} for p in periods] if len(periods)==2 else [])
        answer=dict(result,period='当前可用流水' if all_rows else first['label'],scope=scope,query=query,**aggregate(first['rows']))
        answer['anomalies']=detect_anomalies(rows,scope['start'],scope['end'])
        answer['plain_summary']=plain_summary(answer['categories'],answer['anomalies'],first['expense_cents'])
        if len(periods)==2:
            second=periods[1]
            answer.update(comparison_periods=periods,delta_cents=first['expense_cents']-second['expense_cents'],
                category_deltas={c:first['categories'].get(c,0)-second['categories'].get(c,0) for c in first['categories'].keys()|second['categories'].keys()})
        if proposal is not None:
            # A semantic proposal is checked independently against host-parsed
            # parameters and verbatim spans. Disagreement never emits a total.
            proposed=proposal.model_dump() if hasattr(proposal,'model_dump') else proposal
            if proposed.get('exclude') and set(map(norm,proposed['exclude']))!={norm(x['value']) for x in exclusions}:return clarify()
            if any(norm(x) not in norm(original_message) for x in proposed.get('exclude',[])):return clarify()
            for field in ('category','merchant'):
                value=proposed.get(field)
                actual=category if field=='category' else merchant_token
                if value is not None and (not proposed.get(field+'_evidence') or proposed[field+'_evidence'] not in original_message or norm(value)!=norm(actual or '')):
                    return clarify()
            for prefix,period in (('period',scope),('compare',query['comparison_scopes'][1] if len(periods)==2 else {})):
                keys=('period_start','period_end') if prefix=='period' else ('compare_start','compare_end')
                values=[proposed.get(k) for k in keys]
                if any(v is not None for v in values):
                    evidence=proposed.get(prefix+'_evidence')
                    # “最近N天” has two legitimate readings (exclusive vs inclusive
                    # of today); the host reading is authoritative, so recompute
                    # from the verbatim evidence instead of rejecting a 1-day shift.
                    days_range=re.fullmatch(r'(?:最近|近|过去)\s*(\d{1,3})\s*天',evidence or '')
                    if days_range and period.get('end'):
                        expected_start=(date.fromisoformat(period['end'])-timedelta(days=int(days_range.group(1))-1)).isoformat()
                        agreed=values[0] in (expected_start,(date.fromisoformat(period['end'])-timedelta(days=int(days_range.group(1)))).isoformat()) and values[1]==period.get('end')
                    else:
                        agreed=values==[period.get('start'),period.get('end')]
                    if not agreed or not evidence or evidence not in original_message:return clarify()
            answer['query_verification']='model_host_agreement'
        else:answer['query_verification']='host_only'
        return answer
    if re.search(r'上旬|中旬|下旬|上半月|下半月|月初|月底|上午|下午|晚上|\d+点|\d+时|以外|除外|排除|不包括|不含|不算|不是|除了|不看',message): return clarify()
    if explicit_days:
        if len(explicit_days)>2: return clarify()
        remaining=re.sub(day_pattern,'',message)
        if re.search(r'\d+月|\d+年|以前|以后|之前|之后',remaining): return clarify()
        comparison=bool(re.search(r'比较|对比|相比|比.{0,12}(?:多|少)|差多少|差额',message))
        if len(explicit_days)==2:
            if comparison and not re.search(r'到|至|—|~|～',message):
                return finish([scope_entry(d,d) for d in explicit_days])
            if not re.search(r'到|至|—|~|～|\d{2}\s*-\s*\d{4}',message): return clarify()
            start,end=explicit_days
            if start>end: raise Denied('开始日期晚于结束日期，请核对范围。','BILL_SCOPE')
        else:
            # "9月1日以前" is not a one-day request.
            if re.search(r'到|至|之前|以前|之后|以后|以来|起',message): return clarify()
            start=end=explicit_days[0]
        return finish([scope_entry(start,end)])
    if re.search(r'\d\s*[日号]|\d{4}-\d|\d{1,2}/\d{1,2}',message): return clarify()
    if re.search(r'以来|至今',message):
        return dict(result,needs_clarification=True,question='请明确起止范围，例如“2025年11月到2026年1月”；我不会把“以来”改成只统计某一年。')
    if not spans:
        days=re.search(r'(?:最近|近|过去)\s*(\d{1,3})\s*天',message)
        years=re.search(r'(?:(\d{4})年|今年|去年|本年)',message)
        if days:
            count=int(days.group(1))
            if not 1<=count<=366: raise Denied('天数范围支持1至366天。','BILL_SCOPE')
            start,end=today-timedelta(days=count-1),today
        elif years:
            year=int(years.group(1)) if years.group(1) else today.year-(1 if '去年' in years.group() else 0)
            start,end=date(year,1,1),date(year,12,31)
        elif re.search(r'最近.{0,4}个月|近.{0,4}个月|季度|上周|这周|周末|年初|月初|以来|到|至',message):
            return dict(result,needs_clarification=True,question='请明确日期范围，例如“最近90天”“2026年9月”或“上个月”。我不会把其他月份混入。')
        elif old_scope:
            if previous.get('comparison_scopes'):
                return finish([scope_entry(date.fromisoformat(p['start']),date.fromisoformat(p['end'])) for p in previous['comparison_scopes']])
            start,end=date.fromisoformat(old_scope['start']),date.fromisoformat(old_scope['end'])
        else: start,end=date.min,today
        return finish([scope_entry(start,end)],start==date.min)
    if len(spans)>2:
        return dict(result,needs_clarification=True,question='一次可核对两个明确月份；请指定这次要比较的两个月。')
    if len(spans)==1 and old_scope and re.search(r'比较|对比|相比|比(?:呢|一下|多|少)|差多少|差额',message):
        spans.insert(0,(date.fromisoformat(old_scope['start']),date.fromisoformat(old_scope['end'])))
    periods=[scope_entry(start,end) for start,end in spans]
    first=periods[0]
    if len(periods)==2 and re.search(r'(?:月|月份)\s*(?:到|至|—|-)\s*(?:\d{4}年)?[0-9一二三四五六七八九十]+月',message):
        start,end=first['start'],periods[1]['end']
        if start>end: raise Denied('开始月份晚于结束月份，请核对范围。','BILL_SCOPE')
        return finish([scope_entry(date.fromisoformat(start),date.fromisoformat(end))])
    return finish(periods)
