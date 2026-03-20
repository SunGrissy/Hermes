# -*- coding: utf-8 -*-
"""
Detached helper: shutdown dingtalk daemon -> start py daemon.py -> POST webhook when healthy.
Spawned with DETACHED_PROCESS from desk_ops so parent daemon can exit safely.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from daemon_health_notify import (  # noqa: E402
    _DAEMON_URL,
    _post_shutdown,
    _start_daemon_bg,
    analyze_health,
    fetch_health,
    wait_healthy,
)

_KEYWORD = "小秘书提醒"


def _send_md(webhook_url: str, title: str, text: str) -> None:
    if not (webhook_url or "").strip():
        return
    payload = json.dumps(
        {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook_url.strip(),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            out = json.loads(resp.read().decode("utf-8", errors="replace"))
        if out.get("errcode") != 0:
            print("[desk_ops_restart] webhook err:", out, flush=True)
    except (urllib.error.URLError, OSError) as e:
        print("[desk_ops_restart] webhook fail:", e, flush=True)


def main() -> int:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--webhook", default="", help="memo_tracker webhook URL for completion notify")
    args = ap.parse_args()

    time.sleep(2)
    print("[desk_ops_restart] shutdown", flush=True)
    _post_shutdown(_DAEMON_URL)
    time.sleep(3)
    print("[desk_ops_restart] start daemon.py", flush=True)
    _start_daemon_bg()
    time.sleep(2)

    ok, data, err = wait_healthy(max_wait=60, interval=3)
    healthy, lines = analyze_health(data if ok and data else None)
    body = "\n".join(lines) if lines else (err or "no health")
    title = f"{_KEYWORD} · 运维"
    if healthy and ok:
        md = (
            f"### {title}\n"
            f"**执行完成：重启大门**\n\n"
            f"daemon 已恢复 healthy。\n\n"
            f"```\n{body}\n```\n\n"
            f"---\n###### ※ {_KEYWORD}"
        )
    else:
        md = (
            f"### {title}\n"
            f"**执行完成：重启大门（异常）**\n\n"
            f"请人工检查 `py daemon.py` 与 Frida。\n\n"
            f"```\n{body}\n```\n\n"
            f"---\n###### ※ {_KEYWORD}"
        )
    _send_md(args.webhook, title, md)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
