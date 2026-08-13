"""BillHub 主面板：整页合同列表（报销/预览走弹窗）。"""
from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

import db

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def dashboard():
    from web.routes.contracts import build_rows
    q = request.args.get('q', '').strip()
    preview = request.args.get('preview', type=int)
    owner = None if current_user.is_admin else int(current_user.id)
    rows = build_rows(owner, q)
    return render_template('dashboard.html', rows=rows, q=q, preview=preview)
