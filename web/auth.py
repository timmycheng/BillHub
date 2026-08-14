"""BillHub 认证层：Flask-Login 集成 + 本地账号密码 + 权限装饰器。

P1 阶段仅本地账号密码；P5 将在此加入 LDAP/AD 双通道（verify_password 旁扩展）。"""
from functools import wraps
import re

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash

import db

PASSWORD_RULE = '密码至少 8 位，且需包含大写字母、小写字母和特殊字符'


def password_error(password):
    """密码强度校验：8 位以上、包含大小写和特殊字符。返回错误文案或 None。"""
    if len(password) < 8:
        return '密码至少 8 位'
    if not re.search(r'[a-z]', password) or not re.search(r'[A-Z]', password):
        return '密码需包含大写和小写字母'
    if not re.search(r'[^A-Za-z0-9]', password):
        return '密码需包含特殊字符'
    return None

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录。'
login_manager.login_message_category = 'warning'


class User(UserMixin):
    """Flask-Login 用户包装，封装 db.users 行。id 转字符串供 session 序列化。"""

    def __init__(self, row):
        self.id = str(row['id'])
        self.username = row['username']
        self.display_name = row.get('display_name') or row['username']
        self.is_admin = bool(row.get('is_admin'))


@login_manager.user_loader
def load_user(user_id):
    row = db.get_user(int(user_id))
    return User(row) if row else None


# ============ 密码工具（db 层不依赖 werkzeug，哈希在此完成）============
def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


# ============ 权限装饰器 ============
def admin_required(f):
    """要求登录且为管理员；否则 403。"""
    @wraps(f)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def can_access_contract(contract):
    """当前用户能否访问该合同：管理员或拥有者。"""
    return current_user.is_admin or (contract.get('owner_id') == int(current_user.id))


# ============ 登录 / 登出蓝图 ============
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user_row = db.get_user_by_username(username)

        # 通道 1：本地账号密码
        ok = bool(user_row) and verify_password(password, user_row.get('password_hash'))
        # 通道 2：LDAP/AD（本地验证失败或本地无此用户时尝试）
        ad_info = None
        if not ok:
            from flask import current_app
            from web.ldap_auth import ldap_authenticate
            ad_info = ldap_authenticate(username, password, current_app.config)
            if ad_info:
                if user_row is None:
                    # AD 首次登录自动建档（本地无密码，走 AD 通道）
                    new_id = db.create_user(ad_info['username'], None,
                                            ad_info.get('display_name', ''),
                                            is_admin=0, ad_dn=ad_info.get('ad_dn'))
                    if new_id:
                        user_row = db.get_user(new_id)
                else:
                    # 已有本地记录：记录 AD DN（存在则保留本地 is_admin 配置）
                    db.update_user(user_row['id'], ad_dn=ad_info.get('ad_dn'))
                ok = user_row is not None

        if ok and user_row:
            login_user(User(user_row))
            next_url = request.args.get('next') or url_for('main.dashboard')
            # 防开放重定向：只允许站内相对路径
            if not next_url.startswith('/') or next_url.startswith('//'):
                next_url = url_for('main.dashboard')
            return redirect(next_url)
        flash('用户名或密码错误', 'danger')
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/account/password', methods=['GET', 'POST'])
@login_required
def change_password():
    user_row = db.get_user(int(current_user.id))
    if not user_row.get('password_hash'):
        # AD 账号无本地密码，提示走公司系统
        flash('该账号使用 AD 认证，请通过公司系统修改密码', 'info')
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not verify_password(old, user_row.get('password_hash')):
            flash('原密码错误', 'danger')
        elif new != confirm:
            flash('两次输入的新密码不一致', 'danger')
        else:
            err = password_error(new)
            if err:
                flash(err, 'danger')
            else:
                db.update_user(int(current_user.id), password_hash=hash_password(new))
                flash('密码已修改，请牢记', 'success')
                return redirect(url_for('main.dashboard'))
    return render_template('account/password.html')
