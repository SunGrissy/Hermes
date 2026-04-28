#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Code headless 执行封装。

为每个任务：
1. 创建 git worktree .worktrees/{task_id} + 分支 agent/{task_id}
2. 组装上下文包（task_context.py）
3. 调用 claude --bare -p ... --output-format json
4. 解析 JSON 结果，提取执行摘要和修改文件列表
5. 更新任务队列文件状态

调用方式（异步）：
    result = await asyncio.to_thread(run_dev_agent, task, task_path)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger("dev-agent-runner")

_REPO_ROOT = Path(__file__).parent.parent.parent  # multica-dingtalk-bridge -> tools -> MyAgents
_AGENT_TIMEOUT_SECONDS = int(os.environ.get("DEV_AGENT_TIMEOUT", "600"))
_AGENT_MAX_TURNS = int(os.environ.get("DEV_AGENT_MAX_TURNS", "15"))
_EVAL_MAX_TURNS = int(os.environ.get("DEV_EVAL_MAX_TURNS", "5"))
_EVAL_TIMEOUT_SECONDS = int(os.environ.get("DEV_EVAL_TIMEOUT", "180"))
_WORKTREE_ROOT = Path(os.environ.get("DEV_AGENT_WORKTREE_ROOT", _REPO_ROOT / ".worktrees"))


@dataclass
class SubTask:
    """评估阶段拆分出的一个子任务。"""
    index: int
    title: str
    description: str
    files_hint: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Phase-1 评估+拆分结果。"""
    complexity: str = "medium"
    risks: list[str] = field(default_factory=list)
    sub_tasks: list[SubTask] = field(default_factory=list)
    notes: str = ""
    raw: str = ""  # Claude 原始输出（调试用）


@dataclass
class AgentRunResult:
    task_id: str
    branch: str
    success: bool
    summary: str
    files_changed: list[str] = field(default_factory=list)
    worktree_path: str = ""
    error: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "branch": self.branch,
            "success": self.success,
            "summary": self.summary,
            "files_changed": self.files_changed,
            "worktree_path": self.worktree_path,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 1),
        }


def _resolve_claude_bin() -> str:
    custom = (os.environ.get("CLAUDE_BIN") or "").strip()
    if custom:
        return custom
    found = shutil.which("claude")
    if found:
        return found
    # WinGet 默认安装路径
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    winget_root = local_app / "Microsoft" / "WinGet" / "Packages"
    if winget_root.exists():
        for pkg_dir in winget_root.glob("Anthropic.ClaudeCode*"):
            exe = pkg_dir / "claude.exe"
            if exe.exists():
                return str(exe)
    return "claude"


def _update_task_file(task_path: Path, **kwargs: Any) -> None:
    """幂等更新任务 JSON 文件中的字段。"""
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task.update(kwargs)
        task_path.write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        LOG.warning("task file update failed: %s", exc)


def _git(args: list[str], *, cwd: Path | None = None, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd or _REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _worktree_path(task_id: str) -> Path:
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(task_id)).strip("-") or "unknown"
    return _WORKTREE_ROOT / safe_task_id


def _path_key(path: Path | str) -> str:
    return str(Path(path)).replace("\\", "/").rstrip("/").lower()


def _worktree_entries(stdout: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["worktree"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].replace("refs/heads/", "")
    if current:
        entries.append(current)
    return entries


def _ensure_worktree(task_id: str, branch: str) -> Path:
    """为单个工单准备独立 worktree；不切换根仓工作目录。"""
    worktree = _worktree_path(task_id)
    listed = _git(["worktree", "list", "--porcelain"])
    if listed.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {listed.stderr.strip()}")

    target_key = _path_key(worktree)
    for entry in _worktree_entries(listed.stdout):
        if _path_key(entry.get("worktree", "")) != target_key:
            continue
        if entry.get("branch") == branch:
            return worktree
        raise RuntimeError(
            f"worktree {worktree} already belongs to {entry.get('branch') or 'unknown'}, not {branch}"
        )

    worktree.parent.mkdir(parents=True, exist_ok=True)
    existing_branch = _git(["branch", "--list", branch])
    if existing_branch.returncode != 0:
        raise RuntimeError(f"git branch --list {branch} failed: {existing_branch.stderr.strip()}")

    if existing_branch.stdout.strip():
        cmd = ["worktree", "add", str(worktree), branch]
    else:
        cmd = ["worktree", "add", "-b", branch, str(worktree), "main"]
    created = _git(cmd, timeout=60)
    if created.returncode != 0:
        raise RuntimeError(f"git {' '.join(cmd)} failed: {created.stderr.strip()}")
    return worktree


def _call_claude(
    prompt: str,
    *,
    allowed_tools: str = "Read,Write,Edit,Bash",
    max_turns: int = _AGENT_MAX_TURNS,
    timeout: int = _AGENT_TIMEOUT_SECONDS,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    """统一 Claude CLI 调用入口，返回 (success, output_text)。"""
    claude_bin = _resolve_claude_bin()
    try:
        proc = subprocess.run(
            [
                claude_bin, "--bare", "-p", prompt,
                "--allowedTools", allowed_tools,
                "--max-turns", str(max_turns),
                "--output-format", "json",
            ],
            cwd=str(cwd or _REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        LOG.warning("[CLAUDE TIMEOUT] timeout=%ds", timeout)
        return False, f"(timeout after {timeout}s)"
    except OSError as exc:
        LOG.error("[CLAUDE ERROR] failed to start claude: %s", exc)
        return False, f"(failed to start claude: {exc})"
    return _parse_claude_result(proc.stdout or proc.stderr or "")


def _parse_eval_result(text: str) -> EvalResult:
    """从 Claude 评估阶段输出中解析 JSON，提取 EvalResult。"""
    # 先找 ```json ... ``` 或 ``` ... ``` 代码块
    patterns = [
        r"```json\s*(\{[\s\S]+?\})\s*```",
        r"```\s*(\{[\s\S]+?\})\s*```",
        r"(\{[\s\S]+\})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.MULTILINE)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        raw_tasks = data.get("sub_tasks") or []
        sub_tasks: list[SubTask] = []
        for i, st in enumerate(raw_tasks, 1):
            sub_tasks.append(SubTask(
                index=int(st.get("index") or i),
                title=str(st.get("title") or f"子任务{i}"),
                description=str(st.get("description") or ""),
                files_hint=list(st.get("files_hint") or []),
            ))
        if not sub_tasks:
            sub_tasks = [SubTask(1, "完成整个任务", "按任务描述完成所有内容", [])]
        return EvalResult(
            complexity=str(data.get("complexity") or "medium"),
            risks=list(data.get("risks") or []),
            sub_tasks=sub_tasks,
            notes=str(data.get("notes") or ""),
            raw=text[:500],
        )

    LOG.warning("[EVAL PARSE] JSON not found in eval output, falling back to single sub-task")
    return EvalResult(
        complexity="medium",
        sub_tasks=[SubTask(1, "完成整个任务", "按工单描述完成，无法拆分", [])],
        raw=text[:500],
    )


def _parse_claude_result(stdout: str) -> tuple[bool, str]:
    """从 claude --output-format json 的 stdout 中提取 (success, summary)。"""
    if not stdout:
        return False, "(no output)"
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            if data.get("type") == "result":
                is_error = bool(data.get("is_error"))
                result_text = str(data.get("result") or "").strip()
                return not is_error, result_text or "(empty result)"
        except json.JSONDecodeError:
            pass
    # 降级：返回最后 500 字符
    return True, stdout[-500:]


def run_dev_agent(
    task: dict[str, Any],
    task_path: Path | None = None,
) -> AgentRunResult:
    """同步执行开发 Agent 三阶段流程；用 asyncio.to_thread 包裹以异步调用。

    阶段一（评估+拆分）：Claude 只读代码，输出 JSON 规划，发 webhook。
    阶段二（执行子任务）：每个子任务独立调用 Claude，完成后发 webhook。
    阶段三（汇总）：汇总全部结果，发 webhook 通知完成。
    """
    from task_context import build_eval_context, build_sub_task_context
    from feedback_handler import (
        notify_agent_started,
        notify_eval_split,
        notify_sub_task_done,
        notify_agent_done,
    )

    task_id = task.get("id", "unknown")
    branch = f"agent/{task_id}"
    start = time.time()

    def _elapsed() -> float:
        return time.time() - start

    def _fail(msg: str, *, checkout_back: bool = False) -> AgentRunResult:
        if task_path:
            _update_task_file(
                task_path,
                status="failed",
                error=msg,
                completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
        return AgentRunResult(
            task_id=task_id,
            branch=branch,
            success=False,
            summary="",
            error=msg,
            duration_seconds=_elapsed(),
        )

    # ── 1. 标记为已认领 ──────────────────────────────────────
    if task_path:
        _update_task_file(
            task_path,
            status="claimed",
            claimed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            branch=branch,
        )

    # ═══════════════════════════════════════════════════════
    # PHASE 1: 评估 + 拆分（read-only，不需要分支）
    # ═══════════════════════════════════════════════════════
    LOG.info("=" * 60)
    LOG.info("[PHASE-1 EVAL] task=%s  max_turns=%d  timeout=%ds",
             task_id, _EVAL_MAX_TURNS, _EVAL_TIMEOUT_SECONDS)
    try:
        eval_prompt = build_eval_context(task)
    except Exception as exc:
        return _fail(f"eval context build failed: {exc}")

    eval_success, eval_text = _call_claude(
        eval_prompt,
        allowed_tools="Read,Glob,Grep",
        max_turns=_EVAL_MAX_TURNS,
        timeout=_EVAL_TIMEOUT_SECONDS,
    )
    LOG.info("[PHASE-1 EVAL DONE] success=%s output_bytes=%d", eval_success, len(eval_text))

    eval_result = _parse_eval_result(eval_text)
    n_tasks = len(eval_result.sub_tasks)
    LOG.info(
        "[PHASE-1 RESULT] complexity=%s  sub_tasks=%d  risks=%d",
        eval_result.complexity, n_tasks, len(eval_result.risks),
    )

    try:
        notify_eval_split(eval_result, task)
    except Exception as exc:
        LOG.warning("notify_eval_split failed: %s", exc)

    # ── 2. 创建独立 worktree + 分支 ──────────────────────────
    try:
        worktree = _ensure_worktree(task_id, branch)
    except Exception as exc:
        return _fail(f"git worktree prepare failed: {exc}")

    # ── 3. 标记进行中 + 通知已启动 ────────────────────────────
    if task_path:
        _update_task_file(task_path, status="in_progress", worktree_path=str(worktree))

    try:
        notify_agent_started(task)
    except Exception as exc:
        LOG.debug("notify_agent_started skipped: %s", exc)

    # ═══════════════════════════════════════════════════════
    # PHASE 2: 逐个执行子任务
    # ═══════════════════════════════════════════════════════
    completed_sub_tasks: list[dict[str, Any]] = []
    overall_success = True

    task_with_meta = {**task, "_total_sub_tasks": n_tasks}

    for sub_task in eval_result.sub_tasks:
        LOG.info("=" * 60)
        LOG.info("[PHASE-2 SUB] task=%s  sub=%d/%d  title=%s",
                 task_id, sub_task.index, n_tasks, sub_task.title[:40])

        try:
            sub_prompt = build_sub_task_context(
                {
                    "index": sub_task.index,
                    "title": sub_task.title,
                    "description": sub_task.description,
                    "files_hint": sub_task.files_hint,
                },
                task_with_meta,
                completed_sub_tasks,
            )
        except Exception as exc:
            LOG.error("[PHASE-2 SUB] context build failed: %s", exc)
            sub_success, sub_summary = False, f"(context build failed: {exc})"
        else:
            LOG.info("[PHASE-2 SUB] prompt_bytes=%d  max_turns=%d  timeout=%ds",
                     len(sub_prompt.encode("utf-8")), _AGENT_MAX_TURNS, _AGENT_TIMEOUT_SECONDS)
            sub_success, sub_summary = _call_claude(
                sub_prompt,
                allowed_tools="Read,Write,Edit,Bash",
                max_turns=_AGENT_MAX_TURNS,
                timeout=_AGENT_TIMEOUT_SECONDS,
                cwd=worktree,
            )

        LOG.info("[PHASE-2 SUB DONE] sub=%d/%d  success=%s  summary_bytes=%d",
                 sub_task.index, n_tasks, sub_success, len(sub_summary))

        if not sub_success:
            overall_success = False

        try:
            notify_sub_task_done(
                sub_task.index, n_tasks, sub_task.title, sub_success, sub_summary, task_id
            )
        except Exception as exc:
            LOG.warning("notify_sub_task_done failed: %s", exc)

        completed_sub_tasks.append({
            "index": sub_task.index,
            "title": sub_task.title,
            "success": sub_success,
            "summary": sub_summary[:200],
        })

    # ─── 收集全部修改文件 ──────────────────────────────────
    diff = _git(["diff", "--name-only", "main...HEAD"], cwd=worktree)
    files_changed = [f.strip() for f in diff.stdout.splitlines() if f.strip()]

    duration = _elapsed()

    # ── 汇总 summary ─────────────────────────────────────
    summary_lines = [
        f"子任务{c['index']}: {'完成' if c['success'] else '未完成'} — {c['summary'][:80]}"
        for c in completed_sub_tasks
    ]
    final_summary = "\n".join(summary_lines) or "(无摘要)"

    LOG.info(
        "[ALL DONE] task=%s  overall=%s  sub_tasks=%d  files=%d  duration=%.1fs",
        task_id, overall_success, n_tasks, len(files_changed), duration,
    )

    if task_path:
        _update_task_file(
            task_path,
            status="done" if overall_success else "partial",
            summary=final_summary[:1000],
            files_changed=files_changed,
            worktree_path=str(worktree),
            sub_tasks=[
                {"index": c["index"], "title": c["title"], "success": c["success"]}
                for c in completed_sub_tasks
            ],
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

    result = AgentRunResult(
        task_id=task_id,
        branch=branch,
        success=overall_success,
        summary=final_summary,
        files_changed=files_changed,
        worktree_path=str(worktree),
        duration_seconds=duration,
    )

    try:
        notify_agent_done(result, task)
    except Exception as exc:
        LOG.warning("notify_agent_done failed: %s", exc)

    return result


def enqueue_task(task: dict[str, Any], queue_dir: Path | None = None) -> Path:
    """把任务写入 shared-memory/agent-tasks/ 队列。返回文件路径。"""
    if queue_dir is None:
        queue_dir = _REPO_ROOT / "shared-memory" / "agent-tasks"
    queue_dir.mkdir(parents=True, exist_ok=True)
    task_id = task.get("id", f"task-{int(time.time())}")
    task.setdefault("status", "pending")
    task.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    task_path = queue_dir / f"{task_id}.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    return task_path


def load_pending_tasks(queue_dir: Path | None = None) -> list[tuple[dict[str, Any], Path]]:
    """返回所有 status=pending 的任务列表，每项为 (task_dict, file_path)。"""
    if queue_dir is None:
        queue_dir = _REPO_ROOT / "shared-memory" / "agent-tasks"
    if not queue_dir.exists():
        return []
    results = []
    for p in sorted(queue_dir.glob("*.json")):
        try:
            task = json.loads(p.read_text(encoding="utf-8"))
            if task.get("status") == "pending":
                results.append((task, p))
        except Exception:
            pass
    return results
