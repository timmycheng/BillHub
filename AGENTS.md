# AGENTS.md — BillHub 开发约定（所有 code agent 必须遵守）

## 项目概况

- BillHub：合同 / 发票 / 审批 / 报销一体化处理平台，自 2.0 起完全 Web 化（Flask + Jinja2 + HTMX），桌面版（PyQt6）已下线
- 入口 `run_web.py`；应用工厂 `web/app.py`；蓝图 `web/routes/`；模板 `web/templates/`；静态 `web/static/`
- 数据层 `db.py`（SQLite，WAL）；新增列用 `_NEW_COLUMNS` 增量迁移，必须兼容旧库；共享逻辑 `utils.py` / `ocr.py` / `template_engine.py` / `contract_io.py`
- 本地审批表模板 `templates/*.xlsx` 与示例合同不入库（.gitignore 已忽略）

## 变更日志规则（Keep a Changelog，强制）

- **任何行为变化（新增/变更/修复/移除）都必须在 `CHANGELOG.md` 顶部 `## [Unreleased]` 的对应小节追加一条，与代码同一提交**
- 禁止直接编辑已发布版本的小节；禁止在本地手动 bump `pyproject.toml` 版本号或打 git tag
- 纯文档 / 注释 / 无行为变化的杂项改动可不写条目

## 发版流程（交给 CI，禁止手动发版）

- 发版统一走 GitHub Actions「Build & Release」→ **Run workflow** 填版本号（如 2.0.3），CI 自动：bump 版本 → `[Unreleased]` 转正为版本小节 → 提交推送 → 构建 Docker 镜像 → 发布 Release（Notes 取 CHANGELOG）→ 邮件分卷分发
- 兜底（仅 CI 不可用时）：本地改好 pyproject + CHANGELOG 后 `git tag vX.Y.Z && git push origin vX.Y.Z`
- 邮件 SMTP 配置与收件地址（MAIL_TO）均在 GitHub Secrets，仓库内禁止出现明文

## 测试约定

- 改动后必须跑冒烟测试（Flask `test_client` 覆盖登录 / 合同 / 附件 / 报销 / 状态流转 / OCR / 分页 / 迁移兼容），全部 PASS 才能提交
- 冒烟脚本位于 `test/smoke_test.py`（`python test/smoke_test.py`），用临时 `BILLHUB_DB` / `BILLHUB_UPLOAD_DIR`，不得动真实 `bill.db`；依赖外部文件的部分（审批表模板、示例合同 PDF）有 SKIP 兜底
- 另有辅助脚本：`test/test_contract_ocr.py`（示例合同识别探查）、`test/test_release_prep.py`（发版 prep 逻辑测试）

## 其他约定

- 界面文案与 CHANGELOG 用中文；提交信息简洁说明行为变化（CI/发版类用 `ci:` / `chore:` 前缀）
- 不提交任何密钥 / 令牌 / 收件地址，敏感配置走环境变量或 GitHub Secrets
- `issue.md` 中的任务完成后勾选 `[x]` 并随对应提交一起更新
