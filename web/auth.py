"""BillHub 认证层：Flask-Login 集成 + 本地账号密码 + 权限装饰器。

P1 阶段仅本地账号密码；P5 将在此加入 LDAP/AD 双通道（verify_password 旁扩展）。"""
from functools import wraps

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash

import db

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
        # P5 在此插入 LDAP 分支：本地命中失败且 LDAP_ENABLED → ldap3 bind
        if user_row and verify_password(password, user_row.get('password_hash')):
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
