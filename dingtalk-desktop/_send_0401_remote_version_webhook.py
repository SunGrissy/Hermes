# -*- coding: utf-8 -*-
"""定时任务入口：与 _push_versions_webhook_at_dm 同一套渲染与发送（PLD/PM 行动项、DoD 降噪、pipelineDdls 等）。

默认只推版本名 0401；Webhook 取自 PM 中该版本的 progressNotifyWebhooks（与 digest_config.pm_system_url 同源）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from contextlib import contextmanager

_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNNING_LOCK = os.path.join(_DIR, ".send_0401_remote.running")
_COOLDOWN_FILE = os.path.join(_DIR, ".send_0401_remote.last_ok")
_DEFAULT_COOLDOWN_SEC = 3600


@contextmanager
def _running_exclusive():
    try:
        fd = os.open(_RUNNING_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        try:
            age = time.time() - os.path.getmtime(_RUNNING_LOCK)
            if age > 600:
                os.remove(_RUNNING_LOCK)
                fd = os.open(_RUNNING_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
            else:
                print("SKIP: another instance is running", flush=True)
                raise SystemExit(0)
        except FileExistsError:
            print("SKIP: another instance is running", flush=True)
            raise SystemExit(0)
        except OSError:
            print("SKIP: another instance is running", flush=True)
            raise SystemExit(0)
    try:
        yield
    finally:
        try:
            if os.path.isfile(_RUNNING_LOCK):
                os.remove(_RUNNING_LOCK)
        except OSError:
            pass


def _cooldown_remaining(force: bool) -> int:
    if force:
        return 0
    if not os.path.isfile(_COOLDOWN_FILE):
        return 0
    try:
        last = int(open(_COOLDOWN_FILE, "r", encoding="utf-8").read().strip() or "0")
    except Exception:
        return 0
    elapsed = int(time.time()) - last
    if elapsed < _DEFAULT_COOLDOWN_SEC:
        return _DEFAULT_COOLDOWN_SEC - elapsed
    return 0


def _mark_send_ok() -> None:
    try:
        with open(_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--version-name",
        default="0401",
        help="PM 版本名，传给 _push_versions_webhook_at_dm.py --only",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="忽略冷却（仍受单实例互斥保护）",
    )
    args = ap.parse_args()

    wait = _cooldown_remaining(args.force)
    if wait > 0:
        print(
            f"SKIP: cooldown active, next allowed in ~{wait}s (use --force to override)",
            flush=True,
        )
        raise SystemExit(0)

    v = (args.version_name or "0401").strip()
    if not v:
        print("ERROR: empty version name", flush=True)
        raise SystemExit(2)

    push_script = os.path.join(_DIR, "_push_versions_webhook_at_dm.py")
    if not os.path.isfile(push_script):
        print(f"ERROR: missing {push_script}", flush=True)
        raise SystemExit(3)

    with _running_exclusive():
        r = subprocess.run(
            [sys.executable, push_script, "--only", v],
            cwd=_DIR,
        )
        if r.returncode == 0:
            _mark_send_ok()
        raise SystemExit(r.returncode if r.returncode is not None else 1)


if __name__ == "__main__":
    main()
