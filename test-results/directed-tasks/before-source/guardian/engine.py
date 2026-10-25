"""Integer-money ledger, bound approvals and recoverable sandbox operations.

All mutations serialize through SQLite BEGIN IMMEDIATE. The simulated bank commits
its receipt before the application acknowledges it, permitting real timeout and
restart tests. No generated code, arbitrary tools or real payment providers run.
"""
import calendar
import csv
import hmac
import io
import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from guardian.core import canonical, digest, parse_major_units
from guardian.fraud import assess

TZ = timezone(timedelta(hours=8))
ACTIVE = ('CONFIRMED', 'SCHEDULED', 'UNKNOWN', 'SUCCEEDED')


class Denied(Exception):
    def __init__(self, message, code='DENIED'):
        self.message, self.code = message, code
        super().__init__(message)


def money(text):
    """Reject fractional cents, non-finite values, exponents and signed inputs."""
    try:
        value = parse_major_units(text, exponent=2)
    except ValueError:
        raise Denied('金额须为最多两位小数的正数字符串', 'AMOUNT')
    if value <= 0 or value > 10_000_000:
        raise Denied('单笔沙箱转账范围为0.01至100000元', 'AMOUNT')
    return value


def now():
    return datetime.now(TZ)


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS accounts(owner TEXT PRIMARY KEY, floor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,owner TEXT NOT NULL,amount INTEGER NOT NULL,
 merchant TEXT NOT NULL,category TEXT NOT NULL,day TEXT NOT NULL,source TEXT NOT NULL,
 UNIQUE(owner,source));
CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,
 amount INTEGER NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,
 payload TEXT NOT NULL,binding TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,
 idem TEXT NOT NULL,level TEXT NOT NULL,approved REAL,UNIQUE(owner,idem));
CREATE TABLE IF NOT EXISTS challenges(op TEXT PRIMARY KEY,owner TEXT NOT NULL,hash TEXT NOT NULL,
 expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS provider_receipts(op TEXT PRIMARY KEY,owner TEXT NOT NULL,
 receipt TEXT NOT NULL UNIQUE,amount INTEGER NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS locks(owner TEXT PRIMARY KEY,failures INTEGER NOT NULL DEFAULT 0,
 locked_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,
 event TEXT NOT NULL,payload TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,owner TEXT NOT NULL,
 csrf TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS dispatch(op TEXT PRIMARY KEY,token TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS commitments(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,
 kind TEXT NOT NULL,amount INTEGER NOT NULL,day TEXT NOT NULL,essential INTEGER NOT NULL,
 recipient TEXT,archived INTEGER NOT NULL DEFAULT 0,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_links(item TEXT PRIMARY KEY,op TEXT NOT NULL UNIQUE,
 FOREIGN KEY(item) REFERENCES commitments(id),FOREIGN KEY(op) REFERENCES operations(id));
CREATE TABLE IF NOT EXISTS planning_profiles(owner TEXT PRIMARY KEY,balance INTEGER NOT NULL,floor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS transfer_holds(owner TEXT PRIMARY KEY,reason TEXT NOT NULL,created REAL NOT NULL);
'''


class Engine:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as c:
            c.executescript(SCHEMA)
            c.execute('PRAGMA journal_mode=WAL')

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def audit(self, c, owner, event, payload):
        previous = c.execute('SELECT hash FROM audit WHERE owner=? ORDER BY seq DESC LIMIT 1', (owner,)).fetchone()
        previous = previous[0] if previous else '0' * 64
        record = dict(owner=owner, event=event, payload=payload, previous=previous, created=time.time())
        c.execute('INSERT INTO audit(owner,event,payload,previous,hash,created) VALUES(?,?,?,?,?,?)',
                  (owner, event, canonical(payload), previous, digest(record), record['created']))

    def bootstrap(self):
        owner, token, csrf = uuid.uuid4().hex, secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        today = now().date()
        with self.tx() as c:
            c.execute('INSERT INTO accounts VALUES(?,?)', (owner, 200000))
            c.execute('INSERT INTO locks(owner) VALUES(?)', (owner,))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), owner, csrf, time.time() + 86400))
            c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',
                      (uuid.uuid4().hex, owner, 1200000, '期初余额', '期初', (today-timedelta(days=100)).isoformat(), 'opening'))
            for offset in (3, 2, 1):
                absolute = today.year * 12 + today.month - 1 - offset
                day = f'{absolute//12:04d}-{absolute%12+1:02d}-05'
                for key, merchant, amount, category in [('cloud-a', '云盘会员 A', 2900, '订阅'),
                  ('cloud-b', '云盘会员 B', 2900, '订阅'), ('video', '视频会员', 3900, '订阅'),
                  ('food', '日常餐饮', 65000, '餐饮')]:
                    c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',
                              (uuid.uuid4().hex, owner, -amount, merchant, category, day, key+day))
            for key, name, amount in [('cloud-a','云盘会员 A',2900),('cloud-b','云盘会员 B',2900),('video','视频会员',3900)]:
                c.execute('INSERT INTO subscriptions VALUES(?,?,?,?,?)', (owner+':'+key, owner, name, amount, 'ACTIVE'))
            self.audit(c, owner, 'SANDBOX_OPENED', {'opening_cents':1200000,'floor_cents':200000})
        return dict(owner=owner, token=token, csrf=csrf)

    def session(self, token):
        with closing(self.connect()) as c:
            row = c.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (digest(token), time.time())).fetchone()
        if not row:
            raise Denied('演示会话已过期，请刷新页面', 'SESSION')
        return dict(row)

    def contacts(self):
        return [dict(id='landlord',name='林女士（房东）',last4='8026'),
                dict(id='zhang-work',name='张伟（同事）',last4='1218'),
                dict(id='zhang-school',name='张伟（同学）',last4='6739')]

    def hold_transfer(self, owner, risk):
        """Persistent hold: neither model instructions nor direct API can clear it.

        This local version has no bank/manual-review integration. The hold remains
        until an operator reviews it; querying/reconciling existing work is allowed.
        """
        with self.tx() as c:
            c.execute('INSERT OR REPLACE INTO transfer_holds VALUES(?,?,?)',
                      (owner, canonical(risk), time.time()))
            self.audit(c, owner, 'TRANSFER_SAFETY_HOLD', {'signals': risk['signals']})

    def check_transfer_hold(self, c, owner):
        if c.execute('SELECT 1 FROM transfer_holds WHERE owner=?', (owner,)).fetchone():
            raise Denied('当前账户的转账已暂停，需通过官方渠道人工核实；不能直接继续付款。', 'SAFETY_HOLD')

    def balance(self, c, owner):
        return c.execute("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE owner=? AND source NOT LIKE 'csv:%'", (owner,)).fetchone()[0]

    def reserved(self, c, owner):
        # A receipt means money has already left the ledger. Never deduct its hold twice.
        rows = c.execute("SELECT payload FROM operations o WHERE owner=? AND kind='transfer' AND status IN ('CONFIRMED','SCHEDULED','UNKNOWN') AND NOT EXISTS(SELECT 1 FROM provider_receipts p WHERE p.op=o.id)", (owner,)).fetchall()
        return sum(json.loads(r[0])['amount_cents'] for r in rows)

    def required_floor(self,c,owner):
        account=c.execute('SELECT floor FROM accounts WHERE owner=?',(owner,)).fetchone()
        if not account: raise Denied('账户不存在','SESSION')
        floors=[account[0]]
        rows=c.execute("SELECT payload FROM operations o WHERE owner=? AND kind='transfer' AND status IN ('CONFIRMED','SCHEDULED','UNKNOWN') AND NOT EXISTS(SELECT 1 FROM provider_receipts r WHERE r.op=o.id)",(owner,))
        floors.extend(json.loads(row['payload']).get('minimum_balance_cents',0) for row in rows)
        return max(floors)

    def tier(self, c, owner, payload, exclude=None):
        rows = c.execute("SELECT id,payload FROM operations WHERE owner=? AND kind='transfer' AND status IN ('CONFIRMED','SCHEDULED','UNKNOWN','SUCCEEDED')", (owner,)).fetchall()
        total = sum(json.loads(r['payload'])['amount_cents'] for r in rows
                    if r['id'] != exclude and json.loads(r['payload'])['due_day'] == payload['due_day'])
        return 'RED' if total + payload['amount_cents'] > 100000 else 'YELLOW'

    def check_lock(self, c, owner):
        row = c.execute('SELECT * FROM locks WHERE owner=?', (owner,)).fetchone()
        if row and row['locked_until'] > time.time():
            raise Denied('连续验证失败，账户已熔断锁定5分钟', 'LOCKED')

    def operation(self, c, owner, op):
        row = c.execute('SELECT * FROM operations WHERE id=? AND owner=?', (op, owner)).fetchone()
        if not row:
            raise Denied('操作不存在或不属于当前会话', 'NOT_FOUND')
        return row

    @staticmethod
    def view(row):
        d = dict(row)
        d['payload'] = json.loads(d['payload'])
        return d

    def prepare(self, owner, kind, payload, idem, source_item=None, task_id=None, task_revision=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', idem):
            raise Denied('幂等键格式无效', 'SCHEMA')
        if kind == 'transfer':
            if not {'recipient','amount','due_day','note'}<=set(payload) or set(payload)-{'recipient','amount','due_day','note','minimum_balance'}:
                raise Denied('转账参数字段不在白名单', 'SCHEMA')
            if payload['recipient'] not in {x['id'] for x in self.contacts()}:
                raise Denied('须从已核对联系人中明确选择收款人', 'RECIPIENT')
            due = datetime.strptime(payload['due_day'], '%Y-%m-%d').date()
            if not now().date() <= due <= now().date()+timedelta(days=30):
                raise Denied('预约日期须为今天至未来30天', 'DATE')
            if len(payload['note']) > 200:
                raise Denied('备注过长', 'SCHEMA')
            risk = assess(payload['note'])
            if risk['blocked']:
                self.hold_transfer(owner, risk)
                raise Denied('这段转账描述包含可疑诱导，已暂停资金操作，请先人工核实。', 'SAFETY_HOLD')
            cleaned = dict(recipient=payload['recipient'],amount_cents=money(payload['amount']),
                           due_day=due.isoformat(),note=payload['note'],currency='CNY')
            if payload.get('minimum_balance'):
                cleaned['minimum_balance_cents']=money(payload['minimum_balance'])
        elif kind == 'cancel_subscription':
            if set(payload) != {'subscription_id'}:
                raise Denied('订阅参数字段不在白名单', 'SCHEMA')
            cleaned = payload.copy()
        else:
            raise Denied('没有此写入能力', 'CAPABILITY')
        binding = digest(dict(owner=owner,kind=kind,payload=cleaned))
        with self.tx() as c:
            self.check_lock(c, owner)
            if kind == 'transfer': self.check_transfer_hold(c, owner)
            task_data = None
            if task_id:
                task_row = c.execute('SELECT data FROM assistant_tasks WHERE id=? AND owner=? AND kind=?',
                                     (task_id, owner, 'subscriptions' if kind=='cancel_subscription' else kind)).fetchone()
                if not task_row: raise Denied('办理任务不属于当前账户或类型不符', 'STATE')
                task_data = json.loads(task_row['data'])
                if task_revision is not None and task_data.get('revision',1)!=task_revision:
                    raise Denied('任务版本已变化，不能使用旧草稿。','STALE_TASK')
                if task_data.get('status') in ('PAUSED','HANDOFF'):
                    raise Denied('任务已暂停或转人工。','TASK_PAUSED')
                if kind=='transfer':
                    requested=task_data.get('draft',{}).get('minimum_balance')
                    if requested and cleaned.get('minimum_balance_cents')!=money(requested):
                        raise Denied('草稿不能丢弃任务中的余额条件。','CONSTRAINT')
                else:
                    sub_choice=next((s for s in task_data.get('subscriptions',[]) if s['id']==cleaned['subscription_id']),None)
                    if not sub_choice or sub_choice.get('preference')!='unneeded' or time.time()-task_data.get('consent_at',0)>600:
                        raise Denied('协议查询和选择已变化，不能使用旧选择。','APPROVAL')
                for prior_id in task_data.get('operation_ids', []):
                    prior = self.operation(c, owner, prior_id)
                    if prior['status'] == 'CANCELLED': continue
                    if kind=='cancel_subscription' and json.loads(prior['payload']).get('subscription_id')!=cleaned['subscription_id']:
                        continue
                    if prior['binding'] == binding: return self.view(prior)
                    if prior['status'] != 'PREPARED':
                        raise Denied('这项任务已有已确认、已付款或未知操作，请先核查原操作，不能另建付款。', 'TASK_IN_FLIGHT')
                    c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?", (prior_id,))
                    self.audit(c, owner, 'DRAFT_SUPERSEDED', {'op': prior_id, 'task': task_id})
                if kind=='transfer':
                    needed=max(self.required_floor(c,owner),cleaned.get('minimum_balance_cents',0))
                    if self.balance(c,owner)-self.reserved(c,owner)-cleaned['amount_cents']<needed:
                        raise Denied('当前余额不能同时满足付款和保留底线条件。','RESERVE_FLOOR')
            if source_item:
                item=c.execute('SELECT * FROM commitments WHERE id=? AND owner=? AND archived=0',(source_item,owner)).fetchone()
                if not item or item['source']=='manual_plan' or kind!='transfer' or item['kind']!='expense' or (item['recipient'],item['amount'],item['day'])!=(cleaned['recipient'],cleaned['amount_cents'],cleaned['due_day']):
                    raise Denied('计划已变化，请重新检查后准备付款','PLAN_CHANGED')
                linked=c.execute('SELECT o.* FROM plan_links l JOIN operations o ON o.id=l.op WHERE l.item=?',(source_item,)).fetchone()
                if linked and linked['status']!='CANCELLED':
                    if linked['binding']!=binding: raise Denied('已有操作与计划不一致','PLAN_CHANGED')
                    return self.view(linked)
                idem='plan_'+source_item+('_'+linked['id'] if linked else '')
            existing = c.execute('SELECT * FROM operations WHERE owner=? AND idem=?', (owner,idem)).fetchone()
            if existing and task_data is not None and existing['status']=='CANCELLED':
                # Returning to an earlier amount creates a new draft revision;
                # replay must not resurrect its cancelled authorization.
                idem = idem + '_' + str(len(task_data.get('operation_ids', [])))
                existing = c.execute('SELECT * FROM operations WHERE owner=? AND idem=?', (owner,idem)).fetchone()
            if existing:
                if existing['binding'] != binding:
                    raise Denied('同一幂等键不能绑定不同参数', 'IDEMPOTENCY_CONFLICT')
                return self.view(existing)
            if kind == 'cancel_subscription':
                sub = c.execute("SELECT * FROM subscriptions WHERE id=? AND owner=? AND status='ACTIVE'", (cleaned['subscription_id'],owner)).fetchone()
                if not sub:
                    raise Denied('有效订阅不存在', 'SUBSCRIPTION')
            level = self.tier(c, owner, cleaned) if kind == 'transfer' else 'YELLOW'
            op = uuid.uuid4().hex
            c.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (op,owner,kind,canonical(cleaned),binding,'PREPARED',time.time(),idem,level,None))
            if source_item:
                c.execute('INSERT OR REPLACE INTO plan_links VALUES(?,?)',(source_item,op))
            self.audit(c, owner, 'OPERATION_PREPARED', dict(op=op,binding=binding,level=level,payload=cleaned))
            if task_data is not None:
                task_data.setdefault('operation_ids', []).append(op)
                task_data['revision']=task_data.get('revision',1)+1
                if kind=='transfer': task_data.setdefault('draft',{}).update(recipient=cleaned['recipient'],amount=payload['amount'],due_day=cleaned['due_day'])
                c.execute('UPDATE assistant_tasks SET data=? WHERE id=?', (canonical(task_data), task_id))
            return self.view(self.operation(c,owner,op))

    def challenge(self, owner, op, binding):
        code = f'{secrets.randbelow(1000000):06d}'
        with self.tx() as c:
            self.check_lock(c,owner)
            row=self.operation(c,owner,op)
            if row['status'] != 'PREPARED' or row['binding'] != binding or time.time()-row['created'] > 600:
                raise Denied('待确认操作已变化、过期或已处理', 'APPROVAL')
            c.execute('INSERT OR REPLACE INTO challenges VALUES(?,?,?,?,0,0)',
                      (op,owner,digest(dict(op=op,binding=binding,code=code)),time.time()+120))
            self.audit(c,owner,'DEMO_CHALLENGE_ISSUED',dict(op=op,expires_in=120))
        return dict(demo_code=code, expires_in=120, mode='SANDBOX_ONLY_NOT_REAL_MFA')

    def confirm(self, owner, op, binding, approved, otp=None):
        failure=None
        with self.tx() as c:
            self.check_lock(c,owner)
            row=self.operation(c,owner,op)
            if not approved or not hmac.compare_digest(row['binding'],binding):
                raise Denied('必须明确确认原始参数，参数摘要不匹配', 'BINDING')
            if row['status'] in ACTIVE:
                return self.view(row)
            if row['status'] != 'PREPARED' or time.time()-row['created'] > 600:
                raise Denied('操作已取消或确认已过期', 'EXPIRED')
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_tasks'").fetchone():
                for task_row in c.execute('SELECT data FROM assistant_tasks WHERE owner=?',(owner,)):
                    task_data=json.loads(task_row['data'])
                    if op in task_data.get('operation_ids',[]) and (task_data.get('status') in ('PAUSED','HANDOFF') or
                        any(task_data.get(flag) for flag in ('unresolved_constraint','unresolved_amount','unsupported_currency','unresolved_schedule'))):
                        raise Denied('所属任务已暂停或转人工，原草稿不能确认。','TASK_PAUSED')
            payload=json.loads(row['payload'])
            if row['kind']=='transfer': self.check_transfer_hold(c, owner)
            level=self.tier(c,owner,payload) if row['kind']=='transfer' else 'YELLOW'
            if level=='RED':
                ch=c.execute('SELECT * FROM challenges WHERE op=? AND owner=?',(op,owner)).fetchone()
                valid=bool(ch and not ch['consumed'] and ch['expires']>time.time() and otp and
                           hmac.compare_digest(ch['hash'],digest(dict(op=op,binding=binding,code=otp))))
                if not valid:
                    c.execute('UPDATE locks SET failures=failures+1 WHERE owner=?',(owner,))
                    c.execute('UPDATE locks SET locked_until=? WHERE owner=? AND failures>=3',(time.time()+300,owner))
                    self.audit(c,owner,'VERIFICATION_REJECTED',dict(op=op,level=level))
                    failure=Denied('当前日累计已超过1000元，需有效演示验证码；3次失败将锁定', 'MFA_REQUIRED')
                else:
                    c.execute('UPDATE challenges SET consumed=1 WHERE op=?',(op,))
            if failure is None:
                if row['kind']=='transfer':
                    if payload['due_day'] < now().date().isoformat():
                        raise Denied('预约日期已过，请重新准备', 'DATE')
                    floor=max(self.required_floor(c,owner),payload.get('minimum_balance_cents',0))
                    if self.balance(c,owner)-self.reserved(c,owner)-payload['amount_cents'] < floor:
                        raise Denied(f'执行后可用余额低于{floor/100:.2f}元保留底线条件', 'RESERVE_FLOOR')
                status='SCHEDULED' if row['kind']=='transfer' and payload['due_day']>now().date().isoformat() else 'CONFIRMED'
                c.execute('UPDATE operations SET status=?,level=?,approved=? WHERE id=?',(status,level,time.time(),op))
                c.execute('UPDATE locks SET failures=0 WHERE owner=?',(owner,))
                self.audit(c,owner,'USER_CONFIRMED',dict(op=op,binding=binding,level=level,status=status))
                result=self.view(self.operation(c,owner,op))
        if failure:
            raise failure
        return result

    def execute(self, owner, op, fault='none'):
        """Fault 'timeout_after_accept' loses acknowledgment AFTER the bank commit."""
        if fault not in {'none','timeout_after_accept','timeout_before_accept'}:
            raise Denied('未知沙箱故障', 'SCHEMA')
        dispatch_token=secrets.token_hex(16)
        with self.tx() as c:
            self.check_lock(c,owner)
            row=self.operation(c,owner,op)
            if row['status']=='SUCCEEDED': return self.view(row)
            if row['kind']=='transfer': self.check_transfer_hold(c, owner)
            if row['status']=='UNKNOWN':
                raise Denied('状态未知，必须先回查原交易，不能直接重付', 'RECONCILE_FIRST')
            if row['status'] not in {'CONFIRMED','SCHEDULED'}:
                raise Denied('尚未确认，不可执行', 'APPROVAL')
            p=json.loads(row['payload'])
            if row['kind']=='transfer' and p['due_day']!=now().date().isoformat():
                raise Denied('预约未到期或已错过日期；过期须重新审批', 'NOT_DUE')
            # Persist UNKNOWN before contacting the provider. A crash is recoverable.
            c.execute("UPDATE operations SET status='UNKNOWN' WHERE id=?",(op,))
            c.execute('INSERT OR REPLACE INTO dispatch VALUES(?,?,?)',(op,dispatch_token,time.time()+30))
            self.audit(c,owner,'EXECUTION_STARTED',dict(op=op, fault=fault))
        if fault=='timeout_before_accept':
            self.release_dispatch(op,dispatch_token)
            return self.get_operation(owner,op)
        # Provider transaction: idempotency, debit and receipt commit atomically.
        with self.tx() as c:
            row=self.operation(c,owner,op);p=json.loads(row['payload'])
            if row['kind']=='transfer': self.check_transfer_hold(c, owner)
            lease=c.execute('SELECT * FROM dispatch WHERE op=?',(op,)).fetchone()
            if row['status']!='UNKNOWN' or not lease or lease['token']!=dispatch_token or lease['expires']<=time.time():
                raise Denied('执行租约失效，请回查后再处理','LEASE')
            if not c.execute('SELECT 1 FROM provider_receipts WHERE op=?',(op,)).fetchone():
                if row['kind']=='transfer':
                    remaining=self.balance(c,owner)-self.reserved(c,owner)
                    if remaining<max(self.required_floor(c,owner),p.get('minimum_balance_cents',0)):
                        raise Denied('付款前余额条件已变化，请核实原交易。','RESERVE_FLOOR')
                    c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',
                              (uuid.uuid4().hex,owner,-p['amount_cents'],p['recipient'],'转账',now().date().isoformat(),'payment:'+op))
                else:
                    c.execute("UPDATE subscriptions SET status='CANCELLED' WHERE id=? AND owner=?",(p['subscription_id'],owner))
                c.execute('INSERT INTO provider_receipts VALUES(?,?,?,?,?)',
                          (op,owner,'SBX-'+uuid.uuid4().hex[:16],p.get('amount_cents',0),time.time()))
                self.audit(c,owner,'SANDBOX_PROVIDER_ACCEPTED',dict(op=op,amount_cents=p.get('amount_cents',0)))
        self.release_dispatch(op,dispatch_token)
        if fault=='timeout_after_accept': return self.get_operation(owner,op)
        return self.recover(owner,op)

    def release_dispatch(self, op, token):
        with self.tx() as c:
            c.execute('UPDATE dispatch SET expires=0 WHERE op=? AND token=?',(op,token))

    def recover(self, owner, op):
        with self.tx() as c:
            self.check_lock(c,owner)
            row=self.operation(c,owner,op)
            if row['status']=='SUCCEEDED': return self.view(row)
            if row['status']!='UNKNOWN': raise Denied('此操作不需要回查', 'STATE')
            lease=c.execute('SELECT expires FROM dispatch WHERE op=?',(op,)).fetchone()
            if lease and lease[0]>time.time():
                raise Denied('执行仍在进行；进程意外退出时请等待30秒再回查','IN_FLIGHT')
            receipt=c.execute('SELECT * FROM provider_receipts WHERE op=? AND owner=?',(op,owner)).fetchone()
            # The local provider is authoritative. Real adapters must distinguish
            # definitive NOT_FOUND from eventually consistent or failed queries.
            state='SUCCEEDED' if receipt else 'CONFIRMED'
            c.execute('UPDATE operations SET status=? WHERE id=?',(state,op))
            self.audit(c,owner,'RECONCILED',dict(op=op,status=state,receipt=receipt['receipt'] if receipt else None))
            return self.view(self.operation(c,owner,op))

    def cancel(self, owner, op):
        with self.tx() as c:
            self.check_lock(c,owner)
            row=self.operation(c,owner,op)
            if row['status'] not in {'PREPARED','SCHEDULED','CONFIRMED'}:
                raise Denied('已付款／状态未知不能本地撤销，请回查或另走退款', 'STATE')
            c.execute("UPDATE operations SET status='CANCELLED' WHERE id=?",(op,))
            self.audit(c,owner,'OPERATION_CANCELLED',dict(op=op))
            return self.view(self.operation(c,owner,op))

    def get_operation(self, owner, op):
        with closing(self.connect()) as c: return self.view(self.operation(c,owner,op))

    def run_due(self):
        """Only preapproved, immutable scheduled payments due today are dispatched.

        Missed-date payments deliberately require a new operation. UNKNOWN work
        remains visible for explicit reconciliation rather than automatic replay.
        """
        with closing(self.connect()) as c:
            rows=c.execute("SELECT id,owner,payload FROM operations WHERE status='SCHEDULED'").fetchall()
        for row in rows:
            if json.loads(row['payload'])['due_day']==now().date().isoformat():
                try: self.execute(row['owner'],row['id'])
                except Denied: pass  # Policy/lock refusal leaves the reservation visible.

    def import_csv(self, owner, text):
        if len(text)>300000: raise Denied('CSV超过300KB上限','CSV')
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
        if set(reader.fieldnames or []) != {'id','date','merchant','amount','category'}:
            raise Denied('列必须为id,date,merchant,amount,category','CSV')
        rows=list(reader)
        if not rows or len(rows)>500: raise Denied('每次导入1至500行','CSV')
        cleaned=[]
        for r in rows:
            try:
                day=datetime.strptime(r['date'],'%Y-%m-%d').date()
                if day>now().date() or len(r['id'])>80 or not r['id'] or not 1<=len(r['merchant'])<=200 or not 1<=len(r['category'])<=30:
                    raise ValueError()
                raw=r['amount'];amount=money(raw[1:] if raw.startswith('-') else raw)
                amount=-amount if raw.startswith('-') else amount
            except (ValueError, TypeError): raise Denied('CSV日期或字段无效','CSV')
            cleaned.append((r['id'],day.isoformat(),r['merchant'],amount,r['category']))
        inserted=0
        with self.tx() as c:
            self.check_lock(c,owner)
            for source,day,merchant,amount,category in cleaned:
                source='csv:'+source
                old=c.execute('SELECT * FROM ledger WHERE owner=? AND source=?',(owner,source)).fetchone()
                if old:
                    if (old['day'],old['merchant'],old['amount'],old['category'])!=(day,merchant,amount,category):
                        raise Denied('同一CSV流水ID内容冲突，整批撤销','IMPORT_CONFLICT')
                    continue
                # CSV is evidence, never the authority for spendable money.
                c.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,owner,amount,merchant,category,day,source))
                inserted+=1
            self.audit(c,owner,'CSV_IMPORTED',dict(inserted=inserted,total=len(rows),source='analysis_only'))
        return dict(inserted=inserted,duplicates=len(rows)-inserted,scope='analysis_only')

    def snapshot(self, owner):
        with closing(self.connect()) as c:
            # Imported statements are analysis evidence; they cannot mint funds.
            balance=c.execute("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE owner=? AND source NOT LIKE 'csv:%'",(owner,)).fetchone()[0]
            reserved=self.reserved(c,owner)
            bills=[dict(r) for r in c.execute("SELECT * FROM ledger WHERE owner=? AND source!='opening' ORDER BY day DESC,id",(owner,))]
            subs=[dict(r) for r in c.execute('SELECT * FROM subscriptions WHERE owner=?',(owner,))]
            ops=[self.view(r) for r in c.execute('SELECT * FROM operations WHERE owner=? ORDER BY created DESC',(owner,))]
            audit=[dict(r) for r in c.execute('SELECT * FROM audit WHERE owner=? ORDER BY seq',(owner,))]
            lock=dict(c.execute('SELECT * FROM locks WHERE owner=?',(owner,)).fetchone())
        categories={}
        for b in bills:
            if b['amount']<0: categories[b['category']]=categories.get(b['category'],0)-b['amount']
        recurring=[]
        for merchant in sorted({b['merchant'] for b in bills if b['category']=='订阅'}):
            history=sorted([b for b in bills if b['merchant']==merchant],key=lambda b:b['day'])
            intervals=[(datetime.fromisoformat(b['day'])-datetime.fromisoformat(a['day'])).days for a,b in zip(history,history[1:])]
            if len(history)>=3 and all(25<=x<=35 for x in intervals):
                recurring.append(dict(merchant=merchant,observations=len(history),intervals=intervals,amount_cents=abs(history[-1]['amount'])))
        return dict(mode='LOCAL_BANK_SANDBOX',balance_cents=balance,reserved_cents=reserved,
                    available_cents=balance-reserved,floor_cents=200000, bills=bills,subscriptions=subs,
                    operations=ops,contacts=self.contacts(),categories=categories,recurring=recurring,
                    potential_duplicate='云盘A/B用途可能重叠，尚不能证明重复扣费；请核对两个会员是否都需要。',
                    audit=audit,lock=lock,audit_valid=self.verify_audit(audit),planner='deterministic_baseline')

    @staticmethod
    def verify_audit(rows):
        previous='0'*64
        for r in rows:
            record=dict(owner=r['owner'],event=r['event'],payload=json.loads(r['payload']),previous=r['previous'],created=r['created'])
            if previous!=r['previous'] or not hmac.compare_digest(digest(record),r['hash']): return False
            previous=r['hash']
        return True

    def plan(self, owner, message):
        """Bounded rule baseline; never pretend these labels came from an LLM."""
        state=self.snapshot(owner)
        if re.search(r'忽略.*(?:规则|限制|权限)|绕过|免验证|ignore.*(?:rules|instructions)',message,re.I):
            return dict(mode='deterministic_baseline',text='不能绕过确认或验证。你可以查询账单，或准备一笔需要本人确认的转账。',nodes=[])
        if '张伟' in message:
            return dict(mode='deterministic_baseline',text='有两位张伟，请在收款人中明确选择同事或同学，再准备转账。',nodes=[])
        rent=bool(re.search(r'房租|房东',message));billing=bool(re.search(r'账单|分析|消费|订阅|会员|续费|现金流|生活费',message))
        if not rent and not billing:
            return dict(mode='deterministic_baseline',text='当前规则基线支持账单分析、订阅核查、给房东准备转账。其他需求请使用下方结构化转账入口；不会猜测收款人或金额。',nodes=[])
        nodes=[dict(id='bills',capability='analyze_bills',depends_on=[],status='DONE',permission='GREEN'),
               dict(id='subscriptions',capability='review_subscriptions',depends_on=['bills'],status='DONE',permission='YELLOW_READ_ONLY_PREVIEW')]
        text=f"可用余额{state['available_cents']/100:.2f}元；生活费底线2000元。找到{len(state['recurring'])}个周期扣费候选。云盘A/B可能用途重叠，需本人核查。"
        draft=None
        if rent:
            matches=re.findall(r'(\d+(?:\.\d{1,2})?)\s*元?',message)
            if not matches:
                text+=' 房租金额未明确，请填写金额后准备操作。'
            else:
                # Multiple amounts are ambiguous. Never infer which one is rent.
                if len(matches)!=1:
                    text+=' 检测到多个金额，请在转账表单中明确房租金额与预约日期。'
                else:
                    draft=dict(recipient='landlord',amount=matches[0],due_day=now().date().isoformat(),note='房租')
                    text+=' 已填入房东转账草稿，请核对金额与日期；尚未创建或执行付款。'
                    nodes.append(dict(id='rent',capability='prepare_transfer',depends_on=['bills','subscriptions'],status='DRAFT',permission='BACKEND_DECIDES'))
        return dict(mode='deterministic_baseline',text=text,nodes=nodes,draft=draft)
