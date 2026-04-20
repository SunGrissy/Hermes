#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""钉钉 Stream 机器人收消息 -> 本机 multica issue create / issue status cancelled（删除派单）。运行前须 multica login 且 multica 在 PATH。"""

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
from typing import Dict, Optional, Tuple

from dingtalk_stream import AckMessage
import dingtalk_stream

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_a, **_k):
        return False


# [AgentMltc Task] 开始时间: 2026-04-18
# [AgentMltc Task] 任务目标: multica-dingtalk-bridge Task3-4 Stream 派单桥

LOG = logging.getLogger("multica-bridge")

_DELETE_DISPATCH_HELP = (
    "🗑️ **请指定要取消的工单**\n\n"
    "Multica 无物理删除；本操作会把工单状态设为 **已取消**（`cancelled`）。\n\n"
    "**格式样例**\n\n"
    "- `删除派单 UUM-10` 或 `删除派单 10`（短号对应当前列表里的 **number**）\n"
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
    "取消工单：`删除派单 UUM-9` 或 `删除派单 9`（详见「删除派单」仅一行时的提示）。"
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_ISSUE_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")


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


async def _resolve_issue_ref_for_status(
    multica_bin: str, env: dict, token: str
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
        proj = _issue_list_project_args()
        d = await _multica_issue_list_json(multica_bin, env, proj, limit=500)
        if not d:
            return None
        issues = d.get("issues")
        if not isinstance(issues, list):
            return None
        for it in issues:
            if isinstance(it, dict) and it.get("number") == n:
                ident = it.get("identifier")
                if isinstance(ident, str) and ident.strip():
                    return ident.strip()
        return None
    return None


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
    """钉钉 Stream 回调：派单 -> multica issue create；回复优先 Markdown 互动卡片。"""

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

    async def _handle_delete_dispatch(
        self,
        incoming: dingtalk_stream.ChatbotMessage,
        rest: str,
        multica_bin: str,
    ) -> Tuple[int, str]:
        """删除派单：将工单状态设为 cancelled（无物理删除）。"""
        env = os.environ.copy()
        lines = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        if not lines:
            self._reply_dispatch_message(incoming, "Multica 取消派单", _DELETE_DISPATCH_HELP)
            return AckMessage.STATUS_OK, "OK"
        parts = lines[0].split()
        if not parts:
            self._reply_dispatch_message(incoming, "Multica 取消派单", _DELETE_DISPATCH_HELP)
            return AckMessage.STATUS_OK, "OK"
        token = parts[0]

        issue_ref = await _resolve_issue_ref_for_status(multica_bin, env, token)
        if not issue_ref:
            self._reply_dispatch_message(
                incoming,
                "Multica 取消派单",
                "⚠️ **未找到可取消的工单引用**\n\n"
                f"输入：`{token}`\n\n"
                "请使用 **标识**（如 `UUM-10`）、**短号**（如 `10`，在最多 **500** 条已列出工单中匹配 `number`）"
                " 或 **Issue UUID**。\n\n"
                "若短号未命中，请改用完整标识，或在 Multica 网页确认该工单是否在当前 Workspace / `MULTICA_PROJECT_ID` 下。",
            )
            return AckMessage.STATUS_OK, "OK"

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

        if proc.returncode != 0:
            self._log.warning(
                "multica issue status rc=%s ref=%s stderr=%s stdout=%s",
                proc.returncode,
                issue_ref,
                err,
                out,
            )
            self._reply_dispatch_message(
                incoming,
                "Multica 取消派单",
                "❌ **取消失败**（CLI 非零退出）\n\n"
                f"- 引用：`{issue_ref}`（由 `{token}` 解析）\n\n"
                "**stderr**\n```\n"
                + (err or "(空)")[:600]
                + "\n```\n",
            )
            return AckMessage.STATUS_OK, "OK"

        data = _parse_create_stdout(out)
        if not data:
            self._log.warning("multica issue status parse fail stdout=%s", (out or "")[:800])
            self._reply_dispatch_message(
                incoming,
                "Multica 取消派单",
                "⚠️ **已请求取消，但未解析到返回 JSON**\n\n"
                "请在 Multica 网页核对工单状态是否已为 **已取消**。\n\n```\n"
                + (out or "(空)")[:800]
                + "\n```",
            )
            return AckMessage.STATUS_OK, "OK"

        identifier = data.get("identifier") or data.get("id") or issue_ref
        title_disp = (data.get("title") or "")[:80]
        app_url = _read_multica_app_url()
        stats_md = _format_issue_stats_md(
            *await _fetch_workspace_issue_stats(multica_bin, env)
        )
        title_line = f"📝 **标题** {title_disp}\n\n" if title_disp else ""
        reply = (
            "✅ **工单已设为已取消**（`cancelled`）\n\n"
            f"📋 **编号** `{identifier}`\n\n"
            + title_line
            + "---\n\n"
            f"🌐 **在网页查看** [{app_url}]({app_url})\n\n"
            f"{stats_md}"
        )
        self._reply_dispatch_message(incoming, "Multica 取消派单", reply)
        _notify_webhook(
            "Multica 工单取消",
            "### 钉钉派单桥已将工单设为已取消\n\n"
            f"- **{identifier}** · {title_disp or '（无标题）'}\n",
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
        app_url = _read_multica_app_url()
        self._log.info(
            "multica issue created identifier=%s id=%s multica_bin=%s json=%s",
            identifier,
            issue_id,
            multica_bin,
            json.dumps(data, ensure_ascii=False)[:4000],
        )

        title_short = title if len(title) <= 80 else title[:77] + "..."
        stats_md = _format_issue_stats_md(
            *await _fetch_workspace_issue_stats(multica_bin, os.environ.copy())
        )
        reply = (
            "✅ **工单已写入 Multica**（todo / medium）\n\n"
            f"📋 **编号** `{identifier}`\n\n"
            f"📝 **标题** {title_short}\n\n"
            "---\n\n"
            f"🌐 **在网页查看**  \n登录 [{app_url}]({app_url}) → 打开应用 → 在当前 Workspace 看板搜索 **{identifier}**\n\n"
            f"{stats_md}\n\n"
            "> 本条建单的完整 JSON 已记在本机「派单桥」终端日志。"
        )
        self._reply_dispatch_message(incoming, "Multica 派单", reply)
        _notify_webhook(
            "Multica 新单",
            "### 钉钉派单已落 Multica\n\n"
            f"- **{identifier}** · {title_short}\n"
            f"- Issue ID `{issue_id}`\n",
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
