# WZBill

发票 / 审批 / 报销一体化处理工具（PyQt6 + RapidOCR + PyInstaller 打包为 Windows exe）。

## 本地开发

```bash
uv sync            # 或 pip install -r requirements.txt
python main.py     # 启动应用
```

## 打包 exe

```bash
build_exe.bat      # 自动安装依赖、拷贝 OCR 模型并执行 PyInstaller
```

产物：`dist/WZBill.exe`（onefile，windowed）。`models/` 与运行数据（`bill.db`、发票）不入库。

## CI/CD：push 后自动打包并邮件分发

`.github/workflows/build-and-email.yml` 在 push 到 `main`（或手动触发）时执行：

1. 在 `windows-latest` 上安装依赖、拷贝 OCR 模型、`pyinstaller WZBill.spec` 打包
2. 用 7-Zip 把 exe 分卷压成 ≤30MB 的 `WZBill.7z.001/.002/…`
3. 分卷同时上传到 GitHub Actions artifacts（备份）
4. `scripts/send_email.py` 把每个分卷单独发一封邮件到 `12305@wzbank.cn`

### 首次使用需配置 GitHub Secrets

仓库 `Settings → Secrets and variables → Actions` 添加：

| Secret | 值 |
|---|---|
| `SMTP_USER` | 发件 QQ 邮箱完整地址（如 `xxx@qq.com`） |
| `SMTP_PASS` | QQ 邮箱**授权码**（`设置→账户→POP3/SMTP 服务` 生成，非登录密码） |

收件人 `12305@wzbank.cn` 固定在 workflow 中，如需修改只改 `build-and-email.yml` 里的 `MAIL_TO`。

### 收件人如何解压分卷

收齐全部卷（`.001`、`.002`、…）后，用 7-Zip 选中 `WZBill.7z.001` → 解压，自动合并出 `WZBill.exe`。
