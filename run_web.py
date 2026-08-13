#!/usr/bin/env python3
"""BillHub Web 版启动入口。

开发模式（默认）: python run_web.py            → http://127.0.0.1:5000 (debug)
生产模式:        set PORT=8000 && python run_web.py --prod  → waitress 0.0.0.0:8000

注意：开发模式每个实例含 2 个进程（热重载器 + 服务进程）。
端口被占用时会直接提示退出，不会陷入重复启动的空转循环。
"""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import create_app

app = create_app()


def _port_in_use(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _ensure_port_free(host, port):
    # 热重载子进程跳过检查（Werkzeug 会给子进程设 WERKZEUG_RUN_MAIN=true）：
    # 重载瞬间端口可能仍被旧子进程短暂持有，检查会误报导致重启死循环
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        return
    if not _port_in_use(host, port):
        return
    print(f'[ERROR] 端口 {port} 已被占用：可能已有一个 BillHub 服务在运行。')
    print(f'        已有服务直接访问 http://{host}:{port} 即可，无需重复启动。')
    print('        如需重启，请先关闭旧实例（旧终端 Ctrl+C，或任务管理器结束 python 进程）。')
    sys.exit(1)


if __name__ == '__main__':
    if '--prod' in sys.argv:
        from waitress import serve
        port = int(os.environ.get('PORT', 8000))
        _ensure_port_free('0.0.0.0', port)
        print(f'BillHub Web 生产服务启动: http://0.0.0.0:{port}')
        serve(app, host='0.0.0.0', port=port)
    else:
        port = int(os.environ.get('PORT', 5000))
        _ensure_port_free('127.0.0.1', port)
        print(f'BillHub Web 开发服务启动: http://127.0.0.1:{port} (debug)')
        app.run(host='127.0.0.1', port=port, debug=True)
