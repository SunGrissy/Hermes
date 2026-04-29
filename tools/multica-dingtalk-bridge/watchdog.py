#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_bot.py 守护进程：崩溃自恢复。每 30 秒检查子进程存活，挂了等 5 秒后重启，每小时最多重试 3 次。"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# [AgentBridge Task] 2026-04-29 单实例常驻：启动前清理 + 文件锁，避免两组 watchdog/dispatch 抢 Stream

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "watchdog.log"
DISPATCH_BOT = SCRIPT_DIR / "dispatch_bot.py"
LOCK_PATH = SCRIPT_DIR / ".multica_bridge_watchdog.lock"
CHECK_INTERVAL = 30   # 秒
RESTART_DELAY = 5     # 秒
MAX_RETRIES_PER_HOUR = 3

# 单实例锁文件句柄：进程退出前保持打开，避免第二组 watchdog+dispatch 常驻
_LOCK_FH = None


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _acquire_singleton_lock() -> None:
    """同目录仅允许一个 watchdog；已存在则退出（避免双开 Stream / 双份 webhook）。"""
    global _LOCK_FH
    fh = None
    try:
        fh = open(LOCK_PATH, "a+b")
        fh.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass
        log("singleton lock not acquired; another bridge watchdog is already running; exiting")
        print(
            "multica bridge: another watchdog is already running for this directory.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    _LOCK_FH = fh
    try:
        _LOCK_FH.seek(0)
        _LOCK_FH.truncate()
        _LOCK_FH.write(str(os.getpid()).encode("ascii"))
        _LOCK_FH.flush()
    except OSError:
        pass


def start_dispatch() -> subprocess.Popen:
    """启动 dispatch_bot.py 子进程。"""
    log(f"Starting dispatch_bot.py...")
    # 不使用 stdout=PIPE：watchdog 不消费管道时，子进程日志写满会阻塞，导致派单/审查链路假死。
    proc = subprocess.Popen(
        [sys.executable, str(DISPATCH_BOT)],
        cwd=str(SCRIPT_DIR),
    )
    log(f"dispatch_bot.py started (pid={proc.pid})")
    return proc


class RetryLimiter:
    """滑动窗口重试限制：一小时内最多 N 次。"""

    def __init__(self, max_retries: int = MAX_RETRIES_PER_HOUR, window: timedelta = timedelta(hours=1)):
        self._max = max_retries
        self._window = window
        self._timestamps: list[datetime] = []

    def can_retry(self) -> bool:
        now = datetime.now()
        cutoff = now - self._window
        # 剪掉窗口外的记录
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.pop(0)
        return len(self._timestamps) < self._max

    def record_failure(self) -> None:
        self._timestamps.append(datetime.now())


def main() -> None:
    if not DISPATCH_BOT.is_file():
        log(f"ERROR: dispatch_bot.py not found at {DISPATCH_BOT}")
        sys.exit(1)

    _acquire_singleton_lock()

    log("=== Watchdog started ===")

    proc = start_dispatch()
    retry_limiter = RetryLimiter()

    while True:
        time.sleep(CHECK_INTERVAL)

        # 检查子进程是否存活
        poll = proc.poll()
        if poll is None:
            # 进程还在跑
            continue

        # 进程挂了
        exit_code = proc.returncode or poll
        log(f"dispatch_bot.py exited with code {exit_code}")

        if not retry_limiter.can_retry():
            log("Hit hourly retry limit (3). Watchdog will not restart. Exiting.")
            sys.exit(1)

        retry_limiter.record_failure()
        log(f"Waiting {RESTART_DELAY}s before restart...")
        time.sleep(RESTART_DELAY)
        proc = start_dispatch()


if __name__ == "__main__":
    main()
