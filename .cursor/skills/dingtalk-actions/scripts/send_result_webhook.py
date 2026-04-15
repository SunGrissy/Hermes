# -*- coding: utf-8 -*-
"""
通过钉钉机器人 Webhook 发送 Markdown 消息。
标题：环境变量 DINGTALK_TITLE（默认 Agent代号-工作摘要），建议设为「本会话代号-工作摘要」如 AgentFlow-工作摘要。
正文由 stdin 或文件传入，末尾自动加 footer「###### ※ 小秘书提醒」。
URL: DINGTALK_WEBHOOK_URL；否则读 dingtalk-desktop/webhook_config.json。
配置 key 由环境变量 DINGTALK_WEBHOOK_KEY 指定（默认 cursor_session）；该 key 为空时回退 default。
"""
import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime

FOOTER = "\n\n###### ※ 小秘书提醒"
SEND_LOG_NAME = "cursor_webhook_sends.log"


def _log_send(title: str, content_len: int):
    """追加一条发送记录到 dingtalk-desktop/logs/，便于按时间查是哪个 Agent 发的。"""
    root = _workspace_root()
    log_dir = os.path.join(root, "dingtalk-desktop", "logs")
    log_path = os.path.join(log_dir, SEND_LOG_NAME)
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\t{title}\tlen={content_len}\n"
            )
    except Exception:
        pass
DEFAULT_TITLE = "Agent代号-工作摘要"
DEFAULT_WEBHOOK_KEY = "cursor_session"


def _workspace_root():
    """从脚本位置推到工作空间根目录。"""
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def _get_webhook_url() -> str:
    """优先 DINGTALK_WEBHOOK_URL；否则读 webhook_config.json 中 DINGTALK_WEBHOOK_KEY 对应项，空则回退 default。"""
    url = os.environ.get("DINGTALK_WEBHOOK_URL", "").strip()
    if url:
        return url
    root = _workspace_root()
    path = os.path.join(root, "dingtalk-desktop", "webhook_config.json")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        key = os.environ.get("DINGTALK_WEBHOOK_KEY", "").strip() or DEFAULT_WEBHOOK_KEY
        url = (cfg.get(key) or "").strip()
        if not url and key != "default":
            url = (cfg.get("default") or "").strip()
        return url
    except Exception:
        return ""


def send_markdown(webhook_url: str, title: str, text: str) -> tuple[bool, str]:
    """发送 Markdown 类型消息，text 末尾已带 footer。"""
    body = {
        "msgtype": "markdown",
        "markdown": {
            "title": title[:50],
            "text": text,
        },
    }
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errcode") == 0:
            return True, "ok"
        return False, data.get("errmsg", str(data))
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8")
        except Exception:
            err = str(e)
        return False, err
    except Exception as e:
        return False, str(e)


def _read_content() -> str:
    """读正文：优先 UTF-8 文件路径，否则 stdin（强制 UTF-8），最后才用 argv。避免 Windows 下中文变问号。"""
    # 1) 首个参数为存在的文件路径 → 从文件读 UTF-8
    if len(sys.argv) > 1:
        path = os.path.abspath(sys.argv[1])
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
    # 2) 有 stdin 输入（管道/重定向）→ 按 UTF-8 读
    if not sys.stdin.isatty():
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        raw = sys.stdin.buffer.read()
        return raw.decode("utf-8", errors="replace").strip()
    # 3) 命令行参数字符串（Windows 下长中文易乱码，推荐用文件或 stdin）
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()
    return ""


def main():
    url = _get_webhook_url()
    if not url:
        print(
            "error: set DINGTALK_WEBHOOK_URL or dingtalk-desktop/webhook_config.json "
            "(DINGTALK_WEBHOOK_KEY or cursor_session / default)",
            file=sys.stderr,
        )
        return 1

    content = _read_content()
    if not content:
        print("error: empty content", file=sys.stderr)
        return 1

    scope = os.environ.get("TAO_UPDATE_SCOPE", "").strip()
    if scope and "tao-update-scope:" not in content:
        content = content + "\n\ntao-update-scope:" + scope

    text = content + FOOTER
    title = os.environ.get("DINGTALK_TITLE", "").strip() or DEFAULT_TITLE
    ok, msg = send_markdown(url, title, text)
    if ok:
        _log_send(title, len(content))
        print("sent")
        return 0
    print("error:", msg, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
