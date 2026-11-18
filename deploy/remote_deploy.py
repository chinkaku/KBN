# -*- coding: utf-8 -*-
"""组合麻将 — 远程部署驱动（paramiko，密码认证，密码从 agent.md 读取，不落盘）

用法:
  python deploy/remote_deploy.py precheck   # 只查看服务器环境(不改动)
  python deploy/remote_deploy.py deploy     # 上传代码包并部署
"""
import os
import re
import sys
import time

import paramiko

HOST = "49.233.87.144"
USER = "ubuntu"
PORT = 22
AGENT_MD = r"Q:\mmcrdlc\agent.md"
PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comb_deploy.tar.gz")
REMOTE_PKG = "/tmp/comb_deploy.tar.gz"
REMOTE_DIR = "/tmp/comb_deploy"


def read_password():
    with open(AGENT_MD, encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"#\s*密码[：:]\s*(\S+)", txt)
    if not m:
        sys.exit("在 agent.md 中没找到密码")
    return m.group(1)


def connect():
    pwd = read_password()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=PORT, username=USER, password=pwd, timeout=15, banner_timeout=15)
    return cli


def run(cli, cmd, timeout=180, check=True, quiet=False):
    _in, out, err = cli.exec_command(cmd, timeout=timeout, get_pty=False)
    code = out.channel.recv_exit_status()
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    if not quiet:
        print(f"$ {cmd}")
        if o.strip():
            print(o.rstrip())
        if e.strip():
            print("[stderr]", e.rstrip())
    if check and code != 0:
        raise SystemExit(f"命令失败({code}): {cmd}")
    return code, o, e


def precheck(cli):
    print("========== 服务器环境检查（只读） ==========")
    run(cli, "hostname; whoami; uname -r")
    run(cli, "echo '--- comb 目录 ---'; ls -la /home/ubuntu/comb/ 2>&1 | head -20")
    run(cli, "echo '--- app 目录 ---'; ls -la /home/ubuntu/comb/app/ 2>&1 | head -30")
    run(cli, "echo '--- comb.service ---'; systemctl cat comb.service 2>&1 | head -40")
    run(cli, "echo '--- 服务状态 ---'; systemctl is-active comb.service; systemctl status comb.service --no-pager 2>&1 | head -20")
    run(cli, "echo '--- 8100 监听 ---'; ss -ltnp 2>/dev/null | grep ':8100' || echo 'no listener on 8100'")
    run(cli, "echo '--- health ---'; curl -s -m 5 localhost:8100/api/health || echo '(no response)'")
    run(cli, "echo '--- venv ---'; /home/ubuntu/venv/bin/python -V; /home/ubuntu/venv/bin/pip list 2>/dev/null | grep -Ei 'fastapi|uvicorn|aiohttp' || echo '(no fastapi/uvicorn/aiohttp)'")
    run(cli, "echo '--- sudo 免密? ---'; sudo -n true && echo 'SUDO_NOPASSWD_OK' || echo 'SUDO_NEEDS_PASSWORD'")
    run(cli, "echo '--- 内存/磁盘 ---'; free -m | head -3; df -h / | tail -1")
    run(cli, "echo '--- 其它业务进程(概览, 不触碰) ---'; ps aux | grep -E 'ppo_eff_srv|eval_multi|python' | grep -v grep | head -10")


def deploy(cli):
    print("========== 部署 ==========")
    print("1) 安装依赖到 venv（fastapi/uvicorn）")
    run(cli, "/home/ubuntu/venv/bin/pip install -q --upgrade fastapi uvicorn", timeout=600)
    run(cli, "/home/ubuntu/venv/bin/pip list 2>/dev/null | grep -Ei 'fastapi|uvicorn' || echo 'MISSING'")

    print(f"2) 上传 {PKG} → {REMOTE_PKG}")
    sftp = cli.open_sftp()
    sftp.put(PKG, REMOTE_PKG)
    st = sftp.stat(REMOTE_PKG)
    print(f"   远端文件大小: {st.st_size} bytes")
    sftp.close()

    print("3) 解包 + 运行部署脚本")
    run(cli, f"rm -rf {REMOTE_DIR} && mkdir -p {REMOTE_DIR} && tar -xzf {REMOTE_PKG} -C {REMOTE_DIR} && ls {REMOTE_DIR} | head -20")
    run(cli, f"bash {REMOTE_DIR}/deploy/deploy.sh {REMOTE_DIR}", timeout=300)

    print("========== 验收 ==========")
    run(cli, "sleep 3; curl -s -m 5 localhost:8100/api/health; echo")
    run(cli, "systemctl is-active comb.service; systemctl status comb.service --no-pager 2>&1 | head -14")
    run(cli, "curl -s -m 5 -o /dev/null -w '首页 http://127.0.0.1:8100/ → %{http_code}\\n' http://127.0.0.1:8100/")
    run(cli, "curl -s -m 5 -o /dev/null -w '公网 http://49.233.87.144:8100/ → %{http_code}\\n' http://49.233.87.144:8100/")
    run(cli, "curl -s -m 5 http://127.0.0.1:8100/api/v1/lobby/sessions | head -c 200; echo")
    run(cli, "echo '--- data 目录 ---'; du -sh /home/ubuntu/comb/data; ls -la /home/ubuntu/comb/data")
    run(cli, "echo '--- 日志尾部 ---'; tail -n 12 /home/ubuntu/comb/logs/app.log")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "precheck"
    cli = connect()
    try:
        if mode == "precheck":
            precheck(cli)
        elif mode == "deploy":
            deploy(cli)
        else:
            sys.exit("用法: precheck | deploy")
    finally:
        cli.close()


if __name__ == "__main__":
    main()
