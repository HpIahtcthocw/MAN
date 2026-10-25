"""今日叮咛：deterministic proactive briefing. Facts come from the ledger only;
no LLM call, no invented numbers. The agent speaks first — that is the hook."""
import json
import json
import time
from guardian.bill_scope import estimate_next_charge
from datetime import timedelta
from datetime import timedelta
from guardian.engine import now


def _yuan(cents):
    value = abs(cents) / 100
    return str(int(value)) if cents % 100 == 0 else f'{value:.2f}'


def build(engine, owner, today=None):
    today = today or now().date()
    state = engine.snapshot(owner)
    with engine.tx() as c:
        watches = [dict(r) for r in c.execute(
            'SELECT id,merchant,amount_cents,last_day,created,resolved FROM watches WHERE owner=? ORDER BY created DESC LIMIT 20', (owner,))]
        cards = [dict(r) for r in c.execute("SELECT * FROM cards WHERE owner=? AND status='LOST'", (owner,))]
    items = []
    # 1) 跟进中的可疑扣费：盯到了→提醒（结果由用户回答，系统不代答）；
    #    跟进中→最旧一笔展开证据与追回路径，其余聚合成一句，避免挤掉善后与到账。
    with engine.tx() as c:
        unresolved = [w for w in watches if not w['resolved']]
        extra_watching = 0
        for index, watch in enumerate(unresolved):
            hit = c.execute('SELECT day,amount FROM ledger WHERE owner=? AND merchant=? AND source NOT LIKE ? ORDER BY day DESC LIMIT 1',
                            (owner, watch['merchant'], 'csv:%')).fetchone()
            if hit and hit['day'] >= time.strftime('%Y-%m-%d', time.localtime(watch['created'])):
                items.append(dict(kind='watch_hit', merchant=watch['merchant'], text=f"你让我盯的“{watch['merchant']}”又有新动作了：{hit['day']} 一笔{_yuan(hit['amount'])}元。是不是你本人办的？不是的话，下面的追回路径用得上。",
                    action='查这笔'))
            elif index < 2:
                last = c.execute('SELECT day,amount FROM ledger WHERE owner=? AND merchant=? AND amount<0 AND source NOT LIKE ? ORDER BY day DESC LIMIT 1',
                                 (owner, watch['merchant'], 'csv:%')).fetchone()
                scope = f"{_yuan(last['amount'])}元，{last['day']}扣的" if last else '这笔扣费'
                evidence = [dict(day=r['day'], amount=r['amount'],
                    channel='本行转账回执' if str(r['source']).startswith('payment:') else '银行渠道扣款记录')
                    for r in c.execute('SELECT day,amount,source FROM ledger WHERE owner=? AND merchant=? AND amount<0 AND source NOT LIKE ? ORDER BY day DESC LIMIT 3',
                        (owner, watch['merchant'], 'csv:%'))]
                items.append(dict(kind='watching', merchant=watch['merchant'], evidence=evidence,
                    text=f"你在跟进“{watch['merchant']}”的扣费，{scope}。是不是你本人办的？不是的话，打银行客服可以发起交易争议把钱要回来，需要的证据我整理好了；涉及诈骗先拨96110。有结果了点下面告诉我，我帮你记着追回了没有。",
                    action='有结果了'))
            else:
                extra_watching += 1
        if extra_watching:
            items.append(dict(kind='watching_more', text=f"还有{extra_watching}笔你在跟进的扣费，一项一项来：上面处理完一笔，下一笔自动顶上来。", action=''))
    # 1b) 已撤销的协议又出现扣款：撤销承诺的兑现警报，优先级仅次于盯到了。
    contacts = {c['id']: c['name'] for c in engine.contacts()}
    with engine.tx() as c:
        for sub in state.get('subscriptions', []):
            if sub['status'] != 'CANCELLED': continue
            row = c.execute("SELECT MAX(created) FROM operations WHERE owner=? AND kind='cancel_subscription' AND json_extract(payload,'$.subscription_id')=?",
                            (owner, sub['id'])).fetchone()
            if not row or not row[0]: continue
            cancel_day = time.strftime('%Y-%m-%d', time.localtime(row[0]))
            charged = c.execute('SELECT day,amount FROM ledger WHERE owner=? AND merchant=? AND amount<0 AND day>=? ORDER BY day DESC LIMIT 1',
                                (owner, sub['name'], cancel_day)).fetchone()
            if charged:
                items.append(dict(kind='cancelled_charge', merchant=sub['name'],
                    text=f"注意：{sub['name']}的银行代扣你已经撤销了，但{charged['day']}又扣了{_yuan(charged['amount'])}元。它可能换了别的渠道扣款——这种最该盯紧，要我跟进吗？",
                    action='帮我跟进'))
    # 2) 可疑扣费跟进（近30天异常候选）。
    rows = state['bills']
    from guardian.bill_scope import detect_anomalies
    start = (today.replace(day=1)).isoformat()
    anomalies = detect_anomalies(rows, start, today.isoformat())
    for anomaly in anomalies:
        items.append(dict(kind='anomaly', merchant=anomaly['merchant'], amount_cents=anomaly['amount_cents'],
            day=anomaly['day'], text=f"本月有一笔{_yuan(anomaly['amount_cents'])}元的“{anomaly['merchant']}”，之前没见过。{anomaly['basis']}。",
            action='帮我跟进'))
    # 3) 临期扣费：active协议的预计下期扣费日在未来14天内，聚合成一句话。
    upcoming = []
    with engine.tx() as c:
        for sub in c.execute("SELECT id,name,amount FROM subscriptions WHERE owner=? AND status='ACTIVE'", (owner,)):
            observations = [dict(b) for b in c.execute(
                "SELECT day,amount FROM ledger WHERE owner=? AND merchant=? AND source NOT LIKE 'csv:%' ORDER BY day DESC", (owner, sub['name']))]
            estimate = estimate_next_charge(observations, today)
            if estimate:
                from datetime import date as date_type
                days_left = (date_type.fromisoformat(estimate['date']) - today).days
                if 0 <= days_left <= 14:
                    upcoming.append((sub['name'], sub['amount'], estimate['date']))
    if upcoming:
        names = '、'.join(name for name, _, _ in upcoming)
        total = sum(amount for _, amount, _ in upcoming)
        items.append(dict(kind='upcoming', text=f"{upcoming[0][2]}前后有{len(upcoming)}笔自动扣费（{names}），共{_yuan(total)}元。不需要的可以现在停，我不会自己动。", action='去看看'))
    # 4) 挂失善后未处理：有挂失卡且仍有ACTIVE协议。
    if cards:
        active_subs = [s for s in state.get('subscriptions', []) if s['status'] == 'ACTIVE']
        if active_subs:
            names = '、'.join(s['name'] for s in active_subs[:3])
            items.append(dict(kind='aftermath', text=f"{cards[0]['name']}挂失了，还有{len(active_subs)}笔绑卡扣费要处理（{names}等）。逐项定一下：停掉，还是等新卡改绑。", action='去处理'))
    # 4b) 预约兑现：今天/明天到期的预约提醒＋近两天完成的转账回执播报。
    tomorrow_iso = (today + timedelta(days=1)).isoformat()
    scheduled = [o for o in state.get('operations', []) if o['kind'] == 'transfer' and o['status'] == 'SCHEDULED']
    for op in scheduled:
        due = op['payload'].get('due_day')
        if due in (today.isoformat(), tomorrow_iso):
            when = '今天' if due == today.isoformat() else '明天'
            name = contacts.get(op['payload'].get('recipient'), '已核对收款人')
            items.append(dict(kind='scheduled', text=f"{when}有一笔{_yuan(op['payload']['amount_cents'])}元预约转账给{name}，钱已经预留好，到点自动转。", action=''))
            break
    with engine.tx() as c:
        recent = c.execute("SELECT o.payload FROM provider_receipts r JOIN operations o ON o.id=r.op WHERE r.owner=? AND o.kind='transfer' AND o.status='SUCCEEDED' AND r.created>=?",
                           (owner, time.time() - 48 * 3600)).fetchall()
    if recent:
        payload = json.loads(recent[0]['payload'])
        name = contacts.get(payload.get('recipient'), '已核对收款人')
        items.append(dict(kind='receipt', text=f"{_yuan(payload['amount_cents'])}元转给{name}的钱已经转出去了，回执在办理记录里。", action=''))
    # 4c) AA拆分的下一笔：上一笔完成，下一笔自动顶上来。
    with engine.tx() as c:
        has_tasks = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_tasks'").fetchone()
        if has_tasks:
            for row in c.execute("SELECT id,data FROM assistant_tasks WHERE owner=? AND kind='transfer'", (owner,)).fetchall():
                data = json.loads(row['data'])
                plan = data.get('split_plan')
                if not plan: continue
                statuses = [c.execute('SELECT status FROM operations WHERE id=?', (oid,)).fetchone() for oid in data.get('operation_ids', [])]
                done = sum(1 for s in statuses if s and s['status'] == 'SUCCEEDED')
                if done and done < len(plan['shares']):
                    share = plan['shares'][done]
                    amount = share['amount_cents'] / 100
                    amount_text = str(int(amount)) if share['amount_cents'] % 100 == 0 else f'{amount:.2f}'
                    items.append(dict(kind='aa_next', message=f"给{share['name']}转{amount_text}",
                        text=f"AA拆分下一笔：给{share['name']}转{amount_text}元。上一笔已经办完，这一句就能发。", action='继续办'))
    # 5) 养老金/收入本月已到账。
    for row in rows:
        if row['amount'] > 0 and row['category'] == '收入' and row['day'].startswith(today.strftime('%Y-%m')):
            items.append(dict(kind='income', text=f"养老金到账了：{row['day'][5:].replace('-', '月')}日 {_yuan(row['amount'])}元。这个月的钱是够用的，我帮你看着。", action=''))
            break
    # 6) 结果未知的转账。
    unknown = [o for o in state.get('operations', []) if o['kind'] == 'transfer' and o['status'] == 'UNKNOWN']
    if unknown:
        items.append(dict(kind='unknown', text=f"有一笔{_yuan(unknown[0]['payload']['amount_cents'])}元的转账还没确认结果，我一直在查原交易，有消息第一时间告诉你。", action='去查看'))
    if not items:
        items.append(dict(kind='calm', text='今天账户没什么要紧事，钱都在。有想办的事直接跟我说就行。', action=''))
    return dict(items=items[:5],
        spoken=''.join(item['text'].rstrip('。') + '。' for item in items[:5]))
