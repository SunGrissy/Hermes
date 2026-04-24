# -*- coding: utf-8 -*-
"""
Detached helper: shutdown dingtalk daemon -> start py daemon.py -> optionally notify via webhook.
Usage: python restart_daemon.py [--webhook <url>]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

_DAEMON_PORT = int(os.environ.get('DINGTALK_DAEMON_PORT', '19200'))
_HEALTH_URL = f'http://127.0.0.1:{_DAEMON_PORT}/health'
_SHUTDOWN_URL = f'http://127.0.0.1:{_DAEMON_PORT}/shutdown'
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _log(msg: str):
    ts = time.strftime('%H:%M:%S')
    print(f'[restart_daemon][{ts}] {msg}', flush=True)


def _http_json(url: str, timeout: int = 5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def _post_json(url: str, payload: dict, timeout: int = 8) -> bool:
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        _log(f'webhook failed: {e}')
        return False


def _get_daemon_pid() -> int | None:
    data = _http_json(_HEALTH_URL, timeout=5)
    if data and data.get('daemon') == 'running':
        return data.get('pid')
    return None


def _shutdown_daemon(timeout: int = 3) -> bool:
    try:
        req = urllib.request.Request(_SHUTDOWN_URL, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        _log(f'shutdown request failed: {e}')
        return False


def _kill_pid(pid: int) -> bool:
    try:
        _log(f'killing PID {pid}')
        subprocess.run(
            ['taskkill', '/F', '/PID', str(pid)],
            capture_output=True, check=False,
        )
        return True
    except Exception as e:
        _log(f'kill failed: {e}')
        return False


def _start_daemon():
    """启动新的 daemon.py（新开控制台窗口）。"""
    creationflags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x00000010)
    subprocess.Popen(
        ['py', '-u', 'daemon.py'],
        cwd=_PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    _log('started daemon.py in new console window')


def _send_webhook(webhook_url: str, title: str, text: str):
    if not webhook_url:
        return
    payload = {
        'msgtype': 'markdown',
        'markdown': {'title': title, 'text': text},
    }
    _post_json(webhook_url, payload)


def main():
    ap = argparse.ArgumentParser(description='Restart dingtalk-desktop daemon')
    ap.add_argument('--webhook', default='', help='DingTalk webhook URL for notification')
    args = ap.parse_args()
    webhook = args.webhook.strip()

    _log('restart sequence started')
    old_pid = _get_daemon_pid()
    if old_pid:
        _log(f'old daemon PID: {old_pid}')

    # 1) 尝试优雅关闭
    if old_pid:
        _log('attempting graceful shutdown')
        _shutdown_daemon()
        time.sleep(3)

    # 2) 强制杀掉
    if _get_daemon_pid():
        _log('daemon still alive, forcing kill')
        if old_pid:
            _kill_pid(old_pid)
        else:
            # fallback: 杀掉占用端口的进程
            _log('no PID known, falling back to netscan')
            try:
                result = subprocess.run(
                    ['cmd', '/c', f'netstat -ano | findstr :{_DAEMON_PORT}'],
                    capture_output=True, text=True, check=False,
                )
                for line in result.stdout.splitlines():
                    if 'LISTENING' in line:
                        parts = line.split()
                        if parts:
                            try:
                                pid = int(parts[-1])
                                _kill_pid(pid)
                                break
                            except ValueError:
                                continue
            except Exception as e:
                _log(f'fallback kill failed: {e}')
        time.sleep(2)

    # 3) 启动新进程
    _start_daemon()

    # 4) 等待并确认健康（每 500ms 检查一次，最多 30 秒）
    _log('waiting for daemon to become healthy...')
    healthy = False
    new_pid = None
    for _ in range(60):
        time.sleep(0.5)
        new_pid = _get_daemon_pid()
        if new_pid and new_pid != old_pid:
            healthy = True
            break

    if healthy:
        _log(f'daemon is healthy, new PID: {new_pid}')
        if webhook:
            _send_webhook(
                webhook,
                '大门已打开',
                f'**大门已打开** ✅\n\n旧 PID `{old_pid or "?"}` 已关闭，新 PID `{new_pid}` 已启动。',
            )
        return 0
    else:
        _log('daemon health check timeout')
        if webhook:
            _send_webhook(
                webhook,
                '开门异常',
                f'**开门异常** ❌\n\n重启超时，请手动检查 daemon 状态。',
            )
        return 1


if __name__ == '__main__':
    sys.exit(main())
