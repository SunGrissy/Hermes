#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multica In Review 自动审查失败时的钉钉 Webhook 兜底（人工介入）。"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path

LOG = logging.getLogger("review-escalation")

_REPO_ROOT = Path(__file__).parent.parent.parent
_WEBHOOK_CONFIG_PATH = _REPO_ROOT / "dingtalk-desktop" / "webhook_config.json"


def load_escalation_webhook_url() -> str:
    """优先 MULTICA_REVIEW_ESCALATION_WEBHOOK_URL；否则 dingtalk-desktop/webhook_config.json 键「当当」或 dangdang_review_escalation。"""
    url = (os.environ.get("MULTICA_REVIEW_ESCALATION_WEBHOOK_URL") or "").strip()
    if url:
        return url
    try:
        raw = _WEBHOOK_CONFIG_PATH.read_text(encoding="utf-8")
        config = json.loads(raw)
        for key in ("当当", "dangdang_review_escalation"):
            u = (config.get(key) or "").strip()
            if u and not u.startswith("***"):
                return u
    except (OSError, json.JSONDecodeError) as exc:
        LOG.debug("escalation webhook config unreadable: %s", exc)
    return ""


def escalation_enabled() -> bool:
    return bool(load_escalation_webhook_url())


def _issue_label(issue: dict) -> str:
    return str(issue.get("identifier") or issue.get("id") or "UNKNOWN").strip()


def send_review_escalation(
    issue: dict,
    *,
    reason: str,
    backend: str,
) -> bool:
    """审查链路失败时通知老大介入。backend: cli | hermes"""
    url = load_escalation_webhook_url()
    if not url:
        LOG.warning("review escalation skipped: no webhook URL")
        return False

    issue_id = _issue_label(issue)
    title_text = str(issue.get("title") or issue.get("name") or "")[:80]
    backend_cn = "Claude CLI（code_review_dispatcher）" if backend == "cli" else "Hermes（当当侧 run_agent）"

    text = (
        f"## [审查兜底] 自动审查未成功完成\n\n"
        f"**工单：** {issue_id}\n\n"
        f"**标题：** {title_text or '（无）'}\n\n"
        f"**审查后端：** {backend_cn}\n\n"
        f"**原因：** {reason}\n\n"
        f"**建议：** 检查 Hermes / `run_agent.py` / dingtalk-desktop daemon；或在钉钉对当当发「审查 {issue_id}」手动触发。\n"
    )

    body = {
        "msgtype": "markdown",
        "markdown": {"title": f"[审查兜底] {issue_id}", "text": text},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except OSError as exc:
        LOG.warning("review escalation webhook failed: %s", exc)
        return False

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    errcode = data.get("errcode", 0)
    if errcode != 0:
        LOG.warning("review escalation dingtalk err: %s", raw[:500])
        return False
    LOG.info("review escalation sent for issue %s backend=%s", issue_id, backend)
    return True
