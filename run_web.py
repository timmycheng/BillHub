#!/usr/bin/env python3
"""BillHub Web 版启动入口。

开发模式（默认）: python run_web.py            → http://127.0.0.1:5000 (debug)
生产模式:        set PORT=8000 && python run_web.py --prod  → waitress 0.0.0.0:8000
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import create_app

app = create_app()


if __name__ == '__main__':
    if '--prod' in sys.argv:
        from waitress import serve
        port = int(os.environ.get('PORT', 8000))
        print(f'BillHub Web 生产服务启动: http://0.0.0.0:{port}')
        serve(app, host='0.0.0.0', port=port)
    else:
        port = int(os.environ.get('PORT', 5000))
        print(f'BillHub Web 开发服务启动: http://127.0.0.1:{port} (debug)')
        app.run(host='127.0.0.1', port=port, debug=True)
