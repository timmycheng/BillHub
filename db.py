#!/usr/bin/env python3
"""BillHub - SQLite 数据层
表结构：
  contracts       合同信息表
  payment_records 支付进度表
"""
import sqlite3
import os
import re
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get('BILLHUB_DB') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'bill.db')

# 北京时间（东八区固定偏移，无夏令时；不依赖系统时区与 tzdata）
_CN_TZ = timezone(timedelta(hours=8))


def cn_now():
    """当前北京时间（aware datetime），与服务器/容器时区无关。"""
    return datetime.now(_CN_TZ)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')  # 启用外键级联删除
    return conn


def init_db():
    conn = get_conn()
    conn.execute('PRAGMA journal_mode=WAL')  # 并发读优化（持久化到 db 文件）
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_no TEXT UNIQUE,               -- 合同编号（可空，靠隐藏 id 区分）
        contract_name TEXT NOT NULL,           -- 合同名称
        customer_name TEXT,                    -- 客户/甲方名称
        contract_manager TEXT,                 -- 经办人（仅合同管理用，不填入审批表）
        category TEXT,                         -- 分类：人力外包/采购/维保/软件开发/收据
        payee TEXT,                            -- 收款单位（随合同走，填入审批表）
        bank_name TEXT,                        -- 开户银行
        bank_account TEXT,                     -- 银行账号
        total_amount REAL NOT NULL,            -- 合同总金额
        sign_date TEXT,                        -- 签订日期 YYYY-MM-DD
        start_date TEXT,                       -- 生效时间 YYYY-MM-DD
        end_date TEXT,                         -- 结束时间 YYYY-MM-DD
        doc_file TEXT,                         -- 合同电子稿文件路径（doc/docx）
        scan_file TEXT,                        -- 合同扫描件文件路径（PDF）
        remark TEXT,                           -- 备注
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS payment_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL,
        pay_date TEXT NOT NULL,                -- 报销日期（= 创建日期）
        invoice_date TEXT,                     -- 发票开票日期（OCR 识别，可空）
        stage TEXT,                            -- 阶段/期数
        amount REAL NOT NULL,                  -- 本次支付金额
        invoice_no TEXT,                       -- 发票号
        main_content TEXT,                     -- 主要内容（留空时自动生成的介绍文案）
        remark TEXT,                           -- 备注
        invoice_file TEXT,                     -- 本次上传的发票/收据文件路径
        report_file TEXT,                      -- 本次生成的审批表 Excel 路径
        status TEXT DEFAULT '已提交',          -- 报销状态：已提交/审核中/已打款
        submitted_at TEXT,                     -- 已提交时间
        reviewed_at TEXT,                      -- 审核中时间
        paid_at TEXT,                          -- 已打款时间
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (contract_id) REFERENCES contracts(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS payment_plan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL,          -- 所属合同
        seq INTEGER NOT NULL,                  -- 期数序号，从 1 开始
        condition TEXT,                        -- 支付条件，如 "签订后7天内"
        ratio REAL,                            -- 比例（0.3 表示 30%）
        amount REAL NOT NULL,                  -- 计划金额（元）
        FOREIGN KEY (contract_id) REFERENCES contracts(id) ON DELETE CASCADE,
        UNIQUE (contract_id, seq)
    );

    CREATE TABLE IF NOT EXISTS payment_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER NOT NULL,
        orig_name TEXT,                       -- 原始文件名（展示用）
        path TEXT NOT NULL,                   -- 存储路径
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (payment_id) REFERENCES payment_records(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,                  -- 配置项名（如 ldap_uri / ocr_rules）
        value TEXT                             -- 配置值（JSON 或字符串）
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,         -- 登录名
        password_hash TEXT,                    -- 本地账号密码哈希（AD 用户留空）
        display_name TEXT,                     -- 显示名
        is_admin INTEGER DEFAULT 0,            -- 管理员绕过经办人隔离
        ad_dn TEXT,                            -- LDAP distinguishedName，启用 AD 时用
        must_change_password INTEGER DEFAULT 0, -- 批量导入初始密码用户：首次登录强制改密
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,                  -- 配置项名（如 ldap_uri / ocr_rules）
        value TEXT                             -- 配置值（JSON 或字符串）
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,                       -- 操作人 id（登录失败等场景可空）
        username TEXT NOT NULL,                -- 操作人用户名（快照，用户删除后仍可读）
        action TEXT NOT NULL,                  -- 操作类型（如 登录成功 / 新建合同 / 报销状态流转）
        target TEXT DEFAULT '',                -- 操作对象描述（合同编号+名称 / 用户名 / BX-xxxxx 等）
        detail TEXT DEFAULT '',                -- 补充说明（如状态流转方向）
        ip TEXT DEFAULT '',                    -- 来源 IP
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );
    ''')
    conn.commit()
    conn.close()
    _migrate_contracts()
    _migrate_payments()
    _migrate_users()


_NEW_COLUMNS = {  # 增量迁移：列名 -> 定义
    'contract_manager': 'TEXT',
    'category': 'TEXT',
    'payee': 'TEXT',
    'bank_name': 'TEXT',
    'bank_account': 'TEXT',
    'start_date': 'TEXT',
    'end_date': 'TEXT',
    'doc_file': 'TEXT',
    'scan_file': 'TEXT',
}


def _migrate_payments():
    """payment_records 增量迁移：补 invoice_file / report_file / 报销状态等列。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(payment_records)').fetchall()}
        for name in ('invoice_date', 'invoice_file', 'report_file', 'main_content'):
            if name not in cols:
                conn.execute(f'ALTER TABLE payment_records ADD COLUMN {name} TEXT')
        # 报销状态字段（已提交/审核中/已打款）
        for name, ddl in (('status', "TEXT DEFAULT '已提交'"),
                          ('submitted_at', 'TEXT'), ('reviewed_at', 'TEXT'),
                          ('paid_at', 'TEXT')):
            if name not in cols:
                conn.execute(f'ALTER TABLE payment_records ADD COLUMN {name} {ddl}')
        # 回填历史记录：状态默认已提交，提交时间=创建时间
        conn.execute("UPDATE payment_records SET status='已提交' WHERE status IS NULL OR status=''")
        conn.execute("UPDATE payment_records SET submitted_at=created_at "
                     "WHERE (submitted_at IS NULL OR submitted_at='') AND created_at IS NOT NULL")
        conn.commit()
    finally:
        conn.close()


def _migrate_users():
    """增量迁移：contracts 加 owner_id，payment_records 加 user_id（引用 users 表）。
    桌面版不传这两个字段，默认 NULL（管理员视角可见全部）。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(contracts)').fetchall()}
        if 'owner_id' not in cols:
            conn.execute('ALTER TABLE contracts ADD COLUMN owner_id INTEGER REFERENCES users(id)')
        cols = {r[1] for r in conn.execute('PRAGMA table_info(payment_records)').fetchall()}
        if 'user_id' not in cols:
            conn.execute('ALTER TABLE payment_records ADD COLUMN user_id INTEGER REFERENCES users(id)')
        cols = {r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()}
        if 'must_change_password' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0')
        conn.commit()
    finally:
        conn.close()


def _migrate_contracts():
    """一次性迁移：
    1) 旧表（contract_no NOT NULL、无 contract_manager）→ 重建为新结构；
    2) 已迁移表缺新列（category/payee 等）→ ALTER TABLE ADD COLUMN 增量补齐。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(contracts)').fetchall()}
        if 'contract_manager' not in cols:  # 最旧结构 → 重建
            conn.execute('PRAGMA foreign_keys=OFF')  # 重建期间暂停外键检查
            conn.executescript('''
            CREATE TABLE contracts_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_no TEXT UNIQUE,
                contract_name TEXT NOT NULL,
                customer_name TEXT,
                contract_manager TEXT,
                category TEXT,
                payee TEXT,
                bank_name TEXT,
                bank_account TEXT,
                total_amount REAL NOT NULL,
                sign_date TEXT,
                remark TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            INSERT INTO contracts_new (id, contract_no, contract_name, customer_name,
                                       total_amount, sign_date, remark, created_at)
                SELECT id, contract_no, contract_name, customer_name,
                       total_amount, sign_date, remark, created_at FROM contracts;
            DROP TABLE contracts;
            ALTER TABLE contracts_new RENAME TO contracts;
            ''')
            conn.commit()
            cols = {r[1] for r in conn.execute('PRAGMA table_info(contracts)').fetchall()}
        for name, ddl in _NEW_COLUMNS.items():
            if name not in cols:
                conn.execute(f'ALTER TABLE contracts ADD COLUMN {name} {ddl}')
        conn.commit()
    finally:
        conn.close()


# ============ 合同 CRUD ============
def add_contract(contract_no, contract_name, customer_name, total_amount, sign_date='', remark='',
                 contract_manager='', category='', payee='', bank_name='', bank_account='',
                 start_date='', end_date='', owner_id=None):
    conn = get_conn()
    try:
        cur = conn.execute(
            'INSERT INTO contracts (contract_no, contract_name, customer_name, contract_manager, '
            'category, payee, bank_name, bank_account, total_amount, sign_date, '
            'start_date, end_date, remark, owner_id, created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (contract_no.strip() or None, contract_name, customer_name, contract_manager,
             category, payee, bank_name, bank_account, float(total_amount),
             sign_date, start_date, end_date, remark, owner_id,
             cn_now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def update_contract(cid, contract_no, contract_name, customer_name, total_amount, sign_date='', remark='',
                    contract_manager='', category='', payee='', bank_name='', bank_account='',
                    start_date='', end_date='', owner_id=None):
    conn = get_conn()
    conn.execute(
        'UPDATE contracts SET contract_no=?, contract_name=?, customer_name=?, contract_manager=?, '
        'category=?, payee=?, bank_name=?, bank_account=?, total_amount=?, sign_date=?, '
        'start_date=?, end_date=?, remark=?, owner_id=? WHERE id=?',
        (contract_no.strip() or None, contract_name, customer_name, contract_manager,
         category, payee, bank_name, bank_account, float(total_amount),
         sign_date, start_date, end_date, remark, owner_id, cid))
    conn.commit()
    conn.close()


def delete_contract(cid):
    conn = get_conn()
    conn.execute('DELETE FROM contracts WHERE id=?', (cid,))
    conn.commit()
    conn.close()


def set_contract_file(cid, kind, path):
    """更新合同附件路径。kind 为 'doc_file' 或 'scan_file'。"""
    assert kind in ('doc_file', 'scan_file')
    conn = get_conn()
    conn.execute(f'UPDATE contracts SET {kind}=? WHERE id=?', (path or None, cid))
    conn.commit()
    conn.close()


def list_contracts(owner_id=None):
    """合同列表。传 owner_id 只返回该用户的合同；不传返回全部（管理员视角）。"""
    conn = get_conn()
    if owner_id is not None:
        rows = conn.execute(
            'SELECT * FROM contracts WHERE owner_id=? ORDER BY id DESC', (owner_id,)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM contracts ORDER BY id DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contract(cid):
    conn = get_conn()
    row = conn.execute('SELECT * FROM contracts WHERE id=?', (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ============ 支付记录 ============
def add_payment(contract_id, pay_date, stage, amount, invoice_no='', invoice_date='',
                remark='', invoice_file='', report_file='', user_id=None,
                main_content=''):
    conn = get_conn()
    cur = conn.execute(
        'INSERT INTO payment_records (contract_id, pay_date, invoice_date, stage, amount, '
        'invoice_no, main_content, remark, invoice_file, report_file, user_id, created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (contract_id, pay_date, invoice_date or '', stage, float(amount), invoice_no,
         main_content, remark, invoice_file, report_file, user_id,
         cn_now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_invoice_nos():
    """所有已填报过的发票号（非空）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT invoice_no FROM payment_records WHERE invoice_no IS NOT NULL AND invoice_no != ''"
    ).fetchall()
    conn.close()
    return [r['invoice_no'] for r in rows]


# 报销状态流转顺序与对应时间戳字段
PAYMENT_STATUS_FLOW = ['已提交', '审核中', '已打款']
PAYMENT_STATUS_TS = {'已提交': 'submitted_at', '审核中': 'reviewed_at', '已打款': 'paid_at'}


def set_payment_status(pid, status):
    """推进报销状态并记录对应时间戳。仅允许向后流转到 status（顺序见 PAYMENT_STATUS_FLOW）。"""
    if status not in PAYMENT_STATUS_FLOW:
        raise ValueError(f'非法状态：{status}')
    ts_col = PAYMENT_STATUS_TS[status]
    now = cn_now().strftime('%Y-%m-%d %H:%M')
    conn = get_conn()
    cur = conn.execute('SELECT status FROM payment_records WHERE id=?', (pid,)).fetchone()
    if not cur:
        conn.close()
        return False
    cur_idx = PAYMENT_STATUS_FLOW.index(cur['status']) if cur['status'] in PAYMENT_STATUS_FLOW else 0
    new_idx = PAYMENT_STATUS_FLOW.index(status)
    if new_idx <= cur_idx:  # 不回退（保持已记录的更靠后状态）
        conn.close()
        return True
    conn.execute(
        f'UPDATE payment_records SET status=?, {ts_col}=? WHERE id=?',
        (status, now, pid))
    conn.commit()
    conn.close()
    return True


def delete_payment(pid):
    conn = get_conn()
    conn.execute('DELETE FROM payment_records WHERE id=?', (pid,))
    conn.commit()
    conn.close()


def list_payments(contract_id):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM payment_records WHERE contract_id=? ORDER BY pay_date DESC, id DESC',
        (contract_id,)).fetchall()
    conn.close()
    return _with_files([dict(r) for r in rows])


def list_all_payments(owner_id=None, limit=None):
    """全部报销记录（联表合同名）。传 owner_id 只返回该用户合同的记录；
    limit 限制条数（仪表盘用）。按 id 倒序（最新在前）。每条附带相关文件列表。"""
    sql = ('SELECT p.*, c.contract_name, c.contract_no FROM payment_records p '
           'JOIN contracts c ON c.id = p.contract_id')
    params = []
    if owner_id is not None:
        sql += ' WHERE c.owner_id=?'
        params.append(owner_id)
    sql += ' ORDER BY p.id DESC'
    if limit:
        sql += ' LIMIT ?'
        params.append(int(limit))
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return _with_files([dict(r) for r in rows])


def _with_files(records):
    """给每条记录挂上 'files'（相关附件列表）。"""
    if not records:
        return records
    conn = get_conn()
    pids = [r['id'] for r in records]
    placeholders = ','.join('?' * len(pids))
    frows = conn.execute(
        f'SELECT * FROM payment_files WHERE payment_id IN ({placeholders}) ORDER BY id',
        pids).fetchall()
    conn.close()
    by_pid = {}
    for f in frows:
        by_pid.setdefault(f['payment_id'], []).append(dict(f))
    for r in records:
        r['files'] = by_pid.get(r['id'], [])
    return records


def get_payment(pid):
    conn = get_conn()
    row = conn.execute('SELECT * FROM payment_records WHERE id=?', (pid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_contract_stats(cid):
    """统计：已支付总额、剩余未付金额"""
    conn = get_conn()
    row = conn.execute(
        'SELECT COALESCE(SUM(amount),0) AS paid FROM payment_records WHERE contract_id=?', (cid,)).fetchone()
    total = conn.execute('SELECT total_amount FROM contracts WHERE id=?', (cid,)).fetchone()
    conn.close()
    paid = row['paid'] if row else 0
    total_amount = total['total_amount'] if total else 0
    return {
        'paid': paid,
        'remaining': round(total_amount - paid, 2),
        'total': total_amount,
    }


# ============ 付款计划 ============
def save_payment_plan(contract_id, rows):
    """全量替换付款计划（先删后插，事务）。rows = [{'seq','condition','ratio','amount'}, ...]
    返回写入行数。"""
    conn = get_conn()
    try:
        conn.execute('DELETE FROM payment_plan WHERE contract_id=?', (contract_id,))
        for r in rows:
            conn.execute(
                'INSERT INTO payment_plan (contract_id, seq, condition, ratio, amount) '
                'VALUES (?,?,?,?,?)',
                (contract_id, int(r['seq']), r.get('condition') or '',
                 float(r['ratio']) if r.get('ratio') not in (None, '') else None,
                 round(float(r['amount']), 2)))
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def list_payment_plan(contract_id):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM payment_plan WHERE contract_id=? ORDER BY seq', (contract_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


_CN_DIGITS = '一二三四五六七八九十'


def _match_stage(stage_text, n):
    """从 '第2期'/'二期'/'2'/'一期30%' 等文本提取期数（0基）；识别不出或越界返回 None。
    数字优先（如 '第2期'），数字越界（如 '一期30%' 中的 30 是比例）回退到中文数字。"""
    if not stage_text:
        return None
    s = str(stage_text)
    nums = re.findall(r'\d+', s)
    if len(nums) == 1:
        m = int(nums[0])
        if 1 <= m <= n:
            return m - 1
    for ch in _CN_DIGITS:
        if ch in s:
            m = _CN_DIGITS.index(ch) + 1
            if 1 <= m <= n:
                return m - 1
    return None


def compute_stage_alloc(plan_rows, records):
    """把支付记录分配到各期（纯函数）。plan_rows: list_payment_plan 输出；records: 支付记录列表。
    返回 (paid_list, surplus, invoices_list)：
      paid_list[i]    第 i+1 期累计已支付金额
      surplus         超出计划总额的余量
      invoices_list[i] 该期命中的发票号列表
    乱序处理：记录 stage 能匹配到期 → 优先扣该期，余量先向后顺延再回绕；不匹配 → 从最早未满期起顺序扣。"""
    n = len(plan_rows)
    amt = [round(r['amount'], 2) for r in plan_rows]
    paid = [0.0] * n
    invoices = [[] for _ in range(n)]
    surplus = 0.0
    for rec in sorted(records, key=lambda r: (r['pay_date'], r['id'])):
        rem = round(float(rec['amount']), 2)
        if rem <= 0:
            continue
        target = _match_stage(rec.get('stage'), n)
        if target is not None:
            order = [target] + list(range(target + 1, n)) + list(range(0, target))
        else:
            order = list(range(n))
        first_used = None
        for i in order:
            if rem < 0.005:
                break
            avail = round(amt[i] - paid[i], 2)
            if avail <= 0:
                continue
            take = min(rem, avail)
            paid[i] = round(paid[i] + take, 2)
            rem = round(rem - take, 2)
            if first_used is None:
                first_used = i
        if first_used is not None and rec.get('invoice_no'):
            invoices[first_used].append(rec['invoice_no'])
        surplus = round(surplus + rem, 2)
    return paid, surplus, invoices


def get_plan_status(cid, extra_record=None):
    """合同付款计划状态（UI/xlsx/PDF 共用）。
    extra_record: 预览用的本次填报虚拟记录（同 payment_records 字段，不落库）。
    返回 (stage_list, surplus)；stage_list = [{'seq','condition','ratio','amount',
    'paid','remaining','invoices'}, ...]"""
    plan_rows = list_payment_plan(cid)
    records = list_payments(cid)
    if extra_record:
        records = records + [extra_record]
    paid, surplus, invoices = compute_stage_alloc(plan_rows, records)
    stage_list = []
    for i, p in enumerate(plan_rows):
        stage_list.append({
            'seq': p['seq'],
            'condition': p['condition'] or '',
            'ratio': p['ratio'],
            'amount': p['amount'],
            'paid': round(paid[i], 2),
            'remaining': round(p['amount'] - paid[i], 2),
            'invoices': invoices[i],
        })
    return stage_list, surplus


def backup_db():
    """备份数据库 bill_backup_YYYYMMDD_HHMMSS_mmm.db（微秒时间戳防重名）"""
    ts = cn_now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    backup = os.path.join(os.path.dirname(DB_PATH), f'bill_backup_{ts}.db')
    conn = get_conn()
    conn.execute(f"VACUUM INTO '{backup}'")
    conn.close()
    return backup


# ============ 报销相关文件 ============
def add_payment_file(payment_id, orig_name, path):
    conn = get_conn()
    cur = conn.execute(
        'INSERT INTO payment_files (payment_id, orig_name, path, created_at) VALUES (?,?,?,?)',
        (payment_id, orig_name, path, cn_now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_payment_files(payment_id):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM payment_files WHERE payment_id=? ORDER BY id', (payment_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_payment_file(file_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM payment_files WHERE id=?', (file_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_payment_file(file_id):
    conn = get_conn()
    conn.execute('DELETE FROM payment_files WHERE id=?', (file_id,))
    conn.commit()
    conn.close()


# ============ 用户 CRUD ============
def create_user(username, password_hash, display_name='', is_admin=0, ad_dn='',
                must_change_password=0):
    """新建用户。username 重复返回 None。password_hash 由调用方（web/auth.py）用
    werkzeug 预先哈希，db 层不依赖 werkzeug。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            'INSERT INTO users (username, password_hash, display_name, is_admin, ad_dn, '
            'must_change_password, created_at) VALUES (?,?,?,?,?,?,?)',
            (username.strip(), password_hash, display_name, int(bool(is_admin)), ad_dn,
             int(bool(must_change_password)),
             cn_now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user(user_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username):
    conn = get_conn()
    row = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM users ORDER BY id').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_users():
    """用户总数（用于首次启动时自动种子管理员）"""
    conn = get_conn()
    row = conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()
    conn.close()
    return row['n'] if row else 0


def update_user(user_id, display_name=None, is_admin=None, password_hash=None, ad_dn=None,
                must_change_password=None):
    """部分更新用户；仅传需要修改的字段。"""
    conn = get_conn()
    fields, params = [], []
    if display_name is not None:
        fields.append('display_name=?'); params.append(display_name)
    if is_admin is not None:
        fields.append('is_admin=?'); params.append(int(bool(is_admin)))
    if password_hash is not None:
        fields.append('password_hash=?'); params.append(password_hash)
    if ad_dn is not None:
        fields.append('ad_dn=?'); params.append(ad_dn)
    if must_change_password is not None:
        fields.append('must_change_password=?'); params.append(int(bool(must_change_password)))
    if fields:
        params.append(user_id)
        conn.execute(f'UPDATE users SET {",".join(fields)} WHERE id=?', params)
        conn.commit()
    conn.close()


class UserHasContractsError(Exception):
    """删除用户时其名下仍有合同（需先转移经办人）。"""

    def __init__(self, n):
        self.n = n
        super().__init__(f'该用户名下还有 {n} 个合同')


# ============ 系统设置（键值持久化，页面配置覆盖环境变量默认值）============
def get_settings():
    conn = get_conn()
    rows = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}


def get_setting(key, default=None):
    return get_settings().get(key, default)


def set_settings(items):
    """批量写入配置项（upsert）。items = {key: value}。"""
    conn = get_conn()
    for k, v in items.items():
        conn.execute(
            'INSERT INTO settings (key, value) VALUES (?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, v))
    conn.commit()
    conn.close()


def delete_settings(keys):
    conn = get_conn()
    for k in keys:
        conn.execute('DELETE FROM settings WHERE key=?', (k,))
    conn.commit()
    conn.close()


def delete_user(user_id):
    """删除用户。名下仍有合同时抛 UserHasContractsError（不删除）；
    其填报的报销记录 user_id 置空保留（记录归属合同，与用户解耦）。"""
    conn = get_conn()
    try:
        n = conn.execute(
            'SELECT COUNT(*) AS n FROM contracts WHERE owner_id=?', (user_id,)).fetchone()['n']
        if n:
            raise UserHasContractsError(n)
        conn.execute('UPDATE payment_records SET user_id=NULL WHERE user_id=?', (user_id,))
        conn.execute('DELETE FROM users WHERE id=?', (user_id,))
        conn.commit()
    finally:
        conn.close()


# ============ 审计日志（关键操作留痕，管理员可查）============
AUDIT_KEEP = 5000  # 仅保留最近 N 条，超出自动清理最旧记录


def add_audit_log(action, target='', detail='', username='', user_id=None, ip=''):
    """写入一条审计日志；写入后清理超量旧记录。审计失败不影响业务（由调用方兜底）。"""
    conn = get_conn()
    try:
        conn.execute(
            'INSERT INTO audit_logs (user_id, username, action, target, detail, ip, created_at) '
            'VALUES (?,?,?,?,?,?,?)',
            (user_id, username or '', action, target or '', detail or '', ip or '',
             cn_now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.execute('DELETE FROM audit_logs WHERE id <= '
                     '(SELECT MAX(id) - ? FROM audit_logs)', (AUDIT_KEEP,))
        conn.commit()
    finally:
        conn.close()


def list_audit_logs(page=1, per_page=20, username=None, action=None,
                    start_date=None, end_date=None):
    """分页查询审计日志（可按用户名 / 操作类型 / 时间范围筛选），返回 (rows, total)。"""
    where, params = [], []
    if username:
        where.append('username LIKE ?')
        params.append(f'%{username}%')
    if action:
        where.append('action=?')
        params.append(action)
    if start_date:
        where.append('created_at >= ?')
        params.append(start_date + ' 00:00:00')
    if end_date:
        where.append('created_at <= ?')
        params.append(end_date + ' 23:59:59')
    cond = (' WHERE ' + ' AND '.join(where)) if where else ''
    conn = get_conn()
    total = conn.execute(f'SELECT COUNT(*) AS n FROM audit_logs{cond}', params).fetchone()['n']
    rows = conn.execute(
        f'SELECT * FROM audit_logs{cond} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [per_page, (page - 1) * per_page]).fetchall()
    conn.close()
    return rows, total


def list_audit_actions():
    """所有出现过的操作类型（筛选用）。"""
    conn = get_conn()
    rows = conn.execute('SELECT DISTINCT action FROM audit_logs ORDER BY action').fetchall()
    conn.close()
    return [r['action'] for r in rows]
