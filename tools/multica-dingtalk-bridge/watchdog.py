#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_bot.py 守护进程：崩溃自恢复。每 30 秒检查子进程存活，挂了等 5 秒后重启，每小时最多重试 3 次。"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "watchdog.log"
DISPATCH_BOT = SCRIPT_DIR / "dispatch_bot.py"
CHECK_INTERVAL = 30   # 秒
RESTART_DELAY = 5     # 秒
MAX_RETRIES_PER_HOUR = 3


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def start_dispatch() -> subprocess.Popen:
    """启动 dispatch_bot.py 子进程。"""
    log(f"Starting dispatch_bot.py...")
    proc = subprocess.Popen(
        [sys.executable, str(DISPATCH_BOT)],
        cwd=str(SCRIPT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
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
