# -*- coding: utf-8 -*-
"""重启大门 -> 抓取指定钉钉文档 -> 将结果摘要经 Webhook 推到助理通知（webhook default）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_WS = os.path.abspath(os.path.join(_ROOT, ".."))

from lib.daemon_spawn import start_daemon_background  # noqa: E402
_SEND = os.path.join(
    _WS, ".cursor", "skills", "cursor-to-dingtalk", "scripts", "send_result_webhook.py"
)

DOC_URL = (
    "https://alidocs.dingtalk.com/i/nodes/QG53mjyd80R7N00AtlBlRaNnV6zbX04v"
    "?corpId=ding37c967956637d20d"
)


def _wait_daemon_ready(max_wait: int = 120) -> tuple[bool, str]:
    deadline = time.time() + max_wait
    last = ""
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:19200/health", method="GET"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data.get("daemon") == "running":
                return True, json.dumps(data, ensure_ascii=False)[:500]
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            last = str(e)
        time.sleep(2)
    return False, last or "timeout"


def _fetch_doc() -> dict:
    body = json.dumps({"url": DOC_URL, "wait_extra": 20}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:19200/fetch_report_content",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    os.chdir(_ROOT)
    ex = sys.executable or "py"

    print("[1] kill_old_daemon", flush=True)
    subprocess.run([ex, os.path.join(_ROOT, "kill_old_daemon.py")], cwd=_ROOT)

    time.sleep(2)
    print("[2] start daemon.py（将新开控制台窗口，便于看日志）", flush=True)
    start_daemon_background(cwd=_ROOT, argv=[ex, "daemon.py"])

    ok, detail = _wait_daemon_ready(120)
    print("[3] health:", ok, detail[:200] if detail else "", flush=True)
    if ok:
        # 刚 attach 完立即 open 文档时，CEF/beacon 偶发拿不到 rpt_meta；稍等再抓
        time.sleep(15)
    if not ok:
        md = (
            "### AgentPalace-文档抓取\n\n"
            "**本会话代号：AgentPalace**\n\n"
            "**daemon 未就绪**（120s 内 /health 不可用）\n\n"
            f"```\n{detail}\n```\n"
        )
    else:
        try:
            d = _fetch_doc()
            c = (d.get("content") or "").strip()
            le = d.get("text_length") or len(c)
            meth = d.get("extraction_method") or "?"
            succ = d.get("success")
            err = d.get("error") or ""
            has_m = "\u6210\u529f\u6307\u6807" in c
            has_n = "\u5317\u6781\u661f" in c
            preview = c[-600:] if len(c) > 600 else c
            md = (
                "### AgentPalace-文档抓取\n\n"
                "**本会话代号：AgentPalace**\n\n"
                f"- **fetch_success**: {succ}\n"
                f"- **error**: {err or '(none)'}\n"
                f"- **text_length**: {le}\n"
                f"- **extraction_method**: {meth}\n"
                f"- **content 含「成功指标」**: {has_m}\n"
                f"- **content 含「北极星」**: {has_n}\n\n"
                "**正文尾部预览**（最多600字）\n\n"
                f"```\n{preview}\n```\n"
            )
        except Exception as e:
            md = (
                "### AgentPalace-文档抓取\n\n"
                "**本会话代号：AgentPalace**\n\n"
                f"**fetch 异常**: `{e}`\n"
            )

    out = os.path.join(_ROOT, "logs", "_fetch_notify_body.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)

    env = os.environ.copy()
    env["DINGTALK_TITLE"] = "AgentPalace-文档抓取结果"
    env["DINGTALK_WEBHOOK_KEY"] = "default"
    print("[4] webhook send", flush=True)
    r = subprocess.run([ex, _SEND, out], cwd=_ROOT, env=env)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
