#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Multica 待审查工单交给独立 ClaudeAgent reviewer。"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from claude_call_telemetry.telemetry import call_claude_with_telemetry  # noqa: E402

LOG = logging.getLogger("code-review-dispatcher")


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _split_args(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    return tuple(shlex.split(value, posix=False))


def _issue_id(issue: dict) -> str:
    return str(issue.get("identifier") or issue.get("id") or "").strip()


@dataclass(frozen=True)
class CodeReviewConfig:
    enabled: bool
    command: str
    repo_root: Path
    multica_bin: str
    timeout_s: int
    send_timeout_s: int
    daemon_cid: str
    daemon_url: str
    extra_args: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "CodeReviewConfig":
        return cls(
            enabled=_is_truthy(os.environ.get("CODE_REVIEW_ENABLED", "")),
            command=os.environ.get("CODE_REVIEW_COMMAND", "claude").strip() or "claude",
            repo_root=Path(os.environ.get("CODE_REVIEW_REPO_ROOT", r"D:\MyAgents")),
            multica_bin=os.environ.get("CODE_REVIEW_MULTICA_BIN", "multica").strip() or "multica",
            timeout_s=int(os.environ.get("CODE_REVIEW_TIMEOUT", "1800")),
            send_timeout_s=int(os.environ.get("CODE_REVIEW_SEND_TIMEOUT", "90")),
            daemon_cid=os.environ.get("CODE_REVIEW_DAEMON_CID", "").strip(),
            daemon_url=os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200").rstrip("/"),
            extra_args=_split_args(os.environ.get("CODE_REVIEW_ARGS", "--print --output-format json")),
        )


def build_review_prompt(
    issue: dict,
    prev_status: str,
    curr_status: str,
    platform_workdir: Path | None = None,
) -> str:
    issue_id = _issue_id(issue) or "UNKNOWN"
    title = str(issue.get("title") or issue.get("name") or issue_id)
    payload = json.dumps(issue, ensure_ascii=False, indent=2)
    platform_line = str(platform_workdir) if platform_workdir else "未发现"
    return f"""你是 code-reviewer，只读审查 Multica 工单 {issue_id}。

上下文：
- 工单状态刚从 {prev_status} 进入 {curr_status}
- 工单标题：{title}
- 本地仓库：D:/MyAgents
- 优先检查工作区：D:/MyAgents/.worktrees/{issue_id}
- Multica 平台 run work_dir：{platform_line}
- 优先检查分支：agent/{issue_id}

审查边界：
- 只读代码审查，不修改文件，不提交，不推送，不改变 Multica 状态。
- 定位顺序：先看 Multica 平台 run work_dir 下的真实 Git 项目目录，其次看本地桥 worktree，最后才按 agent/{issue_id} 分支线索检查。
- 如无法定位分支或变更，报告阻塞原因和下一步需要的信息，不要在共享工作区猜测修改。
- 输出中文审查报告，先列问题，按严重程度排序；若无问题，明确说未发现阻塞项，并列出测试缺口。

工单原始 JSON：
```json
{payload}
```
"""


def extract_review_output(stdout: str) -> str:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "result" and data.get("result"):
            return str(data["result"]).strip()
    marker = "🎯 FINAL RESPONSE:"
    if marker in stdout:
        tail = stdout.split(marker, 1)[1]
        for end_marker in ("\n💾 Sample", "\n👋 Agent execution completed!"):
            if end_marker in tail:
                tail = tail.split(end_marker, 1)[0]
        return tail.strip(" \n-")
    return stdout.strip()


def _is_review_passed(report: str) -> bool:
    """审查是否通过：允许“无阻塞/低风险”直接通过。"""
    text = (report or "").strip()
    if not text:
        return False
    lower = text.lower()

    pass_tokens = (
        "未发现阻塞",
        "无阻塞",
        "审查通过",
        "可合并",
        "可以合并",
        "建议合并",
        "未发现问题",
        "no blocker",
        "no blocking",
        "low risk",
        "低风险",
        "风险很低",
        "仅低风险",
    )
    if any(token in lower for token in pass_tokens):
        return True

    fail_tokens = (
        "不通过",
        "未通过",
        "拒绝合并",
        "禁止合并",
        "必须修复",
        "阻塞项",
        "高风险",
        "critical",
        "blocker",
        "failed",
    )
    if any(token in lower for token in fail_tokens):
        return False

    return False


def _mark_issue_done(config: CodeReviewConfig, issue_id: str) -> bool:
    """审查通过后将工单状态改为 done。"""
    try:
        result = subprocess.run(
            [config.multica_bin, "issue", "update", issue_id, "--status", "done", "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("mark issue done failed for %s: %s", issue_id, exc)
        return False
    if result.returncode != 0:
        LOG.warning("mark issue done failed for %s: %s", issue_id, result.stderr[-300:])
        return False
    LOG.info("issue marked done after review: %s", issue_id)
    return True


def _post_review_comment(config: CodeReviewConfig, issue_id: str, report: str) -> bool:
    """将审查结果写回 Multica 工单评论。"""
    try:
        result = subprocess.run(
            [config.multica_bin, "issue", "comment", "add", issue_id,
             "--content", report,
             "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("post review comment failed for %s: %s", issue_id, exc)
        return False
    if result.returncode != 0:
        LOG.warning("post review comment failed for %s: %s", issue_id, result.stderr[-300:])
        return False
    LOG.info("review comment posted for %s", issue_id)
    return True


def _notify_review_done_safe(
    issue_id: str, report: str, backend: str, *, issue_title: str | None = None
) -> None:
    """尝试发审查完毕 webhook，不抛异常。"""
    try:
        from status_watcher import notify_review_done

        notify_review_done(issue_id, report, backend, issue_title=issue_title)
    except Exception as exc:
        LOG.debug("notify_review_done failed: %s", exc)


def resolve_review_workdir(config: CodeReviewConfig, issue_id: str) -> Path:
    platform_workdir = resolve_platform_review_workdir(config, issue_id)
    if platform_workdir:
        return platform_workdir
    worktree = config.repo_root / ".worktrees" / issue_id
    if worktree.exists():
        return worktree
    return config.repo_root


def _is_git_workdir(path: Path) -> bool:
    return (path / ".git").exists()


def _git_workdir_or_child(path: Path) -> Path | None:
    if _is_git_workdir(path):
        return path
    try:
        children = sorted(path.iterdir(), key=lambda child: child.name.lower())
    except OSError:
        return None
    for child in children:
        if child.is_dir() and _is_git_workdir(child):
            return child
    return None


def resolve_platform_review_workdir(config: CodeReviewConfig, issue_id: str) -> Path | None:
    platform_root = resolve_platform_run_workdir(config, issue_id)
    if not platform_root:
        return None
    return _git_workdir_or_child(platform_root)


def resolve_platform_run_workdir(config: CodeReviewConfig, issue_id: str) -> Path | None:
    if not issue_id or issue_id == "UNKNOWN":
        return None
    try:
        result = subprocess.run(
            [config.multica_bin, "issue", "runs", issue_id, "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.debug("failed to query Multica run workdir for %s: %s", issue_id, exc)
        return None
    if result.returncode != 0:
        LOG.debug("Multica runs query failed for %s: %s", issue_id, result.stderr[-300:])
        return None
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        LOG.debug("Multica runs output was not JSON for %s", issue_id)
        return None
    if not isinstance(runs, list):
        return None
    for run in runs:
        if not isinstance(run, dict):
            continue
        payload = run.get("result")
        if not isinstance(payload, dict):
            continue
        work_dir = str(payload.get("work_dir") or "").strip()
        if not work_dir:
            continue
        path = Path(work_dir)
        if path.exists():
            return path
    return None


class CodeReviewDispatcher:
    def __init__(self, config: CodeReviewConfig | None = None):
        self.config = config or CodeReviewConfig.from_env()

    def dispatch(self, issue: dict, prev_status: str, curr_status: str) -> bool:
        if not self.config.enabled:
            LOG.debug("code review disabled")
            return False
        issue_id = _issue_id(issue) or "UNKNOWN"
        workdir = resolve_review_workdir(self.config, issue_id)
        platform_workdir = resolve_platform_run_workdir(self.config, issue_id)
        prompt = build_review_prompt(issue, prev_status, curr_status, platform_workdir)
        cmd = [self.config.command, *self.config.extra_args, prompt]
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        issue_title = str(issue.get("title") or issue.get("name") or issue_id)
        try:
            result = call_claude_with_telemetry(
                cmd=cmd,
                cwd=workdir,
                env=env,
                timeout=self.config.timeout_s,
                task_id=f"code-review:{issue_id}",
                caller="multica-dingtalk-bridge.code_review_dispatcher",
                task_title=issue_title,
            )
        except subprocess.TimeoutExpired:
            LOG.warning("code review timed out: %s", issue_id)
            return False
        except OSError as exc:
            LOG.warning("code review failed to start: %s", exc)
            return False

        if result.returncode != 0:
            LOG.warning("code review failed: %s", (result.stderr or result.stdout)[-500:])
            return False
        report = extract_review_output(result.stdout)
        if not report:
            LOG.warning("code review produced empty report: %s", issue_id)
            return False

        # ── 写回 Multica 评论 ───────────────────────────────────────────
        _post_review_comment(self.config, issue_id, report)
        # ── 审查通过自动置 done（允许低风险通过）────────────────────────
        if _is_review_passed(report):
            _mark_issue_done(self.config, issue_id)
        # ── 审查完毕 webhook 通知 ──────────────────────────────────────
        _notify_review_done_safe(issue_id, report, "cli", issue_title=issue_title)

        if self.config.daemon_cid:
            return self._send_via_dingtalk_daemon(issue_id, report)
        LOG.info("code review finished without delivery target: %s", issue_id)
        return True

    def _send_via_dingtalk_daemon(self, issue_id: str, report: str) -> bool:
        message = f"【Multica 代码审查】{issue_id}\n\n{report} 🤖"
        payload = json.dumps(
            {"cid": self.config.daemon_cid, "message": message},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.daemon_url}/send",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.send_timeout_s) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except OSError as exc:
            LOG.warning("DingTalk daemon delivery failed: %s", exc)
            return False
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        if not data.get("success"):
            LOG.warning("DingTalk daemon delivery returned error: %s", body[-500:])
            return False
        LOG.info("code review delivered via DingTalk daemon: %s", issue_id)
        return True


def trigger_code_review_async(issue: dict, prev_status: str, curr_status: str) -> None:
    dispatcher = CodeReviewDispatcher()
    if not dispatcher.config.enabled:
        LOG.debug("code review disabled, skip async trigger")
        return
    issue_id = _issue_id(issue) or "UNKNOWN"
    thread = threading.Thread(
        target=dispatcher.dispatch,
        args=(issue, prev_status, curr_status),
        daemon=True,
        name=f"code-review-{issue_id}",
    )
    thread.start()
