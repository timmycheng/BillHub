"""BillHub 合同管理蓝图：列表 / 详情 / 增删改 / 付款计划 / 导入导出。
权限：普通用户只看自己的合同（owner_id），管理员（is_admin）看全部。
导入导出为批量管理操作，限管理员。"""
import os
import tempfile
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, send_file, url_for)
from flask_login import current_user, login_required

import contract_io
import db
from web.auth import admin_required, can_access_contract
from web.routes.payments import render_payment_panel

bp = Blueprint('contracts', __name__)

CONTRACT_CATEGORIES = ['人力外包类', '采购类', '维保类', '软件开发类', '收据类']


# ============ 权限辅助 ============
def _owner_filter():
    """列表过滤：管理员返回 None（全部），普通用户返回自己的 id。"""
    return None if current_user.is_admin else int(current_user.id)


# ============ 表单解析 ============
def _parse_form_data(form):
    """提取合同字段并校验。返回 (data_dict, error_str)。"""
    name = form.get('contract_name', '').strip()
    if not name:
        return None, '合同名称不能为空'
    amount_raw = form.get('total_amount', '0').strip().replace(',', '')
    try:
        amount = float(amount_raw)
    except ValueError:
        return None, '合同总金额格式错误'
    if amount <= 0:
        return None, '合同总金额必须大于 0'
    return {
        'contract_no': form.get('contract_no', '').strip(),
        'contract_name': name,
        'customer_name': form.get('customer_name', '').strip(),
        'contract_manager': form.get('contract_manager', '').strip(),
        'category': form.get('category', '').strip(),
        'payee': form.get('payee', '').strip(),
        'bank_name': form.get('bank_name', '').strip(),
        'bank_account': form.get('bank_account', '').strip(),
        'total_amount': amount,
        'sign_date': form.get('sign_date', '').strip(),
        'remark': form.get('remark', '').strip(),
    }, None


def _parse_plan_rows(form):
    """从表单解析付款计划行。plan_condition/plan_ratio/plan_amount 为同名多值列表。
    跳过全空行；ratio（去 % 后 /100）转 0-1 小数。"""
    conds = form.getlist('plan_condition')
    ratios = form.getlist('plan_ratio')
    amounts = form.getlist('plan_amount')
    n = max(len(conds), len(ratios), len(amounts))
    rows = []
    for i in range(n):
        cond = conds[i].strip() if i < len(conds) else ''
        ratio_txt = ratios[i].strip() if i < len(ratios) else ''
        amount_txt = amounts[i].strip() if i < len(amounts) else ''
        if not cond and not ratio_txt and not amount_txt:
            continue
        ratio = None
        if ratio_txt:
            try:
                ratio = float(ratio_txt.replace('%', '')) / 100
            except ValueError:
                ratio = None
        try:
            amount = float(amount_txt.replace(',', '')) if amount_txt else 0.0
        except ValueError:
            amount = 0.0
        rows.append({'seq': len(rows) + 1, 'condition': cond,
                     'ratio': ratio, 'amount': amount})
    return rows


# ============ 列表面板（HTMX 局部）============
@bp.route('/contracts/list')
@login_required
def list_panel():
    q = request.args.get('q', '').strip()
    selected = request.args.get('selected', type=int)
    contracts = db.list_contracts(owner_id=_owner_filter())
    if q:
        ql = q.lower()
        contracts = [c for c in contracts
                     if q in (c['contract_no'] or '') or ql in (c['contract_name'] or '').lower()]
    return render_template('_contract_list.html', contracts=contracts, q=q, selected=selected)


# ============ 详情面板（HTMX 局部）+ 报销面板（OOB）============
@bp.route('/contracts/<int:cid>/info')
@login_required
def info_panel(cid):
    c = db.get_contract(cid)
    if not c or not can_access_contract(c):
        abort(404)
    stats = db.get_contract_stats(cid)
    stages, surplus = db.get_plan_status(cid)
    plan = db.list_payment_plan(cid)
    info = render_template('_contract_info.html', c=c, stats=stats,
                           stages=stages, surplus=surplus, has_plan=bool(plan))
    # 中栏报销面板随详情一起返回（HTMX OOB 交换），切换合同一次加载两栏
    return info + render_payment_panel(cid, oob=True)


# ============ 新增 ============
@bp.route('/contracts/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        data, err = _parse_form_data(request.form)
        if err:
            flash(err, 'danger')
            return _render_form(None, request.form)
        cid = db.add_contract(owner_id=int(current_user.id), **data)
        if cid is None:
            flash('合同编号已存在', 'danger')
            return _render_form(None, request.form)
        db.save_payment_plan(cid, _parse_plan_rows(request.form))
        flash(f'已新增合同：{data["contract_name"]}', 'success')
        return redirect(url_for('main.dashboard', selected=cid))
    return _render_form(None, None)


# ============ 编辑 ============
@bp.route('/contracts/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def edit(cid):
    c = db.get_contract(cid)
    if not c or not can_access_contract(c):
        abort(404)
    if request.method == 'POST':
        data, err = _parse_form_data(request.form)
        if err:
            flash(err, 'danger')
            return _render_form(c, request.form)
        db.update_contract(cid, owner_id=c['owner_id'], **data)
        db.save_payment_plan(cid, _parse_plan_rows(request.form))
        flash('合同已更新', 'success')
        return redirect(url_for('main.dashboard', selected=cid))
    return _render_form(c, None)


# ============ 删除 ============
@bp.route('/contracts/<int:cid>/delete', methods=['POST'])
@login_required
def delete(cid):
    c = db.get_contract(cid)
    if not c or not can_access_contract(c):
        abort(404)
    name = c['contract_name']
    db.delete_contract(cid)
    flash(f'已删除合同：{name}', 'success')
    return redirect(url_for('main.dashboard'))


# ============ 导出（管理员）============
@bp.route('/contracts/export')
@admin_required
def export():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    tmp.close()
    try:
        n = contract_io.export_contracts(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        flash(f'导出失败：{e}', 'danger')
        return redirect(url_for('main.dashboard'))
    # send_file 会自己管理文件句柄；临时文件由系统清理
    return send_file(tmp.name, as_attachment=True, download_name='合同清单.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ============ 导入（管理员）============
@bp.route('/contracts/import', methods=['POST'])
@admin_required
def import_file():
    f = request.files.get('file')
    if not f or not f.filename:
        flash('请选择要导入的 xlsx 文件', 'warning')
        return redirect(url_for('main.dashboard'))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    f.save(tmp.name)
    tmp.close()
    try:
        result = contract_io.import_contracts(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        flash(f'导入失败：{e}', 'danger')
        return redirect(url_for('main.dashboard'))
    os.unlink(tmp.name)
    msg = (f'新增 {result["added"]} 条，跳过 {result["skipped"]} 条（编号重复），'
           f'失败 {result["failed"]} 条')
    if result['errors']:
        detail = '; '.join(f'第{e["row"]}行：{e["reason"]}' for e in result['errors'][:8])
        msg += '。明细：' + detail
    flash(msg, 'success' if result['added'] else 'warning')
    return redirect(url_for('main.dashboard'))


# ============ 表单渲染辅助 ============
_FORM_FIELDS = ['contract_no', 'contract_name', 'customer_name', 'contract_manager',
                'category', 'payee', 'bank_name', 'bank_account',
                'total_amount', 'sign_date', 'remark']


def _render_form(contract, formdata):
    """渲染新增/编辑表单。contract=已有合同(编辑)/None(新增)；
    formdata=POST 失败回显/None。合并出 values 字典供模板使用。"""
    values = {}
    for k in _FORM_FIELDS:
        if formdata is not None:
            values[k] = formdata.get(k, '')
        elif contract:
            v = contract.get(k)
            values[k] = '' if v is None else v
        else:
            values[k] = ''
    # 新增默认签订日期=今天
    if not contract and formdata is None and not values['sign_date']:
        values['sign_date'] = date.today().isoformat()

    # 付款计划回显：POST 失败用表单解析，否则用库内已有
    if formdata is not None:
        plan_rows = _parse_plan_rows(formdata)
    elif contract:
        plan_rows = db.list_payment_plan(contract['id'])
    else:
        plan_rows = []
    # 留一行空白方便新增时直接填
    if not plan_rows:
        plan_rows = [{'seq': 1, 'condition': '', 'ratio': None, 'amount': 0.0}]

    return render_template('contract_form.html', contract=contract, values=values,
                           categories=CONTRACT_CATEGORIES, plan_rows=plan_rows)
