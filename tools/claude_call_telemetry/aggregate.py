# -*- coding: utf-8 -*-
"""按日汇总 JSONL：任务数、调用次数、按 caller 分布、危险词命中次数。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from claude_call_telemetry.telemetry import default_log_dir  # noqa: E402


def _parse_args() -> argparse.Namespace:
    tz = timezone(timedelta(hours=8))
    default_day = datetime.now(tz).strftime("%Y-%m-%d")
    p = argparse.ArgumentParser(description="汇总 Claude 调用 JSONL（按日）")
    p.add_argument("--date", default=default_day, help="YYYY-MM-DD，默认今天（东八区）")
    p.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="日志目录，默认与 telemetry.default_log_dir() 一致",
    )
    return p.parse_args()


def aggregate_day(log_path: Path) -> None:
    if not log_path.exists():
        print(f"no file: {log_path}")
        return

    tasks: set[str] = set()
    calls = 0
    by_caller: Counter[str] = Counter()
    danger_hits = 0
    status_cnt: Counter[str] = Counter()
    calls_per_task: defaultdict[str, int] = defaultdict(int)
    duration_sum = 0
    tokens_in = 0
    tokens_out = 0
    token_rows = 0

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        calls += 1
        tid = str(rec.get("task_id") or "")
        if tid:
            tasks.add(tid)
            calls_per_task[tid] += 1
        by_caller[str(rec.get("caller") or "unknown")] += 1
        status_cnt[str(rec.get("status") or "unknown")] += 1
        duration_sum += int(rec.get("duration_ms") or 0)
        if rec.get("dangerous_keywords_hit"):
            danger_hits += 1
        pin = rec.get("prompt_tokens")
        pout = rec.get("output_tokens")
        if pin is not None:
            try:
                tokens_in += int(pin)
                token_rows += 1
            except (TypeError, ValueError):
                pass
        if pout is not None:
            try:
                tokens_out += int(pout)
            except (TypeError, ValueError):
                pass

    n_tasks = len(tasks)
    avg_calls = (calls / n_tasks) if n_tasks else 0.0
    max_task = ""
    max_n = 0
    for tid, n in calls_per_task.items():
        if n > max_n:
            max_n = n
            max_task = tid

    print(f"file: {log_path}")
    print(f"distinct_tasks: {n_tasks}")
    print(f"total_calls: {calls}")
    print(f"avg_calls_per_task: {avg_calls:.2f}")
    if max_task:
        print(f"max_calls_in_one_task: {max_n} (task_id={max_task})")
    print(f"dangerous_keyword_rows: {danger_hits}")
    print("status:", dict(status_cnt))
    print("by_caller:", dict(by_caller))
    if calls:
        print(f"avg_duration_ms: {duration_sum / calls:.0f}")
    if token_rows:
        print(f"prompt_tokens_sum_partial: {tokens_in} (rows with input: {token_rows})")
        print(f"output_tokens_sum_partial: {tokens_out}")


def main() -> None:
    args = _parse_args()
    log_dir = args.log_dir or default_log_dir()
    path = log_dir / f"calls-{args.date}.jsonl"
    aggregate_day(path)


if __name__ == "__main__":
    main()
