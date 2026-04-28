#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multica 工单状态变更监听器。

后台守护线程，每 STATUS_WATCHER_INTERVAL 秒轮询一次 Multica 工单列表，
检测到关键状态转换（如进入 In Review / Done）时通过钉钉 webhook 发出通知。

通知末尾附带代码审查提示，方便人工或自动化触发后续审查流程。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

try:
    from code_review_dispatcher import trigger_code_review_async
except Exception:  # pragma: no cover - 保持状态通知不被可选审查链路阻断
    def trigger_code_review_async(issue: dict, prev_status: str, curr_status: str) -> None:
        return None

LOG = logging.getLogger("status-watcher")

_REPO_ROOT = Path(__file__).parent.parent.parent
_CACHE_PATH = _REPO_ROOT / "shared-memory" / "multica-status-cache.json"
_POLL_INTERVAL_S = int(os.environ.get("STATUS_WATCHER_INTERVAL", "300"))  # 默认 5 分钟
_STARTUP_DELAY_S = 30  # 启动后延迟，等 multica 登录完成

# key: _normalize_status(status) → 通知标签
_NOTIFY_ON_ENTER: dict[str, str] = {
    "inreview": "[待审查]",
    "done": "[已完成]",
    "cancelled": "[已取消]",
}


# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _normalize_status(s: str) -> str:
    return (s or "").lower().replace(" ", "").replace("_", "").replace("-", "")


def _run_multica(*args: str, timeout: int = 30) -> tuple[bool, str]:
    multica = shutil.which("multica") or "multica"
    try:
        r = subprocess.run(
            [multica, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode == 0, r.stdout or r.stderr or ""
    except Exception as exc:
        return False, str(exc)


def _check_agent_branch(issue_id: str) -> str:
    """检查 agent/{issue_id} 分支是否存在于本地仓库。"""
    branch = f"agent/{issue_id}"
    try:
        r = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return branch if r.stdout.strip() else ""
    except Exception:
        return ""


def _load_cache() -> dict[str, str]:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        LOG.warning("status cache save failed: %s", exc)


def _load_webhook_url() -> str:
    """复用 feedback_handler 的 webhook URL 加载逻辑。"""
    try:
        from feedback_handler import _load_webhook_url as _fw
        return _fw()
    except Exception:
        pass
    return (os.environ.get("DEV_AGENT_NOTIFY_WEBHOOK") or "").strip()


def _send_webhook(url: str, title: str, body: str) -> bool:
    import urllib.request

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title[:50], "text": body},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except OSError as exc:
        LOG.warning("webhook send failed: %s", exc)
        return False


# ─── 通知格式 ────────────────────────────────────────────────────────────────

def _build_notification(
    issue: dict,
    prev_status: str,
    curr_status: str,
    label: str,
) -> tuple[str, str]:
    """返回 (webhook_title, markdown_body)。"""
    issue_id = str(issue.get("identifier") or issue.get("id") or "?")
    title_text = str(issue.get("title") or issue.get("name") or issue_id)
    assignee = str(issue.get("assignee") or issue.get("assigneeId") or "未知")

    # 检查是否有 agent 分支可供审查
    branch = _check_agent_branch(issue_id)
    branch_line = (
        f"\n**分支：** `{branch}`（可 `git checkout {branch}` 查看变更）"
        if branch
        else ""
    )

    # 代码审查触发提示（仅 In Review 时附加）
    hermes_hint = ""
    if _normalize_status(curr_status) == "inreview":
        hermes_hint = (
            "\n\n---\n"
            f"**触发代码审查：** 可发送 `审查 {issue_id}`；若已配置 `CODE_REVIEW_ENABLED=1`，会自动启动 reviewer。"
        )

    webhook_title = f"{label} {issue_id}"
    body = (
        f"## {label} — {issue_id}\n\n"
        f"**工单：** [{issue_id}] {title_text[:60]}\n"
        f"**状态：** {prev_status} → **{curr_status}**\n"
        f"**负责人：** {assignee}"
        f"{branch_line}"
        f"{hermes_hint}"
    )
    return webhook_title, body


# ─── 轮询逻辑 ─────────────────────────────────────────────────────────────────

def poll_once(cache: dict[str, str], webhook_url: str) -> dict[str, str]:
    """执行一次轮询：拉取全量工单，对比状态缓存，发送变更通知。

    返回更新后的 cache（调用方负责存盘）。
    """
    ok, output = _run_multica("issue", "list", "--limit", "500", "--format", "json")
    if not ok:
        LOG.warning("status watcher multica list failed: %s", output[:300])
        return cache  # 保持旧 cache，下次重试

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        LOG.warning("status watcher json parse failed, raw[:100]=%s", output[:100])
        return cache

    issues: list[dict] = data if isinstance(data, list) else data.get("issues", [])
    if not isinstance(issues, list):
        LOG.warning("unexpected issues type: %s", type(issues))
        return cache

    new_cache: dict[str, str] = {}
    transitions: list[tuple[dict, str, str]] = []

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("identifier") or issue.get("id") or "")
        status = str(issue.get("status") or issue.get("state") or "")
        if not issue_id or not status:
            continue

        new_cache[issue_id] = status
        prev = cache.get(issue_id)
        if prev is not None and prev != status:
            transitions.append((issue, prev, status))

    LOG.debug(
        "poll_once done: total=%d transitions=%d", len(new_cache), len(transitions)
    )

    # 发送变更通知
    for issue, prev, curr in transitions:
        norm = _normalize_status(curr)
        label = _NOTIFY_ON_ENTER.get(norm)
        if not label:
            continue
        title, body = _build_notification(issue, prev, curr, label)
        if _send_webhook(webhook_url, title, body):
            LOG.info(
                "notified transition %s: %s -> %s",
                issue.get("identifier") or issue.get("id"), prev, curr,
            )
        else:
            LOG.warning(
                "failed to notify transition %s: %s -> %s",
                issue.get("identifier") or issue.get("id"), prev, curr,
            )
        if norm == "inreview":
            try:
                trigger_code_review_async(issue, prev, curr)
            except Exception as exc:
                LOG.warning("failed to trigger code review: %s", exc)

    _save_cache(new_cache)
    return new_cache


# ─── 后台线程 ─────────────────────────────────────────────────────────────────

class StatusWatcher:
    """后台守护线程：定时轮询 Multica 工单状态，检测关键转换并发 webhook。

    用法：
        watcher = StatusWatcher()
        watcher.start()          # 启动后台线程（daemon=True，主进程退出时自动终止）
        # ...
        watcher.stop()           # 优雅停止（可选）
    """

    def __init__(self, webhook_url: str = ""):
        self._webhook_url: str = webhook_url.strip() or _load_webhook_url()
        self._cache: dict[str, str] = _load_cache()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            LOG.debug("StatusWatcher already running, skip start")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="multica-status-watcher",
        )
        self._thread.start()
        LOG.info(
            "StatusWatcher started (poll_interval=%ds, startup_delay=%ds)",
            _POLL_INTERVAL_S,
            _STARTUP_DELAY_S,
        )

    def stop(self) -> None:
        LOG.info("StatusWatcher stopping...")
        self._stop_event.set()

    def _loop(self) -> None:
        """后台轮询主循环。"""
        # 等待 multica daemon 就绪
        self._stop_event.wait(_STARTUP_DELAY_S)
        while not self._stop_event.is_set():
            try:
                self._cache = poll_once(self._cache, self._webhook_url)
            except Exception as exc:
                LOG.error("StatusWatcher unexpected error: %s", exc)
            self._stop_event.wait(_POLL_INTERVAL_S)
        LOG.info("StatusWatcher stopped")
