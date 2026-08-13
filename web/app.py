"""BillHub Flask 应用工厂。"""
import os
import time

from flask import Flask

import db
from web.auth import auth_bp, hash_password, login_manager
from web.config import Config
from web.routes.admin import bp as admin_bp
from web.routes.contracts import bp as contracts_bp
from web.routes.main import main_bp
from web.routes.ocr_api import bp as ocr_bp
from web.routes.payments import bp as payments_bp
from web.routes.preview import bp as preview_bp


def create_app(config_class=Config):
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    app.config.from_object(config_class)

    # 静态资源不长期缓存（开发期改 CSS/JS 立即生效；配合下面的 ?v= 缓存破坏）
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    # 初始化数据库（建表 + 增量迁移）+ 首次启动种子管理员
    db.init_db()
    _seed_admin(app)

    # Flask-Login
    login_manager.init_app(app)

    # 蓝图
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(preview_bp)
    app.register_blueprint(ocr_bp)
    app.register_blueprint(main_bp)

    # 确保上传目录存在
    os.makedirs(app.config['INVOICE_DIR'], exist_ok=True)
    os.makedirs(app.config['REPORT_DIR'], exist_ok=True)
    os.makedirs(app.config['CONTRACT_FILE_DIR'], exist_ok=True)

    # 静态资源缓存破坏：每次启动服务时间戳变化，浏览器必拉新版 CSS/JS
    app.jinja_env.globals['cache_bust'] = str(int(time.time()))

    # Jinja 过滤器：金额千分位格式化（¥1,234.56）
    @app.template_filter('money')
    def _money(value):
        try:
            return '{:,.2f}'.format(float(value))
        except (TypeError, ValueError):
            return str(value)

    # Jinja 过滤器：取文件名（剥路径）
    @app.template_filter('basename')
    def _basename(value):
        return os.path.basename(value) if value else ''

    return app


def _seed_admin(app):
    """users 表为空时自动创建默认管理员（用户名/密码可由环境变量配置）。
    首次登录后请立即在 P5 用户管理页或命令行修改密码。"""
    if db.count_users() > 0:
        return
    username = app.config['DEFAULT_ADMIN_USERNAME']
    password = app.config['DEFAULT_ADMIN_PASSWORD']
    db.create_user(username, hash_password(password),
                   display_name='管理员', is_admin=1)
    app.logger.info('已创建默认管理员账户：%s（请尽快修改密码）', username)
