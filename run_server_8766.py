# -*- coding: utf-8 -*-
"""启动包装器：用 WindowsSelectorEventLoopPolicy 运行 branches/networking/server.py，
避免 Proactor 事件循环在 WebSocket 断开时的已知崩溃问题。
不改动 server.py 本身。
(注意: 必须导入 branches/networking/server.py —— 根目录旧版 server.py 无冒险模式路由)"""
import asyncio
import sys
import os

if sys.platform == 'win32':
    # Selector loop avoids the Proactor _call_connection_lost crash on
    # client WebSocket disconnect.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Import and run the actual server module from this directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from branches.networking import server  # noqa: E402

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(server.app, host='0.0.0.0', port=8766)
