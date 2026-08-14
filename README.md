# BillHub

合同 / 发票 / 审批 / 报销一体化处理平台。合同管理 + 智能报销生成 + OCR 识别 + 模板驱动。

自 2.0 起完全 Web 化（桌面版已下线）：Flask + Jinja2 + HTMX，内网多人共享，Docker 部署。

## 本地开发

```bash
uv sync                 # 安装依赖
python run_web.py       # 开发模式 → http://127.0.0.1:5000
```

首次启动自动创建管理员：`admin / admin`（建议登录后立即修改密码；可用环境变量 `BILLHUB_ADMIN_USER` / `BILLHUB_ADMIN_PASS` 覆盖）。

## 生产运行（本机直接跑）

```bash
$env:SECRET_KEY = "随机长字符串"   # PowerShell；Linux 用 export
python run_web.py --prod           # waitress → http://0.0.0.0:8000
```

## Docker 内网部署（离线）

镜像从 GitHub Release 下载 `billhub-web-<版本>.tar.zst` 后：

```bash
zstd -d billhub-web-<版本>.tar.zst -o billhub-web-<版本>.tar
docker load -i billhub-web-<版本>.tar
cp .env.example .env && vim .env     # 必改 SECRET_KEY，VERSION 与镜像 tag 一致
mkdir -p data uploads
docker compose up -d                 # → http://<服务器IP>:8000
```

完整步骤见 [deploy.md](./deploy.md)。

## 功能

- 合同管理（付款计划 / 分类 / 收款信息 / 生效与结束时间 / 电子稿与扫描件附件），按经办人隔离，管理员全局可见
- 合同状态自动计算：签订状态（是否已上传 PDF 扫描件）+ 生效状态（未生效 / 生效中 / 已失效）
- 合同文本 OCR：上传合同文件（doc/docx/PDF/图片）自动回填签订单位、金额、收款信息、日期与付款计划
- OCR 发票识别（图片 / PDF 拖拽上传，自动填充发票号 / 日期 / 金额）
- 报销填报（多附件上传）+ 状态流转（已提交 → 审核中 → 已打款，时间轴展示）
- 模板驱动审批表生成（xlsx 下载 + HTML 预览 / 打印，预览与 Excel 排版一致）
- 仪表盘（统计卡 / 付款趋势 / 待办事项）、合同清单分页与筛选
- 用户管理、数据库一键备份、LDAP/AD 登录（可选）

## 数据存储

SQLite（默认 `bill.db`，WAL 模式），环境变量 `BILLHUB_DB` 指定路径；上传发票、合同附件与生成的审批表存 `uploads/`（`BILLHUB_UPLOAD_DIR`）。

## CI/CD

仅在发版时触发（推送 `v*` 标签，或手动 workflow_dispatch），见 `.github/workflows/build-release.yml`：

1. 修改 `pyproject.toml` 版本号，并在 `CHANGELOG.md` 写好对应版本的 `## [x.y.z]` 小节
2. 提交到 `main` 后打标签推送：`git tag v<x.y.z> && git push origin v<x.y.z>`
3. 自动构建 `billhub-web` 镜像并导出离线 tar（zstd 压缩），发布 GitHub Release（Release Notes 自动取 CHANGELOG 对应小节），附带部署包（docker-compose / .env.example / deploy.md）
4. 镜像自动按 25MB 分卷通过邮件发送到收件人（内网环境无法上 GitHub 时可直接收邮件导入）

邮件分发需在仓库 Secrets 配置（保证私密性，仓库内无明文收件信息）：

- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` —— 发件邮箱及授权码
- `MAIL_TO` —— 收件人地址
