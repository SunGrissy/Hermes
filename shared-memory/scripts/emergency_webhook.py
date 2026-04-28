#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emergency_webhook.py — 双挂兜底脚本

独立于任何 Agent，作为一个 Windows 计划任务每 1 分钟运行。
检测 小马(18790) 和 满满(Hermes PID) 是否存活。
如果双方都挂了 → 通过 webhook 发群消息通知老大。

被 watchdog 注册为系统级计划任务，不依赖 Agent 存活。

usage:
    py D:\MyAgents\shared-memory\scripts\emergency_webhook.py
"""

import json
import os
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime

WEBHOOK_URL = os.environ.get(
    "XIAOMA_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=6186943b087de1151578462c166e18cbf7d9509180c0d65beb05aa929ab998c2",
)
LOG_FILE = "D:\\OpenClaw2\\workspace\\logs\\emergency_webhook.log"


def log(msg):
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def tcp_check(host, port, timeout=3):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def check_hermes_alive():
    """检查 Hermes 满满是否活着（通过 gateway_state.json + 进程表）"""
    state_file = "D:\\hermes\\gateway_state.json"
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid")
        if not pid:
            return False
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        )
        return str(pid) in out.stdout
    except Exception:
        return False


def send_webhook(text):
    body = {"msgtype": "text", "text": {"content": text}}
    try:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            WEBHOOK_URL, data=raw,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        return False


def main():
    from pathlib import Path

    xiaoma_alive = tcp_check("127.0.0.1", 18790)
    manman_alive = check_hermes_alive()

    if xiaoma_alive and manman_alive:
        # 都活着，无事
        return 0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not xiaoma_alive and not manman_alive:
        msg = (
            f"【小马自动报告】我和满满都挂了。\n\n"
            f"时间: {ts}\n"
            f"小马(18790): DOWN\n"
            f"满满(Hermes): DOWN\n\n"
            f"老大，帮一把:\n"
            f"1. CMD 跑这两行:\n"
            f"   D:\\OpenClaw2\\gateway.cmd\n"
            f"   D:\\OpenClaw\\scripts\\start_manman.bat\n"
            f"2. 或者远程桌面连上来看看\n"
            f"3. 端口通但服务不活的话可能防火墙/进程被杀了"
        )
        ok = send_webhook(msg)
        log(f"[CRIT] 双挂: 小马={xiaoma_alive} 满满={manman_alive} 通知={'成功' if ok else '失败'}")
        return 1 if ok else 2

    # 单挂不触发紧急通知（由巡检脚本处理）
    log(f"[INFO] 单挂: 小马={xiaoma_alive} 满满={manman_alive} 不触发紧急通知")
    return 0


if __name__ == "__main__":
    sys.exit(main())
