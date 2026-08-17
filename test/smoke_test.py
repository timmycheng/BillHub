#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BillHub 冒烟测试（2.0 全覆盖 + 2.1 新功能）。

用临时 BILLHUB_DB / BILLHUB_UPLOAD_DIR 跑 Flask test_client，不触碰真实 bill.db。
覆盖：登录 / 仪表盘 / 用户管理（弹窗 + 密码强度）/ 合同 / 附件 / 报销 /
状态流转 / 分页 / OCR / 迁移兼容。

运行：python test/smoke_test.py（在项目根目录或任意目录均可）
"""
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import tomllib
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(BASE, 'pyproject.toml'), 'rb') as _fh:
    APP_VER = tomllib.load(_fh)['project']['version']
TMP = tempfile.mkdtemp(prefix='billhub_smoke_')
os.environ['BILLHUB_DB'] = os.path.join(TMP, 'test.db')
os.environ['BILLHUB_UPLOAD_DIR'] = os.path.join(TMP, 'uploads')
sys.path.insert(0, BASE)

fails = []


def check(name, ok, extra=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' | ' + extra if extra and not ok else ''))
    if not ok:
        fails.append(name)


# ============ 应用与登录 ============
from web.app import create_app  # noqa: E402

app = create_app()
c = app.test_client()


def login(u='admin', p='admin'):
    c.get('/logout')
    return c.post('/login', data={'username': u, 'password': p}, follow_redirects=True)


def html_of(resp):
    return resp.get_data(as_text=True)


r = c.get('/login')
check('GET /login 200', r.status_code == 200, str(r.status_code))
check('login page brand', 'BillHub' in html_of(r))
r = c.get('/')
check('GET / redirects to login (unauth)', r.status_code == 302)

r = login()
check('login admin/admin', r.status_code == 200 and '仪表盘' in html_of(r))

# ============ 仪表盘（2.1：改名 / 去左下角用户块）============
html = html_of(c.get('/'))
check('导航显示「仪表盘」', '仪表盘' in html and 'Dashboard' not in html)
check('导航左下角无 mini-user', 'mini-user' not in html)
check('仪表盘统计卡', '合同数量' in html and '待办事项' in html)

# ============ 更新说明（导航 / 版本号 / CHANGELOG 页面）============
check('导航显示「更新说明」', '更新说明' in html and '/changelog' in html)
check('左下角版本号与实际版本一致', f'BillHub v{APP_VER}' in html and '内部版' in html)
r = c.get('/changelog')
html = html_of(r)
check('GET /changelog', r.status_code == 200 and '更新说明' in html)
check('changelog 页面内容与 CHANGELOG 一致',
      f'[{APP_VER}]' in html and 'Unreleased' in html and '变更' in html)
check('changelog 不展示开发者说明（Keep a Changelog 等）',
      'Keep a Changelog' not in html and '语义化版本' not in html and '日常改动请顺手' not in html)
check('changelog 展示面向用户的导语', '各版本变更记录，最新改动显示在最上方' in html)

# ============ 用户管理（2.1：弹窗化 + 密码强度）============
html = html_of(c.get('/admin/users'))
check('GET /admin/users', r.status_code == 200 and '用户管理' in html)
check('用户页无「备份数据库」按钮', 'btn ghost">💾 备份数据库' not in html)
check('用户页新建用户为弹窗', 'openUserModal' in html and 'modal-user' in html)
check('编辑按钮数据属性', 'edit-user' in html and 'data-uid=' in html)

r = c.post('/admin/users', data={'username': 'u1', 'password': 'short',
                                 'display_name': '', 'is_admin': ''},
           follow_redirects=True)
check('创建用户：过短密码拒绝', '密码至少 8 位' in html_of(r))
r = c.post('/admin/users', data={'username': 'u1', 'password': 'NoSpecial123',
                                 'display_name': '', 'is_admin': ''},
           follow_redirects=True)
check('创建用户：无特殊字符拒绝', '特殊字符' in html_of(r))
r = c.post('/admin/users', data={'username': 'u1', 'password': 'alllowercase!1',
                                 'display_name': '', 'is_admin': ''},
           follow_redirects=True)
check('创建用户：无大写拒绝', '大写' in html_of(r))
r = c.post('/admin/users', data={'username': 'u1', 'password': 'Abc12345!',
                                 'display_name': '用户一', 'is_admin': ''},
           follow_redirects=True)
check('强密码创建成功', '已创建用户：u1' in html_of(r))

import db  # noqa: E402
uid = db.get_user_by_username('u1')['id']

r = c.post(f'/admin/users/{uid}/edit',
           data={'display_name': '用户一改', 'is_admin': '', 'password': 'Xyz9876@'},
           follow_redirects=True)
check('编辑用户成功', '已更新用户' in html_of(r))
check('显示名已更新', db.get_user(uid)['display_name'] == '用户一改')
r = c.post(f'/admin/users/{uid}/edit',
           data={'display_name': '用户一改', 'is_admin': '', 'password': 'weak'},
           follow_redirects=True)
check('编辑用户：弱密码拒绝', '密码至少 8 位' in html_of(r))

r = login('u1', 'Xyz9876@')
check('新用户新密码登录', '仪表盘' in html_of(r))
r = c.post('/account/password',
           data={'old_password': 'Xyz9876@', 'new_password': 'weak',
                 'confirm_password': 'weak'}, follow_redirects=True)
check('改密：弱密码拒绝', '密码至少 8 位' in html_of(r))
r = c.post('/account/password',
           data={'old_password': 'Xyz9876@', 'new_password': 'Qwe12345#',
                 'confirm_password': 'Qwe12345#'}, follow_redirects=True)
check('改密：强密码成功', '密码已修改' in html_of(r))
check('GET /account/password', c.get('/account/password').status_code == 200)

login()

# ============ 合同 ============
r = c.get('/contracts')
check('GET /contracts', r.status_code == 200 and '合同管理' in html_of(r))
r = c.get('/contracts/new')
check('GET /contracts/new', r.status_code == 200 and '新建合同' in html_of(r))

r = c.post('/contracts/new', data={
    'contract_no': 'HT-2026-001', 'contract_name': '信息系统安全服务合同',
    'customer_name': 'XX科技有限公司', 'category': '采购类', 'payee': 'XX科技有限公司',
    'bank_name': 'XX银行', 'bank_account': '6222000011112222',
    'total_amount': '860000', 'sign_date': '2026-01-01',
    'start_date': '2026-01-01', 'end_date': '2026-12-31', 'remark': '测试',
    'plan_ratio': ['30', '70'], 'plan_amount': ['258000', '602000'],
}, follow_redirects=True)
txt = html_of(r)
check('POST /contracts/new -> detail', r.status_code == 200 and '信息系统安全服务合同' in txt)
check('detail shows plan', '付款计划' in txt and '第1期' in txt)
plan_seg = txt[txt.index('付款计划'):txt.index('报销记录')]
check('付款计划期次状态默认「待付款」（无对应报销记录）',
      '待付款' in plan_seg and '已提交' not in plan_seg and '部分支付' not in plan_seg)
check('detail shows start/end date', '2026-01-01' in txt and '2026-12-31' in txt)

r = c.get('/contracts/1')
check('GET /contracts/1', r.status_code == 200)
r = c.get('/contracts/1/edit')
check('GET /contracts/1/edit', r.status_code == 200 and '编辑合同' in html_of(r))
r = c.get('/contracts?q=信息系统')
check('contract search', r.status_code == 200 and '信息系统安全服务合同' in html_of(r))
row_btns = html_of(r).count('class="row-btn"')
check('合同列表操作栏样式统一（报销/详情/编辑均为 row-btn）',
      row_btns == 3 and 'btn primary small" onclick="openReimburse' not in html_of(r)
      and 'class="row-btn" onclick="openReimburse' in html_of(r))
r = c.get('/contracts?q=不存在的合同xyz')
check('contract search empty', '无匹配合同' in html_of(r))

# ============ 合同附件（电子稿 / 扫描件）============
r = c.post('/contracts/1/files', data={'kind': 'doc'}, follow_redirects=True)
check('upload no file rejected', '请选择要上传的电子稿文件' in html_of(r))
r = c.post('/contracts/1/files', data={'kind': 'doc', 'file': (io.BytesIO(b'not a docx'), 'x.txt')},
           follow_redirects=True)
check('upload wrong ext rejected', '电子稿仅支持' in html_of(r))
r = c.post('/contracts/1/files',
           data={'kind': 'doc', 'file': (io.BytesIO(b'fake docx bytes'), '合同电子稿.docx')},
           content_type='multipart/form-data', follow_redirects=True)
check('upload docx', '电子稿已上传' in html_of(r))
r = c.get('/files/contract/1/doc')
check('download docx', r.status_code == 200)
r = c.get('/files/contract/1/scan')
check('download missing scan redirects', r.status_code == 302)
r = c.post('/contracts/1/files',
           data={'kind': 'scan', 'file': (io.BytesIO(b'%PDF-1.4 fake'), '扫描件.pdf')},
           content_type='multipart/form-data', follow_redirects=True)
check('upload pdf scan', '扫描件已上传' in html_of(r))
r = c.post('/contracts/1/files/doc/delete', follow_redirects=True)
check('delete docx', '已删除电子稿' in html_of(r))

# ============ 报销 ============
r = c.get('/payments/form/1')
check('GET /payments/form/1', r.status_code == 200 and '填报报销' in html_of(r))
check('报销表单提示留空自动生成介绍', '留空则自动生成介绍' in html_of(r))

TEMPLATE = os.environ.get('BILLHUB_TEMPLATE') or os.path.join(BASE, 'templates', '审批表模板2026.xlsx')
if os.path.exists(TEMPLATE):
    r = c.post('/payments/create', data={
        'contract_id': '1', 'invoice_date': '2026-08-10',
        'invoice_no': '03123456', 'stage': '第1期', 'amount': '258000',
        'main_content': '', 'remark': '首期款',
        'files': [(io.BytesIO(b'attachment one'), '补充说明.pdf'),
                  (io.BytesIO(b'attachment two'), '验收单.docx')],
    }, content_type='multipart/form-data', follow_redirects=True)
    txt = html_of(r)
    check('POST /payments/create', '审批表已生成' in txt, txt[:300])

    r = c.get('/preview/1')
    check('GET /preview/1', r.status_code == 200 and '合同支付审批表' in html_of(r))
    p1 = html_of(r)
    check('留空主要内容自动生成介绍（已存记录预览）',
          '信息系统安全服务合同第1期付款' in p1 and '金额 ¥258,000.00' in p1
          and '发票号 03123456' in p1)
    r = c.post('/preview/draft', data={
        'contract_id': '1', 'pay_date': '2026-08-13', 'invoice_date': '',
        'invoice_no': '', 'stage': '第2期', 'amount': '100000',
        'main_content': '', 'remark': '',
    })
    check('POST /preview/draft', r.status_code == 200 and '合同支付审批表' in html_of(r))
    pd = html_of(r)
    check('留空主要内容自动生成介绍（草稿预览，无发票号）',
          '信息系统安全服务合同第2期付款' in pd and '金额 ¥100,000.00' in pd)
    r = c.post('/preview/draft', data={
        'contract_id': '1', 'pay_date': '2026-08-13', 'invoice_date': '',
        'invoice_no': '', 'stage': '第2期', 'amount': '100000',
        'main_content': '人工填写的内容优先', 'remark': '',
    })
    pm = html_of(r)
    check('手动填写主要内容优先，不被自动文案覆盖',
          '人工填写的内容优先' in pm and '自动生成' not in pm and '第2期付款' not in pm)

    r = c.get('/payments')
    txt = html_of(r)
    check('GET /payments page', r.status_code == 200 and 'BX-00001' in txt)
    check('payments page lists attachments', '补充说明.pdf' in txt and '验收单.docx' in txt)
    check('payments page shows timeline', 'timeline-h' in txt)
    check('payments 时间轴默认折叠（tl-row hidden）', 'tl-row" hidden' in txt)
    check('timeline hidden to field', 'name="to" value="审核中"' in txt)

    # 状态流转：已提交 -> 审核中 -> 已打款
    r = c.post('/payments/1/status', data={'to': '审核中'}, follow_redirects=True)
    txt = html_of(r)
    check('advance to 审核中', '审核中' in txt and '标记为「已打款」' in txt)
    seg = html_of(c.get('/contracts/1'))
    seg = seg[seg.index('付款计划'):seg.index('报销记录')]
    check('付款计划期次状态与报销状态一致（审核中）',
          '审核中' in seg and '待付款' in seg and '¥258,000.00' in seg)
    r = c.post('/payments/1/status', data={'to': '已打款'}, follow_redirects=True)
    txt = html_of(r)
    check('advance to 已打款', '已完成' in txt)
    check('no rollback', '标记为' not in txt)
    seg = html_of(c.get('/contracts/1'))
    seg = seg[seg.index('付款计划'):seg.index('报销记录')]
    check('付款计划期次状态与报销状态一致（已打款）', '已打款' in seg and '待付款' in seg)

    r = c.get('/contracts/1')
    check('detail page lists attachments', '补充说明.pdf' in html_of(r))
    check('合同详情报销时间轴默认折叠（tl-row hidden）', 'tl-row" hidden' in html_of(r))
    r = c.get('/files/attachment/1')
    check('download attachment', r.status_code == 200)
    r = c.post('/files/attachment/1/delete', follow_redirects=True)
    check('delete attachment', '已删除附件' in html_of(r))
    r = c.get('/files/report/1')
    check('GET /files/report/1', r.status_code == 200)
else:
    print('SKIP 报销相关（缺少审批表模板 %s）' % TEMPLATE)

# ============ 仪表盘图表（2.1：数字在条上方）============
html = html_of(c.get('/'))
check('仪表盘付款趋势图表', 'bar-value' in html and '付款趋势' in html)
css = html_of(c.get('/static/style.css'))
check('CSS：时间线居中', 'justify-content: center' in css)
check('CSS：图表数字常显', 'flex-shrink: 0' in css)
check('CSS：表单面板居中', 'margin: 0 auto' in css)
js = html_of(c.get('/static/app.js'))
check('JS：点击报销行展开/收起时间轴',
      'tl.hidden = !tl.hidden' in js
      and "closest('a, button, input, select, textarea, label')" in js)

# ============ 分页 ============
for i in range(2, 22):  # 再建 20 条，连同已有的共 21 条
    c.post('/contracts/new', data={'contract_name': f'分页合同{i}', 'total_amount': '1000'})
html = html_of(c.get('/contracts'))
check('contracts page1 paginated', html.count('分页合同') >= 15 and '共 21 条' in html and '第 1/' in html)
html2 = html_of(c.get('/contracts?page=2'))
check('contracts page2', '分页合同' in html2 and '共 21 条' in html2 and '第 2/' in html2)
r = c.get('/contracts?q=分页合同5')
check('search works with pagination', '分页合同5' in html_of(r))

# ============ 合同文本 OCR ============
# 1) 单元级：生成确定性 docx 直接测 ContractOCR 解析（不依赖 OCR 模型）
def make_docx():
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>'
           '<w:p><w:r><w:t>乙方名称：某某科技有限公司</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>合同金额：¥48000</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>收款单位：某某科技有限公司</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>开户银行：中国银行某某支行</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>银行账号：6222 0000 1111 2222</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>合同期限自2026年1月1日至2026年12月31日</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>第1期：支付30% ¥14400</w:t></w:r></w:p>'
           '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('word/document.xml', xml)
    buf.seek(0)
    return buf


def _check_contract_ocr_fields(j):
    return (j.get('total_amount') == '48000'
            and j.get('customer_name') == '某某科技有限公司'
            and j.get('start_date') == '2026-01-01'
            and j.get('end_date') == '2026-12-31'
            and j.get('bank_account') == '6222000011112222'
            and j.get('plan') and j['plan'][0]['seq'] == 1
            and abs(j['plan'][0]['ratio'] - 0.3) < 1e-6)


from ocr import ContractOCR  # noqa: E402
_buf = make_docx()
_tmp_docx = os.path.join(TMP, 'ocr_sample.docx')
with open(_tmp_docx, 'wb') as _fh:
    _fh.write(_buf.read())
_j = ContractOCR().extract(_tmp_docx)
check('合同 OCR 单元（生成 docx）', _check_contract_ocr_fields(_j), repr(_j)[:300])

# 2) HTTP 端点（需 rapidocr 模型；模型不可用时 SKIP 而非 FAIL）
r = c.post('/api/ocr/contract', data={'file': (make_docx(), '合同.docx')},
           content_type='multipart/form-data')
j = r.get_json() or {}
if r.status_code == 200:
    check('合同 OCR HTTP（生成 docx）', j.get('ok') and _check_contract_ocr_fields(j), repr(j)[:300])
elif r.status_code == 500 and ('No module' in str(j.get('error', '')) or '模型' in str(j.get('error', ''))):
    print('SKIP 合同 OCR HTTP——OCR 模型不可用（%s）' % str(j.get('error', ''))[:80])
else:
    check('合同 OCR HTTP（生成 docx）', False, 'status=%s %s' % (r.status_code, repr(j)[:200]))

r = c.post('/api/ocr/contract', data={'file': (io.BytesIO(b'\xd0\xcf\x11\xe0 fake'), '旧合同.doc')},
           content_type='multipart/form-data')
check('合同 OCR：.doc 拒绝', r.status_code == 400 and 'doc' in html_of(r))

# 3) 真实示例合同（templates 下样例文件被 .gitignore，存在则跑）
import glob  # noqa: E402
pdfs = glob.glob(os.path.join(BASE, 'templates', '*.pdf'))
if pdfs:
    with open(pdfs[0], 'rb') as fh:
        pdf_bytes = fh.read()
    r = c.post('/api/ocr/contract', data={'file': (io.BytesIO(pdf_bytes), 'contract.pdf')},
               content_type='multipart/form-data')
    j = r.get_json() or {}
    ok = r.status_code == 200 and j.get('ok') and j.get('total_amount')
    check('合同 OCR（示例 PDF）', ok, repr(j)[:200])
else:
    print('SKIP 合同 OCR（示例 PDF）——templates 下无样例合同')

# ============ 迁移兼容 ============
old_db = os.path.join(TMP, 'old.db')
conn = sqlite3.connect(old_db)
conn.executescript('''
CREATE TABLE contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_no TEXT NOT NULL UNIQUE,
    contract_name TEXT NOT NULL,
    customer_name TEXT,
    total_amount REAL NOT NULL,
    sign_date TEXT,
    remark TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE payment_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER NOT NULL,
    pay_date TEXT NOT NULL,
    invoice_date TEXT,
    stage TEXT,
    amount REAL NOT NULL,
    invoice_no TEXT,
    remark TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
INSERT INTO contracts (contract_no, contract_name, customer_name, total_amount)
VALUES ('OLD-001', '旧合同', '旧客户', 12345);
INSERT INTO payment_records (contract_id, pay_date, amount) VALUES (1, '2026-01-01', 5000);
''')
conn.commit()
conn.close()
_old_path = db.DB_PATH
db.DB_PATH = old_db
try:
    db.init_db()
    conn = sqlite3.connect(old_db)
    cols = {r2[1] for r2 in conn.execute('PRAGMA table_info(contracts)')}
    n = conn.execute('SELECT COUNT(*) FROM contracts').fetchone()[0]
    name = conn.execute('SELECT contract_name FROM contracts WHERE id=1').fetchone()[0]
    pay = conn.execute('SELECT status, submitted_at FROM payment_records WHERE id=1').fetchone()
    ucols = {r2[1] for r2 in conn.execute('PRAGMA table_info(users)')}
    pcols = {r2[1] for r2 in conn.execute('PRAGMA table_info(payment_records)')}
    conn.close()
    ok = ({'contract_manager', 'category', 'start_date', 'end_date', 'doc_file',
           'scan_file', 'owner_id'} <= cols
          and n == 1 and name == '旧合同'
          and pay[0] == '已提交' and pay[1] is not None
          and {'ad_dn', 'password_hash'} <= ucols
          and 'main_content' in pcols)
    check('迁移兼容（最旧结构重建 + 回填）', ok)
finally:
    db.DB_PATH = _old_path

# ============ 其他 ============
r = c.get('/contracts/999')
check('GET missing contract 404', r.status_code == 404)

# Dockerfile CMD 回归检查：waitress-serve 不支持 create_app() 写法
with open(os.path.join(BASE, 'Dockerfile.web'), encoding='utf-8') as fh:
    df = fh.read()
check('Dockerfile CMD 使用 --call 工厂形式', '--call", "web.app:create_app' in df
      and 'create_app()' not in df)

shutil.rmtree(TMP, ignore_errors=True)
print()
if fails:
    print('FAILED:', fails)
    sys.exit(1)
print('ALL PASS')
