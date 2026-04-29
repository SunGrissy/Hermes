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

try:
    from hermes_review_dispatcher import trigger_hermes_review_async
except Exception:  # pragma: no cover
    def trigger_hermes_review_async(issue: dict, prev_status: str, curr_status: str) -> None:
        return None

try:
    from review_escalation import escalation_enabled
except Exception:  # pragma: no cover
    def escalation_enabled() -> bool:
        return False

from notify_scope import is_minimal_webhook_scope

LOG = logging.getLogger("status-watcher")

_REPO_ROOT = Path(__file__).parent.parent.parent
_CACHE_PATH = _REPO_ROOT / "shared-memory" / "multica-status-cache.json"
_RUN_FAIL_CACHE_PATH = _REPO_ROOT / "shared-memory" / "multica-run-fail-cache.json"
_RUN_TRANSITION_CACHE_PATH = _REPO_ROOT / "shared-memory" / "multica-run-transition-cache.json"
_POLL_INTERVAL_S = int(os.environ.get("STATUS_WATCHER_INTERVAL", "300"))  # 默认 5 分钟
_STARTUP_DELAY_S = 30  # 启动后延迟，等 multica 登录完成

# key: _normalize_status(status) → 通知标签
_NOTIFY_ON_ENTER: dict[str, str] = {
    "inreview": "[待审查]",
    "done": "[已完成]",
    "cancelled": "[已取消]",
    "failed": "[运行失败]",
    "approved": "[审查通过]",
}


# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _normalize_status(s: str) -> str:
    return (s or "").lower().replace(" ", "").replace("_", "").replace("-", "")


def _auto_merge_trigger_norm() -> str:
    """MULTICA_AUTO_MERGE_TRIGGER_STATUS：approved（默认）| done。

    Multica 工作区若无 **approved** 状态，可设为 **done**，在关单时尝试合并本地 ``agent/{工单号}``。
    """
    raw = (os.environ.get("MULTICA_AUTO_MERGE_TRIGGER_STATUS") or "approved").strip().lower()
    if raw == "done":
        return "done"
    return "approved"


def _should_auto_merge_on_status(norm: str) -> bool:
    return norm == _auto_merge_trigger_norm()


def _webhook_merge_ack_line() -> str:
    """审查完毕 webhook 末尾一句：按当前合并触发状态提示。"""
    if _auto_merge_trigger_norm() == "done":
        return "若认可：在 Multica 标 **Done**，会按配置尝试把 agent 分支合进 main。"
    return (
        "若认可：工作区若有 **approved** 可用来触合并；若没有，在桥 `.env` 设 "
        "`MULTICA_AUTO_MERGE_TRIGGER_STATUS=done` 后用 **Done** 触发。"
    )


def _review_backend_mode() -> str:
    """IN_REVIEW_REVIEW_BACKEND：cli | hermes | both；非法值回退 cli。"""
    mode = os.environ.get("IN_REVIEW_REVIEW_BACKEND", "cli").strip().lower()
    if mode not in ("cli", "hermes", "both"):
        return "cli"
    return mode


def _thread_issue_tag(issue: dict) -> str:
    raw = str(issue.get("identifier") or issue.get("id") or "issue")[:40]
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in raw)


def _cli_dispatch_with_escalation(issue: dict, prev_status: str, curr_status: str) -> None:
    """同步跑 CLI 审查；失败则发兜底 webhook（需配置 escalation URL）。"""
    from code_review_dispatcher import CodeReviewDispatcher
    from review_escalation import send_review_escalation

    dispatcher = CodeReviewDispatcher()
    if not dispatcher.config.enabled:
        return
    ok = dispatcher.dispatch(issue, prev_status, curr_status)
    if not ok:
        send_review_escalation(
            issue,
            reason="Claude CLI 审查失败或未产出可投递结果（含 dingtalk daemon 私聊投递失败）。",
            backend="cli",
        )


def _hermes_dispatch_with_escalation(issue: dict, prev_status: str, curr_status: str) -> None:
    """同步跑 Hermes 审查；失败则发兜底 webhook。"""
    from hermes_review_dispatcher import HermesReviewDispatcher
    from review_escalation import send_review_escalation

    dispatcher = HermesReviewDispatcher()
    if not dispatcher.config.enabled:
        return
    ok = dispatcher.dispatch(issue, prev_status, curr_status)
    if not ok:
        send_review_escalation(
            issue,
            reason="Hermes（当当侧 run_agent）未成功：脚本缺失、超时、空输出、或 daemon 投递失败（当当/Hermes 进程异常时可出现）。",
            backend="hermes",
        )


def _invoke_review_chain(issue: dict, prev_status: str, curr_status: str) -> None:
    """工单进入 In Review 后触发审查：CLI（claude）、Hermes（当当侧 run_agent + skill）、或二者。

    若配置了审查兜底 webhook（webhook_config「当当」或 MULTICA_REVIEW_ESCALATION_WEBHOOK_URL），
    则在后台线程内**同步**执行 dispatch，失败时向该 webhook 发 Markdown 提醒老大介入。
    """
    mode = _review_backend_mode()
    issue_id = str(issue.get("identifier") or issue.get("id") or "")
    cli_on = _is_truthy_env("CODE_REVIEW_ENABLED")
    hermes_on = _is_truthy_env("HERMES_REVIEW_ENABLED")
    use_esc = False
    try:
        use_esc = escalation_enabled()
    except Exception as exc:
        LOG.debug("escalation_enabled check failed: %s", exc)

    if mode in ("cli", "both"):
        if not cli_on:
            LOG.info("skip CLI auto review for %s: CODE_REVIEW_ENABLED is off", issue_id)
        try:
            if use_esc:
                threading.Thread(
                    target=_cli_dispatch_with_escalation,
                    args=(issue, prev_status, curr_status),
                    daemon=True,
                    name=f"code-review-esc-{_thread_issue_tag(issue)}",
                ).start()
            else:
                trigger_code_review_async(issue, prev_status, curr_status)
        except Exception as exc:
            LOG.warning("failed to trigger CLI code review: %s", exc)

    if mode in ("hermes", "both"):
        if not hermes_on:
            LOG.info("skip Hermes auto review for %s: HERMES_REVIEW_ENABLED is off", issue_id)
        try:
            if use_esc:
                threading.Thread(
                    target=_hermes_dispatch_with_escalation,
                    args=(issue, prev_status, curr_status),
                    daemon=True,
                    name=f"hermes-review-esc-{_thread_issue_tag(issue)}",
                ).start()
            else:
                trigger_hermes_review_async(issue, prev_status, curr_status)
        except Exception as exc:
            LOG.warning("failed to trigger Hermes review: %s", exc)


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




def _load_run_transition_cache() -> dict[str, str]:
    try:
        if _RUN_TRANSITION_CACHE_PATH.exists():
            return json.loads(_RUN_TRANSITION_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_run_transition_cache(cache: dict[str, str]) -> None:
    try:
        _RUN_TRANSITION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RUN_TRANSITION_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        LOG.warning("run transition cache save failed: %s", exc)

def _is_truthy_env(name: str) -> bool:
    return (os.environ.get(name, "") or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _review_trigger_summary(issue_id: str) -> str:
    """返回 in_review 下可直接给人的审查链路状态说明。"""
    mode = _review_backend_mode()
    cli_on = _is_truthy_env("CODE_REVIEW_ENABLED")
    hermes_on = _is_truthy_env("HERMES_REVIEW_ENABLED")

    if mode == "cli":
        if cli_on:
            return "自动审查：已触发 ClaudeReviewer，结果会回写到 Multica 评论。"
        return f"自动审查：未启用（CLI 开关关闭）。如需现在审查：对当当说 `审查 {issue_id}`。"

    if mode == "hermes":
        if hermes_on:
            return "自动审查：已触发当当/Hermes 审查，结果会回写到 Multica 评论。"
        return f"自动审查：未启用（Hermes 审查开关关闭）。如需现在审查：对当当说 `审查 {issue_id}`。"

    # both
    if cli_on and hermes_on:
        return "自动审查：双通道已触发（ClaudeReviewer + 当当/Hermes），可能收到两份审查结果。"
    if cli_on:
        return "自动审查：配置为双通道，但当前仅 ClaudeReviewer 已启用。"
    if hermes_on:
        return "自动审查：配置为双通道，但当前仅当当/Hermes 已启用。"
    return f"自动审查：未启用（CLI/Hermes 均关闭）。如需现在审查：对当当说 `审查 {issue_id}`。"


def _get_issue_title(issue_id: str, issues_map: dict[str, dict] | None) -> str:
    """从 issues_map 或缓存中取工单标题；回退用 issue_id。"""
    if issues_map and issue_id in issues_map:
        return str(issues_map[issue_id].get("title") or issue_id)
    return issue_id


def _build_review_status_line(status: str) -> str:
    """根据当前工单状态，生成审查状态说明。"""
    issue_id = "{issue_id}"
    if status in ("in_review", "In Review"):
        return f"**审查状态：** 已进入 In Review。{_review_trigger_summary(issue_id)}"
    return (
        "**审查状态：** 未自动进入 In Review。\n"
        "如需审查：在 Multica 将工单状态改为 **In Review**，"
        "或告诉当当 `审查 {issue_id}`。"
    )


def _check_run_transitions(
    cache: dict[str, str], webhook_url: str, issues_map: dict[str, dict] | None = None
) -> dict[str, str]:
    """检测 run 状态变化，发通知（Claude 开始/完成）。
    通知标题格式：[标签] ISSUE-ID: 工单标题
    Claude 完成时顺带说明审查状态（是否已自动进入 in_review / 如何触发审查）。
    返回更新后的 transition cache。"""
    tcache = _load_run_transition_cache()
    for issue_id, status in cache.items():
        norm = _normalize_status(status)
        if norm not in ("todo", "inprogress", "inreview"):
            continue
        latest = _get_latest_run(issue_id)
        if not latest:
            continue
        run_id = latest.get("id") or ""
        run_status = (latest.get("status") or "").lower()
        if not run_id:
            continue
        prev = tcache.get(issue_id, "")
        if prev != run_id:
            # 获取工单标题
            issue_title = _get_issue_title(issue_id, issues_map)
            if run_status == "in_progress":
                if not is_minimal_webhook_scope():
                    webhook_title = f"[Claude 工作中] {issue_id}: {issue_title}"
                    body = (f"## [Claude 工作中] {issue_id}: {issue_title}\n\n"
                            f"Claude 已开始处理 {issue_id}，正在执行中。")
                    _send_webhook(webhook_url, webhook_title, body)
                    LOG.info("notified run started: %s (run=%s)", issue_id, run_id)
            elif run_status == "completed":
                if not is_minimal_webhook_scope():
                    review_info = _build_review_status_line(status).replace("{issue_id}", issue_id)
                    webhook_title = f"[Claude 完成] {issue_id}: {issue_title}"
                    body = (f"## [Claude 完成] {issue_id}: {issue_title}\n\n"
                            f"Claude 已完成 {issue_id}。\n\n"
                            f"{review_info}")
                    _send_webhook(webhook_url, webhook_title, body)
                    LOG.info("notified run completed: %s (run=%s)", issue_id, run_id)
            tcache[issue_id] = run_id
    _save_run_transition_cache(tcache)
    return tcache


# ─── Run 失败检测兜底 ─────────────────────────────────────────────────────────

def _load_run_fail_cache() -> dict[str, str]:
    """加载已通知过的 run failure id 缓存。"""
    try:
        if _RUN_FAIL_CACHE_PATH.exists():
            return json.loads(_RUN_FAIL_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_run_fail_cache(cache: dict[str, str]) -> None:
    try:
        _RUN_FAIL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RUN_FAIL_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        LOG.warning("run fail cache save failed: %s", exc)


def _get_latest_run(issue_id: str) -> dict | None:
    """查询工单的最新一条 run，返回 run dict 或 None。"""
    ok, output = _run_multica("issue", "runs", issue_id, "--output", "json")
    if not ok:
        LOG.debug("fetch runs for %s failed: %s", issue_id, output[:200])
        return None
    try:
        runs = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(runs, list) and len(runs) > 0:
        return runs[0]  # 首位 = 最新
    return None




def _merge_agent_branch(issue: dict) -> bool:
    """进入配置的合并触发状态（默认 approved，见 MULTICA_AUTO_MERGE_TRIGGER_STATUS）后自动合并 agent 分支 → main → push。"""
    issue_id = str(issue.get("identifier") or issue.get("id") or "")
    if not issue_id:
        return False
    branch = f"agent/{issue_id}"
    # 检查分支存在
    try:
        r = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        LOG.warning("merge check branch failed for %s: %s", issue_id, exc)
        return False
    if not r.stdout.strip():
        LOG.info("merge skipped for %s: branch %s not found", issue_id, branch)
        return False
    # 检查是否已合入
    try:
        r2 = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, "main"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r2.returncode == 0:
            LOG.info("merge skipped for %s: already merged", issue_id)
            return True
    except Exception:
        pass
    # 执行合并
    try:
        r3 = subprocess.run(
            ["git", "merge", branch],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r3.returncode != 0:
            LOG.warning("merge conflict for %s: %s", issue_id, r3.stderr[-300:])
            # 发 webhook 通知冲突
            url = _load_webhook_url()
            if url:
                _send_webhook(url, f"[合并冲突] {issue_id}",
                    f"## [合并冲突] {issue_id}\n\n"
                    f"分支 `{branch}` 合并到 main 时冲突。\n"
                    f"请手动处理：`cd D:/MyAgents && git merge {branch}`")
            return False
        # 推送
        r4 = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r4.returncode != 0:
            LOG.warning("merge push failed for %s: %s", issue_id, r4.stderr[-300:])
            return False
        LOG.info("merged %s to main and pushed", issue_id)
        # ── 自动改 Multica 状态为 done ────────────────────────
        _run_multica("issue", "update", issue_id, "--status", "done")
        return True
    except Exception as exc:
        LOG.warning("merge failed for %s: %s", issue_id, exc)
        return False

# ─── 审查完毕通知（供 dispatcher 调用） ────────────────────────────────────

def _dingtalk_markdown_title(prefix: str, issue_id: str, subtitle: str, max_len: int = 50) -> str:
    """钉钉 markdown.title 长度上限约 50，截断避免被截断成半截词。"""
    subtitle = (subtitle or "").strip() or issue_id
    base = f"{prefix} {issue_id}"
    room = max_len - len(base) - 2
    if room < 4:
        return base[:max_len]
    tail = subtitle[:room]
    if len(base) + 2 + len(tail) > max_len:
        tail = tail[: max(0, max_len - len(base) - 2)]
    out = f"{base}: {tail}".strip()
    return out[:max_len]


def notify_review_done(
    issue_id: str,
    report: str,
    backend: str,
    *,
    issue_title: str | None = None,
) -> bool:
    """审查结束后向 webhook 发短摘要（去表格、口语化）；完整报告已在 Multica 评论。"""
    from review_webhook_format import humanize_review_for_webhook

    url = _load_webhook_url()
    if not url:
        return False
    backend_cn = "Claude CLI" if backend == "cli" else "Hermes（当当）"
    title_display = (issue_title or "").strip() or issue_id
    human = humanize_review_for_webhook(report)
    body = (
        f"## [审查完毕] {issue_id}：{title_display}\n\n"
        f"这条工单刚跑完自动代码审查（{backend_cn}）。下面是说人话的摘要；"
        f"表格和原文细节都在 **Multica 工单评论** 里。\n\n"
        f"{human}\n\n"
        f"{_webhook_merge_ack_line()}"
    )
    md_title = _dingtalk_markdown_title("[审查完毕]", issue_id, title_display)
    return _send_webhook(url, md_title, body)


# ─── Run 失败检测兜底 ─────────────────────────────────────────────────────

def _check_run_failures(cache: dict[str, str], webhook_url: str) -> dict[str, str]:
    """对缓存中 status 为 in_progress 的工单，检查最新 run 是否失败。
    
    若 run 进入 failed 但 issue status 未变，通过 webhook 发通知，
    避免因 status 卡住而漏报。
    
    返回更新后的 run-fail-cache（调用方负责存盘）。
    """
    fail_cache = _load_run_fail_cache()
    for issue_id, status in cache.items():
        norm = _normalize_status(status)
        # 只在工单仍在运行 / 待办中时才有必要检测——done/cancelled/inreview 不用
        if norm not in ("inprogress", "todo", "backlog", "blocked"):
            continue
        latest = _get_latest_run(issue_id)
        if not latest:
            continue
        run_status = (latest.get("status") or "").lower()
        if run_status != "failed":
            continue
        run_id = latest.get("id") or ""
        if not run_id:
            continue
        # 已通知过则跳过
        prev_run_id = fail_cache.get(issue_id)
        if prev_run_id == run_id:
            continue
        fail_cache[issue_id] = run_id
        # 构造通知
        failure_reason = latest.get("failure_reason") or latest.get("error") or "agent_error"
        attempt = latest.get("attempt", 1)
        max_attempts = latest.get("max_attempts", 1)
        error_detail = (latest.get("error") or "无详细错误信息")[:200]
        label = "[运行失败]"
        title, _ = _build_notification(
            {"identifier": issue_id, "title": issue_id},
            status,
            f"failed (run #{attempt})",
            label,
        )
        body = (
            f"## {label} — {issue_id}\n\n"
            f"**工单：** {issue_id}\n"
            f"**工单状态：** {status}（未变化）\n"
            f"**Run 状态：** failed（第 {attempt}/{max_attempts} 次尝试）\n"
            f"**失败原因：** {failure_reason}\n"
            f"**错误详情：** {error_detail}\n"
            f"**下一步：** 如需重试，在 Multica 改为 todo + 加评论，或直接联系老大/当当。"
        )
        if _send_webhook(webhook_url, title, body):
            LOG.info("notified run failure for %s (run=%s)", issue_id, run_id)
        else:
            LOG.warning("failed to send run failure webhook for %s", issue_id)
    _save_run_fail_cache(fail_cache)
    return fail_cache


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
    assignee = str(
        issue.get("assignee")
        or issue.get("assignee_name")
        or issue.get("assigneeId")
        or issue.get("assignee_id")
        or ("Agent" if str(issue.get("assignee_type") or "").lower() == "agent" else "未知")
    )

    # 检查是否有 agent 分支可供审查
    branch = _check_agent_branch(issue_id)
    branch_line = (
        f"\n**分支：** `{branch}`（可 `git checkout {branch}` 查看变更）"
        if branch
        else ""
    )

    next_step = ""
    norm = _normalize_status(curr_status)
    if norm == "inreview":
        next_step = _review_trigger_summary(issue_id)
    elif norm == "approved":
        if _auto_merge_trigger_norm() == "approved":
            next_step = "下一步：标为 approved 后，系统会尝试自动合并 agent 分支到 main。"
        else:
            next_step = "当前自动合并由 **Done** 触发；approved 不会执行合并。"
    elif norm == "done":
        if _auto_merge_trigger_norm() == "done":
            next_step = "下一步：关单后系统会尝试自动合并 agent 分支到 main（无本地分支则跳过）。"
        else:
            next_step = (
                "下一步：默认需 **approved** 才会自动合并；若 Multica 没有该状态，"
                "可在桥 `.env` 设 `MULTICA_AUTO_MERGE_TRIGGER_STATUS=done` 后改用关单触发。"
            )
    elif norm == "failed":
        next_step = "下一步：打开工单 runs 看最后一次失败日志并重试。"

    webhook_title = f"{label} {issue_id}"
    body = (
        f"## {label} — {issue_id}\n\n"
        f"**工单：** {title_text[:80]}\n"
        f"**状态：** {prev_status} → **{curr_status}**\n"
        f"**负责人：** {assignee}"
        f"{branch_line}"
    )
    if next_step:
        body += f"\n\n**说明：** {next_step}"
    return webhook_title, body


# ─── 轮询逻辑 ─────────────────────────────────────────────────────────────────

def poll_once(cache: dict[str, str], webhook_url: str) -> dict[str, str]:
    """执行一次轮询：拉取全量工单，对比状态缓存，发送变更通知。

    返回更新后的 cache（调用方负责存盘）。
    """
    ok, output = _run_multica("issue", "list", "--limit", "500", "--output", "json")
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

    # ── 构建 issues_map 供 _check_run_transitions 获取标题 ──────
    issues_map: dict[str, dict] = {
        str(issue.get("identifier") or issue.get("id") or ""): issue
        for issue in issues if isinstance(issue, dict)
    }

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
        if is_minimal_webhook_scope() and label != "[运行失败]":
            LOG.debug(
                "minimal webhook scope: skip status transition %s -> %s (%s)",
                prev,
                curr,
                label,
            )
        elif _send_webhook(webhook_url, title, body):
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
                _invoke_review_chain(issue, prev, curr)
            except Exception as exc:
                LOG.warning("failed to trigger review chain: %s", exc)
        # ── 自动 git merge（MULTICA_AUTO_MERGE_TRIGGER_STATUS，默认 approved）──
        if _should_auto_merge_on_status(norm):
            _merge_agent_branch(issue)

    _save_cache(new_cache)

    # ── Run 级失败兜底检测 ──────────────────────────────────────────────
    try:
        _check_run_failures(new_cache, webhook_url)
    except Exception as exc:
        LOG.warning("run failure check failed: %s", exc)
    # ── Run 过渡通知（Claude 开始/完成） ───────────────────────────────
    try:
        _check_run_transitions(new_cache, webhook_url, issues_map)
    except Exception as exc:
        LOG.warning("run transition check failed: %s", exc)

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
