"""BillHub 管理员蓝图：用户管理（增删改/重置密码）+ 数据库备份。仅管理员可访问。"""
import os
import tempfile

from flask import (Blueprint, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user

import db
from web.auth import admin_required, hash_password

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
    if len(password) < 4:
        flash('密码至少 4 位', 'danger')
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
    # 防止把最后一位管理员降级成普通用户
    if user['is_admin'] and not is_admin and _admin_count() <= 1:
        flash('不能降级最后一位管理员', 'warning')
        return redirect(url_for('admin.users'))
    db.update_user(uid, display_name=display_name, is_admin=is_admin)
    flash(f'已更新用户：{user["username"]}', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/admin/users/<int:uid>/password', methods=['POST'])
@admin_required
def users_password(uid):
    user = db.get_user(uid)
    if not user:
        flash('用户不存在', 'warning')
        return redirect(url_for('admin.users'))
    password = request.form.get('password', '')
    if len(password) < 4:
        flash('密码至少 4 位', 'danger')
        return redirect(url_for('admin.users'))
    db.update_user(uid, password_hash=hash_password(password))
    flash(f'已重置用户「{user["username"]}」的密码', 'success')
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
