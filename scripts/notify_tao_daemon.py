# -*- coding: utf-8 -*-
"""
在 Cursor 里说「请涛哥更新 / 让涛哥更新」时由 Agent 调用：直接 POST daemon /send 私聊杨玉涛，
不经过助理群、不解析群内 tao-update-scope（与 dingtalk-desktop 群内口令分流）。

用法：
  py scripts/notify_tao_daemon.py [子模块名]
  未传参时从环境变量 TAO_UPDATE_SCOPE 读取；仍为空则尝试根据 git status 推断。

环境变量：
  DINGTALK_DAEMON_URL  默认 http://127.0.0.1:19200
  TAO_RECIPIENT_NAME   默认 杨玉涛
  TAO_RECIPIENT_CID    若设置则优先用 cid，不再按姓名解析
  DINGTALK_SEND_TIMEOUT_S  POST /send 等待秒数，默认 120（原 25 易超时误报失败）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

_DEFAULT_RESTART = frozenset(
    x.strip().lower()
    for x in (
        "pm-system",
        "performeval",
        "task_reminder",
        "dingtalk-desktop",
        "cci_system",
        "cci-scoresystem",
    )
    if x.strip()
)


def _workspace_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, ".."))


def _infer_scope_from_git(root: str) -> str:
    try:
        p = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if p.returncode != 0 or not (p.stdout or "").strip():
        return ""
    known = (
        "pm-system",
        "performeval",
        "task_reminder",
        "dingtalk-desktop",
        "md-reader",
        "cci_system",
        "palace",
        "novel",
    )
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("??"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        path = parts[-1].replace("\\", "/").strip().strip('"')
        top = path.split("/")[0].lower()
        for k in known:
            if top == k.lower() or path.lower().startswith(k.lower() + "/"):
                return k
    return ""


def _scope_tail(scope: str) -> str:
    s = (scope or "").replace("\\", "/").strip().strip("/")
    return s.split("/")[-1].lower() if s else ""


def _build_message(scope: str) -> str:
    tail = _scope_tail(scope)
    line = f"涛哥，{scope}求更新~"
    if tail and tail in _DEFAULT_RESTART:
        line += "需要重启"
    # 方括号尾标在钉钉里可能被解析为表情显示，预期行为；勿用裸 emoji（JS 注入易乱码）。
    line += " [忙疯了]"
    return line


def _send_timeout_s() -> int:
    try:
        t = int(float(os.environ.get("DINGTALK_SEND_TIMEOUT_S", "") or 120))
    except (TypeError, ValueError):
        t = 120
    return max(30, min(t, 300))


def _post_send(daemon: str, body: dict) -> tuple[bool, str]:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        daemon.rstrip("/") + "/send",
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_send_timeout_s()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("error"):
            return False, str(data.get("error"))
        return True, json.dumps(data, ensure_ascii=False)
    except urllib.error.HTTPError as e:
        try:
            return False, e.read().decode("utf-8", errors="replace")
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, str(e)


def main() -> int:
    root = _workspace_root()
    scope = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not scope:
        scope = os.environ.get("TAO_UPDATE_SCOPE", "").strip()
    if not scope:
        scope = _infer_scope_from_git(root)
    if not scope:
        print(
            "error: 无法确定子模块名。请传参: py scripts/notify_tao_daemon.py pm-system\n"
            "或设置环境变量 TAO_UPDATE_SCOPE",
            file=sys.stderr,
        )
        return 1

    daemon = os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200").strip()
    cid = os.environ.get("TAO_RECIPIENT_CID", "").strip()
    name = os.environ.get("TAO_RECIPIENT_NAME", "杨玉涛").strip() or "杨玉涛"
    msg = _build_message(scope)

    if cid:
        body = {"cid": cid, "message": msg}
    else:
        body = {"name": name, "message": msg}

    ok, detail = _post_send(daemon, body)
    if ok:
        # Windows 控制台默认 GBK，避免 print 正文含 emoji 崩溃；私聊正文仍含机器人尾标
        print("sent_ok scope=%s recipient=%s" % (scope, "cid" if cid else name))
        return 0
    print("error:", detail, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
