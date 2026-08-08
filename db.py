#!/usr/bin/env python3
"""SmartBill - SQLite 数据层
表结构：
  contracts       合同信息表
  payment_records 支付进度表
"""
import sqlite3
import os
import re
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bill.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')  # 启用外键级联删除
    return conn


def init_db():
    conn = get_conn()
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
        remark TEXT,                           -- 备注
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS payment_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_id INTEGER NOT NULL,
        pay_date TEXT NOT NULL,                -- 支付日期
        stage TEXT,                            -- 阶段/期数
        amount REAL NOT NULL,                  -- 本次支付金额
        invoice_no TEXT,                       -- 发票号
        remark TEXT,                           -- 备注
        invoice_file TEXT,                     -- 本次上传的发票/收据文件路径
        report_file TEXT,                      -- 本次生成的审批表 Excel 路径
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
    ''')
    conn.commit()
    conn.close()
    _migrate_contracts()
    _migrate_payments()


_NEW_COLUMNS = {  # 增量迁移：列名 -> 定义
    'contract_manager': 'TEXT',
    'category': 'TEXT',
    'payee': 'TEXT',
    'bank_name': 'TEXT',
    'bank_account': 'TEXT',
}


def _migrate_payments():
    """payment_records 增量迁移：补 invoice_file / report_file 列"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(payment_records)').fetchall()}
        for name in ('invoice_file', 'report_file'):
            if name not in cols:
                conn.execute(f'ALTER TABLE payment_records ADD COLUMN {name} TEXT')
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
                                       contract_manager, total_amount, sign_date, remark, created_at)
                SELECT id, contract_no, contract_name, customer_name,
                       contract_manager, total_amount, sign_date, remark, created_at FROM contracts;
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
                 contract_manager='', category='', payee='', bank_name='', bank_account=''):
    conn = get_conn()
    try:
        cur = conn.execute(
            'INSERT INTO contracts (contract_no, contract_name, customer_name, contract_manager, '
            'category, payee, bank_name, bank_account, total_amount, sign_date, remark) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (contract_no.strip() or None, contract_name, customer_name, contract_manager,
             category, payee, bank_name, bank_account, float(total_amount),
             sign_date, remark))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def update_contract(cid, contract_no, contract_name, customer_name, total_amount, sign_date='', remark='',
                    contract_manager='', category='', payee='', bank_name='', bank_account=''):
    conn = get_conn()
    conn.execute(
        'UPDATE contracts SET contract_no=?, contract_name=?, customer_name=?, contract_manager=?, '
        'category=?, payee=?, bank_name=?, bank_account=?, total_amount=?, sign_date=?, remark=? '
        'WHERE id=?',
        (contract_no.strip() or None, contract_name, customer_name, contract_manager,
         category, payee, bank_name, bank_account, float(total_amount),
         sign_date, remark, cid))
    conn.commit()
    conn.close()


def delete_contract(cid):
    conn = get_conn()
    conn.execute('DELETE FROM contracts WHERE id=?', (cid,))
    conn.commit()
    conn.close()


def list_contracts():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM contracts ORDER BY id DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contract(cid):
    conn = get_conn()
    row = conn.execute('SELECT * FROM contracts WHERE id=?', (cid,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ============ 支付记录 ============
def add_payment(contract_id, pay_date, stage, amount, invoice_no='', remark='', invoice_file='',
                report_file=''):
    conn = get_conn()
    cur = conn.execute(
        'INSERT INTO payment_records (contract_id, pay_date, stage, amount, invoice_no, remark, '
        'invoice_file, report_file) VALUES (?,?,?,?,?,?,?,?)',
        (contract_id, pay_date, stage, float(amount), invoice_no, remark, invoice_file, report_file))
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
    return [dict(r) for r in rows]


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
    """备份数据库 bill_backup_YYYYMMDD.db"""
    ts = datetime.now().strftime('%Y%m%d')
    backup = os.path.join(os.path.dirname(DB_PATH), f'bill_backup_{ts}.db')
    conn = get_conn()
    conn.execute(f"VACUUM INTO '{backup}'")
    conn.close()
    return backup
