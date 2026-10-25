"""Deterministic bank-ledger queries. No prose or amount comes from the model."""
import calendar
import re
from datetime import date,timedelta
from guardian.engine import Denied
from guardian.task_planner import cn_number


def analyze(state,message,today,previous_scope=None):
    previous=previous_scope or {}
    previous=previous.get('query',previous)
    old_scope=previous.get('scope',previous if 'start' in previous else {})
    old_filters=previous.get('filters',{})
    rows=[b for b in state['bills'] if not b['source'].startswith('csv:')]
    category_names=sorted({b['category'] for b in rows},key=len,reverse=True)
    category=next((c for c in category_names if c in message),None)
    if category is None:
        # Bank categories remain authoritative; aliases only select an existing
        # category and cannot invent rows, amounts or a different time scope.
        aliases={'餐饮':r'吃饭|饭钱|下馆子|餐费','交通':r'坐车|打车|通勤','购物':r'买东西|网购'}
        category=next((c for c,pattern in aliases.items() if c in category_names and re.search(pattern,message)),None)
    merchant_token=next((token for token in ('云盘','视频') if token in message),None)
    unknown_filter=bool(re.fullmatch(r'只看.+?[。.!！?？]*',message.strip())) and category is None and merchant_token is None
    reset_category=bool(re.search(r'(?:全部|所有|不限)(?:类别|分类)|去掉分类|清除分类',message))
    reset_merchant=bool(re.search(r'(?:全部|所有|不限)商户|去掉商户|清除商户',message))
    reset_all=bool(re.search(r'全部|所有|不限|不分|清除筛选|去掉筛选',message)) and not (reset_category or reset_merchant)
    if not (reset_all or reset_category): category=category or old_filters.get('category')
    if not (reset_all or reset_merchant): merchant_token=merchant_token or old_filters.get('merchant_contains')
    def aggregate(selected):
        categories={}
        for b in selected:
            if b['amount']<0: categories[b['category']]=categories.get(b['category'],0)-b['amount']
        return dict(expense_cents=sum(categories.values()),income_cents=sum(b['amount'] for b in selected if b['amount']>0),categories=categories,rows=selected)
    def select(start,end):
        return [b for b in rows if start<=b['day']<=end and (not category or b['category']==category) and
            (not merchant_token or merchant_token in b.get('merchant',''))]
    spans=[]
    # Parse day precision before month precision. Unhandled day expressions
    # must clarify, never silently widen a half-month to a whole month.
    explicit_days=[]
    day_pattern=r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]|(\d{4})-(\d{2})-(\d{2})'
    day_matches=list(re.finditer(day_pattern,message))
    inherited_day_year=today.year
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
    inherited_year=today.year
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
        available_cents=state['balance_cents']-state['reserved_cents'],filters={'category':category,'merchant_contains':merchant_token},
        coverage={'first_day':min((b['day'] for b in rows),default=None),'last_day':max((b['day'] for b in rows),default=None),
            'note':'仅统计本账户当前已有银行流水；未出现记录不代表期间完整或其他账户无消费。'})
    def clarify():
        return dict(result,needs_clarification=True,question='请明确起止日期或要比较的期间；当前不会把日期范围扩大成整月。')
    if unknown_filter:
        return dict(result,needs_clarification=True,question='没有识别到这个分类或商户，请核对名称；当前不会沿用原来的筛选结果。')
    def scope_entry(start,end):
        monthly=start.day==1 and end==date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
        label=f'{start.year:04d}年{start.month:02d}月' if monthly else f'{start.isoformat()} 至 {end.isoformat()}'
        return dict(period=start.strftime('%Y-%m') if monthly else label,label=label,
            start=start.isoformat(),end=end.isoformat(),**aggregate(select(start.isoformat(),end.isoformat())))
    def finish(periods,all_rows=False):
        first=periods[0]
        scope={k:first[k] for k in ('start','end')}
        query=dict(scope=scope,filters=result['filters'],comparison_scopes=[{k:p[k] for k in ('start','end')} for p in periods] if len(periods)==2 else [])
        answer=dict(result,period='当前可用流水' if all_rows else first['label'],scope=scope,query=query,**aggregate(first['rows']))
        if len(periods)==2:
            second=periods[1]
            answer.update(comparison_periods=periods,delta_cents=first['expense_cents']-second['expense_cents'],
                category_deltas={c:first['categories'].get(c,0)-second['categories'].get(c,0) for c in first['categories'].keys()|second['categories'].keys()})
        return answer
    if re.search(r'上旬|中旬|下旬|上半月|下半月|月初|月底|上午|下午|晚上|\d+点|\d+时|以外|排除|不包括|除了|不看',message): return clarify()
    if explicit_days:
        if len(explicit_days)>2: return clarify()
        remaining=re.sub(day_pattern,'',message)
        if re.search(r'\d+月|\d+年|以前|以后|之前|之后',remaining): return clarify()
        comparison=bool(re.search(r'比较|对比|相比|比|差',message))
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
    if len(spans)==1 and old_scope and re.search(r'比较|对比|相比|比|差',message):
        spans.insert(0,(date.fromisoformat(old_scope['start']),date.fromisoformat(old_scope['end'])))
    periods=[scope_entry(start,end) for start,end in spans]
    first=periods[0]
    if len(periods)==2 and re.search(r'(?:月|月份)\s*(?:到|至|—|-)\s*(?:\d{4}年)?[0-9一二三四五六七八九十]+月',message):
        start,end=first['start'],periods[1]['end']
        if start>end: raise Denied('开始月份晚于结束月份，请核对范围。','BILL_SCOPE')
        return finish([scope_entry(date.fromisoformat(start),date.fromisoformat(end))])
    return finish(periods)
