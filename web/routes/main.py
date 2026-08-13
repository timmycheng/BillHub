"""BillHub 主面板：工作台（汇总统计 + 最近报销记录）。"""
from flask import Blueprint, render_template
from flask_login import current_user, login_required

import db

main_bp = Blueprint('main', __name__)


def _owner_filter():
    return None if current_user.is_admin else int(current_user.id)


@main_bp.route('/')
@login_required
def dashboard():
    owner = _owner_filter()
    contracts = db.list_contracts(owner_id=owner)
    total_amount = paid = 0.0
    for c in contracts:
        s = db.get_contract_stats(c['id'])
        total_amount += s['total']
        paid += s['paid']
    stats = {
        'count': len(contracts),
        'total': total_amount,
        'paid': paid,
        'remaining': total_amount - paid,
    }
    recent = db.list_all_payments(owner_id=owner, limit=8)
    return render_template('dashboard.html', stats=stats, recent=recent)
