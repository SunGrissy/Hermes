# -*- coding: utf-8 -*-
"""
通过钉钉机器人 Webhook 发送 Markdown 消息。
正文由 stdin 或参数传入，末尾自动加 footer「小秘书提醒」（满足机器人关键词校验）。
用法:
  echo "## 摘要\n- 完成 xxx" | python send_result_webhook.py
  python send_result_webhook.py "## 摘要\n- 完成 xxx"
环境变量:
  DINGTALK_WEBHOOK_URL  完整 webhook URL（必填，勿提交到仓库）
"""
import os
import sys
import json
import urllib.request
import urllib.error

FOOTER = "\n\n---\n小秘书提醒"


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
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
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


def main():
    url = os.environ.get("DINGTALK_WEBHOOK_URL", "").strip()
    if not url:
        print("error: DINGTALK_WEBHOOK_URL not set", file=sys.stderr)
        return 1

    if len(sys.argv) > 1:
        content = " ".join(sys.argv[1:])
    else:
        content = sys.stdin.read()

    content = content.strip()
    if not content:
        print("error: empty content", file=sys.stderr)
        return 1

    text = content + FOOTER
    title = "Cursor 会话结果"
    ok, msg = send_markdown(url, title, text)
    if ok:
        print("sent")
        return 0
    print("error:", msg, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
