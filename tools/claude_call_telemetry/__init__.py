# -*- coding: utf-8 -*-
"""Claude 调用可观测：按 task_id 聚合多次调用，JSONL 落盘。"""

from .telemetry import (
    call_claude_with_telemetry,
    default_log_dir,
    next_call_index,
    scan_dangerous_keywords,
)

__all__ = [
    "call_claude_with_telemetry",
    "default_log_dir",
    "next_call_index",
    "scan_dangerous_keywords",
]
