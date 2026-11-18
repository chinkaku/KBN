#!/usr/bin/env bash
# 组合麻将 — 服务器部署脚本（在服务器上运行）
# 用法: bash deploy.sh [代码包目录，默认 /tmp/comb_deploy]
# 只操作 /home/ubuntu/comb/** 与 comb.service 自身；不碰 /home/ubuntu/sp、不占其它端口。
set -euo pipefail

APP=/home/ubuntu/comb/app
DATA=/home/ubuntu/comb/data
LOGS=/home/ubuntu/comb/logs
VENV=/home/ubuntu/venv
PKG=${1:-/tmp/comb_deploy}

echo "== 0) 目录准备 =="
mkdir -p "$APP" "$DATA" "$LOGS"

echo "== 1) 依赖 =="
"$VENV/bin/pip" install -q --upgrade fastapi uvicorn

echo "== 2) 部署代码（保留 data/） =="
# 仅替换 app/ 下的游戏代码与静态资源；data/ 与 logs/ 不动
rm -rf "$APP/branches" "$APP/static" "$APP/story" "$APP/game_engine.py"
cp -r "$PKG/game_engine.py" "$PKG/branches" "$PKG/static" "$PKG/story" "$APP/"
cp "$PKG/deploy/server_entry.py" "$APP/server.py"
# 代码包里的说明文档放一份到 comb/ 下备查（可选）
cp -f "$PKG/RULES_GAP.md" "$PKG/dev_notes.md" /home/ubuntu/comb/ 2>/dev/null || true

echo "== 3) systemd 单元 =="
sudo cp "$PKG/deploy/comb.service" /etc/systemd/system/comb.service
sudo systemctl daemon-reload
sudo systemctl enable comb.service >/dev/null 2>&1 || true
sudo systemctl restart comb.service

echo "== 4) 健康检查 =="
sleep 3
echo -n "GET /api/health → "
curl -s -m 5 http://localhost:8100/api/health || echo "(无响应)"
echo
systemctl status comb.service --no-pager -l | head -n 15
echo
echo "== 5) 外网自检（从服务器本机访问公网地址） =="
curl -s -m 5 -o /dev/null -w "http://49.233.87.144:8100/ → %{http_code}\n" http://49.233.87.144:8100/ || true
