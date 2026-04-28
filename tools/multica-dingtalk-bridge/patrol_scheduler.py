#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时巡检调度器：定期扫描 Multica 工单，把符合条件的工单派给开发 Agent。

运行方式（单次，由 Windows Task Scheduler 调用）：
    py patrol_scheduler.py

环境变量：
  MULTICA_BOT_MEMORY_DB      MemoryStore 路径（可选）
  DEV_AGENT_NOTIFY_WEBHOOK   Agent 完成通知 Webhook
  MULTICA_PROJECT_ID         Multica 项目 ID（multica_client 已读取）
  PATROL_INTERVAL_MINUTES    自循环模式下的间隔分钟数（默认 30）；设为 0 则单次运行
  PATROL_AUTO_DISPATCH       设为 1 则自动派单（默认 0 = 只报告不派单）

安全阀：只有打了 agent-ready 标签的工单才会被自动派单。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOG = logging.getLogger("patrol-scheduler")

_REPO_ROOT = _HERE.parent.parent
_QUEUE_DIR = _REPO_ROOT / "shared-memory" / "agent-tasks"
_AGENT_READY_LABELS = {"agent-ready", "agent_ready", "dev-agent", "auto-dispatch"}
_ACTIONABLE_STATUSES = {"todo", "backlog", "open", "unstarted"}


# ── 加载 .env ──────────────────────────────────────────────────────────────────

def _load_env() -> None:
    env_path = _HERE / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
    except Exception as exc:
        LOG.warning("failed to load .env: %s", exc)


# ── 工单筛选 ───────────────────────────────────────────────────────────────────

def _issue_labels(issue: dict[str, Any]) -> set[str]:
    raw = issue.get("labels") or []
    if isinstance(raw, list):
        return {str(lbl).lower() for lbl in raw}
    return set()


def _has_dod(issue: dict[str, Any]) -> bool:
    dod = issue.get("definition_of_done")
    if isinstance(dod, list) and dod:
        return True
    desc = str(issue.get("description") or "")
    return any(tok in desc for tok in ("验收：", "验收:", "DoD:", "DoD：", "definition of done"))


def _is_already_queued(issue_id: str, queue_dir: Path) -> bool:
    """检查队列里是否已存在 pending/claimed/in_progress 的同 ID 任务。"""
    p = queue_dir / f"{issue_id}.json"
    if not p.exists():
        return False
    try:
        task = json.loads(p.read_text(encoding="utf-8"))
        return task.get("status") in {"pending", "claimed", "in_progress"}
    except Exception:
        return False


def _is_agent_ready(issue: dict[str, Any]) -> bool:
    return bool(_issue_labels(issue) & _AGENT_READY_LABELS)


def _build_task(issue: dict[str, Any]) -> dict[str, Any]:
    """把 Multica 工单 dict 转为任务队列 dict。"""
    issue_id = str(issue.get("identifier") or issue.get("id") or "unknown")
    title = str(issue.get("title") or "（无标题）")
    description = str(issue.get("description") or "")
    dod_raw = issue.get("definition_of_done") or []
    dod: list[str] = dod_raw if isinstance(dod_raw, list) else []

    # 从 description 提取验收行（兼容文字格式）
    if not dod and description:
        for line in description.splitlines():
            s = line.strip()
            if s.startswith(("验收：", "验收:", "DoD:", "DoD：")):
                item = s.split(":", 1)[-1].strip() if ":" in s else s.split("：", 1)[-1].strip()
                if item:
                    dod.append(item)

    return {
        "id": issue_id,
        "title": title,
        "description": description,
        "definition_of_done": dod,
        "category": str(issue.get("stateType") or issue.get("category") or "task"),
        "priority": str(issue.get("priority") or "medium"),
        "project_hint": str(issue.get("project") or ""),
        "multica_labels": list(_issue_labels(issue)),
        "source": "patrol",
    }


# ── 主巡检逻辑 ─────────────────────────────────────────────────────────────────

async def run_patrol(*, auto_dispatch: bool = False) -> dict[str, Any]:
    """执行一轮巡检。返回巡检摘要 dict。"""
    from multica_client import MulticaClient

    client = MulticaClient()
    result = await client.list_issues(limit=500)

    if not result.ok:
        LOG.warning("multica list_issues failed: %s", result)
        return {"ok": False, "error": "multica CLI failed", "dispatched": 0}

    raw = result.data or {}
    if isinstance(raw, list):
        all_issues = raw
    elif isinstance(raw, dict):
        all_issues = raw.get("issues") or []
    else:
        all_issues = []

    issues = [i for i in all_issues if isinstance(i, dict)]
    total = len(issues)

    # 筛选可派工单
    actionable = [
        i for i in issues
        if str(i.get("status") or i.get("state") or "").lower() in _ACTIONABLE_STATUSES
        or str(i.get("stateType") or "").lower() in {"unstarted", "unprocessed", "backlog"}
    ]
    with_dod = [i for i in actionable if _has_dod(i)]
    agent_ready = [i for i in with_dod if _is_agent_ready(i)]

    LOG.info(
        "patrol: total=%d actionable=%d with_dod=%d agent_ready=%d",
        total, len(actionable), len(with_dod), len(agent_ready),
    )

    if not agent_ready:
        return {
            "ok": True,
            "total": total,
            "actionable": len(actionable),
            "with_dod": len(with_dod),
            "agent_ready": 0,
            "dispatched": 0,
            "skipped": 0,
        }

    dispatched = 0
    skipped = 0
    _QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    for issue in agent_ready:
        issue_id = str(issue.get("identifier") or issue.get("id") or "")
        if not issue_id:
            continue
        if _is_already_queued(issue_id, _QUEUE_DIR):
            LOG.info("skipping already-queued issue: %s", issue_id)
            skipped += 1
            continue

        if not auto_dispatch:
            LOG.info("found agent-ready issue %s (auto_dispatch=off, skipping)", issue_id)
            skipped += 1
            continue

        # 写入队列并触发 Agent
        task = _build_task(issue)
        from dev_agent_runner import enqueue_task, run_dev_agent
        from feedback_handler import comment_on_multica_issue, notify_agent_done

        task_path = enqueue_task(task, _QUEUE_DIR)
        LOG.info("dispatching issue %s to dev agent", issue_id)

        try:
            agent_result = await asyncio.to_thread(run_dev_agent, task, task_path)
        except Exception as exc:
            LOG.error("agent run failed for %s: %s", issue_id, exc)
            continue

        try:
            notify_agent_done(agent_result, task)
        except Exception as exc:
            LOG.warning("notify failed: %s", exc)

        try:
            comment_on_multica_issue(agent_result, task)
        except Exception:
            pass

        dispatched += 1

    return {
        "ok": True,
        "total": total,
        "actionable": len(actionable),
        "with_dod": len(with_dod),
        "agent_ready": len(agent_ready),
        "dispatched": dispatched,
        "skipped": skipped,
    }


async def _patrol_loop(interval_minutes: int, auto_dispatch: bool) -> None:
    """持续巡检循环（适合长驻进程模式，不推荐用于 Task Scheduler）。"""
    while True:
        try:
            summary = await run_patrol(auto_dispatch=auto_dispatch)
            LOG.info("patrol summary: %s", json.dumps(summary, ensure_ascii=False))
        except Exception as exc:
            LOG.error("patrol loop error: %s", exc)
        await asyncio.sleep(interval_minutes * 60)


def main() -> None:
    _load_env()

    interval = int(os.environ.get("PATROL_INTERVAL_MINUTES", "0"))
    auto_dispatch = os.environ.get("PATROL_AUTO_DISPATCH", "0").strip() == "1"

    LOG.info(
        "patrol_scheduler starting: interval=%d auto_dispatch=%s",
        interval,
        auto_dispatch,
    )

    if interval > 0:
        # 持续循环模式（一般不用，Task Scheduler 单次调用更稳）
        asyncio.run(_patrol_loop(interval, auto_dispatch))
    else:
        # 单次执行
        summary = asyncio.run(run_patrol(auto_dispatch=auto_dispatch))
        LOG.info("patrol done: %s", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
