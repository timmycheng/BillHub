"""BillHub 管理员蓝图：用户管理（增删改/重置密码/批量导入）+ 数据库备份。仅管理员可访问。"""
import io
import os
import tempfile

import openpyxl
from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user

import db
from web.auth import admin_required, hash_password, password_error

bp = Blueprint('admin', __name__)


@bp.route('/admin/users')
@admin_required
def users():
    return render_template('admin/users.html', users=db.list_users())


@bp.route('/admin/users', methods=['POST'])
@admin_required
def users_create():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    display_name = request.form.get('display_name', '').strip()
    is_admin = request.form.get('is_admin') == 'on'
    if not username:
        flash('用户名不能为空', 'danger')
        return redirect(url_for('admin.users'))
    err = password_error(password)
    if err:
        flash(err, 'danger')
        return redirect(url_for('admin.users'))
    if db.create_user(username, hash_password(password),
                      display_name=display_name, is_admin=is_admin) is None:
        flash(f'用户名「{username}」已存在', 'danger')
    else:
        flash(f'已创建用户：{username}', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/admin/users/<int:uid>/edit', methods=['POST'])
@admin_required
def users_edit(uid):
    user = db.get_user(uid)
    if not user:
        flash('用户不存在', 'warning')
        return redirect(url_for('admin.users'))
    display_name = request.form.get('display_name', '').strip()
    is_admin = request.form.get('is_admin') == 'on'
    password = request.form.get('password', '')
    # 防止把最后一位管理员降级成普通用户
    if user['is_admin'] and not is_admin and _admin_count() <= 1:
        flash('不能降级最后一位管理员', 'warning')
        return redirect(url_for('admin.users'))
    if password:
        err = password_error(password)
        if err:
            flash(err, 'danger')
            return redirect(url_for('admin.users'))
        db.update_user(uid, display_name=display_name, is_admin=is_admin,
                       password_hash=hash_password(password))
        flash(f'已更新用户「{user["username"]}」并重置密码', 'success')
    else:
        db.update_user(uid, display_name=display_name, is_admin=is_admin)
        flash(f'已更新用户：{user["username"]}', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/admin/users/<int:uid>/delete', methods=['POST'])
@admin_required
def users_delete(uid):
    user = db.get_user(uid)
    if not user:
        flash('用户不存在', 'warning')
        return redirect(url_for('admin.users'))
    if uid == int(current_user.id):
        flash('不能删除自己', 'warning')
        return redirect(url_for('admin.users'))
    if user['is_admin'] and _admin_count() <= 1:
        flash('不能删除最后一位管理员', 'warning')
        return redirect(url_for('admin.users'))
    db.delete_user(uid)
    flash(f'已删除用户：{user["username"]}', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/admin/backup')
@admin_required
def backup():
    """一键备份数据库并下载（bill_backup_YYYYMMDD.db）。"""
    try:
        path = db.backup_db()
    except Exception as e:
        flash(f'备份失败：{e}', 'danger')
        return redirect(url_for('admin.users'))
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path), mimetype='application/x-sqlite3')


def _admin_count():
    return sum(1 for u in db.list_users() if u['is_admin'])


# ============ 用户批量导入（Excel）============
_TRUE_WORDS = {'是', 'y', 'Y', '1', 'true', 'TRUE', 'True', '管理员', 'admin'}


def _import_col(header, keywords):
    """按表头关键字定位列号（含「用户名」「账号」等模糊匹配）。"""
    for i, h in enumerate(header):
        if h and any(k in str(h) for k in keywords):
            return i
    return None


@bp.route('/admin/users/import', methods=['POST'])
@admin_required
def users_import():
    """批量导入用户：Excel 列「用户名 / 显示名 / 是否管理员」。
    初始密码统一为 IMPORT_DEFAULT_PASSWORD（可用 BILLHUB_IMPORT_PASSWORD 覆盖），
    导入用户首次登录强制改密；重复用户名跳过。"""
    f = request.files.get('file')
    if not f or not f.filename:
        flash('请选择要导入的 Excel 文件（.xlsx）', 'danger')
        return redirect(url_for('admin.users'))
    if not f.filename.lower().endswith('.xlsx'):
        flash('仅支持 .xlsx 格式的 Excel 文件', 'danger')
        return redirect(url_for('admin.users'))
    default_pwd = current_app.config['IMPORT_DEFAULT_PASSWORD']
    err = password_error(default_pwd)
    if err:
        flash(f'导入初始密码不符合强度要求（{err}），请检查 BILLHUB_IMPORT_PASSWORD 配置', 'danger')
        return redirect(url_for('admin.users'))
    try:
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    except Exception as e:
        flash(f'Excel 解析失败：{e}', 'danger')
        return redirect(url_for('admin.users'))
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        wb.close()
        flash('Excel 内容为空，请按模板填写后再导入', 'danger')
        return redirect(url_for('admin.users'))
    ci_user = _import_col(header, ('用户名', '账号'))
    ci_disp = _import_col(header, ('显示名', '姓名'))
    ci_admin = _import_col(header, ('管理员', '角色'))
    if ci_user is None:
        wb.close()
        flash('未找到「用户名」列（表头需含：用户名 / 显示名 / 是否管理员，可先下载导入模板）',
              'danger')
        return redirect(url_for('admin.users'))
    pwd_hash = hash_password(default_pwd)
    created, skipped = [], []
    seen = set()
    for row in rows:
        if row is None:
            continue
        username = str(row[ci_user] or '').strip() if ci_user < len(row) else ''
        if not username:
            continue
        disp = str(row[ci_disp] or '').strip() if (ci_disp is not None and ci_disp < len(row)) else ''
        admin_raw = str(row[ci_admin] or '').strip() if (ci_admin is not None and ci_admin < len(row)) else ''
        is_admin = admin_raw in _TRUE_WORDS
        if username in seen or db.get_user_by_username(username):
            skipped.append(username)
            continue
        seen.add(username)
        if db.create_user(username, pwd_hash, display_name=disp,
                          is_admin=is_admin, must_change_password=1) is None:
            skipped.append(username)
        else:
            created.append(username)
    wb.close()
    msg = f'导入完成：新增 {len(created)} 人'
    if skipped:
        msg += f'，跳过 {len(skipped)} 人（重复用户名：{"、".join(skipped)}）'
    flash(msg, 'success' if created else 'warning')
    if created:
        flash(f'导入用户初始密码为默认密码（首登强制修改），请妥善分发给 {len(created)} 位新用户', 'info')
    return redirect(url_for('admin.users'))


@bp.route('/admin/users/import/template')
@admin_required
def users_import_template():
    """下载用户导入模板（用户名 / 显示名 / 是否管理员）。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '用户'
    ws.append(['用户名', '显示名', '是否管理员'])
    ws.append(['zhangsan', '张三', '否'])
    ws.append(['lisi', '李四', '是'])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='用户导入模板.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
