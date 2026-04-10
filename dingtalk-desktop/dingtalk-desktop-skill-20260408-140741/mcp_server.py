# -*- coding: utf-8 -*-
"""
DingTalk Desktop MCP Server — 独立可分发版

通过 MCP 协议（stdio 传输）暴露 daemon.py 的 HTTP API。
不依赖 UltraAI，可在任何支持 MCP 的 AI Agent 框架中使用。

用法:
  # stdio 模式（Cursor / Claude Desktop 等）
  python mcp_server.py

  # 或通过 mcp.json 配置
  {
    "mcpServers": {
      "dingtalk-desktop": {
        "command": "python",
        "args": ["path/to/mcp_server.py"]
      }
    }
  }

依赖: pip install mcp frida-tools msgpack
"""
import os
import sys
import json
import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from mcp.server.fastmcp import FastMCP

# ── config ──────────────────────────────────────────────────────────

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_config() -> dict:
    cfg_path = os.path.join(_SKILL_DIR, "config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


_CFG = _load_config()
DAEMON_PORT = int(os.environ.get("DINGTALK_DAEMON_PORT", "19200"))
DAEMON_SCRIPT = os.path.join(_SKILL_DIR, "daemon.py")
PYTHON = os.environ.get("PYTHON_PATH", sys.executable)
LOG_FILE = os.environ.get(
    "DINGTALK_LOG_FILE",
    os.path.join(_SKILL_DIR, "..", "..", "data", "dingtalk", "_msg_log.jsonl"),
)

BASE_URL = f"http://127.0.0.1:{DAEMON_PORT}"

# ── HTTP helpers ────────────────────────────────────────────────────


def _http(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}
    except urllib.error.URLError as e:
        raise ConnectionError(f"daemon 不可达: {e}")
    except TimeoutError:
        raise TimeoutError(f"请求超时 ({timeout}s)")


def _is_daemon_running() -> bool:
    try:
        r = _http("GET", "/health", timeout=3)
        return r.get("daemon") == "running"
    except Exception:
        return False


def _start_daemon() -> bool:
    """尝试启动 daemon 并等待就绪（最多 30 秒）。"""
    if not os.path.isfile(DAEMON_SCRIPT):
        return False
    env = {**os.environ, "DINGTALK_DAEMON_PORT": str(DAEMON_PORT)}
    subprocess.Popen(
        [PYTHON, DAEMON_SCRIPT],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(30):
        time.sleep(1)
        if _is_daemon_running():
            return True
    return False


def _ensure_daemon() -> None:
    """确保 daemon 正在运行，否则尝试启动。"""
    if _is_daemon_running():
        return
    if not _start_daemon():
        raise RuntimeError(
            "无法启动 daemon。请确认钉钉桌面端已运行，且 frida-tools 已安装。"
        )


def _health_check() -> tuple[bool, str]:
    try:
        r = _http("GET", "/health", timeout=5)
        if r.get("daemon") != "running":
            return False, "daemon 未运行"
        if r.get("frida") == "detached":
            return False, "Frida 已断开"
        return True, ""
    except Exception as e:
        return False, str(e)


def _search_log(keyword: str, limit: int = 30) -> list[str]:
    """直接从日志文件搜索（daemon 不在线时的备选）。"""
    log_path = os.path.normpath(LOG_FILE)
    if not os.path.isfile(log_path):
        return []
    results = []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not keyword or keyword in line:
                results.append(line.rstrip())
                if len(results) > limit * 3:
                    results = results[-limit:]
    return results[-limit:]


# ── MCP Server ──────────────────────────────────────────────────────

mcp = FastMCP("dingtalk-desktop")


@mcp.tool(
    name="dingtalk_send_message",
    description=(
        "通过钉钉桌面客户端发送文本消息。"
        "支持通过 CID 或联系人姓名发送（姓名须与联系人库/contacts.json 中显示名完全一致）。"
        "单聊 CID 格式: \"自己UID:对方UID\"；群聊 CID: 纯数字。"
        "钉钉必须在运行中（前台或托盘）。"
    ),
)
def dingtalk_send_message(
    message: str,
    cid: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    """发送文本消息到钉钉会话。"""
    _ensure_daemon()
    body: dict = {"message": message}
    if cid:
        body["cid"] = cid
    elif name:
        body["name"] = name
    else:
        return "错误: 需要提供 cid 或 name"

    result = _http("POST", "/send", body, timeout=30)
    if result.get("success"):
        target = result.get("resolved_name", cid or name)
        resolved_cid = result.get("resolved_cid", "")
        if resolved_cid:
            target = f"{target} ({resolved_cid})"
        return f"消息已发送到 {target}"
    return f"发送失败: {result.get('error', json.dumps(result))}"


@mcp.tool(
    name="dingtalk_fetch_history",
    description=(
        "获取钉钉指定会话的历史消息。通过常驻 Frida daemon 获取，无需重复初始化。"
        "支持通过 CID 或联系人姓名查询（姓名须与联系人库显示名完全一致）。"
    ),
)
def dingtalk_fetch_history(
    cid: Optional[str] = None,
    name: Optional[str] = None,
    count: int = 20,
    before: Optional[str] = None,
    after: Optional[str] = None,
) -> str:
    """获取钉钉会话历史消息。"""
    _ensure_daemon()
    ok, detail = _health_check()
    if not ok:
        return f"daemon 不可用: {detail}"

    body: dict = {"count": min(count, 50)}
    if cid:
        body["cid"] = cid
    elif name:
        body["name"] = name
    else:
        return "错误: 需要提供 cid 或 name"
    if before:
        body["before"] = before
    if after:
        body["after"] = after

    result = _http("POST", "/fetch", body, timeout=60)
    if not result.get("success"):
        return result.get("error", "获取失败")

    msgs = result.get("messages", [])
    if not msgs:
        return "没有找到历史消息"

    lines = []
    for m in msgs:
        text = m.get("text") or f"[{m.get('content_type_name', '未知类型')}]"
        lines.append(f"[{m.get('time', '')}] {m.get('sender', '?')}: {text}")

    header = f"{result.get('cid', '')} 最近 {len(msgs)} 条消息"
    if result.get("has_more"):
        header += "（还有更多）"
    return f"{header}\n" + "\n".join(lines)


@mcp.tool(
    name="dingtalk_search_log",
    description=(
        "搜索钉钉消息监听器的 JSONL 日志。"
        "可按联系人名称、CID、消息内容等关键词搜索。"
        "返回最近匹配的记录（最新在后）。"
    ),
)
def dingtalk_search_log(keyword: str, limit: int = 30) -> str:
    """按关键词搜索消息日志。"""
    if _is_daemon_running():
        qs = urllib.parse.urlencode({"keyword": keyword, "limit": limit})
        result = _http("GET", f"/search?{qs}")
        if result.get("count", 0) == 0:
            return f'未找到包含 "{keyword}" 的记录'
        return f"找到 {result['count']} 条匹配:\n" + "\n".join(result["results"])

    lines = _search_log(keyword, limit)
    if not lines:
        return f'未找到包含 "{keyword}" 的记录'
    return f"找到 {len(lines)} 条匹配:\n" + "\n".join(lines)


@mcp.tool(
    name="dingtalk_find_conversation",
    description=(
        "按显示姓名在联系人库与 contacts.json 中精确查找会话 CID。"
        "不再搜索消息日志；多条精确同名会话会返回歧义错误，需改用 cid。"
    ),
)
def dingtalk_find_conversation(name: str) -> str:
    """按姓名查找钉钉会话 CID。"""
    _ensure_daemon()
    qs = urllib.parse.urlencode({"name": name})
    result = _http("GET", f"/contacts?{qs}")

    if result.get("error"):
        extra = ""
        candidates = result.get("candidates", [])
        if candidates:
            extra = "\n候选:\n" + "\n".join(
                f"  CID: {c.get('cid', '')} | {c.get('sender', c.get('name', ''))} | {c.get('preview', '')}"
                for c in candidates
            )
        return f"{result['error']}{extra}"

    entries = result.get("results", [])
    if not entries:
        return f"未找到显示名与「{name}」完全一致的会话"

    formatted = "\n".join(
        f"CID: {e.get('cid', '')} | {e.get('sender', e.get('name', ''))} | {e.get('time', '')} | {e.get('preview', '')}"
        for e in entries
    )
    return f"找到 {len(entries)} 个会话:\n{formatted}"


@mcp.tool(
    name="dingtalk_fetch_reports",
    description=(
        "获取钉钉工作汇报（日报/周报/月报）。"
        "从工作汇报会话中拉取 contentType=300 的消息，解析 b_form 表单内容。"
        "支持按日期范围、作者、汇报类型过滤。"
        "需要在 config.json 中配置 report_cid。"
    ),
)
def dingtalk_fetch_reports(
    count: int = 10,
    before: Optional[str] = None,
    after: Optional[str] = None,
    author: Optional[str] = None,
    report_type: Optional[str] = None,
    max_content_length: int = 5000,
) -> str:
    """获取钉钉工作汇报。"""
    _ensure_daemon()
    ok, detail = _health_check()
    if not ok:
        return f"daemon 不可用: {detail}"

    body: dict = {"count": count}
    if before:
        body["before"] = before
    if after:
        body["after"] = after
    if author:
        body["author"] = author
    if report_type:
        body["report_type"] = report_type

    timeout = max(count * 10, 120)
    result = _http("POST", "/fetch_reports", body, timeout=min(timeout, 240))
    if not result.get("success"):
        return result.get("error", "获取失败")

    msgs = result.get("messages", [])
    if not msgs:
        return "没有找到匹配的工作汇报"

    reports = []
    for m in msgs:
        text = m.get("text", "")
        parts = text.split(" || ")
        header_part = parts[0] if parts else ""

        import re
        title_match = re.match(r"^(.+?)\s*\[(.+?)\]", header_part)
        title = title_match.group(1) if title_match else header_part
        category = title_match.group(2) if title_match else ""

        formatted = f"📋 {title}"
        if category:
            formatted += f" [{category}]"
        formatted += f"\n   时间: {m.get('time', '')} | 发送者: {m.get('sender', '')}"

        content_len = 0
        for i in range(1, len(parts)):
            sep = parts[i].find("::")
            if sep > 0:
                key = parts[i][:sep].strip()
                value = parts[i][sep + 2:].strip()
                line = f"\n   【{key}】{value}"
            elif parts[i].strip():
                line = f"\n   {parts[i].strip()}"
            else:
                continue
            if 0 < max_content_length <= content_len + len(line):
                formatted += f"\n   ... [内容已截断，共 {len(parts) - 1} 个字段]"
                break
            formatted += line
            content_len += len(line)
        reports.append(formatted)

    total = result.get("total_ct300", "?")
    pages = result.get("pages", "?")
    header = f"共 {len(reports)} 份工作汇报（翻页 {pages} 次，原始 {total} 条ct=300）"
    sep = "─" * 40
    return f"{header}\n{sep}\n" + f"\n{sep}\n".join(reports)


@mcp.tool(
    name="dingtalk_fetch_my_reports",
    description=(
        "获取自己的钉钉工作汇报（日报/周报/月报）。"
        "从「我的报」群中提取转发的报告卡片（ct=2950），通过 CEF DOM 方式获取完整内容。"
        "与 dingtalk_fetch_reports（获取他人日报）分开使用。"
        "注意：加载完整内容时每份报告需要约 20 秒。"
        "需要在 config.json 中配置 my_report_group_cid。"
    ),
)
def dingtalk_fetch_my_reports(
    count: int = 3,
    before: Optional[str] = None,
    after: Optional[str] = None,
    report_type: Optional[str] = None,
    full_content: bool = True,
    max_content_length: int = 3000,
) -> str:
    """获取自己的工作汇报。"""
    _ensure_daemon()
    ok, detail = _health_check()
    if not ok:
        return f"daemon 不可用: {detail}"

    body: dict = {"count": min(count, 10), "full_content": full_content}
    if before:
        body["before"] = before
    if after:
        body["after"] = after
    if report_type:
        body["report_type"] = report_type

    timeout = 180 if full_content else 30
    result = _http("POST", "/fetch_my_reports", body, timeout=timeout)
    if not result.get("success"):
        return result.get("error", "获取失败")

    reports_data = result.get("reports", [])
    if not reports_data:
        return "没有找到匹配的工作汇报"

    import re
    NOISE_RE = re.compile(r"^(钉钉|已读|点赞|评论|推荐|更多未读|查看全部|日志接收人|添加到)")

    formatted_reports = []
    for r in reports_data:
        out = f"📋 {r.get('title', '未知')}\n   时间: {r.get('time', '')}"
        if r.get("extraction_method"):
            out += f" [提取: {r['extraction_method']}]"
        content = r.get("content", "")
        if content:
            meaningful = [
                l for l in content.split("\n")
                if l.strip() and not NOISE_RE.match(l.strip()) and len(l.strip()) > 2
            ]
            body_text = "\n".join(f"   {l}" for l in meaningful)
            if 0 < max_content_length < len(body_text):
                body_text = body_text[:max_content_length] + f"\n   ... [内容已截断，原始长度: {len(body_text)} 字符]"
            out += "\n" + body_text
        formatted_reports.append(out)

    sep = "─" * 40
    return f"共 {len(formatted_reports)} 份我的工作汇报\n{sep}\n" + f"\n{sep}\n".join(formatted_reports)


@mcp.tool(
    name="dingtalk_monitor_status",
    description=(
        "检查钉钉消息监听器的运行状态。"
        "返回进程是否存活、日志文件大小和最近更新时间。"
    ),
)
def dingtalk_monitor_status() -> str:
    """获取 daemon / monitor 运行状态。"""
    if _is_daemon_running():
        h = _http("GET", "/health")
        lines = [
            f"Daemon: 运行中 ✅ (PID={h.get('pid', '?')}, uptime={h.get('uptime_seconds', '?')}s)",
            f"DingTalk: {'运行中 (PID=' + str(h.get('dingtalk_pid', '?')) + ')' if h.get('dingtalk_running') else '未运行 ❌'}",
            f"Frida: {'已附加 ✅' if h.get('frida_attached') else '未附加 ❌'}",
            f"CEF: {'就绪 ✅' if h.get('cef_ready') else '未就绪 ❌'}",
            f"监听器: {'运行中 ✅ (' + str(h.get('monitor_messages', 0)) + ' 条消息)' if h.get('monitor_running') else '未启动'}",
            f"已获取: {h.get('fetches', 0)} 次",
            f"已发送: {h.get('sends', 0)} 条",
            f"日志: {'存在' if h.get('log_exists') else '不存在'} → {h.get('log_file', '')}",
        ]
        return "\n".join(lines)

    lines = ["Daemon: 未运行 ❌"]
    log_path = os.path.normpath(LOG_FILE)
    if os.path.isfile(log_path):
        stat = os.stat(log_path)
        lines.append(
            f"日志文件: 存在 ({stat.st_size // 1024}KB, "
            f"更新于 {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(stat.st_mtime))})"
        )
    else:
        lines.append("日志文件: 不存在")
    return "\n".join(lines)


# ── entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
