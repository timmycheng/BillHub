"""BillHub 主面板：工作台（汇总统计 + 付款趋势 + 待办 + 最近报销记录）与更新说明页。"""
import os
import re
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, render_template, url_for
from flask_login import current_user, login_required
from markupsafe import escape

import db
from utils import contract_statuses
from web.config import PROJECT_ROOT

main_bp = Blueprint('main', __name__)


def _owner_filter():
    return None if current_user.is_admin else int(current_user.id)


@main_bp.route('/')
@login_required
def dashboard():
    owner = _owner_filter()
    contracts = db.list_contracts(owner_id=owner)
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=30)).isoformat()

    total_amount = paid = 0.0
    expiring = pending_effective = 0
    for c in contracts:
        s = db.get_contract_stats(c['id'])
        total_amount += s['total']
        paid += s['paid']
        st = contract_statuses(c)
        if st['effective_key'] == 'pending':
            pending_effective += 1
        # 即将到期：生效中且 30 天内到期
        if st['effective_key'] == 'active' and c.get('end_date') and c['end_date'] <= soon:
            expiring += 1
    stats = {
        'count': len(contracts),
        'total': total_amount,
        'paid': paid,
        'remaining': total_amount - paid,
    }

    # 近 6 个月付款趋势（按报销记录 pay_date 的年月汇总）
    all_payments = db.list_all_payments(owner_id=owner)
    now = date.today()
    months = []
    for i in range(5, -1, -1):
        mm, yy = now.month - i, now.year
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append({'key': f'{yy:04d}-{mm:02d}', 'label': f'{mm}月', 'total': 0.0})
    midx = {m['key']: i for i, m in enumerate(months)}
    reviewing = 0
    for p in all_payments:
        if p.get('status') == '审核中':
            reviewing += 1
        ym = (p.get('pay_date') or '')[:7]
        if ym in midx:
            months[midx[ym]]['total'] += float(p['amount'])
    max_total = max((m['total'] for m in months), default=0)
    for m in months:
        m['pct'] = int(round(m['total'] / max_total * 100)) if max_total else 0

    recent = all_payments[:8]

    return render_template('dashboard.html', stats=stats, recent=recent,
                           months=months, max_total=max_total,
                           expiring=expiring, pending_effective=pending_effective,
                           reviewing=reviewing)


# ============ 更新说明（CHANGELOG 同步展示）============
def _changelog_inline(text):
    text = escape(text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    return text


def changelog_to_html(md):
    """把 CHANGELOG.md 转成 HTML（仅需 #/##/###/列表/加粗/链接，零第三方依赖）。"""
    html, in_list = [], False
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith('### '):
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<h3>{_changelog_inline(s[4:])}</h3>')
        elif s.startswith('## '):
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<h2>{_changelog_inline(s[3:])}</h2>')
        elif s.startswith('# '):
            continue  # 文档主标题由页面自带
        elif s.startswith('- '):
            if not in_list:
                html.append('<ul>')
                in_list = True
            html.append(f'<li>{_changelog_inline(s[2:])}</li>')
        else:
            if in_list:
                html.append('</ul>')
                in_list = False
            html.append(f'<p>{_changelog_inline(s)}</p>')
    if in_list:
        html.append('</ul>')
    return '\n'.join(html)


@main_bp.route('/changelog')
@login_required
def changelog():
    path = os.path.join(PROJECT_ROOT, 'CHANGELOG.md')
    if not os.path.exists(path):
        return render_template('changelog.html', content_html='')
    with open(path, encoding='utf-8') as fh:
        return render_template('changelog.html', content_html=changelog_to_html(fh.read()))
