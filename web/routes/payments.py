"""BillHub 报销填报蓝图：面板渲染 / 生成审批表 / 删除记录 / 文件下载。
复用 template_engine + utils.build_report_context（与桌面版同逻辑）。"""
import os
import re
from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, url_for)
from flask_login import current_user, login_required

import db
import template_engine
from utils import build_report_context, safe_dirname
from web.auth import can_access_contract

bp = Blueprint('payments', __name__)


# ============ 报销管理页（全部记录）============
@bp.route('/payments')
@login_required
def page():
    owner = None if current_user.is_admin else int(current_user.id)
    records = db.list_all_payments(owner_id=owner)
    return render_template('payments.html', records=records)


# ============ 报销表单（弹窗内容）============
@bp.route('/payments/form/<int:cid>')
@login_required
def form(cid):
    c = db.get_contract(cid)
    if not c or not can_access_contract(c):
        abort(404)
    plan = db.list_payment_plan(cid)
    paid_stages = set()
    if plan:
        n = len(plan)
        for rec in db.list_payments(cid):
            idx = db._match_stage(rec.get('stage'), n)
            if idx is not None:
                paid_stages.add(idx + 1)
    default_seq = next((p['seq'] for p in plan if p['seq'] not in paid_stages), None)
    return render_template('_reimburse_form.html', c=c, plan=plan,
                           paid_stages=paid_stages, default_seq=default_seq,
                           today=datetime.now().strftime('%Y-%m-%d'))


def _get_accessible_contract(cid):
    c = db.get_contract(cid)
    if not c or not can_access_contract(c):
        abort(404)
    return c


# ============ 生成报销单 ============
@bp.route('/payments/create', methods=['POST'])
@login_required
def create():
    cid = request.form.get('contract_id', type=int)
    c = _get_accessible_contract(cid)

    amount_raw = request.form.get('amount', '0').replace(',', '').strip()
    try:
        amount = float(amount_raw)
    except ValueError:
        flash('金额格式错误', 'danger')
        return redirect(url_for('contracts.detail', cid=cid))
    if amount <= 0:
        flash('请输入本次报销金额', 'danger')
        return redirect(url_for('contracts.detail', cid=cid))

    template_path = current_app.config['APPROVAL_TEMPLATE']
    if not os.path.exists(template_path):
        flash(f'找不到审批表模板：{template_path}', 'danger')
        return redirect(url_for('contracts.detail', cid=cid))

    pay_date = request.form.get('pay_date', '').strip()
    invoice_date = request.form.get('invoice_date', '').strip()
    invoice_no = request.form.get('invoice_no', '').strip()
    stage = request.form.get('stage', '').strip()
    main_content = request.form.get('main_content', '').strip()
    remark = request.form.get('remark', '').strip()

    # 发票号重复/相似校验（归一化后与历史记录一致则禁止填报）
    if invoice_no:
        norm = re.sub(r'[^A-Za-z0-9]', '', invoice_no).upper()
        for old in db.list_invoice_nos():
            if re.sub(r'[^A-Za-z0-9]', '', old).upper() == norm:
                flash(f'发票号「{invoice_no}」与历史记录「{old}」相同，不能重复填报！', 'danger')
                return redirect(url_for('contracts.detail', cid=cid))

    ctx, stages, _this_pay = build_report_context(
        c, pay_date, invoice_date, amount, invoice_no, stage, main_content, remark)

    # 统一保存到 uploads/reports/<合同名>/ 下，文件名带日期时间防重名
    contract_dir = os.path.join(current_app.config['REPORT_DIR'],
                                safe_dirname(c['contract_name']))
    os.makedirs(contract_dir, exist_ok=True)
    fname = f"审批表_{pay_date}_{datetime.now().strftime('%H%M%S%f')}.xlsx"
    out_path = os.path.join(contract_dir, fname)
    try:
        template_engine.render_approval_template(template_path, out_path, ctx, stages)
    except Exception as e:
        flash(f'审批表生成失败：{e}', 'danger')
        return redirect(url_for('contracts.detail', cid=cid))

    # 保存本次上传的发票/收据文件
    invoice_file = ''
    f = request.files.get('invoice_file')
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower() or ''
        safe_no = re.sub(r'[^\w\-]', '', c['contract_no'] or '') or f"id{c['id']}"
        inv_fname = f"{safe_no}_{pay_date}_{datetime.now().strftime('%H%M%S')}{ext}"
        inv_dir = current_app.config['INVOICE_DIR']
        os.makedirs(inv_dir, exist_ok=True)
        dest = os.path.join(inv_dir, inv_fname)
        try:
            f.save(dest)
            invoice_file = dest
        except OSError:
            invoice_file = ''

    new_pid = db.add_payment(contract_id=cid, pay_date=pay_date, invoice_date=invoice_date,
                             stage=stage, amount=amount, invoice_no=invoice_no, remark=remark,
                             invoice_file=invoice_file, report_file=out_path,
                             user_id=int(current_user.id))
    flash('✅ 审批表已生成并保存记录！', 'success')
    return redirect(url_for('contracts.detail', cid=cid, preview=new_pid))


# ============ 删除记录 ============
@bp.route('/payments/<int:pid>/delete', methods=['POST'])
@login_required
def delete(pid):
    rec = db.get_payment(pid)
    if not rec:
        abort(404)
    _get_accessible_contract(rec['contract_id'])
    db.delete_payment(pid)
    flash('支付记录已删除（合同已付/剩余金额已重新计算）', 'success')
    return redirect(url_for('contracts.detail', cid=rec['contract_id']))


# ============ 文件下载 ============
def _send_payment_file(pid, key, download_name):
    rec = db.get_payment(pid)
    if not rec:
        abort(404)
    _get_accessible_contract(rec['contract_id'])
    path = rec.get(key) or ''
    if not path or not os.path.exists(path):
        flash('该记录没有可用的文件（可能已移动或删除）', 'warning')
        return redirect(url_for('contracts.detail', cid=rec['contract_id']))
    return send_file(path, as_attachment=True, download_name=download_name)


@bp.route('/files/report/<int:pid>')
@login_required
def download_report(pid):
    return _send_payment_file(pid, 'report_file', f'审批表_{pid}.xlsx')


@bp.route('/files/invoice/<int:pid>')
@login_required
def download_invoice(pid):
    rec = db.get_payment(pid)
    if not rec:
        abort(404)
    fname = os.path.basename(rec.get('invoice_file') or f'票据_{pid}')
    return _send_payment_file(pid, 'invoice_file', fname)
