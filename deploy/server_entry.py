#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组合麻将 — 服务器部署入口 (systemd: comb.service)

原环境是 Python + aiohttp 的占位应用; 本项目是 FastAPI + uvicorn,
这里保留 server.py 入口名, 通过 venv 启动真正的组合麻将服务。
端口/数据目录由 systemd 注入: PORT(默认8100) / CMJ_DATA_DIR(/home/ubuntu/comb/data)
"""
import asyncio
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
# 兼容两种布局: 部署后 app/server.py 与 branches/ 同级; 仓库里 deploy/server_entry.py 的父目录才有 branches/
for _cand in (BASE, os.path.dirname(BASE)):
    if os.path.isdir(os.path.join(_cand, "branches")):
        BASE = _cand
        break
sys.path.insert(0, BASE)

# 与本地启动器一致: Windows 用 Selector 事件循环避免 WebSocket 断开崩溃; Linux 无需特殊处理
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from branches.networking import server  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8100"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(server.app, host=host, port=port, log_level="info")
