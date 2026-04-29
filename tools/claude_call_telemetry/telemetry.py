# -*- coding: utf-8 -*-
# [AgentTel Task] 开始时间: 2026-04-29
# [AgentTel Task] 任务目标: Claude 调用 JSONL 遥测（task_id + call_index + 痛点字段）
"""封装 `claude` 子进程调用，并追加 JSONL 遥测记录。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# 与 prompt 文本匹配（小写），命中即记入 dangerous_keywords_hit
_DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"git\s+reset\s+--hard", "git reset --hard"),
    (r"git\s+clean\s+-fd", "git clean -fd"),
    (r"push\s+--force", "push --force"),
    (r"git\s+push[^;\n]*--force", "git push --force"),
    (r"--force\s+push", "force push"),
    (r"rm\s+-rf", "rm -rf"),
    (r"format\s+c\s*:", "format c:"),
    (r"del\s+/[fsq]", "del /f/s/q"),
    (r"rmdir\s+/s", "rmdir /s"),
    (r"chmod\s+777", "chmod 777"),
)


def default_log_dir() -> Path:
    env = os.environ.get("CLAUDE_CALL_LOG_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "shared-memory" / "claude-calls"


def _today_log_path(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    tz = timezone(timedelta(hours=8))
    day = datetime.now(tz).strftime("%Y-%m-%d")
    return log_dir / f"calls-{day}.jsonl"


def next_call_index(log_path: Path, task_id: str) -> int:
    """扫描当日文件，取该 task_id 的最大 call_index + 1。"""
    if not log_path.exists():
        return 1
    max_idx = 0
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 1
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("task_id") != task_id:
            continue
        try:
            idx = int(rec.get("call_index") or 0)
        except (TypeError, ValueError):
            idx = 0
        max_idx = max(max_idx, idx)
    return max_idx + 1


def scan_dangerous_keywords(text: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    hits: list[str] = []
    for pattern, label in _DANGEROUS_PATTERNS:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            if label not in hits:
                hits.append(label)
    return hits


def _extract_usage_from_json_obj(obj: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        msg = obj.get("message")
        if isinstance(msg, dict):
            usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None, None
    inp = usage.get("input_tokens")
    if inp is None:
        inp = usage.get("prompt_tokens")
    out = usage.get("output_tokens")
    if out is None:
        out = usage.get("completion_tokens")
    try:
        inp_i = int(inp) if inp is not None else None
    except (TypeError, ValueError):
        inp_i = None
    try:
        out_i = int(out) if out is not None else None
    except (TypeError, ValueError):
        out_i = None
    return inp_i, out_i


def parse_token_usage_from_claude_stdout(stdout: str) -> tuple[int | None, int | None]:
    """从 claude --print --output-format json 的多行 JSON 输出中尽量提取 token。"""
    best_in: int | None = None
    best_out: int | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        inp, out = _extract_usage_from_json_obj(obj)
        if inp is not None:
            best_in = inp
        if out is not None:
            best_out = out
    return best_in, best_out


def _append_jsonl(log_path: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)


def call_claude_with_telemetry(
    *,
    cmd: list[str],
    cwd: str | Path,
    env: dict[str, str],
    timeout: float | int,
    task_id: str,
    caller: str,
    task_title: str | None = None,
    call_index: int | None = None,
    log_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    执行 cmd（通常为 claude + 参数 + prompt），写一条 JSONL 后返回 CompletedProcess。

    task_id 由上游为「老大的一条任务」生成并在多次调用中复用；
    call_index 省略时按当日日志中该 task_id 自动递增。
    """
    log_root = log_dir or default_log_dir()
    log_path = _today_log_path(log_root)

    tid = (task_id or "").strip() or f"auto-{uuid.uuid4().hex[:12]}"
    idx = call_index if call_index is not None else next_call_index(log_path, tid)

    prompt_text = ""
    if cmd:
        prompt_text = str(cmd[-1])

    started = time.perf_counter()
    status = "ok"
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    proc: subprocess.CompletedProcess[str]

    def _write_record() -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        pin, pout = parse_token_usage_from_claude_stdout(stdout)
        hits = scan_dangerous_keywords(prompt_text)
        title = (task_title or "").strip()
        title_out = title if len(title) <= 200 else title[:197] + "..."
        digest = hashlib.sha256(
            prompt_text.encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        record: dict[str, Any] = {
            "ts": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "task_id": tid,
            "call_index": idx,
            "caller": caller,
            "task_title": title_out or None,
            "prompt_sha256_16": digest,
            "prompt_chars": len(prompt_text),
            "duration_ms": duration_ms,
            "status": status,
            "exit_code": exit_code,
            "dangerous_keywords_hit": hits,
            "prompt_tokens": pin,
            "output_tokens": pout,
            "stdout_chars": len(stdout),
            "stderr_tail": (stderr or "")[-400:] if stderr else "",
        }
        try:
            _append_jsonl(log_path, record)
        except OSError:
            pass

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if exit_code != 0:
            status = "error"
        _write_record()
        return proc
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = None
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else str(exc)
        _write_record()
        raise
    except OSError as exc:
        status = "error"
        exit_code = None
        stderr = str(exc)
        proc = subprocess.CompletedProcess(args=cmd, returncode=-1, stdout="", stderr=stderr)
        stdout = ""
        _write_record()
        raise
