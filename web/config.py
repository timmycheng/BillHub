"""BillHub Web 配置。
所有路径与开关优先读环境变量，便于 Docker 部署；不设时回退到项目本地默认值。"""
import os
import pathlib
import re

# 项目根（web/ 的上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = PROJECT_ROOT


def read_version():
    """从 pyproject.toml 读当前版本号（与发版 CI 保持同源），读不到时兜底 unknown。"""
    try:
        text = pathlib.Path(os.path.join(PROJECT_ROOT, 'pyproject.toml')).read_text(encoding='utf-8')
        m = re.search(r'(?m)(?<=^version = ")[^"]+(?=")', text)
        if m:
            return m.group(0)
    except OSError:
        pass
    return 'unknown'


class Config:
    # Flask 会话签名密钥：生产环境必须通过 SECRET_KEY 环境变量覆盖
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # 文件存储：上传的发票 / 生成的审批表 / 合同附件
    UPLOAD_DIR = os.environ.get('BILLHUB_UPLOAD_DIR') or os.path.join(_BASE, 'uploads')
    INVOICE_DIR = os.path.join(UPLOAD_DIR, 'invoices')
    REPORT_DIR = os.path.join(UPLOAD_DIR, 'reports')
    CONTRACT_FILE_DIR = os.path.join(UPLOAD_DIR, 'contracts')
    PAYMENT_FILE_DIR = os.path.join(UPLOAD_DIR, 'payment_files')

    # 审批表 Excel 模板（占位符驱动）
    APPROVAL_TEMPLATE = os.environ.get('BILLHUB_TEMPLATE') or os.path.join(
        _BASE, 'templates', '审批表模板2026.xlsx')

    # LDAP / AD（P5 阶段接入，默认关闭）
    LDAP_ENABLED = os.environ.get('LDAP_ENABLED', 'false').lower() == 'true'
    LDAP_URI = os.environ.get('LDAP_URI', '')
    LDAP_BASE_DN = os.environ.get('LDAP_BASE_DN', '')
    LDAP_BIND_DN = os.environ.get('LDAP_BIND_DN', '')          # 搜索用服务账号（可选）
    LDAP_BIND_PASSWORD = os.environ.get('LDAP_BIND_PASSWORD', '')
    LDAP_USER_DN_TEMPLATE = os.environ.get('LDAP_USER_DN_TEMPLATE', '')  # 如 uid={user},ou=users,{BASE}
    LDAP_SEARCH_FILTER = os.environ.get('LDAP_SEARCH_FILTER', '')

    # 首次启动自动种子的默认管理员（仅当 users 表为空时生效）
    DEFAULT_ADMIN_USERNAME = os.environ.get('BILLHUB_ADMIN_USER', 'admin')
    DEFAULT_ADMIN_PASSWORD = os.environ.get('BILLHUB_ADMIN_PASS', 'admin')

    # 批量导入用户的初始密码（须满足密码强度规则：8 位以上含大小写与特殊字符）
    IMPORT_DEFAULT_PASSWORD = os.environ.get('BILLHUB_IMPORT_PASSWORD', 'Abc12345!')
