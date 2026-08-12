"""BillHub LDAP/AD 认证（P5）。
用 ldap3 做 bind 验证，支持两种用户查找方式：
  1. LDAP_USER_DN_TEMPLATE 直接拼用户 DN（如 uid={user},ou=users,dc=example,dc=com）
  2. 用服务账号（LDAP_BIND_DN/PASSWORD）搜索 base DN 下 sAMAccountName|uid 匹配的用户
ldap3 惰性导入：未配置 AD 的部署不依赖该包。"""
import logging

log = logging.getLogger(__name__)


def ldap_authenticate(username, password, config):
    """LDAP 认证。成功返回用户信息 dict（display_name 等）；失败返回 None。
    config: Flask app.config（读 LDAP_* 配置）。"""
    if not config.get('LDAP_ENABLED'):
        return None
    if not (username and password):
        return None
    try:
        import ldap3
    except ImportError:
        log.warning('ldap3 未安装，AD 认证不可用')
        return None

    uri = config.get('LDAP_URI', '')
    base_dn = config.get('LDAP_BASE_DN', '')
    if not uri:
        log.warning('LDAP_ENABLED 但未配置 LDAP_URI')
        return None

    try:
        server = ldap3.Server(uri, get_info=ldap3.ALL)
        user_dn, attrs = _find_user_dn(ldap3, server, username, base_dn, config)
        if not user_dn:
            return None
        # 用用户自己的 DN + 密码 bind（真正的密码校验）
        conn = ldap3.Connection(server, user=user_dn, password=password,
                                authentication=ldap3.SIMPLE, auto_bind=True)
        try:
            conn.bind()  # auto_bind=True 时已绑定，此处冗余无害
        except ldap3.core.exceptions.LDAPException:
            return None
        conn.unbind()
        return {
            'username': username,
            'display_name': attrs.get('display_name') or attrs.get('cn') or username,
            'ad_dn': user_dn,
        }
    except Exception:
        log.exception('LDAP 认证异常')
        return None


def _find_user_dn(ldap3, server, username, base_dn, config):
    """定位用户 DN。优先模板直拼；否则服务账号搜索。
    返回 (user_dn, attributes_dict) 或 (None, {})。"""
    template = config.get('LDAP_USER_DN_TEMPLATE', '')
    if template:
        return template.format(user=username), {}

    search_filter = config.get('LDAP_SEARCH_FILTER') or \
        '(|(sAMAccountName={user})(uid={user}))'
    bind_dn = config.get('LDAP_BIND_DN', '')
    bind_pwd = config.get('LDAP_BIND_PASSWORD', '')
    if bind_dn:
        conn = ldap3.Connection(server, user=bind_dn, password=bind_pwd,
                                authentication=ldap3.SIMPLE, auto_bind=True)
    else:
        conn = ldap3.Connection(server, auto_bind=True)  # 匿名
    try:
        attrs_to_get = ['sAMAccountName', 'uid', 'cn', 'displayName']
        conn.search(search_base=base_dn, search_filter=search_filter.format(user=username),
                    attributes=attrs_to_get, size_limit=1)
        if not conn.entries:
            return None, {}
        entry = conn.entries[0]
        display = entry.displayName.value or entry.cn.value or username
        return entry.entry_dn, {'display_name': display, 'cn': entry.cn.value}
    finally:
        conn.unbind()
