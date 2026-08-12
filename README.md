# BillHub

发票 / 审批 / 报销一体化处理工具。合同管理 + 智能报销生成 + OCR 识别 + 模板驱动。

支持两种形态：
- **桌面版**（PyQt6 + RapidOCR + PyInstaller 打包为 Windows exe）
- **Web 版**（Flask + Jinja2，内网多人共享，Docker 部署）—— 规划中，见 [改造方案](./BillHub-改造方案.md)

## 本地开发（桌面版）

```bash
uv sync            # 或 pip install -r requirements.txt
python main.py     # 启动桌面应用
```

## 打包桌面 exe

```bash
build_exe.bat      # 自动安装依赖、拷贝 OCR 模型并执行 PyInstaller
```

产物：`dist/BillHub.exe`（onefile，windowed）。`models/` 与运行数据（`bill.db`、发票）不入库。

## 数据存储

完全离线运行，数据存储于本地 SQLite（`bill.db`）。可通过环境变量 `BILLHUB_DB` 指定数据库路径（Web 版 / Docker 部署用）。

## CI/CD

push 到 `main`（或手动触发）时自动构建并发布：

- **桌面版**：在 `windows-latest` 上 PyInstaller 打包 `BillHub.exe`
- **Web 版镜像**：在 `ubuntu-latest` 构建 Docker 镜像并导出为 tar（供离线内网 `docker load`）

详细设计见 [BillHub-改造方案.md](./BillHub-改造方案.md)。

> 邮件分发功能目前暂停，相关脚本保留在 `scripts/` 下，待稳定后恢复。
