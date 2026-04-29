#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发 Agent 结果反馈处理器。

负责：
1. 通过钉钉 Webhook 发送「Agent 完成」通知（包含分支名、摘要、DoD 对照）
2. 可选：通过 Multica CLI 在工单上加评论（当 MULTICA_PROJECT_ID 已配置时）

环境变量：
  DEV_AGENT_NOTIFY_WEBHOOK   钉钉 webhook URL，用于发送 Agent 完成通知
                              （不设时尝试读 dingtalk-desktop/webhook_config.json 的 cursor_session 键）
  MULTICA_PROJECT_ID         如果设置，Agent 完成后会在对应工单加评论
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dev_agent_runner import AgentRunResult, EvalResult

LOG = logging.getLogger("feedback-handler")

try:
    from notify_scope import is_minimal_webhook_scope
except ImportError:  # pragma: no cover

    def is_minimal_webhook_scope() -> bool:
        return False


_REPO_ROOT = Path(__file__).parent.parent.parent
_WEBHOOK_CONFIG_PATH = _REPO_ROOT / "dingtalk-desktop" / "webhook_config.json"


def _load_webhook_url() -> str:
    """优先读 DEV_AGENT_NOTIFY_WEBHOOK，再从 webhook_config.json 取 cursor_session。"""
    env_url = (os.environ.get("DEV_AGENT_NOTIFY_WEBHOOK") or "").strip()
    if env_url:
        return env_url
    try:
        config = json.loads(_WEBHOOK_CONFIG_PATH.read_text(encoding="utf-8"))
        url = (config.get("cursor_session") or "").strip()
        if url:
            return url
    except Exception:
        pass
    return ""


def _send_webhook(url: str, title: str, text: str) -> bool:
    """发送钉钉 Markdown 消息，返回是否成功。"""
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title[:50], "text": text},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
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


def _format_notification(result: "AgentRunResult", task: dict[str, Any]) -> tuple[str, str]:
    """返回 (title, markdown_body)。"""
    status_icon = "[完成]" if result.success else "[未完成]"
    title_text = task.get("title", result.task_id)
    title = f"{status_icon} {result.task_id} {title_text}"

    files_text = (
        "\n".join(f"- `{f}`" for f in result.files_changed[:10])
        if result.files_changed
        else "- （无文件变更）"
    )
    if len(result.files_changed) > 10:
        files_text += f"\n- ...共 {len(result.files_changed)} 个文件"

    summary = result.summary or "（无摘要）"
    duration = f"{result.duration_seconds:.0f}s"
    branch = result.branch
    worktree_path = getattr(result, "worktree_path", "") or ""
    worktree_line = f"**工作区：** `{worktree_path}`" if worktree_path else "**工作区：** （未记录）"

    body_lines = [
        f"## {status_icon} {result.task_id} {title_text}",
        "",
        f"**分支：** `{branch}`",
        worktree_line,
        f"**耗时：** {duration}",
        "",
        "### 修改文件",
        files_text,
        "",
        "### 执行摘要",
        summary[:600] if summary else "（无摘要）",
        "",
        "### 下一步",
        f"```",
        f"cd \"{worktree_path or _REPO_ROOT}\"",
        f"```",
        "在该独立工作区验收，确认无误后再合并到 main。",
    ]

    if not result.success and result.error:
        body_lines.insert(3, f"\n**错误：** {result.error[:200]}")

    return title, "\n".join(body_lines)


def notify_agent_started(task: dict[str, Any], webhook_url: str = "") -> bool:
    """Agent 真正开始执行时发送钉钉通知，让用户知道 claude 已启动。"""
    if is_minimal_webhook_scope():
        LOG.debug("minimal webhook scope: skip agent-started for %s", task.get("id"))
        return True
    url = webhook_url.strip() or _load_webhook_url()
    if not url:
        return False
    issue_id = task.get("id", "?")
    title_text = task.get("title", issue_id)
    title = f"[启动] {issue_id}"
    body = (
        f"## ⚡ Agent 开始执行\n\n"
        f"**工单：** `{issue_id}` {title_text[:60]}\n\n"
        f"Claude Code 已启动，预计 5-10 分钟完成。完成后会再发通知。"
    )
    return _send_webhook(url, title, body)


def notify_agent_done(
    result: "AgentRunResult",
    task: dict[str, Any],
    webhook_url: str = "",
) -> bool:
    """发送 Agent 完成钉钉通知。返回是否发送成功。"""
    if is_minimal_webhook_scope() and result.success:
        LOG.debug(
            "minimal webhook scope: skip agent-done success for %s",
            result.task_id,
        )
        return True
    url = webhook_url.strip() or _load_webhook_url()
    if not url:
        LOG.warning("no webhook URL configured, skipping DingTalk notification")
        return False

    title, body = _format_notification(result, task)
    LOG.info(
        "sending agent-done notification task=%s success=%s",
        result.task_id,
        result.success,
    )
    return _send_webhook(url, title, body)


def notify_eval_split(
    eval_result: "EvalResult",
    task: dict[str, Any],
    webhook_url: str = "",
) -> bool:
    """Phase-1 完成后：发送评估结果 + 拆分计划到钉钉 webhook。"""
    if is_minimal_webhook_scope():
        LOG.debug("minimal webhook scope: skip eval-split for %s", task.get("id"))
        return True
    url = webhook_url.strip() or _load_webhook_url()
    if not url:
        return False

    issue_id = task.get("id", "?")
    title_text = task.get("title", issue_id)
    n = len(eval_result.sub_tasks)
    complexity_label = {"low": "低", "medium": "中", "high": "高"}.get(
        eval_result.complexity, eval_result.complexity
    )

    sub_tasks_text = "\n".join(
        f"{st.index}. **{st.title}**  \n   {st.description[:80]}"
        for st in eval_result.sub_tasks
    )
    risks_text = (
        "\n".join(f"- {r}" for r in eval_result.risks)
        if eval_result.risks
        else "- 无明显风险"
    )
    notes_line = f"\n\n**备注：** {eval_result.notes}" if eval_result.notes else ""

    title = f"[规划] {issue_id} 拆分为 {n} 个子任务"
    body = (
        f"## 📋 评估完成 — {issue_id}\n\n"
        f"**工单：** `{issue_id}` {title_text[:50]}\n\n"
        f"**复杂度：** {complexity_label} | **子任务数：** {n}\n\n"
        f"### 子任务列表\n{sub_tasks_text}\n\n"
        f"### 风险\n{risks_text}{notes_line}"
    )
    LOG.info("sending eval-split notification task=%s sub_tasks=%d", issue_id, n)
    return _send_webhook(url, title, body)


def notify_sub_task_done(
    idx: int,
    total: int,
    sub_task_title: str,
    success: bool,
    summary: str,
    task_id: str,
    webhook_url: str = "",
) -> bool:
    """每个子任务完成后发送进度通知。"""
    if is_minimal_webhook_scope():
        LOG.debug(
            "minimal webhook scope: skip sub-task-done %s %d/%d",
            task_id,
            idx,
            total,
        )
        return True
    url = webhook_url.strip() or _load_webhook_url()
    if not url:
        return False

    icon = "[完成]" if success else "[未完成]"
    progress_bar = "█" * idx + "░" * (total - idx)
    next_line = (
        f"子任务 {idx + 1}/{total} 即将开始..."
        if idx < total
        else "全部子任务已处理，正在汇总..."
    )

    title = f"[进度 {idx}/{total}] {task_id} 子任务{idx} {icon}"
    body = (
        f"## {icon} 子任务 {idx}/{total}\n\n"
        f"**工单：** `{task_id}`\n"
        f"**子任务：** {sub_task_title}\n"
        f"**进度：** `{progress_bar}` {idx}/{total}\n\n"
        f"### 执行摘要\n{summary[:400] or '（无摘要）'}\n\n"
        f"---\n{next_line}"
    )
    LOG.info(
        "sending sub-task-done notification task=%s idx=%d/%d success=%s",
        task_id, idx, total, success,
    )
    return _send_webhook(url, title, body)


def comment_on_multica_issue(result: "AgentRunResult", task: dict[str, Any]) -> bool:
    """可选：在 Multica 工单上加评论。需要 MULTICA_PROJECT_ID 已配置。"""
    import subprocess
    import shutil

    project_id = (os.environ.get("MULTICA_PROJECT_ID") or "").strip()
    if not project_id:
        return False

    multica = shutil.which("multica") or "multica"
    issue_id = task.get("id", "")
    if not issue_id:
        return False

    comment_text = (
        f"[Agent] 分支 `{result.branch}` 已完成处理。\n\n{result.summary[:300]}"
        if result.success
        else f"[Agent] 处理失败（分支 `{result.branch}`）：{result.error[:200]}"
    )

    try:
        r = subprocess.run(
            [multica, "issue", "comment", issue_id, "--body", comment_text],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            LOG.warning("multica comment failed: %s", r.stderr[:200])
            return False
        return True
    except Exception as exc:
        LOG.warning("multica comment exception: %s", exc)
        return False
