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


def test_connection(cfg, username='', password=''):
    """测试 LDAP 配置连通性 / 认证，返回 (ok, message)。
    未填测试账号：仅测服务器连通（按配置用服务账号或匿名 bind，并尝试检索 Base DN）；
    填写测试账号：走完整认证流程。"""
    if not cfg.get('LDAP_URI'):
        return False, '未配置服务器地址（LDAP_URI）'
    try:
        import ldap3
    except ImportError:
        return False, 'ldap3 库未安装，无法测试连接'
    try:
        server = ldap3.Server(cfg['LDAP_URI'], get_info=ldap3.ALL, connect_timeout=10)
        if username and password:
            info = ldap_authenticate(username, password, cfg)
            if info:
                dn = info.get('ad_dn') or ''
                return True, f'认证成功（DN: {dn}）' if dn else '认证成功'
            return False, '认证失败：用户名或密码错误，或该用户不在 Base DN 范围内'
        if cfg.get('LDAP_BIND_DN'):
            conn = ldap3.Connection(server, user=cfg['LDAP_BIND_DN'],
                                    password=cfg.get('LDAP_BIND_PASSWORD', ''),
                                    authentication=ldap3.SIMPLE, auto_bind=True,
                                    receive_timeout=10)
        else:
            conn = ldap3.Connection(server, auto_bind=True, receive_timeout=10)
        msg = '连接成功'
        base_dn = cfg.get('LDAP_BASE_DN', '')
        if base_dn:
            found = conn.search(base_dn, '(objectClass=*)', size_limit=1)
            msg = '连接成功，Base DN 可检索到对象' if found else '连接成功，但 Base DN 下未检索到任何对象'
        conn.unbind()
        return True, msg
    except Exception as e:
        return False, f'连接失败：{e}'
