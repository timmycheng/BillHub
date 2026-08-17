# BillHub

合同 / 发票 / 审批 / 报销一体化处理平台：合同管理 + OCR 识别 + 模板驱动审批表 + 报销状态流转，内网多人共享、Docker 一键部署。

自 2.0 起完全 Web 化（桌面版已下线）：**Flask + Jinja2 + HTMX**，数据存储于本地 SQLite，全流程离线可用。

## 功能

- 合同管理（付款计划 / 分类 / 收款信息 / 生效与结束时间 / 电子稿与扫描件附件），按经办人隔离，管理员全局可见
- 合同状态自动计算：签订状态（是否已上传 PDF 扫描件）+ 生效状态（未生效 / 生效中 / 已失效）
- 合同文本 OCR：上传合同文件（doc/docx/PDF/图片）自动回填签订单位、金额、收款信息、日期与付款计划
- 发票 OCR 识别（图片 / PDF 拖拽上传，自动填充发票号 / 日期 / 金额）
- 报销填报（多附件上传）+ 状态流转（已提交 → 审核中 → 已打款，时间轴展示）
- 模板驱动审批表生成（xlsx 下载 + HTML 预览 / 打印，预览与 Excel 排版一致）
- 仪表盘（统计卡 / 付款趋势 / 待办事项）、合同清单分页与筛选
- 用户管理（本地账号 + LDAP/AD 登录）、密码强度校验、数据库一键备份

## 快速开始

```bash
uv sync                 # 安装依赖
python run_web.py       # 开发模式 → http://127.0.0.1:5000
```

首次启动自动创建管理员：`admin / admin`（**登录后请立即修改密码**；可用环境变量 `BILLHUB_ADMIN_USER` / `BILLHUB_ADMIN_PASS` 覆盖）。

## Docker 部署

### 方式一：Docker Hub（有公网）

```bash
docker pull <namespace>/billhub-web:latest
cp .env.example .env && vim .env     # 必改 SECRET_KEY
mkdir -p data uploads
docker compose up -d                 # → http://<服务器IP>:8000
```

### 方式二：离线内网（完全隔离环境）

镜像从 GitHub Release 下载 `billhub-web-<版本>.tar.zst` 后：

```bash
zstd -d billhub-web-<版本>.tar.zst -o billhub-web-<版本>.tar
docker load -i billhub-web-<版本>.tar
cp .env.example .env && vim .env     # 必改 SECRET_KEY，VERSION 与镜像 tag 一致
mkdir -p data uploads
docker compose up -d
```

完整部署 / 升级 / 备份 / LDAP 配置见 [deploy.md](./deploy.md)。

## 数据存储

- SQLite（默认 `bill.db`，WAL 模式），环境变量 `BILLHUB_DB` 指定路径
- 上传发票、合同附件与生成的审批表存 `uploads/`（环境变量 `BILLHUB_UPLOAD_DIR`）
- 审批表 Excel 模板 `templates/*.xlsx` 随仓库入库（Docker 镜像构建依赖）

## 配置

环境变量（`docker-compose.yml` / `.env`，详见 `.env.example`）：

| 变量 | 说明 |
|---|---|
| `SECRET_KEY` | Flask 会话签名密钥，**生产必改** |
| `BILLHUB_DB` | SQLite 路径（默认 `bill.db`） |
| `BILLHUB_UPLOAD_DIR` | 上传文件目录 |
| `BILLHUB_ADMIN_USER/PASS` | 首次启动种子管理员（仅用户表为空时生效） |
| `BILLHUB_IMPORT_PASSWORD` | 批量导入用户的初始密码（首登强制修改） |
| `LDAP_*` | LDAP/AD 登录（默认关闭，`LDAP_ENABLED=true` 启用） |

## 开发与贡献

需求与缺陷用 GitHub Issues 管理（功能需求 / Bug 报告模板），main 分支有保护规则：

- 改动必须通过 PR 合并：需 1 人批准且冒烟检查（`smoke`）通过；禁止直接 force push main
- Issue 下评论 `/dev` 自动创建关联分支 `issue-N`；PR 描述写 `Closes #N` 自动关闭 Issue
- PR 合并后 changelog-bot 自动按标签（新增 / 变更 / 修复 / 移除）把条目追加到 `CHANGELOG.md` 顶部 `## [Unreleased]`（Keep a Changelog 约定）
- 本地提交代码时请顺手更新 `CHANGELOG.md`；改动后必须通过冒烟测试：`python test/smoke_test.py`

## 发版

### 一键发版（推荐）

仓库 → Actions → **Build & Release** → Run workflow，填版本号（如 `2.1.1`；留空沿用 pyproject.toml 当前版本）。

流水线自动完成：版本 bump → `[Unreleased]` 转正为版本小节（内容为空时从最近提交生成）→ 提交推送 main → 构建 Docker 镜像 → 发布 GitHub Release（Notes 取 CHANGELOG）→ 推送 Docker Hub（配置了 `DOCKERHUB_*` Secrets 时）→ 邮件分发（配置了 SMTP Secrets 时）。

### 手动发版（备用）

本地改好 `pyproject.toml` 版本号 + `CHANGELOG.md` 小节后提交，再打标签推送：

```bash
git tag v2.1.1 && git push origin v2.1.1
```

### 需要的 Secrets（仓库内无明文敏感信息）

- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` —— 发版后镜像分卷邮件分发（未配置则跳过）
- `DOCKERHUB_NAMESPACE` / `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` —— Docker Hub 推送（未配置则跳过）
- `BILLHUB_ADMIN_TOKEN` —— 供发版 / changelog 自动化以管理员身份推送 main（绕过分支保护）
