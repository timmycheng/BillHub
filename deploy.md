# BillHub Web 版内网部署（离线环境）

> 内网服务器无法访问公网，镜像通过 `docker load` 离线导入。
> BillHub 自 2.0 起完全 Web 化（桌面版已下线），多人共享通过 Web 版实现。

## 前置条件

- 内网服务器已装 Docker（≥ 20.10，支持 compose v2）
- 获取镜像（两种方式任选其一）：
  1. **GitHub Release**：带公网的机器下载 `billhub-web-<VERSION>.tar.zst` 与 `deploy-bundle.zip`，通过 USB/介质拷入内网
  2. **邮件分卷**：CI 发版时会把镜像按 25MB 分卷发到收件邮箱，收齐全部分卷后合并：
     ```bash
     cat *.tar.zst.part* > billhub-web-<VERSION>.tar.zst   # Windows 用 copy /b *.part* 目标名
     ```

## 部署步骤

```bash
# 1. 解压部署包（内含 docker-compose.yml 等）
unzip deploy-bundle.zip -d /opt/billhub && cd /opt/billhub

# 2. 导入镜像
zstd -d billhub-web-<VERSION>.tar.zst -o billhub-web-<VERSION>.tar
docker load -i billhub-web-<VERSION>.tar
docker images   # 确认存在 billhub-web:<VERSION>

# 3. 配置环境变量
cp .env.example .env
vim .env        # 必改：SECRET_KEY（随机长串）；VERSION 与镜像 tag 一致；
                # 建议改 BILLHUB_ADMIN_USER/BILLHUB_ADMIN_PASS（首次启动种子管理员）
                # 启用 AD 时：LDAP_ENABLED=true 并填 LDAP_* 配置

# 4. 创建数据目录并启动
mkdir -p data uploads
docker compose up -d

# 5. 访问
#   浏览器打开 http://<服务器IP>:8000 ，用管理员账号登录
#   首次登录后请立即修改管理员密码（顶栏「修改密码」）
```

## 日常运维

```bash
docker compose ps            # 查看状态
docker compose logs -f       # 查看日志
docker compose restart       # 重启
```

### 数据备份

- 数据库：`data/bill.db`（Web 版界面内也可「备份」一键下载）
- 上传的发票：`uploads/invoices/`
- 生成的审批表 Excel：`uploads/reports/`
- 建议定期整体备份 `data/` 与 `uploads/` 两个目录

### 升级

```bash
docker compose down
docker load -i billhub-web-<新版本>.tar.zst  # 先 zstd -d 解压
# 修改 .env 中 VERSION 为新版本
docker compose up -d
# 数据（data/uploads）目录不动即可无损升级
```

## 启用 LDAP/AD 登录

`.env` 中：

```ini
LDAP_ENABLED=true
LDAP_URI=ldap://ad.example.com:389
LDAP_BASE_DN=dc=example,dc=com
# 两种用户定位方式任选：
# 方式一：直接拼用户 DN
LDAP_USER_DN_TEMPLATE=uid={user},ou=users,dc=example,dc=com
# 方式二：服务账号搜索（AD 常用）
# LDAP_BIND_DN=CN=svc,OU=Services,DC=example,DC=com
# LDAP_BIND_PASSWORD=xxxx
```

登录时本地账号优先，失败或不存在则走 AD 验证；AD 用户首次登录自动建档（显示名取 AD，权限默认为普通用户，可在「用户管理」中提升）。
