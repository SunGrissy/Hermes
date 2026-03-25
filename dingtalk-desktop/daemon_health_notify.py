# -*- coding: utf-8 -*-
"""
One-shot: check dingtalk-desktop daemon /health, restart if needed, notify via webhook.

Usage (in dingtalk-desktop):
    py daemon_health_notify.py
    py daemon_health_notify.py --dry-run          # no webhook, no restart (check only)
    py daemon_health_notify.py --no-restart       # check + notify, never restart
    py daemon_health_notify.py --no-webhook       # print markdown to stdout only (no POST)

Webhook: webhook_config.json key \"default\" (override with --webhook-key).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from lib.utils import get_webhook_url  # noqa: E402
from lib.daemon_spawn import start_daemon_background  # noqa: E402

_DAEMON_URL = os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200").rstrip("/")
_KEYWORD = "小秘书提醒"


def _http_get_json(url: str, timeout: float = 6.0) -> tuple[bool, dict | None, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return True, json.loads(raw), ""
    except urllib.error.HTTPError as e:
        return False, None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, None, str(e.reason or e)
    except Exception as e:
        return False, None, str(e)


def _post_shutdown(base: str) -> None:
    url = base + "/shutdown"
    try:
        req = urllib.request.Request(
            url, data=b"{}", method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _start_daemon_bg() -> None:
    """默认新开 cmd 窗口跑 daemon，便于看日志；无头模式见 lib/daemon_spawn 说明。"""
    start_daemon_background(cwd=_THIS_DIR)


def fetch_health() -> tuple[bool, dict | None, str]:
    ok, data, err = _http_get_json(_DAEMON_URL + "/health", timeout=8.0)
    return ok, data, err


def analyze_health(data: dict | None) -> tuple[bool, list[str]]:
    """Return (all_ok, human lines)。判定与查岗「大门」daemon_full 对齐，避免一条说红一条说绿。"""
    lines: list[str] = []
    if not data:
        lines.append("health: no JSON body")
        return False, lines
    daemon = data.get("daemon", "")
    frida = data.get("frida_attached")
    cef = data.get("cef_ready")
    dt_run = data.get("dingtalk_running")
    pid = data.get("pid", "?")
    lines.append(f"daemon={daemon} pid={pid}")
    lines.append(f"frida_attached={frida} cef_ready={cef} dingtalk_running={dt_run}")
    if "monitor_running" in data:
        lines.append(f"monitor_running={data.get('monitor_running')}")
    ok = (
        daemon == "running"
        and frida is True
        and cef is True
    )
    if not data.get("dingtalk_running"):
        ok = False
    if "monitor_running" in data and data.get("monitor_running") is False:
        ok = False
    return ok, lines


def restart_daemon() -> None:
    _post_shutdown(_DAEMON_URL)
    time.sleep(3)
    _start_daemon_bg()
    time.sleep(2)


def wait_healthy(max_wait: int = 55, interval: int = 3) -> tuple[bool, dict | None, str]:
    deadline = time.time() + max_wait
    last_err = ""
    while time.time() < deadline:
        ok, data, err = fetch_health()
        if ok and data:
            healthy, _ = analyze_health(data)
            if healthy:
                return True, data, ""
        last_err = err or "not healthy yet"
        time.sleep(interval)
    ok, data, err = fetch_health()
    if ok and data:
        healthy, _ = analyze_health(data)
        if healthy:
            return True, data, ""
    return False, data, last_err or err


def build_markdown(
    *,
    title_phase: str,
    lines: list[str],
    restarted: bool,
    healthy: bool,
) -> str:
    restart_note = "已执行重启 (shutdown + py daemon.py)。" if restarted else "未执行重启。"
    body = "\n".join(lines)
    fail_hint = ""
    if not healthy:
        fail_hint = (
            "\n> **请你看一眼本机日志**：Frida / CEF / 钉钉等仍异常时，请到 **daemon 新开的控制台窗口** 看实时报错；"
            "若以无头方式启动，请打开 `dingtalk-desktop` 目录下的 **daemon_stdout.txt**、**daemon_stderr.txt**。\n\n"
        )
    return (
        f"### {_KEYWORD} · 通道自检\n"
        f"**{title_phase}**\n\n"
        f"{restart_note}\n\n"
        f"```\n{body}\n```\n\n"
        f"endpoint: `{_DAEMON_URL}/health`\n"
        f"{fail_hint}"
        f"---\n###### ※ {_KEYWORD}"
    )


def send_default_webhook(webhook_url: str, text: str) -> tuple[bool, str]:
    if not webhook_url:
        return False, "empty webhook url"
    payload = json.dumps(
        {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{_KEYWORD} · 通道自检",
                "text": text,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read().decode("utf-8", errors="replace"))
        if out.get("errcode") == 0:
            return True, "ok"
        return False, str(out)
    except Exception as e:
        return False, str(e)


def main() -> int:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Daemon health check + optional restart + DingTalk notify")
    ap.add_argument("--dry-run", action="store_true", help="check only, no restart, no webhook")
    ap.add_argument("--no-restart", action="store_true", help="never restart daemon")
    ap.add_argument(
        "--no-webhook",
        action="store_true",
        help="do not POST DingTalk webhook; print final markdown to stdout only",
    )
    ap.add_argument("--webhook-key", default="default", help="webhook_config.json key (default: default)")
    args = ap.parse_args()

    webhook = get_webhook_url(args.webhook_key, "")
    restarted = False

    ok_h, data, err = fetch_health()
    healthy, detail_lines = analyze_health(data if ok_h else None)
    if not ok_h:
        detail_lines.insert(0, f"first fetch failed: {err}")

    if args.dry_run:
        print("[dry-run] would restart=%s notify=%s" % (not healthy and not args.no_restart, bool(webhook)))
        for ln in detail_lines:
            print(ln)
        return 0

    if not healthy and not args.no_restart:
        print("[action] restarting daemon...")
        restart_daemon()
        restarted = True
        healthy, data, wait_err = wait_healthy()
        if data:
            _, detail_lines = analyze_health(data)
        else:
            detail_lines = ["no health JSON after restart"]
        if wait_err:
            detail_lines.append("after restart: %s" % wait_err)
    elif not healthy and args.no_restart:
        detail_lines.append("(no-restart: skipped recovery)")

    title = "自检通过" if healthy else "自检未通过"
    md = build_markdown(
        title_phase=title, lines=detail_lines, restarted=restarted, healthy=healthy,
    )

    if args.no_webhook:
        print(md, flush=True)
        return 0 if healthy else 2

    if not webhook:
        print("[warn] no webhook for key=%s" % args.webhook_key)
        print(md)
        return 1 if not healthy else 0

    sent, serr = send_default_webhook(webhook, md)
    if sent:
        print("[notify] webhook OK")
    else:
        print("[notify] webhook FAIL: %s" % serr)
        print(md)

    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(main())
