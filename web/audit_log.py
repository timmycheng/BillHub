"""BillHub 审计日志辅助：业务路由统一埋点入口。
记录失败不阻断业务（审计是旁路能力，任何异常静默吞掉）。"""
from flask import request
from flask_login import current_user

import db


def log_action(action, target='', detail='', username=None, user_id=None):
    """写审计日志。默认取当前登录用户与请求 IP；登录失败等无认证场景
    可用 username / user_id 显式传入（user_id 传 None 且未登录时置空）。"""
    try:
        if username is None and current_user.is_authenticated:
            username = current_user.username
        if user_id is None and current_user.is_authenticated:
            user_id = int(current_user.id)
        ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() \
            if request else ''
        if not ip:
            ip = (request.remote_addr or '') if request else ''
        db.add_audit_log(action, target=target, detail=detail,
                         username=username or '', user_id=user_id, ip=ip)
    except Exception:
        pass
