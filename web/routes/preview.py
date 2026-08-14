"""BillHub 审批表 HTML 预览蓝图：已存记录 / 当前表单草稿。
与 xlsx 模板（合同支付审批表）同款排版，供右栏展示与浏览器打印。"""
from flask import Blueprint, abort, render_template, request
from flask_login import login_required
from datetime import datetime

import db
from utils import build_record_preview, build_report_context
from web.auth import can_access_contract

bp = Blueprint('preview', __name__)


@bp.route('/preview/<int:pid>')
@login_required
def saved(pid):
    """已保存支付记录的审批表预览（历史记录「预览」/ 生成后自动显示）。"""
    rec = db.get_payment(pid)
    if not rec:
        abort(404)
    c = db.get_contract(rec['contract_id'])
    if not c or not can_access_contract(c):
        abort(404)
    ctx, stages, this_pay = build_record_preview(c, rec)
    return render_template('_approval_preview.html', ctx=ctx, stages=stages,
                           this_pay=this_pay, pid=pid,
                           report_exists=bool(rec.get('report_file')))


@bp.route('/preview/draft', methods=['POST'])
@login_required
def draft():
    """当前表单草稿预览（表单「预览本次」按钮，hx-include 提交表单值）。"""
    cid = request.form.get('contract_id', type=int)
    c = db.get_contract(cid)
    if not c or not can_access_contract(c):
        abort(404)
    try:
        amount = float(request.form.get('amount', '0').replace(',', '').strip() or 0)
    except ValueError:
        amount = 0.0
    if amount <= 0:
        return render_template('_approval_preview.html', error='请输入本次报销金额后再预览',
                               ctx=None, stages=[], this_pay=[], pid=None, report_exists=False)
    ctx, stages, this_pay = build_report_context(
        c,
        datetime.now().strftime('%Y-%m-%d'),
        request.form.get('invoice_date', '').strip(),
        amount,
        request.form.get('invoice_no', '').strip(),
        request.form.get('stage', '').strip(),
        request.form.get('main_content', '').strip(),
        request.form.get('remark', '').strip(),
    )
    return render_template('_approval_preview.html', ctx=ctx, stages=stages,
                           this_pay=this_pay, pid=None, report_exists=False)
