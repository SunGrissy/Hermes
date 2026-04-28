#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""钉钉 Stream 机器人收消息 -> multica issue create / 删除派单 / 查工单 等。运行前须 multica login 且 multica 在 PATH。"""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dingtalk_stream import AckMessage
import dingtalk_stream

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_a, **_k):
        return False

LOG = logging.getLogger("multica-bridge")

# [AgentMultica Task] 2026-04-22 钉钉群 @ 机器人后正文不以「派单」开头导致解析不命中
_AT_BEFORE_MULTICA_CMD = re.compile(
    r"^@.+?(?=(?:#删除派单|删除派单|#取消派单|取消派单|#查工单|查工单|#派单|派单|#队列巡查|队列巡查|#巡查工单|巡查工单|#multica巡查|multica巡查|#巡查|巡查|就按这个派|确认派单|按这个派|可以派|#派给Agent|派给Agent))"
)


def _normalize_dingtalk_at_prefixes(raw: str) -> str:
    """去掉群聊里 leading 的 @昵称，使「@机器人 派单」与「派单」走同一套前缀匹配。

    Hermes 钉钉适配器会保留 @ 文本给主 Agent；派单/删单/查单只认固定前缀，故在此统一剥掉。
    先尝试「@… 直到关键字」无空格形态（@机器人派单），再尝试「@token + 空白」分段剥离。
    """
    s = (raw or "").strip()
    for _ in range(8):
        if not s.startswith("@"):
            break
        m = _AT_BEFORE_MULTICA_CMD.match(s)
        if m:
            s = s[m.end() :].lstrip()
            continue
        m2 = re.match(r"^@\S+\s+", s)
        if m2:
            s = s[m2.end() :].lstrip()
            continue
        break
    return s


_DELETE_DISPATCH_HELP = (
    "🗑️ **请指定要取消的工单**\n\n"
    "Multica 无物理删除；本操作会把工单状态设为 **已取消**（`cancelled`）。\n\n"
    "**格式样例**\n\n"
    "- `删除派单 UUM-10` 或 `删除派单 10`（短号对应当前列表里的 **number**）\n"
    "- **多个**：`删除派单 1、2、6` 或 `删除派单 UUM-1, UUM-2`（顿号、中英文逗号/分号、空白均可分隔，最多 **50** 条）\n"
    "- 也支持：`#删除派单`、`取消派单` / `#取消派单`\n"
    "- 可直接写 Issue 的 **UUID**\n"
)

_EMPTY_DISPATCH_HELP = (
    "📝 **请先写标题**\n\n"
    "第一行紧跟在「派单」后面写标题，从第二行起写描述。\n\n"
    "**格式样例**\n\n"
    "```\n"
    "派单 验收：登录页白屏\n"
    "复现：iOS 17，4G\n"
    "期望：正常进入首页\n"
    "```\n\n"
    "也支持：`#派单 标题`（第二行起同上，为描述）。\n\n"
    "取消工单：`删除派单 UUM-9` 或 `删除派单 9`（详见「删除派单」仅一行时的提示）。\n\n"
    "查询：`查工单` 或 `#查工单` — 状态分布 + 按优先级前 10（不含已取消；同档按创建时间由远及近）。"
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_ISSUE_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")
_DELETE_TOKEN_SPLIT_RE = re.compile(r"[\s、,，;；]+")


def _read_multica_app_url() -> str:
    """用于回复里的网页入口；优先本机 multica 配置，其次环境变量。"""
    p = Path.home() / ".multica" / "config.json"
    if p.is_file():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            u = cfg.get("app_url")
            if isinstance(u, str) and u.strip():
                return u.strip().rstrip("/")
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return (os.environ.get("MULTICA_APP_URL") or "https://multica.ai").strip().rstrip("/")


def _issue_page_url_from_create_json(data: dict, identifier: str) -> Optional[str]:
    """若建单 JSON 含网页 URL 则直接使用。"""
    for key in ("html_url", "web_url", "url", "issue_url", "permalink"):
        v = data.get(key)
        if isinstance(v, str) and (v.startswith("https://") or v.startswith("http://")):
            return v.strip().rstrip("/")
    return None


def _issue_page_url_for_reply(data: dict, identifier: str) -> Tuple[str, bool]:
    """返回 (链接, 是否为直达工单页)。无 workspace 路径时退回应用根 URL。"""
    u = _issue_page_url_from_create_json(data, identifier)
    if u:
        return u, True
    seg = (os.environ.get("MULTICA_WORKSPACE_WEB_PATH") or "").strip().strip("/")
    base = _read_multica_app_url().rstrip("/")
    if seg:
        return f"{base}/{seg}/issues/{identifier}", True
    return base, False


def _dispatch_reply_separator() -> str:
    return "——————————————"


def _format_dispatch_create_reply(
    identifier: str,
    title: str,
    description: str,
    data: dict,
    counts: Dict[str, int],
) -> str:
    """建单成功：与产品约定的钉钉 Markdown 版式（编号置顶、分隔线、直链、仅待办数）。"""
    sep = _dispatch_reply_separator()
    issue_url, _ = _issue_page_url_for_reply(data, identifier)
    t = (title or "").strip()
    if len(t) > 300:
        t = t[:297] + "..."
    desc_raw = (description or "").strip()
    if desc_raw == "（钉钉派单，无额外描述）" or not desc_raw:
        desc_raw = "（无额外描述）"
    if len(desc_raw) > 500:
        desc_raw = desc_raw[:497] + "..."
    n_todo = counts.get("todo", 0)
    todo_line = "—" if n_todo < 0 else str(max(0, n_todo))
    click = f"[点击查看]({issue_url})"
    return "\n".join(
        [
            f"📋 编号 `{identifier}`",
            "",
            sep,
            "",
            "✅ 工单已写入 Multica（todo / medium）",
            f"📝 标题 {t}",
            f"📄 描述 {desc_raw}",
            "",
            click,
            "",
            sep,
            "",
            "📊 工单总览",
            f"待办：{todo_line}",
        ]
    )


_ISSUE_STATUS_ORDER = (
    "todo",
    "in_progress",
    "in_review",
    "backlog",
    "done",
    "blocked",
    "cancelled",
)

_ISSUE_STATUS_LABEL = {
    "todo": "待办",
    "in_progress": "进行中",
    "in_review": "评审中",
    "backlog": "待排期",
    "done": "已完成",
    "blocked": "阻塞",
    "cancelled": "已取消",
}


def _issue_list_project_args() -> tuple[str, ...]:
    proj = (os.environ.get("MULTICA_PROJECT_ID") or "").strip()
    if proj:
        return ("--project", proj)
    return ()


async def _multica_issue_list_json(
    multica_bin: str,
    env: dict,
    extra_args: tuple[str, ...],
    limit: int = 1,
) -> Optional[dict]:
    """执行 `multica issue list`，返回解析后的 JSON 对象。"""
    lim = max(1, min(int(limit), 500))
    cmd = [
        multica_bin,
        "issue",
        "list",
        "--output",
        "json",
        "--limit",
        str(lim),
        *extra_args,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    out_b, err_b = await proc.communicate()
    if proc.returncode != 0:
        LOG.warning(
            "multica issue list rc=%s args=%s stderr=%s",
            proc.returncode,
            extra_args,
            _redact_sensitive_text(
                (err_b or b"").decode("utf-8", errors="replace")[:400]
            ),
        )
        return None
    text = (out_b or b"").decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


async def _multica_issue_search_json(
    multica_bin: str,
    env: dict,
    query: str,
    *,
    limit: int = 50,
    include_closed: bool = False,
) -> Optional[list]:
    """执行 `multica issue search <query>`，返回 issues 列表。"""
    cmd = [
        multica_bin, "issue", "search", query,
        "--output", "json",
        "--limit", str(max(1, min(100, limit))),
    ]
    if include_closed:
        cmd.append("--include-closed")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    out_b, err_b = await proc.communicate()
    if proc.returncode != 0:
        LOG.warning(
            "multica issue search rc=%s query=%r stderr=%s",
            proc.returncode,
            query[:80],
            _redact_sensitive_text((err_b or b"").decode("utf-8", errors="replace")[:300]),
        )
        return None
    text = (out_b or b"").decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return obj.get("issues") or obj.get("results") or []
    return None


async def _fetch_workspace_issue_stats(
    multica_bin: str, env: dict
) -> Tuple[Optional[int], Dict[str, int]]:
    """拉取当前 workspace（及可选 project）工单总数与各状态数量；各状态一次 list，limit=1 读 total。"""
    proj_suffix = _issue_list_project_args()
    base = await _multica_issue_list_json(multica_bin, env, proj_suffix)
    total: Optional[int] = None
    if base is not None:
        t = base.get("total")
        if isinstance(t, int):
            total = t

    async def count_one(status: str) -> Tuple[str, int]:
        args = proj_suffix + ("--status", status)
        d = await _multica_issue_list_json(multica_bin, env, args)
        if d is None:
            return status, -1
        n = d.get("total")
        return status, int(n) if isinstance(n, int) else 0

    pairs = await asyncio.gather(*(count_one(s) for s in _ISSUE_STATUS_ORDER))
    counts: Dict[str, int] = {st: n for st, n in pairs}
    return total, counts


def _format_issue_stats_md(total: Optional[int], counts: Dict[str, int]) -> str:
    """生成「工单概况 + 状态分布」Markdown 片段。"""
    lines = ["📊 **工单概况**", ""]
    if total is not None:
        lines.append(f"当前 Workspace 共有 **{total}** 条工单。")
    else:
        lines.append("当前工单总数暂时无法从接口读取。")

    lines.extend(["", "📌 **状态分布**", ""])
    any_pos = False
    any_err = False
    for st in _ISSUE_STATUS_ORDER:
        n = counts.get(st, 0)
        if n < 0:
            any_err = True
            continue
        if n > 0:
            label = _ISSUE_STATUS_LABEL.get(st, st)
            lines.append(f"- {label}（`{st}`）：**{n}**")
            any_pos = True
    if not any_pos and not any_err:
        lines.append("- （各状态均为 0）")
    if any_err:
        lines.append("- 部分状态统计失败，请以 Multica 网页看板为准。")

    if total is not None and not any_err:
        pos_sum = sum(max(0, counts.get(s, 0)) for s in _ISSUE_STATUS_ORDER)
        if pos_sum != total:
            lines.append("")
            lines.append(
                f"> 说明：各状态合计 **{pos_sum}**，接口 total=**{total}**；若不一致以网页看板为准。"
            )

    return "\n".join(lines)


_PRIORITY_WEIGHT = {
    "urgent": 6,
    "critical": 6,
    "high": 5,
    "medium": 4,
    "low": 3,
}

_PRIORITY_LABEL_ZH = {
    "urgent": "紧急",
    "critical": "紧急",
    "high": "高",
    "medium": "中",
    "low": "低",
}


def _is_query_issues_command(raw: str) -> bool:
    s = (raw or "").strip()
    return s in ("查工单", "#查工单")


_DISPATCH_AGENT_RE = re.compile(
    r"^(?:#派给Agent|派给Agent)\s+([A-Za-z0-9_/-]+)"       # 「派给Agent UUM-24」
    r"|^([A-Z]+-\d+)\s*[，,]?\s*(?:#派给Agent|派给Agent)\s*$",  # 「UUM-24，派给Agent」
    re.IGNORECASE,
)

# @bot<id>派给Agent 场景：@昵称紧跟 issue-id，issue-id 后接命令关键字
_AT_ISSUE_DISPATCH_RE = re.compile(
    r"^@\S*?([A-Z]+-\d+)\s*[，,]?\s*(?:#派给Agent|派给Agent)\s*$",
    re.IGNORECASE,
)


def _strip_dispatch_to_agent_prefix(raw: str) -> Optional[str]:
    """若匹配派给Agent命令则返回 issue-id，支持三种写法：
    1. `派给Agent UUM-24`   2. `UUM-24 派给Agent`   3. `@bot<id>派给Agent`
    """
    s = (raw or "").strip()
    # 优先处理 @botUUM-24派给Agent（@剥离前就先提取 ID）
    m_at = _AT_ISSUE_DISPATCH_RE.match(s)
    if m_at:
        return m_at.group(1).strip()
    m = _DISPATCH_AGENT_RE.match(s)
    if m:
        return (m.group(1) or m.group(2) or "").strip()
    return None


def _is_patrol_command(raw: str) -> bool:
    s = (raw or "").strip()
    return s in {
        "巡查",
        "#巡查",
        "队列巡查",
        "#队列巡查",
        "巡查工单",
        "#巡查工单",
        "multica巡查",
        "#multica巡查",
        "Multica巡查",
        "#Multica巡查",
    }


def _is_free_query(raw: str) -> bool:
    """检测自然语言查询意图（排除已被精确路由处理的"查工单"）。"""
    t = (raw or "").strip()
    if not t or _is_query_issues_command(t):
        return False
    has_object = any(kw in t for kw in ("工单", "issue", "Issue"))
    has_trigger = any(kw in t for kw in ("查", "看看", "显示", "列出", "搜", "找"))
    return has_object and has_trigger


def _priority_weight_value(p: object) -> int:
    if not isinstance(p, str):
        return 0
    return _PRIORITY_WEIGHT.get(p.strip().lower(), 0)


def _priority_label_zh(p: object) -> str:
    if not isinstance(p, str) or not p.strip():
        return "未设"
    k = p.strip().lower()
    return _PRIORITY_LABEL_ZH.get(k, p.strip())


def _issue_created_sort_key(iso: object) -> str:
    """同优先级内由远及近：无创建时间的排在同档最后。"""
    if isinstance(iso, str) and iso.strip():
        return iso.strip()
    return "9999-12-31T23:59:59Z"


def _sort_issues_priority_then_created(issues: List[dict]) -> List[dict]:
    """优先级从高到低，同优先级按 created_at 升序（越早越靠前）。"""
    items = [x for x in issues if isinstance(x, dict)]
    return sorted(
        items,
        key=lambda it: (
            -_priority_weight_value(it.get("priority")),
            _issue_created_sort_key(it.get("created_at")),
        ),
    )


def _format_query_issues_reply_body(
    stats_md: str,
    top_issues: list,
    *,
    has_more: bool,
    fetched_len: int,
    total: Optional[int],
) -> str:
    sep = _dispatch_reply_separator()
    lines_out: List[str] = [
        stats_md,
        "",
        sep,
        "",
        "📌 **按优先级前 10**（**不含已取消**；同档按**创建时间**由远及近）",
        "",
    ]
    if not top_issues:
        lines_out.append("（当前无工单）")
    else:
        for i, it in enumerate(top_issues, 1):
            ident = it.get("identifier") or it.get("id") or "?"
            if not isinstance(ident, str):
                ident = str(ident)
            pr = _priority_label_zh(it.get("priority"))
            st = it.get("status")
            st_label = _ISSUE_STATUS_LABEL.get(st, st) if isinstance(st, str) else "?"
            ca = it.get("created_at")
            date_s = (ca[:10] if isinstance(ca, str) and len(ca) >= 10 else "—")
            title = it.get("title") if isinstance(it.get("title"), str) else ""
            title = title.strip() or "（无标题）"
            if len(title) > 44:
                title = title[:41] + "..."
            lines_out.append(
                f"{i}. `{ident}` · {pr} · {st_label} · {date_s} · {title}"
            )
    if has_more:
        lines_out.append("")
        if isinstance(total, int) and total > fetched_len:
            lines_out.append(
                f"> 注：本次仅取前 **{fetched_len}** 条参与排序；Workspace 合计约 **{total}** 条，其余未纳入「前 10」计算。"
            )
        else:
            lines_out.append(
                f"> 注：接口 `has_more=true`，本次仅拉取 **{fetched_len}** 条参与排序。"
            )
    return "\n".join(lines_out)


def _sort_issues_by_spec(issues: List[dict], sort_by: str) -> List[dict]:
    """按 IssueQuerySpec.sort_by 对工单列表排序。"""
    items = [x for x in issues if isinstance(x, dict)]
    if sort_by == "created_asc":
        return sorted(items, key=lambda x: x.get("created_at") or "")
    if sort_by == "updated_desc":
        return sorted(items, key=lambda x: x.get("updated_at") or "", reverse=True)
    if sort_by == "priority_desc":
        return sorted(
            items,
            key=lambda x: (
                -_priority_weight_value(x.get("priority")),
                x.get("created_at") or "",
            ),
        )
    # created_desc (default)
    return sorted(items, key=lambda x: x.get("created_at") or "", reverse=True)


def _format_free_query_reply(
    spec_desc: str,
    issues: List[dict],
    total_fetched: int,
) -> str:
    """格式化自由查询结果。"""
    lines: List[str] = [f"**{spec_desc}**", ""]
    if not issues:
        lines.append("（未找到符合条件的工单）")
        return "\n".join(lines)
    for i, it in enumerate(issues, 1):
        ident = it.get("identifier") or it.get("id") or "?"
        if not isinstance(ident, str):
            ident = str(ident)
        pr = _priority_label_zh(it.get("priority"))
        st = it.get("status")
        st_label = _ISSUE_STATUS_LABEL.get(st, st) if isinstance(st, str) else "?"
        assignee = it.get("assignee") or ""
        if isinstance(assignee, dict):
            assignee = assignee.get("name") or assignee.get("username") or "未分配"
        elif not isinstance(assignee, str) or not assignee.strip():
            assignee = "未分配"
        ca = it.get("created_at")
        date_s = ca[:10] if isinstance(ca, str) and len(ca) >= 10 else "—"
        title = it.get("title") if isinstance(it.get("title"), str) else ""
        title = title.strip() or "（无标题）"
        if len(title) > 44:
            title = title[:41] + "..."
        lines.append(f"{i}. `{ident}` · {pr} · {st_label} · {assignee} · {date_s} · {title}")
    if total_fetched > len(issues):
        lines.append("")
        lines.append(f"> 共拉取 **{total_fetched}** 条参与筛选，展示前 **{len(issues)}** 条。")
    return "\n".join(lines)


def _strip_delete_dispatch_prefix(raw: str) -> Optional[str]:
    """命中「删除派单 / 取消派单」前缀时返回其后正文，否则 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    for prefix in (
        "#删除派单",
        "删除派单",
        "#取消派单",
        "取消派单",
    ):
        if s.startswith(prefix):
            return s[len(prefix) :].lstrip()
    return None


def _parse_delete_dispatch_tokens(rest: str) -> List[str]:
    """删除口令后的多个引用：顿号、中英文逗号/分号及空白分隔；去重保序，最多 50 个。"""
    chunks: List[str] = []
    for ln in (rest or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        for part in _DELETE_TOKEN_SPLIT_RE.split(s):
            t = part.strip()
            if t:
                chunks.append(t)
    seen: set[str] = set()
    out: List[str] = []
    for t in chunks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:50]


async def _resolve_issue_ref_for_status(
    multica_bin: str,
    env: dict,
    token: str,
    issues_cache: Optional[List[dict]] = None,
) -> Optional[str]:
    """解析为 `multica issue status` 可用的 id：UUID、UUM-n 标识，或短数字 number（在列表前 500 条内查找）。"""
    t = (token or "").strip()
    if not t:
        return None
    if _UUID_RE.match(t):
        return t
    if _ISSUE_IDENT_RE.match(t):
        return t
    if t.isdigit():
        n = int(t)
        if n < 1:
            return None

        def _find_ident_in(issues: List[dict]) -> Optional[str]:
            for it in issues:
                if isinstance(it, dict) and it.get("number") == n:
                    ident = it.get("identifier")
                    if isinstance(ident, str) and ident.strip():
                        return ident.strip()
            return None

        if issues_cache is not None:
            return _find_ident_in(issues_cache)

        proj = _issue_list_project_args()
        d = await _multica_issue_list_json(multica_bin, env, proj, limit=500)
        if not d:
            return None
        issues = d.get("issues")
        if not isinstance(issues, list):
            return None
        return _find_ident_in([x for x in issues if isinstance(x, dict)])
    return None


async def _multica_issue_set_cancelled(
    multica_bin: str, env: dict, issue_ref: str
) -> Tuple[int, str, str, Optional[dict]]:
    """执行 `multica issue status <ref> cancelled --output json`，返回 (rc, stdout, stderr, json或None)。"""
    cmd = [
        multica_bin,
        "issue",
        "status",
        issue_ref,
        "cancelled",
        "--output",
        "json",
    ]
    proj = (os.environ.get("MULTICA_PROJECT_ID") or "").strip()
    if proj:
        cmd.extend(["--project", proj])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    out_b, err_b = await proc.communicate()
    out = (out_b or b"").decode("utf-8", errors="replace")
    err = (err_b or b"").decode("utf-8", errors="replace")
    rc = int(proc.returncode or 0)
    data: Optional[dict] = None
    if rc == 0:
        data = _parse_create_stdout(out)
    return rc, out, err, data


def _parse_create_stdout(stdout: str) -> Optional[dict]:
    s = (stdout or "").strip()
    if not s:
        return None
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _resolve_multica_binary() -> Optional[str]:
    """定位 multica 可执行文件：环境变量 MULTICA_BIN → PATH → Windows 默认安装目录。"""
    explicit = (os.environ.get("MULTICA_BIN") or os.environ.get("MULTICA_EXECUTABLE") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p.resolve())
    w = shutil.which("multica") or shutil.which("multica.exe")
    if w:
        return w
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            guess = Path(local) / "Programs" / "multica" / "multica.exe"
            if guess.is_file():
                return str(guess.resolve())
    return None


def _strip_dispatch_prefix(raw: str) -> Optional[str]:
    """命中 `#派单` 或 `派单` 开头时返回标题与描述部分，否则 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith("#派单"):
        return s[len("#派单") :].lstrip()
    if s.startswith("派单"):
        return s[len("派单") :].lstrip()
    return None


_BRAIN_ROUTE_KEYWORDS = (
    "需求",
    "怎么派",
    "派单",
    "派单建议",
    "工单",
    "验收",
    "完成标准",
    "DoD",
    "dod",
    "Multica",
    "multica",
    "队列管家",
    "分给",
    "派给",
    "指派给",
)

# 自然语言指派：「UUM-24，分给克劳德」「把UUM-24派给张三」「UUM-24 指派给 李明」
_ASSIGN_ISSUE_RE = re.compile(
    r"(?:把\s*)?([A-Z]+-\d+)\s*[，,]?\s*(?:分给|派给|指派给|assign\s+to)\s*(.+)$",
    re.IGNORECASE,
)


def _parse_assign_issue_command(raw: str) -> Optional[tuple[str, str]]:
    """返回 (issue_id, assignee_name)，未匹配返回 None。"""
    s = (raw or "").strip()
    m = _ASSIGN_ISSUE_RE.search(s)
    if not m:
        return None
    issue_id = m.group(1).strip()
    assignee = m.group(2).strip().rstrip("。，！!.，")
    if not issue_id or not assignee:
        return None
    return issue_id, assignee


def _default_memory_db_path() -> Path:
    configured = (os.environ.get("MULTICA_BOT_MEMORY_DB") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "data" / "memory.db"


def _is_confirm_dispatch_phrase(text: str) -> bool:
    from brain import is_confirm_dispatch_phrase

    return is_confirm_dispatch_phrase(text)


def _chat_id_for_incoming(incoming: dingtalk_stream.ChatbotMessage) -> str:
    conversation_id = str(getattr(incoming, "conversation_id", "") or "").strip()
    if conversation_id:
        return conversation_id
    sender_staff_id = str(getattr(incoming, "sender_staff_id", "") or "").strip()
    if sender_staff_id:
        return sender_staff_id
    return "default"


def _serialize_brain_decision(decision: Any) -> str:
    return json.dumps(
        {
            "intent": getattr(decision, "intent", ""),
            "category": getattr(decision, "category", ""),
            "confidence": getattr(decision, "confidence", 0.0),
            "missing_info": list(getattr(decision, "missing_info", []) or []),
            "suggested_title": getattr(decision, "suggested_title", ""),
            "suggested_description": getattr(decision, "suggested_description", ""),
            "definition_of_done": list(getattr(decision, "definition_of_done", []) or []),
            "priority": getattr(decision, "priority", "medium"),
            "split_suggestion": getattr(decision, "split_suggestion", ""),
            "recommended_action": getattr(decision, "recommended_action", "reply"),
            "memory_candidates": list(getattr(decision, "memory_candidates", []) or []),
        },
        ensure_ascii=False,
    )


def _is_acceptance_followup(text: str) -> bool:
    lower = (text or "").lower()
    return any(token in lower for token in ("验收", "完成标准", "dod", "definition of done"))


def _merge_clarification_context(raw: str, previous_decision: Any) -> str:
    title = str(getattr(previous_decision, "suggested_title", "") or "").strip()
    description = str(getattr(previous_decision, "suggested_description", "") or "").strip()
    parts = [part for part in (title, description, raw.strip()) if part]
    return "\n".join(parts) if parts else raw


def _redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]{6,}\b", "sk-[REDACTED]", value)
    return re.sub(
        r"(?i)([\"']?(?:\b[\w.-]*(?:access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key|access[_-]?key|refresh[_-]?key|auth[_-]?key|api[_-]?key|password|secret|token)[\w.-]*\b|private\s+key|(?:密码|密钥|令牌))[\"']?)\s*[:=：]\s*[\"']?([^\s,;\"'`)}\]]+)",
        lambda m: f"{m.group(1)}=[REDACTED]",
        value,
    )


def _normalize_for_routing(raw: str) -> str:
    """仅在疑似带 @ 前缀时剥离，避免已归一化文本重复处理。"""
    text = (raw or "").strip()
    if text.startswith("@"):
        return _normalize_dingtalk_at_prefixes(text)
    return text


def classify_incoming_text(raw: str, *, raw_original: str = "") -> str:
    """固定命令优先；非固定命令进入 Brain。
    raw_original: 未经 @剥离的原始文本，用于检测 @botUUM-24派给Agent 格式。
    """
    # @bot<id>派给Agent：@剥离会把 ID 吞掉，必须在剥离前先检测
    if _AT_ISSUE_DISPATCH_RE.match((raw_original or raw or "").strip()):
        return "dispatch_agent"
    text = _normalize_for_routing(raw)
    if _strip_delete_dispatch_prefix(text) is not None:
        return "cancel_issue"
    if _is_query_issues_command(text):
        return "query_issues"
    if _strip_dispatch_to_agent_prefix(text) is not None:
        return "dispatch_agent"
    if _strip_dispatch_prefix(text) is not None:
        return "create_issue"
    if _is_patrol_command(text):
        return "patrol"
    if _parse_assign_issue_command(text) is not None:
        return "assign_issue"
    if _is_free_query(text):
        return "free_query"
    return "brain"


def should_route_to_brain(raw: str) -> bool:
    """仅显式涉及队列/派单意图的非固定命令才交给 Brain。"""
    text = _normalize_for_routing(raw)
    if not text:
        return False
    return any(keyword in text for keyword in _BRAIN_ROUTE_KEYWORDS)


def _notify_webhook(title: str, text: str) -> None:
    url = (os.environ.get("DINGTALK_WEBHOOK_URL") or "").strip()
    if not url:
        return
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
    except OSError as e:
        LOG.warning("webhook notify failed: %s", _redact_sensitive_text(str(e)))


class MulticaDispatchHandler(dingtalk_stream.ChatbotHandler):
    """钉钉 Stream 回调：派单 / 删除派单 / 查工单 -> multica CLI；回复优先 Markdown 互动卡片。"""

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        memory_store: Optional[Any] = None,
        multica_client: Optional[Any] = None,
    ):
        super().__init__()
        self._log = logger or LOG
        # 本进程内一旦确认互动卡片不可用，后续不再调 OpenAPI，避免每条派单都打 403。
        self._interactive_card_broken: bool = False
        self._brain: Optional[Any] = None
        if memory_store is None:
            from memory import MemoryStore

            memory_store = MemoryStore(_default_memory_db_path())
        if multica_client is None:
            from multica_client import MulticaClient

            multica_client = MulticaClient()
        self._memory = memory_store
        self._multica = multica_client
        self._project_context: str = self._load_project_context()

    def _load_project_context(self) -> str:
        """从 knowledge_memory 加载仓库结构知识，供 Brain 参考。"""
        try:
            return self._memory.get_knowledge_by_key("project_map", "myagents_root") or ""
        except Exception as exc:
            self._log.debug("project_context not available: %s", exc)
            return ""

    def _get_brain(self) -> Any:
        if self._brain is None:
            from brain import Brain

            self._brain = Brain()
        return self._brain

    async def _confirm_pending_dispatch_suggestion(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
    ) -> str:
        from brain import parse_brain_decision

        chat_id = _chat_id_for_incoming(incoming)
        suggestion = self._memory.get_session_suggestion(chat_id)
        if not suggestion:
            return "没有待确认的派单建议"

        try:
            decision = parse_brain_decision(suggestion)
        except ValueError as exc:
            self._log.warning(
                "pending dispatch suggestion parse failed: %s",
                _redact_sensitive_text(str(exc)),
            )
            return f"待确认的派单建议格式有误：{exc}"

        try:
            result = await self._multica.create_issue(
                title=decision.suggested_title,
                description=decision.suggested_description,
                priority=decision.priority,
                status="todo",
            )
        except Exception as exc:
            self._log.warning(
                "multica create issue raised: %s",
                _redact_sensitive_text(str(exc)),
            )
            return "建单失败：Multica CLI 调用异常，请查看桥进程日志。"
        if not result.ok:
            self._log.warning(
                "multica create issue failed rc=%s stderr=%s stdout=%s",
                getattr(result, "returncode", "?"),
                _redact_sensitive_text((getattr(result, "stderr", "") or "")[:600]),
                _redact_sensitive_text((getattr(result, "stdout", "") or "")[:600]),
            )
            return "建单失败：Multica CLI 返回错误，请查看桥进程日志。"

        data = result.data or {}
        identifier = data.get("identifier") or data.get("id") or "（未返回编号）"
        self._memory.clear_session_suggestion(chat_id)
        return f"已按建议写入 Multica：`{identifier}`"

    def _reply_dispatch_message(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        card_header_title: str,
        markdown_body: str,
    ) -> None:
        """降级链：互动 Markdown 卡片 -> session Markdown（带标题栏）-> 纯文本。"""
        skip_card = (os.environ.get("DISPATCH_SKIP_MARKDOWN_CARD") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        try_card = (
            not skip_card
            and not self._interactive_card_broken
        )
        if try_card:
            try:
                inst = self.reply_markdown_card(
                    markdown_body,
                    incoming,
                    title=card_header_title,
                    logo="",
                    at_sender=False,
                )
                cid = (getattr(inst, "card_instance_id", None) or "").strip()
                if cid:
                    return
                self._interactive_card_broken = True
                self._log.warning(
                    "互动卡片不可用（如未开通 Card.Instance.Write），本进程内后续将只用 session Markdown"
                )
            except Exception as exc:
                self._interactive_card_broken = True
                self._log.warning(
                    "reply_markdown_card 异常，降级 session Markdown: %s",
                    _redact_sensitive_text(str(exc)),
                )
        elif self._interactive_card_broken and not skip_card:
            self._log.debug("skip interactive card (cached unavailable)")
        try:
            self.reply_markdown(card_header_title, markdown_body, incoming)
        except Exception as exc2:
            self._log.warning(
                "reply_markdown failed, fallback text: %s",
                _redact_sensitive_text(str(exc2)),
            )
            self.reply_text(f"{card_header_title}\n{markdown_body}", incoming)

    async def _handle_query_issues(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        multica_bin: str,
    ) -> Tuple[int, str]:
        """查工单：状态分布 + 按优先级前 10（不含已取消；同档 created_at 由远及近）。"""
        env = os.environ.copy()
        proj = _issue_list_project_args()
        total, counts = await _fetch_workspace_issue_stats(multica_bin, env)
        stats_md = _format_issue_stats_md(total, counts)
        d = await _multica_issue_list_json(multica_bin, env, proj, limit=500)
        if not d:
            self._reply_dispatch_message(
                incoming,
                "Multica 查工单",
                "❌ **无法拉取工单列表**\n\n"
                "请检查：`multica auth status`、网络；若需限定项目请配置 `MULTICA_PROJECT_ID`。",
            )
            return AckMessage.STATUS_OK, "OK"
        raw = d.get("issues")
        if not isinstance(raw, list):
            raw = []
        issues = [
            x
            for x in raw
            if isinstance(x, dict)
            and str(x.get("status") or "").strip().lower() != "cancelled"
        ]
        ranked = _sort_issues_priority_then_created(issues)
        top10 = ranked[:10]
        has_more = bool(d.get("has_more"))
        reply = _format_query_issues_reply_body(
            stats_md,
            top10,
            has_more=has_more,
            fetched_len=len(issues),
            total=total,
        )
        self._reply_dispatch_message(incoming, "Multica 查工单", reply)
        return AckMessage.STATUS_OK, "OK"

    async def _handle_assign_issue(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        raw: str,
        multica_bin: str,
    ) -> Tuple[int, str]:
        """自然语言指派：「UUM-24，分给克劳德」→ multica issue assign <id> --to <name>"""
        parsed = _parse_assign_issue_command(raw)
        if not parsed:
            self._reply_dispatch_message(
                incoming, "Multica 工单指派",
                "请用格式：`UUM-24，分给<人名或Agent名>`",
            )
            return AckMessage.STATUS_OK, "OK"
        issue_id, assignee = parsed
        env = os.environ.copy()
        cmd = [multica_bin, "issue", "assign", issue_id, "--to", assignee]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            out_b, err_b = await proc.communicate()
        except Exception as exc:
            self._log.warning("multica issue assign failed: %s", exc)
            self._reply_dispatch_message(
                incoming, "Multica 工单指派",
                f"❌ 指派失败（内部错误）：{_redact_sensitive_text(str(exc))[:200]}",
            )
            return AckMessage.STATUS_OK, "OK"
        if proc.returncode != 0:
            err_text = (err_b or b"").decode("utf-8", errors="replace").strip()[:300]
            self._reply_dispatch_message(
                incoming, "Multica 工单指派",
                f"❌ 指派失败\n\n`{issue_id}` → `{assignee}`\n\n```\n{err_text}\n```",
            )
            return AckMessage.STATUS_OK, "OK"
        self._reply_dispatch_message(
            incoming, "Multica 工单指派",
            f"✅ `{issue_id}` 已指派给 **{assignee}**",
        )
        return AckMessage.STATUS_OK, "OK"

    async def _handle_free_query(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        raw: str,
        multica_bin: str,
    ) -> Tuple[int, str]:
        """自然语言工单查询：LLM 解析意图 → multica CLI → 排序过滤 → 格式化回复。"""
        from brain import parse_issue_query, IssueQuerySpec

        try:
            spec = await parse_issue_query(raw, self._get_brain().provider)
        except Exception as exc:
            self._log.warning("parse_issue_query failed: %s", exc)
            spec = IssueQuerySpec()

        env = os.environ.copy()
        proj = _issue_list_project_args()
        issues_raw: Optional[list] = None
        fetch_limit = min(200, max(spec.limit * 4, 50))

        if spec.search:
            issues_raw = await _multica_issue_search_json(
                multica_bin, env, spec.search,
                limit=fetch_limit,
                include_closed=spec.include_closed,
            )
        else:
            extra = list(proj)
            if spec.status:
                extra += ["--status", spec.status]
            if spec.assignee:
                extra += ["--assignee", spec.assignee]
            d = await _multica_issue_list_json(
                multica_bin, env, tuple(extra), limit=fetch_limit
            )
            if d is not None:
                raw_list = d.get("issues")
                issues_raw = raw_list if isinstance(raw_list, list) else []

        if issues_raw is None:
            self._reply_dispatch_message(
                incoming,
                "Multica 工单查询",
                "❌ 无法拉取工单，请检查 `multica auth status` 和网络。",
            )
            return AckMessage.STATUS_OK, "OK"

        # 过滤
        filtered: List[dict] = []
        for it in issues_raw:
            if not isinstance(it, dict):
                continue
            st = str(it.get("status") or "").strip().lower()
            # 未指定 include_closed 时排除 done/cancelled
            if not spec.include_closed and not spec.status and st in ("done", "cancelled"):
                continue
            # assignee 过滤（search 模式下 CLI 不支持 --assignee，Python 侧补充）
            if spec.assignee and spec.search:
                assignee_val = it.get("assignee") or ""
                if isinstance(assignee_val, dict):
                    assignee_val = assignee_val.get("name") or assignee_val.get("username") or ""
                if spec.assignee.lower() not in str(assignee_val).lower():
                    continue
            filtered.append(it)

        # 排序 + 截断
        sorted_issues = _sort_issues_by_spec(filtered, spec.sort_by)
        result = sorted_issues[: spec.limit]

        # 构造描述行
        sort_label = {
            "created_desc": "最近创建",
            "created_asc": "最早创建",
            "priority_desc": "按优先级",
            "updated_desc": "最近更新",
        }.get(spec.sort_by, spec.sort_by)
        status_label = (
            _ISSUE_STATUS_LABEL.get(spec.status, spec.status) if spec.status else "全部未完结"
        )
        parts = [f"查询 {spec.limit} 条", status_label, sort_label]
        if spec.assignee:
            parts.append(f"经办人={spec.assignee}")
        if spec.search:
            parts.append(f"关键词={spec.search!r}")
        spec_desc = " · ".join(parts)

        reply = _format_free_query_reply(spec_desc, result, len(filtered))
        self._reply_dispatch_message(incoming, "Multica 工单查询", reply)
        return AckMessage.STATUS_OK, "OK"

    async def _handle_patrol(self, incoming: dingtalk_stream.ChatbotMessage) -> Tuple[int, str]:
        """只读巡查：仅拉取列表并渲染摘要，不修改 Multica 工单。"""
        from brain import render_patrol_summary

        try:
            result = await self._multica.list_issues(limit=500)
        except Exception as exc:
            self._log.warning(
                "multica patrol list raised: %s",
                _redact_sensitive_text(str(exc)),
            )
            self._reply_dispatch_message(
                incoming,
                "Multica 队列巡查",
                "巡查失败：Multica CLI 返回错误，请查看桥进程日志。",
            )
            return AckMessage.STATUS_OK, "OK"

        if not result.ok:
            self._log.warning(
                "multica patrol list failed rc=%s stderr=%s stdout=%s",
                getattr(result, "returncode", "?"),
                _redact_sensitive_text((getattr(result, "stderr", "") or "")[:1200]),
                _redact_sensitive_text((getattr(result, "stdout", "") or "")[:1200]),
            )
            self._reply_dispatch_message(
                incoming,
                "Multica 队列巡查",
                "巡查失败：Multica CLI 返回错误，请查看桥进程日志。",
            )
            return AckMessage.STATUS_OK, "OK"

        data = result.data or {}
        if isinstance(data, list):
            raw_issues = data
        elif isinstance(data, dict):
            raw_issues = data.get("issues")
        else:
            raw_issues = []
        issues = [item for item in raw_issues if isinstance(item, dict)] if isinstance(raw_issues, list) else []
        self._reply_dispatch_message(
            incoming,
            "Multica 队列巡查",
            render_patrol_summary(issues),
        )
        return AckMessage.STATUS_OK, "OK"

    async def _handle_dispatch_to_agent(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        issue_id: str,
    ) -> Tuple[int, str]:
        """把 Multica 工单派给 Claude Code 开发 Agent 异步处理。"""
        # 先回复用户"已派出"，再后台跑
        self._reply_dispatch_message(
            incoming,
            "开发 Agent 派单",
            f"已把 **{issue_id}** 排进队列，Agent 启动后会再发一条「开始执行」通知。\n\n"
            f"完成后通过钉钉推送（分支名 + 摘要）。\n\n"
            f"进度文件：`shared-memory/agent-tasks/{issue_id}.json`",
        )

        # 拉取工单信息构建任务
        try:
            list_result = await self._multica.list_issues(limit=500)
            issue_data: Dict[str, Any] = {}
            if list_result.ok:
                raw = list_result.data or {}
                issues = (
                    raw if isinstance(raw, list)
                    else raw.get("issues", []) if isinstance(raw, dict)
                    else []
                )
                for iss in issues:
                    if isinstance(iss, dict):
                        iss_id = str(iss.get("identifier") or iss.get("id") or "")
                        if iss_id == issue_id or iss_id.endswith(f"-{issue_id.split('-')[-1]}"):
                            issue_data = iss
                            break
        except Exception as exc:
            self._log.warning("failed to fetch issue %s: %s", issue_id, exc)
            issue_data = {}

        # 构建任务字典
        title = str(issue_data.get("title") or issue_id)
        description = str(issue_data.get("description") or "")
        dod_raw = issue_data.get("definition_of_done") or []
        dod: List[str] = dod_raw if isinstance(dod_raw, list) else []

        # 尝试从 description 解析 DoD（兼容纯文字格式）
        if not dod and description:
            for line in description.splitlines():
                s = line.strip()
                if s.startswith(("验收：", "验收:", "DoD:", "DoD：")):
                    dod.append(s.split(":", 1)[-1].strip() or s.split("：", 1)[-1].strip())

        task: Dict[str, Any] = {
            "id": issue_id,
            "title": title,
            "description": description,
            "definition_of_done": dod,
            "category": str(issue_data.get("category") or "task"),
            "priority": str(issue_data.get("priority") or "medium"),
            "project_hint": str(issue_data.get("project") or ""),
            "multica_labels": issue_data.get("labels") or [],
        }

        # 异步触发 Agent（不阻塞钉钉 Stream 回调）
        asyncio.create_task(self._run_agent_task(incoming, task))
        return AckMessage.STATUS_OK, "OK"

    async def _run_agent_task(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        task: Dict[str, Any],
    ) -> None:
        """后台运行开发 Agent；状态通知走当当 Webhook，不走 Stream 回复。"""
        from dev_agent_runner import AgentRunResult, enqueue_task, run_dev_agent
        from feedback_handler import comment_on_multica_issue, notify_agent_done, notify_agent_started

        task_path = enqueue_task(task)
        issue_id = task.get("id", "?")
        self._log.info("agent task enqueued: %s -> %s", issue_id, task_path)

        # 状态 1：Agent 开始执行（webhook）
        try:
            notify_agent_started(task)
        except Exception as exc:
            self._log.debug("notify_agent_started skipped: %s", exc)

        try:
            result: AgentRunResult = await asyncio.to_thread(run_dev_agent, task, task_path)
        except Exception as exc:
            self._log.error("agent run raised: %s", _redact_sensitive_text(str(exc)))
            return

        self._log.info(
            "agent task done: %s success=%s duration=%.1fs",
            result.task_id, result.success, result.duration_seconds,
        )

        # 状态 2：完成或失败（webhook）
        try:
            notify_agent_done(result, task)
        except Exception as exc:
            self._log.warning("notify_agent_done failed: %s", _redact_sensitive_text(str(exc)))

        try:
            comment_on_multica_issue(result, task)
        except Exception as exc:
            self._log.debug("multica comment skipped: %s", exc)

    async def _handle_delete_dispatch(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        rest: str,
        multica_bin: str,
    ) -> Tuple[int, str]:
        """删除派单：将工单状态设为 cancelled；支持顿号/逗号等分隔的多个引用。"""
        env = os.environ.copy()
        tokens = _parse_delete_dispatch_tokens(rest)
        if not tokens:
            self._reply_dispatch_message(incoming, "Multica 取消派单", _DELETE_DISPATCH_HELP)
            return AckMessage.STATUS_OK, "OK"

        proj = _issue_list_project_args()
        d_list = await _multica_issue_list_json(multica_bin, env, proj, limit=500)
        issues_cache: List[dict] = []
        if isinstance(d_list, dict):
            raw_issues = d_list.get("issues")
            if isinstance(raw_issues, list):
                issues_cache = [x for x in raw_issues if isinstance(x, dict)]

        failed_parse: List[str] = []
        pairs: List[Tuple[str, str]] = []
        seen_ref: set[str] = set()
        for token in tokens:
            ref = await _resolve_issue_ref_for_status(
                multica_bin, env, token, issues_cache=issues_cache
            )
            if not ref:
                failed_parse.append(token)
                continue
            if ref in seen_ref:
                continue
            seen_ref.add(ref)
            pairs.append((token, ref))

        if not pairs:
            joined = "、".join(failed_parse) if failed_parse else "（空）"
            self._reply_dispatch_message(
                incoming,
                "Multica 取消派单",
                "⚠️ **未找到可取消的工单引用**\n\n"
                f"输入：`{joined}`\n\n"
                "支持 **顿号 `、`**、中英文逗号/分号及空白分隔多个引用。\n\n"
                "每条可为 **标识**（如 `UUM-10`）、**短号**（在最多 **500** 条已列出工单中匹配 `number`）或 **Issue UUID**。\n\n"
                "若短号未命中，请改用完整标识，或在 Multica 网页确认该工单是否在当前 Workspace / `MULTICA_PROJECT_ID` 下。",
            )
            return AckMessage.STATUS_OK, "OK"

        ok_lines: List[str] = []
        api_fail: List[str] = []
        json_fail: List[str] = []

        for token, issue_ref in pairs:
            rc, out, err, data = await _multica_issue_set_cancelled(
                multica_bin, env, issue_ref
            )
            if rc != 0:
                self._log.warning(
                    "multica issue status rc=%s ref=%s token=%s stderr=%s",
                    rc,
                    issue_ref,
                    token,
                    _redact_sensitive_text(err[:400] if err else ""),
                )
                redacted_err = _redact_sensitive_text((err or "(空)")[:400])
                api_fail.append(
                    f"- `{issue_ref}`（输入 `{token}`）\n```\n{redacted_err}\n```"
                )
                continue
            if not data:
                self._log.warning(
                    "multica issue status parse fail ref=%s stdout=%s",
                    issue_ref,
                    _redact_sensitive_text((out or "")[:500]),
                )
                json_fail.append(f"- `{issue_ref}`（输入 `{token}`）")
                continue
            ident = data.get("identifier") or data.get("id") or issue_ref
            title_disp = (data.get("title") or "")[:60]
            ok_lines.append(
                f"- **`{ident}`** · {title_disp or '（无标题）'}（`{token}`）"
            )

        app_url = _read_multica_app_url()
        stats_md = _format_issue_stats_md(
            *await _fetch_workspace_issue_stats(multica_bin, env)
        )

        body_parts: List[str] = []
        if ok_lines:
            body_parts.append(
                f"✅ **已请求取消**（`cancelled`）**{len(ok_lines)}** 条\n\n"
                + "\n".join(ok_lines)
            )
        if failed_parse:
            body_parts.append(
                "⚠️ **未能解析**（跳过）：`"
                + "、".join(failed_parse)
                + "`\n\n短号仅在当前拉取的列表范围内匹配。"
            )
        if api_fail:
            body_parts.append("❌ **接口返回失败**\n\n" + "\n".join(api_fail))
        if json_fail:
            body_parts.append(
                "⚠️ **已执行取消但未解析到 JSON**（请在网页核对）\n\n"
                + "\n".join(json_fail)
            )

        body_parts.append("---\n\n" + f"🌐 **在网页查看** [{app_url}]({app_url})\n\n" + stats_md)
        self._reply_dispatch_message(
            incoming, "Multica 取消派单", "\n\n".join(body_parts)
        )

        if ok_lines:
            hook_lines = "\n".join(ok_lines[:20])
            more = "\n…" if len(ok_lines) > 20 else ""
            _notify_webhook(
                "Multica 工单取消",
                "### 钉钉派单桥批量取消\n\n" + hook_lines + more,
            )
        return AckMessage.STATUS_OK, "OK"

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        tc = incoming.text
        raw_original = ((tc.content if tc else "") or "").strip()
        raw = _normalize_dingtalk_at_prefixes(raw_original)
        route = classify_incoming_text(raw, raw_original=raw_original)

        if route == "brain":
            if _is_confirm_dispatch_phrase(raw):
                reply = await self._confirm_pending_dispatch_suggestion(incoming)
                self._reply_dispatch_message(incoming, "Multica 队列管家", reply)
                return AckMessage.STATUS_OK, "OK"
            if not should_route_to_brain(raw):
                return AckMessage.STATUS_OK, "OK"
            try:
                chat_id = _chat_id_for_incoming(incoming)
                brain = self._get_brain()
                brain_input = raw
                if _is_acceptance_followup(raw):
                    try:
                        from brain import parse_brain_decision

                        stored = self._memory.get_session_clarification(chat_id)
                        if stored:
                            previous_decision = parse_brain_decision(stored)
                            if previous_decision.recommended_action == "ask_clarification":
                                brain_input = _merge_clarification_context(raw, previous_decision)
                    except Exception as exc:
                        self._log.warning(
                            "pending clarification context ignored: %s",
                            _redact_sensitive_text(str(exc)),
                        )
                decision = await brain.decide(
                    brain_input,
                    project_context=self._project_context,
                )
                if decision.recommended_action == "ask_confirm":
                    self._memory.set_session_suggestion(
                        chat_id,
                        _serialize_brain_decision(decision),
                    )
                    self._memory.clear_session_clarification(chat_id)
                elif decision.recommended_action == "ask_clarification":
                    self._memory.set_session_clarification(
                        chat_id,
                        _serialize_brain_decision(decision),
                    )
                reply = brain.render_reply(decision)
                try:
                    memory_counts = self._memory.process_memory_candidates(
                        decision.memory_candidates,
                        source=chat_id,
                    )
                except Exception as exc:
                    self._log.warning(
                        "memory candidate processing failed: %s",
                        _redact_sensitive_text(str(exc)),
                    )
                else:
                    pending_count = int(memory_counts.get("pending", 0))
                    if pending_count > 0:
                        reply += (
                            f"\n\n我还提取到 {pending_count} 条长期记忆候选，"
                            "后续可汇总给老大确认。"
                        )
            except Exception as exc:
                self._log.warning("brain route failed: %s", _redact_sensitive_text(str(exc)))
                reply = "我暂时没能把这条需求整理清楚。老大可以换成固定格式：`派单 标题`，第二行写验收说明。"
            self._reply_dispatch_message(incoming, "Multica 队列管家", reply)
            return AckMessage.STATUS_OK, "OK"

        if route == "assign_issue":
            multica_bin = _resolve_multica_binary()
            if not multica_bin:
                self._reply_dispatch_message(
                    incoming, "Multica 工单指派",
                    "⚠️ 本机找不到 multica，请用 `quick_start.bat 7` 重启派单桥。",
                )
                return AckMessage.STATUS_OK, "OK"
            return await self._handle_assign_issue(incoming, raw, multica_bin)

        if route == "free_query":
            multica_bin = _resolve_multica_binary()
            if not multica_bin:
                self._reply_dispatch_message(
                    incoming, "Multica 工单查询",
                    "⚠️ 本机找不到 multica，请用 `quick_start.bat 7` 重启派单桥。",
                )
                return AckMessage.STATUS_OK, "OK"
            return await self._handle_free_query(incoming, raw, multica_bin)

        if route == "patrol":
            return await self._handle_patrol(incoming)

        if route == "dispatch_agent":
            issue_id = _strip_dispatch_to_agent_prefix(raw)
            if issue_id:
                return await self._handle_dispatch_to_agent(incoming, issue_id)
            self._reply_dispatch_message(
                incoming,
                "开发 Agent 派单",
                "请指定工单 ID，例：`#派给Agent UUM-42`",
            )
            return AckMessage.STATUS_OK, "OK"

        del_rest = _strip_delete_dispatch_prefix(raw)
        if del_rest is not None:
            multica_bin = _resolve_multica_binary()
            if not multica_bin:
                self._reply_dispatch_message(
                    incoming,
                    "Multica 派单",
                    "⚠️ **本机找不到 multica**\n\n"
                    "请任选其一：\n\n"
                    "1️⃣ 用 **run_bridge.ps1** 启动桥（已合并系统 PATH）；仍失败则在终端执行 `where multica`。\n\n"
                    "2️⃣ 在 `.env` 写 `MULTICA_BIN=` + `multica.exe` 的绝对路径。\n\n"
                    "3️⃣ 把 multica 安装目录加入 **用户或系统 PATH**，重启派单桥。",
                )
                return AckMessage.STATUS_OK, "OK"
            return await self._handle_delete_dispatch(incoming, del_rest, multica_bin)

        if _is_query_issues_command(raw):
            multica_bin = _resolve_multica_binary()
            if not multica_bin:
                self._reply_dispatch_message(
                    incoming,
                    "Multica 派单",
                    "⚠️ **本机找不到 multica**\n\n"
                    "请任选其一：\n\n"
                    "1️⃣ 用 **run_bridge.ps1** 启动桥（已合并系统 PATH）；仍失败则在终端执行 `where multica`。\n\n"
                    "2️⃣ 在 `.env` 写 `MULTICA_BIN=` + `multica.exe` 的绝对路径。\n\n"
                    "3️⃣ 把 multica 安装目录加入 **用户或系统 PATH**，重启派单桥。",
                )
                return AckMessage.STATUS_OK, "OK"
            return await self._handle_query_issues(incoming, multica_bin)

        body = _strip_dispatch_prefix(raw)
        if body is None:
            return AckMessage.STATUS_OK, "OK"
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if not lines:
            self._reply_dispatch_message(incoming, "派单助手", _EMPTY_DISPATCH_HELP)
            return AckMessage.STATUS_OK, "OK"

        title = lines[0][:500]
        description = "\n".join(lines[1:]) if len(lines) > 1 else "（钉钉派单，无额外描述）"

        multica_bin = _resolve_multica_binary()
        if not multica_bin:
            self._reply_dispatch_message(
                incoming,
                "Multica 派单",
                "⚠️ **本机找不到 multica**\n\n"
                "请任选其一：\n\n"
                "1️⃣ 用 **run_bridge.ps1** 启动桥（已合并系统 PATH）；仍失败则在终端执行 `where multica`。\n\n"
                "2️⃣ 在 `.env` 写 `MULTICA_BIN=` + `multica.exe` 的绝对路径。\n\n"
                "3️⃣ 把 multica 安装目录加入 **用户或系统 PATH**，重启派单桥。",
            )
            return AckMessage.STATUS_OK, "OK"

        cmd = [
            multica_bin,
            "issue",
            "create",
            "--title",
            title,
            "--description",
            description,
            "--priority",
            "medium",
            "--status",
            "todo",
            "--output",
            "json",
        ]
        proj = (os.environ.get("MULTICA_PROJECT_ID") or "").strip()
        if proj:
            cmd.extend(["--project", proj])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        out_b, err_b = await proc.communicate()
        out = (out_b or b"").decode("utf-8", errors="replace")
        err = (err_b or b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            redacted_err = _redact_sensitive_text(err)
            redacted_out = _redact_sensitive_text(out)
            self._log.warning(
                "multica exit=%s stderr=%s stdout=%s",
                proc.returncode,
                redacted_err,
                redacted_out,
            )
            self._reply_dispatch_message(
                incoming,
                "Multica 派单",
                "❌ **建单失败**（CLI 非零退出）\n\n"
                "请检查：`multica auth status`、workspace，必要时配置 `MULTICA_PROJECT_ID`。\n\n"
                "**stderr**\n```\n"
                + (redacted_err or "(空)")[:600]
                + "\n```\n**stdout**\n```\n"
                + (redacted_out or "(空)")[:600]
                + "\n```",
            )
            return AckMessage.STATUS_OK, "OK"

        data = _parse_create_stdout(out)
        if not data:
            redacted_out = _redact_sensitive_text(out)
            redacted_err = _redact_sensitive_text(err)
            self._log.warning(
                "multica exit=0 but JSON parse failed or missing id stdout=%s stderr=%s",
                redacted_out,
                redacted_err,
            )
            self._reply_dispatch_message(
                incoming,
                "Multica 派单",
                "⚠️ **未确认是否写入 Multica**\n\n"
                "CLI 退出码为 0，但未能解析建单 JSON，**请勿当作已成功**。\n\n"
                "原始输出：\n```\n"
                + (redacted_out or "(空)")[:1000]
                + "\n```",
            )
            return AckMessage.STATUS_OK, "OK"

        issue_id = data.get("id", "")
        identifier = data.get("identifier") or issue_id
        self._log.info(
            "multica issue created identifier=%s id=%s multica_bin=%s json=%s",
            identifier,
            issue_id,
            multica_bin,
            _redact_sensitive_text(json.dumps(data, ensure_ascii=False)[:4000]),
        )

        title_short = title if len(title) <= 80 else title[:77] + "..."
        _total, counts = await _fetch_workspace_issue_stats(
            multica_bin, os.environ.copy()
        )
        reply = _format_dispatch_create_reply(
            str(identifier), title, description, data, counts
        )
        self._reply_dispatch_message(incoming, "Multica 派单", reply)
        issue_url, _ = _issue_page_url_for_reply(data, str(identifier))
        _notify_webhook(
            "Multica 新单",
            "### 钉钉派单已落 Multica\n\n"
            f"- **{identifier}** · {title_short}\n"
            f"- Issue ID `{issue_id}`\n"
            f"- [打开工单]({issue_url})\n",
        )
        return AckMessage.STATUS_OK, "OK"


def setup_logger() -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        root.addHandler(h)
    root.setLevel(logging.INFO)
    return root


def main() -> None:
    _load_env_file()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client_id",
        default=os.environ.get("DINGTALK_CLIENT_ID", ""),
        help="钉钉应用 Client ID（或环境变量 DINGTALK_CLIENT_ID）",
    )
    parser.add_argument(
        "--client_secret",
        default=os.environ.get("DINGTALK_CLIENT_SECRET", ""),
        help="钉钉应用 Client Secret（或环境变量 DINGTALK_CLIENT_SECRET）",
    )
    args = parser.parse_args()
    if not args.client_id or not args.client_secret:
        print("需要 --client_id / --client_secret 或对应环境变量", file=sys.stderr)
        sys.exit(2)

    logger = setup_logger()
    credential = dingtalk_stream.Credential(args.client_id, args.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        MulticaDispatchHandler(logger),
    )
    # ── 启动工单状态变更监听器（后台线程） ─────────────────────────
    from status_watcher import StatusWatcher
    _status_watcher = StatusWatcher()
    _status_watcher.start()

    logger.info("DingTalk stream started; ensure `multica` is on PATH and logged in.")
    client.start_forever()


if __name__ == "__main__":
    main()
