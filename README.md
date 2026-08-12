# BillHub

发票 / 审批 / 报销一体化处理工具。合同管理 + 智能报销生成 + OCR 识别 + 模板驱动。

支持两种形态（共享同一套数据层与报表逻辑）：

- **Web 版**（Flask + Jinja2 + HTMX，内网多人共享，Docker 部署）—— 主力形态
- **桌面版**（PyQt6 + RapidOCR + PyInstaller 打包为 Windows exe）—— 单机离线兜底

## Web 版（推荐）

### 本地开发

```bash
uv sync                 # 安装全部依赖（桌面 + Web）
python run_web.py       # 开发模式 → http://127.0.0.1:5000
```

首次启动自动创建管理员：`admin / admin`（建议登录后立即修改密码；可用环境变量 `BILLHUB_ADMIN_USER` / `BILLHUB_ADMIN_PASS` 覆盖）。

### 生产运行（本机直接跑）

```bash
$env:SECRET_KEY = "随机长字符串"   # PowerShell；Linux 用 export
python run_web.py --prod           # waitress → http://0.0.0.0:8000
```

### Docker 内网部署（离线）

镜像从 GitHub Release 下载 `billhub-web-<版本>.tar.zst` 后：

```bash
zstd -d billhub-web-<版本>.tar.zst -o billhub-web-<版本>.tar
docker load -i billhub-web-<版本>.tar
cp .env.example .env && vim .env     # 必改 SECRET_KEY，VERSION 与镜像 tag 一致
mkdir -p data uploads
docker compose up -d                 # → http://<服务器IP>:8000
```

完整步骤见 [deploy.md](./deploy.md)。

### 功能

- 合同管理（付款计划 / 分类 / 收款信息），按经办人隔离，管理员全局可见
- OCR 发票识别（图片 / PDF 拖拽上传，自动填充发票号 / 日期 / 金额）
- 模板驱动审批表生成（xlsx 下载 + HTML 预览 / 打印）
- 历史支付记录 / 期数自动联动 / 发票号重复校验
- 用户管理、数据库一键备份、LDAP/AD 登录（可选）

## 桌面版

```bash
python main.py       # 启动桌面应用
build_exe.bat        # 打包 → dist/BillHub.exe
```

## 数据存储

SQLite（默认 `bill.db`，WAL 模式），环境变量 `BILLHUB_DB` 指定路径；上传发票与生成的审批表存 `uploads/`（`BILLHUB_UPLOAD_DIR`）。

## CI/CD

push 到 `main`（或手动触发）自动构建发布（见 `.github/workflows/build-release.yml`）：

- **桌面版**：windows-latest 上 PyInstaller 打包 `BillHub.exe`
- **Web 镜像**：ubuntu-latest 构建 `billhub-web` 并导出离线 tar（zstd 压缩）
- **Release**：统一挂载 exe + 镜像 tar + 部署包（docker-compose / .env.example / deploy.md）

> 邮件分发功能目前暂停，脚本保留在 `scripts/` 下，待稳定后恢复。
