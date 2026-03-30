# -*- coding: utf-8 -*-
"""
脚本里拉起 dingtalk daemon 时，默认 **新开一个控制台窗口**，便于直接看 print 日志。

若必须无窗口（例如无人值守机器），设环境变量 DINGTALK_DAEMON_HEADLESS=1：
  则仍写 logs/daemon_console.log（与旧行为一致）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

_DINGTALK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_log_handles: list = []


def _headless() -> bool:
    return os.environ.get('DINGTALK_DAEMON_HEADLESS', '').strip().lower() in (
        '1', 'true', 'yes',
    )


def daemon_console_log_path() -> str:
    d = os.path.join(_DINGTALK_ROOT, 'logs')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'daemon_console.log')


def start_daemon_background(
    cwd: str | None = None,
    argv: list[str] | None = None,
    creationflags: int | None = None,
) -> subprocess.Popen:
    """
    启动 py daemon.py。默认 Windows 下 CREATE_NEW_CONSOLE，子进程自带可见终端。
    creationflags 非 None 时按调用方传入（高级用法）。
    """
    cwd = cwd or _DINGTALK_ROOT
    if argv is None:
        argv = [sys.executable or 'py', 'daemon.py']

    if creationflags is None:
        if sys.platform == 'win32':
            if _headless():
                creationflags = getattr(
                    subprocess, 'CREATE_NO_WINDOW', 0x08000000,
                )
            else:
                creationflags = getattr(
                    subprocess, 'CREATE_NEW_CONSOLE', 0x00000010,
                )
        else:
            creationflags = 0

    if _headless() and sys.platform == 'win32':
        path = daemon_console_log_path()
        f = open(path, 'a', encoding='utf-8', errors='replace')
        _log_handles.append(f)
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f.write('\n' + '=' * 72 + '\n[%s] spawn %s\n' % (ts, ' '.join(argv)))
        f.write('cwd=%s\n' % cwd)
        f.flush()
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=False,
        )

    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
