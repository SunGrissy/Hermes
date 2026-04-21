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
from typing import Dict, List, Optional, Tuple

from dingtalk_stream import AckMessage
import dingtalk_stream

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_a, **_k):
        return False

LOG = logging.getLogger("multica-bridge")

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
            (err_b or b"").decode("utf-8", errors="replace")[:400],
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
        LOG.warning("webhook notify failed: %s", e)


class MulticaDispatchHandler(dingtalk_stream.ChatbotHandler):
    """钉钉 Stream 回调：派单 / 删除派单 / 查工单 -> multica CLI；回复优先 Markdown 互动卡片。"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__()
        self._log = logger or LOG
        # 本进程内一旦确认互动卡片不可用，后续不再调 OpenAPI，避免每条派单都打 403。
        self._interactive_card_broken: bool = False

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
                self._log.warning("reply_markdown_card 异常，降级 session Markdown: %s", exc)
        elif self._interactive_card_broken and not skip_card:
            self._log.debug("skip interactive card (cached unavailable)")
        try:
            self.reply_markdown(card_header_title, markdown_body, incoming)
        except Exception as exc2:
            self._log.warning("reply_markdown failed, fallback text: %s", exc2)
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
                    err[:400] if err else "",
                )
                api_fail.append(
                    f"- `{issue_ref}`（输入 `{token}`）\n```\n{(err or '(空)')[:400]}\n```"
                )
                continue
            if not data:
                self._log.warning(
                    "multica issue status parse fail ref=%s stdout=%s",
                    issue_ref,
                    (out or "")[:500],
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
        raw = ((tc.content if tc else "") or "").strip()

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
            self._log.warning("multica exit=%s stderr=%s stdout=%s", proc.returncode, err, out)
            self._reply_dispatch_message(
                incoming,
                "Multica 派单",
                "❌ **建单失败**（CLI 非零退出）\n\n"
                "请检查：`multica auth status`、workspace，必要时配置 `MULTICA_PROJECT_ID`。\n\n"
                "**stderr**\n```\n"
                + (err or "(空)")[:600]
                + "\n```\n**stdout**\n```\n"
                + (out or "(空)")[:600]
                + "\n```",
            )
            return AckMessage.STATUS_OK, "OK"

        data = _parse_create_stdout(out)
        if not data:
            self._log.warning("multica exit=0 but JSON parse failed or missing id stdout=%s stderr=%s", out, err)
            self._reply_dispatch_message(
                incoming,
                "Multica 派单",
                "⚠️ **未确认是否写入 Multica**\n\n"
                "CLI 退出码为 0，但未能解析建单 JSON，**请勿当作已成功**。\n\n"
                "原始输出：\n```\n"
                + (out or "(空)")[:1000]
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
            json.dumps(data, ensure_ascii=False)[:4000],
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
    logger.info("DingTalk stream started; ensure `multica` is on PATH and logged in.")
    client.start_forever()


if __name__ == "__main__":
    main()
