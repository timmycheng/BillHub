#!/usr/bin/env python3
"""BillHub - 将构建产物分卷(7z)逐卷通过 SMTP 发送到指定邮箱。

只依赖 Python 标准库（smtplib + email.mime）。所有配置从环境变量读取，
由 GitHub Actions 注入，仓库内不含任何明文凭证。

环境变量：
    SMTP_HOST     SMTP 服务器（QQ: smtp.qq.com）
    SMTP_PORT     端口（QQ: 465, SSL）
    SMTP_USER     发件邮箱完整地址（QQ 要求与登录账号一致）
    SMTP_PASS     SMTP 授权码（QQ 邮箱设置里生成，非登录密码）
    MAIL_TO       收件人地址
    SPLIT_DIR     存放 7z 分卷的目录
    MAIL_SUBJECT  邮件主题前缀（可选，默认 "BillHub 构建产物"）
"""
import glob
import os
import smtplib
import sys
import time
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

# 统一 UTF-8 输出：GitHub Windows runner 默认 cp1252，直接打印中文会 UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

REQUIRED_ENV = ('SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS', 'MAIL_TO', 'SPLIT_DIR')


def load_config():
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise SystemExit(f'[ERROR] 缺少环境变量: {", ".join(missing)}')
    return {
        'host': os.environ['SMTP_HOST'],
        'port': int(os.environ['SMTP_PORT']),
        'user': os.environ['SMTP_USER'],
        'password': os.environ['SMTP_PASS'],
        'to': os.environ['MAIL_TO'],
        'split_dir': os.environ['SPLIT_DIR'],
        'subject_prefix': os.environ.get('MAIL_SUBJECT', 'BillHub 构建产物'),
    }


def collect_parts(split_dir):
    """收集 .7z.001/.002/... 分卷，按序号排序。"""
    parts = sorted(glob.glob(os.path.join(split_dir, '*.7z.*')))
    return parts


def send_part(cfg, path, index, total):
    filename = os.path.basename(path)

    msg = MIMEMultipart()
    msg['From'] = formataddr(('BillHub CI', cfg['user']))
    msg['To'] = cfg['to']
    msg['Subject'] = Header(f'{cfg["subject_prefix"]} - 第 {index}/{total} 卷 ({filename})', 'utf-8')

    body = (
        f'BillHub 构建产物分卷 第 {index}/{total} 卷\n'
        f'附件: {filename}\n\n'
        '请将全部卷收齐后，用 7-Zip 选中第一个文件 BillHub.7z.001 解压，即可合并得到 BillHub.exe。\n'
        '若任一卷缺失，请到 GitHub Actions 的 artifacts 中重新下载。'
    )
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    with open(path, 'rb') as fh:
        payload = fh.read()

    attachment = MIMEBase('application', 'octet-stream')
    attachment.set_payload(payload)
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', 'attachment', filename=('utf-8', '', filename))
    msg.attach(attachment)

    print(f'发送第 {index}/{total} 卷: {filename} ({len(payload) / 1024 / 1024:.1f} MB) ...')
    with smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=120) as server:
        server.login(cfg['user'], cfg['password'])
        server.sendmail(cfg['user'], [cfg['to']], msg.as_string())


def main():
    cfg = load_config()
    parts = collect_parts(cfg['split_dir'])
    if not parts:
        raise SystemExit(f'[ERROR] {cfg["split_dir"]} 下没有找到 .7z.* 分卷文件')

    total = len(parts)
    for i, path in enumerate(parts, 1):
        send_part(cfg, path, i, total)
        if i < total:
            # 间隔发送，规避 QQ 对批量大附件的风控
            time.sleep(10)

    print(f'完成，共发送 {total} 封邮件。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
