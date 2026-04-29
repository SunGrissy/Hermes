# -*- coding: utf-8 -*-
"""主 webhook（DEV_AGENT_NOTIFY_WEBHOOK / cursor_session）投递范围。

MULTICA_WEBHOOK_NOTIFY_SCOPE（默认 review_and_failures）：
- review_and_failures：只发「审查完毕」+「运行/工单失败」+「自动合并冲突」等阻塞类；
  不发 Claude 工作中/完成、待审查、已完成、审查通过、Agent 启动/规划/进度等噪音。
- all：恢复此前「状态与 run 全量通知」行为。
"""
from __future__ import annotations

import os

_MINIMAL_ALIASES = frozenset(
    {"review_and_failures", "minimal", "quiet", "review_and_failure"}
)


def webhook_notify_scope() -> str:
    raw = (os.environ.get("MULTICA_WEBHOOK_NOTIFY_SCOPE") or "review_and_failures").strip().lower()
    if raw in _MINIMAL_ALIASES:
        return "review_and_failures"
    return "all"


def is_minimal_webhook_scope() -> bool:
    return webhook_notify_scope() == "review_and_failures"
