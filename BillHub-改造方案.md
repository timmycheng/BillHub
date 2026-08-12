# BillHub 改造方案

> 原 `WZBill`（PyQt6 桌面应用）改造为 **BillHub**：保留桌面版 + 新增 Web 版（内网多人共享）+ CI/CD 双产物（exe + Docker 镜像）。本仓库将转为公开。

---

## 0. 总体目标与决策汇总

| 维度 | 决策 |
|---|---|
| 项目名 | `WZBill` → **`BillHub`** |
| 仓库可见性 | 转为公开（需脱敏银行特定信息） |
| 部署形态 | 内网多人共享，完全隔离（离线） |
| 前端 | Flask + Jinja2 + HTMX 局部刷新 |
| 桌面版 | 保留并存（共享底层模块） |
| OCR | 服务端复用 `ocr.py` |
| 数据隔离 | 按 `owner_id`（经办人）隔离，管理员 `is_admin=1` 全局可见 |
| 认证 | 本地账号密码先行；AD/LDAP 留 P5 接入 |
| 数据库 | SQLite + WAL 模式（沿用 `db.py`） |
| 审批表预览 | Jinja2 渲染 HTML 仿模板排版 + 浏览器打印；xlsx 另供下载 |
| CI/CD 产物 | 桌面 exe + Docker 镜像（tar，离线 load） |
| 邮件分发 | 暂停（脚本保留，`if: false` 禁用） |

---

## 1. 改名：WZBill → BillHub

### 1.1 命名层级

| 层级 | 旧 | 新 |
|---|---|---|
| 品牌名（标题/About） | WZBill | BillHub |
| exe 产物 | WZBill.exe | BillHub.exe |
| Docker 镜像 | — | billhub-web |
| Python 包名 | wzbill | billhub |
| GitHub 仓库 | WZBill | BillHub（需手动在 GitHub 改） |

### 1.2 改名引用清单（30 处 + SmartBill 4 处）

| 文件 | 改动点 |
|---|---|
| `pyproject.toml` | `name = "wzbill"` → `billhub`；版本统一为 `1.2.0` |
| `uv.lock` | 包名同步 |
| `main.py` | docstring、窗口标题、About 对话框共 5 处；About 版本号改读 pyproject |
| `db.py`、`ocr.py`、`template_engine.py`、`contract_io.py` | docstring `SmartBill` → `BillHub`（消除内部不一致） |
| `WZBill.spec` → **重命名为 `BillHub.spec`** | `name='BillHub'` |
| `build_exe.bat` | 注释、`--name`、产物路径共 6 处 |
| `README.md` | 标题、产物路径、7z 名共 5 处；改写为公开仓库版 |
| `scripts/send_email.py` | docstring、邮件主题、From 名、正文共 5 处 |
| 工作流（重写时一并改） | exe 名、artifact 名、release 标题 |

### 1.3 敏感信息脱敏（公开必须）

- `内部收件邮箱`（README ×2、workflow `MAIL_TO` ×1）→ 占位符 `your-recipient@example.com`
- README 增加说明："收件人地址自行在 workflow `MAIL_TO` 配置"

### 1.4 需单独在 GitHub 操作

仓库 Settings → Rename `WZBill` → `BillHub`。GitHub 会自动对旧名做重定向，本地 `origin` URL 无需改动。

---

## 2. Web 应用架构

```
┌─────────────────────────────────────────────────────────┐
│  浏览器（内网任意设备：PC / 手机 / 平板）                  │
│  Flask + Jinja2 + HTMX（局部刷新，免 SPA 工程化）         │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────┐
│  Flask 后端（waitress 部署）                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ auth 蓝图 │ │contracts │ │ payments │ │ ocr/files  │  │
│  │登录/权限  │ │ 合同CRUD │ │ 报销填报 │ │ 上传/下载   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘  │
│       │ Flask-Login + @login_required + @admin_required  │
├───────┴────────────┴────────────┴────────────┴──────────┤
│  复用层（几乎不改）                                       │
│  db.py ◇ ocr.py ◇ template_engine.py ◇ contract_io.py   │
├──────────────────────────────────────────────────────────┤
│  SQLite（bill.db，WAL 模式） + 文件存储（uploads/）       │
└──────────────────────────────────────────────────────────┘
```

**核心原则**：4 个业务模块（`db / ocr / template_engine / contract_io`）几乎原样复用，只把 `main.py`（PyQt6 UI）替换为 Flask。桌面版 `main.py` 保留，两套 UI 共享同一套底层。

### 2.1 新增项目结构

```
BillHub/
├── main.py                 # ← 保留，桌面版入口（PyQt6）
├── db.py                   # ← 加 users 表 + owner/user 字段迁移
├── ocr.py                  # ← 不动
├── template_engine.py      # ← 不动
├── contract_io.py          # ← 不动
├── utils.py                # ← 新增：抽 num_to_cn 等公共函数
├── web/                    # ← 新增：Web 版
│   ├── app.py              # Flask 工厂 + 蓝图注册
│   ├── config.py           # 密钥/LDAP/路径配置
│   ├── auth.py             # Flask-Login + 本地密码 + AD 双通道
│   ├── uploads.py          # 文件保存/下载辅助
│   ├── routes/
│   │   ├── main.py         # 首页面板（三栏布局）
│   │   ├── contracts.py    # 合同 CRUD + 付款计划
│   │   ├── payments.py     # 报销填报 + 历史
│   │   ├── ocr_api.py      # 上传→OCR→返回 JSON（HTMX 调用）
│   │   ├── files.py        # 票据/审批表下载
│   │   └── admin.py        # 用户管理（仅管理员）
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html  # 三栏主界面
│   │   ├── contract_form.html
│   │   ├── payment_form.html
│   │   ├── approval_preview.html  # 右栏审批表 HTML 预览（可打印）
│   │   └── admin/users.html
│   └── static/
│       ├── style.css
│       └── app.js
├── uploads/                # ← 运行时生成（不入库）
│   ├── invoices/
│   └── reports/
├── Dockerfile.web          # ← 新增
├── docker-compose.yml      # ← 新增
├── requirements-web.txt    # ← 新增
├── .env.example            # ← 新增
├── deploy.md               # ← 新增
└── run_web.py              # Web 版启动入口
```

---

## 3. 数据库改动（最小化迁移）

现有 3 张表保留，新增 1 张用户表 + 给合同/支付记录加所有者字段。

### 3.1 新增表与字段

```sql
-- 新增：用户表
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT,          -- 本地账号（AD 用户留空）
    display_name TEXT,
    is_admin INTEGER DEFAULT 0,  -- 管理员绕过经办人隔离
    ad_dn TEXT,                  -- LDAP distinguishedName，启用 AD 时用
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- contracts 增量加列（沿用现有 _migrate 机制）
ALTER TABLE contracts ADD COLUMN owner_id INTEGER REFERENCES users(id);
-- contract_manager 字段保留为"显示用文本"，owner_id 用于权限判断

-- payment_records 增量加列（审计谁填报的）
ALTER TABLE payment_records ADD COLUMN user_id INTEGER REFERENCES users(id);
```

### 3.2 权限规则

- 普通用户：只能看/编辑 `owner_id = 自己` 的合同；只能看自己填报的支付记录
- 管理员（`is_admin=1`）：看所有合同、所有记录，可管理用户

### 3.3 并发

SQLite 开启 WAL：`PRAGMA journal_mode=WAL;` —— 十几人内网并发读写完全足够。

---

## 4. 后端模块设计

### 4.1 模块复用度

| 模块 | 行数 | 改动 |
|---|---|---|
| `main.py` | 1085 | 保留（桌面版入口）；Web 版不引用 |
| `db.py` | 368 | 加 users 表 + owner/user 字段迁移；`DB_PATH` 环境变量化 |
| `ocr.py` | 116 | 不动 |
| `template_engine.py` | 174 | 不动 |
| `contract_io.py` | 192 | 不动 |

### 4.2 Flask 路由蓝图

| 蓝图 | 路径 | 功能 |
|---|---|---|
| `auth` | `/login`, `/logout` | 登录/登出 |
| `main` | `/` | 三栏主面板 |
| `contracts` | `/contracts`, `/contracts/new`, `/contracts/<id>/edit`, `/contracts/import`, `/contracts/export` | 合同 CRUD + 清单导入导出 |
| `payments` | `/contracts/<id>/payments`, `/payments/new` | 报销填报 + 历史记录 |
| `ocr_api` | `/api/ocr`（POST） | 上传文件 → OCR → 返回 JSON |
| `files` | `/files/invoice/<id>`, `/files/report/<id>` | 票据/审批表下载或预览 |
| `admin` | `/admin/users` | 用户管理（仅管理员） |

### 4.3 认证与权限（双通道登录）

```
用户输入用户名 + 密码
  ├─ 先查 users 表 password_hash → 命中则本地登录
  └─ 本地无此用户 / 标记为 AD → ldap3 连公司 AD 做 bind 验证
        ├─ 成功 → 自动建/更新本地用户记录（首次登录自动建档）
        └─ 失败 → 拒绝
```

- `Flask-Login` 管 session，`@login_required` 全站守护
- `@admin_required` 装饰器保护用户管理/备份/全局视图
- 配置项 `LDAP_ENABLED`、`LDAP_URI`、`LDAP_BASE_DN` 在 `config.py`
- **不启用 AD 时纯本地账号也能跑**（P1–P4 阶段）

---

## 5. 前端设计（对应 issue.md 三栏布局）

### 5.1 主面板 `dashboard.html`（单页三栏，HTMX 驱动）

```
┌──────────────┬──────────────────┬────────────────────┐
│ 左栏         │ 中栏              │ 右栏                │
│              │                  │                    │
│ ┌──────────┐ │ ┌──────────────┐ │ ┌────────────────┐ │
│ │🔍 搜索   │ │ │📷 上传发票   │ │ │  审批表预览     │ │
│ ├──────────┤ │ │  (拖拽/点击) │ │ │  (HTML 渲染，   │ │
│ │ 合同列表 │ │ │  → 自动OCR   │ │ │   模拟模板排版) │ │
│ │ (可滚动) │ │ ├──────────────┤ │ │                │ │
│ │          │ │ │ 发票号/金额  │ │ │  [🖨 打印]      │ │
│ │          │ │ │ 日期/阶段    │ │ │  [📥 下载Excel] │ │
│ ├──────────┤ │ │ 备注…        │ │ └────────────────┘ │
│ │ 合同详情 │ │ ├──────────────┤ │                    │
│ │ 付款计划 │ │ │[生成报销单]  │ │                    │
│ │ 摘要     │ │ ├──────────────┤ │                    │
│ │          │ │ │ 历史支付记录 │ │                    │
│ └──────────┘ │ │ (本合同)     │ │                    │
│              │ └──────────────┘ │                    │
└──────────────┴──────────────────┴────────────────────┘
```

### 5.2 交互（HTMX 局部刷新，无需整页跳转）

- 点左栏合同 → 中栏/右栏表单数据切换（`hx-get` 局部刷新）
- 上传发票 → POST `/api/ocr` → 返回 JSON → JS 自动填入表单
- 点"生成报销单" → 后端生成 xlsx + 保存记录 → 右栏刷新预览

### 5.3 关键工作流映射

| 桌面版（PyQt6） | Web 版（Flask） |
|---|---|
| `QFileDialog` 选发票 | `<input type="file">` + 拖拽上传 |
| `OCRThread` 后台识别 | POST `/api/ocr`，`ocr.py.extract()` 服务端跑 |
| `QMessageBox` 提示 | Flash 消息 / Toast |
| `template_engine.render` 生成 xlsx | 同，结果存 `uploads/reports/` |
| `os.startfile()` 打开文件 | `/files/<id>` 路由下载/在线预览 |
| 右栏 PDF | HTML 预览模板 + 浏览器打印；附 xlsx 下载 |
| 合同清单导入导出 | `/contracts/import`、`/contracts/export` |
| 备份数据库 | 管理员后台一键下载 `bill_backup_*.db` |

---

## 6. CI/CD 设计

### 6.1 现状 vs 目标

| 维度 | 现状（单 Job） | 目标 |
|---|---|---|
| 触发 | push main / 手动 | 不变 |
| 桌面版 exe | windows-latest 打包 | 保留，去掉 7z 分卷 |
| Web Docker 镜像 | — | 新增，ubuntu-latest 构建 |
| 邮件分发 | SMTP 发分卷 | 暂停（脚本保留，step 禁用） |
| GitHub Release | exe | exe + docker tar + 部署文件 |
| 产物送达内网 | 邮件 | Release/Artifact 下载后手动拷入 |

### 6.2 工作流结构（2 构建并行 + 1 发版 + 1 禁用）

```yaml
name: Build & Release
on: { push: { branches: [main] }, workflow_dispatch: }
concurrency: { group: build-release, cancel-in-progress: true }

jobs:
  build-exe:        # Job 1 — windows-latest（桌面版）
  build-docker:     # Job 2 — ubuntu-latest（Web 镜像），与 Job 1 并行
  release:          # Job 3 — needs [build-exe, build-docker]，统一发版
  email:            # Job 4 — if: false 禁用，脚本保留
```

#### Job 1 `build-exe`
```
Checkout → Setup Python 3.11 → pip install -r requirements.txt
→ 拷 OCR ONNX 模型到 models/
→ pyinstaller --clean BillHub.spec        # 产物 dist/BillHub.exe
→ Upload artifact（整 exe，不再分卷）
```

#### Job 2 `build-docker`
```
Checkout → Set up Docker Buildx
→ docker build -t billhub-web:<version> -f Dockerfile.web .
→ docker save billhub-web:<version> | zstd -19 -o billhub-web-<version>.tar.zst
→ 打包部署文件 (docker-compose.yml + .env.example + deploy.md) → deploy-bundle.zip
→ Upload artifact: 镜像 tar + 部署包
```

> 用 `zstd -19` 压缩：1GB 镜像通常压到 300–500MB，便于拷贝。Release 单文件限 2GB，足够。

#### Job 3 `release`（统一发版，避免两 Job 抢同一 tag）
```
needs: [build-exe, build-docker]
→ Download 两个 artifact
→ 从 pyproject.toml 读 version → tag = v<version>
→ gh release create $tag 上挂:
    • BillHub.exe                    (桌面版)
    • billhub-web-<version>.tar.zst  (Docker 镜像)
    • deploy-bundle.zip              (内网部署包)
```

#### Job 4 `email`（保留代码，禁用触发）
```yaml
email:
  if: false        # ← 一行禁用，等稳定后改 true
  needs: release
  ... 原 send_email.py 逻辑（含 7z 分卷）保持不动 ...
```

`scripts/send_email.py` 文件原样保留；恢复时只需去掉 `if: false`、重新启用 7z 分卷步骤。

---

## 7. Docker 镜像设计

### 7.1 `Dockerfile.web`

```dockerfile
FROM python:3.11-slim

# onnxruntime 运行时依赖 OpenMP（slim 镜像不带）
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷依赖清单装包（利用层缓存；Web 版不含 PyQt6/pyinstaller）
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# 拷业务代码 + 模板
COPY db.py ocr.py template_engine.py contract_io.py utils.py ./
COPY web/ ./web/
COPY templates/ ./templates/

# 构建期从 rapidocr 包内提取 ONNX 模型（与 exe 打包同一手法）
RUN python -c "import rapidocr_onnxruntime as r,os,shutil; \
    src=os.path.join(os.path.dirname(r.__file__),'models'); \
    dst='/app/models'; os.makedirs(dst); \
    [shutil.copy2(os.path.join(src,f),os.path.join(dst,f)) \
     for f in os.listdir(src) if f.endswith('.onnx')]"

# 数据落卷（DB、上传发票、生成的审批表）
VOLUME ["/app/data", "/app/uploads"]
ENV BILLHUB_DB=/app/data/bill.db
ENV BILLHUB_UPLOAD_DIR=/app/uploads
EXPOSE 8000

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8000", "web.app:create_app()"]
```

### 7.2 `requirements-web.txt`

```
flask==3.1.3
flask-login==0.6.3
waitress==3.0.0          # 生产 WSGI（跨平台，Linux/Windows 通用）
openpyxl==3.1.5
xlrd==2.0.2
xlutils==2.0.0
xlwt==1.3.0
rapidocr-onnxruntime==1.4.4
Pillow>=9.0
pymupdf>=1.24
ldap3==2.9.1             # P5 阶段 AD 接入用（先装上免得改 Dockerfile）
```

> 原 `requirements.txt`（含 PyQt6/pyinstaller）保持不动，继续给桌面版 / Job1 用。

### 7.3 `docker-compose.yml`

```yaml
services:
  billhub:
    image: billhub-web:${VERSION}
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # SQLite 持久化
      - ./uploads:/app/uploads    # 发票/审批表持久化
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - BILLHUB_DB=/app/data/bill.db
      - LDAP_ENABLED=false        # P5 启用 AD 时改 true
    restart: unless-stopped
```

### 7.4 `.env.example`

```
VERSION=1.2.0
SECRET_KEY=请改成随机长字符串
LDAP_ENABLED=false
```

### 7.5 `deploy.md`（内网部署说明，随镜像交付）

```
1. docker load -i billhub-web-<version>.tar.zst
2. cp .env.example .env && 编辑 SECRET_KEY / VERSION
3. mkdir data uploads
4. docker compose up -d
5. 浏览器访问 http://<服务器>:8000
```

### 7.6 内网交付流程（离线场景）

```
GitHub Actions（公网）
   ↓ Release 产物
带公网的机器下载 → billhub-web-x.x.x.tar.zst + deploy-bundle.zip
   ↓ USB / 经办介质拷入内网
内网服务器:
   docker load -i billhub-web-x.x.x.tar.zst
   解压 deploy-bundle.zip → docker compose up -d
```

桌面版 exe 同理：下载后双击运行（与现状一致）。

---

## 8. 配套小改动（容器化必要）

| 文件 | 改动 | 影响 |
|---|---|---|
| `db.py` | `DB_PATH` 改读环境变量：`os.environ.get('BILLHUB_DB', 默认本地路径)` | 桌面版零影响（默认值不变） |
| `web/config.py` | 上传/报表目录读 `BILLHUB_UPLOAD_DIR` 环境变量 | 仅 Web 版 |
| `pyproject.toml` | 版本号统一为 `1.2.0`（与 main.py 的 1.1.0 对齐） | CI 从此处读 tag，桌面/Web 版本号一致 |
| `main.py` | About 对话框版本号改读 `pyproject.toml` | 去重，单一来源 |

---

## 9. 实施路线图

| 阶段 | 内容 | 产出 |
|---|---|---|
| **A** | 改名 + 容器化地基（`db.py` 的 `DB_PATH` 环境变量化 + 版本号统一） | 公开仓库可干净上线 |
| **P1** | `web/app.py` 工厂；`db.py` users 表 + owner/user 字段迁移；本地账号登录 | 能登录、空面板 |
| **P2** | 合同列表/详情/增删改/付款计划（按 owner 隔离）；导入导出 | 左栏全功能 |
| **P3** | 中栏表单 + 服务端 OCR 上传 + 生成 xlsx + 历史记录 | 中栏全功能 |
| **P4** | 右栏 HTML 预览模板 + 打印 + 下载 xlsx | 三栏打通 |
| **P5** | 管理员后台、用户管理、LDAP/AD 接入、备份 | 多用户就绪 |
| **P6** | 部署收尾、内网文档 | 上线 |
| **D（CI/CD）** | 新工作流 + Dockerfile + compose（可插在 P1 后任意时点） | 双产物流水线 |

**推荐顺序**：A → P1 → P2 → P3 → P4 → D → P5 → P6

---

## 10. 附录：完整文件变更清单

### 10.1 修改

- `pyproject.toml`、`uv.lock`（包名 + 版本）
- `main.py`（品牌名 + 版本读取）
- `db.py`（品牌名 docstring + DB_PATH 环境变量化 + users 表迁移）
- `ocr.py`、`template_engine.py`、`contract_io.py`（品牌名 docstring）
- `README.md`（品牌名 + 改写为公开版 + 脱敏）
- `scripts/send_email.py`（品牌名）
- `.gitignore`（增 `data/`、`uploads/`、`*.tar.zst`）

### 10.2 重命名

- `WZBill.spec` → `BillHub.spec`（内容同步改）
- `.github/workflows/build-and-email.yml` → `build-release.yml`（整体重写）

### 10.3 新增

- `web/` 整个目录（app、config、auth、routes、templates、static）
- `utils.py`（公共函数）
- `run_web.py`（Web 启动入口）
- `Dockerfile.web`
- `requirements-web.txt`
- `docker-compose.yml`
- `.env.example`
- `deploy.md`

### 10.4 不动

- `build_exe.bat`（仅改品牌名引用）
- `requirements.txt`（桌面版继续用）
- `templates/审批表模板2026.xlsx` 等业务模板
- `scripts/send_email.py` 逻辑（仅改品牌名）
