#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""钉钉 Stream 机器人收消息 -> 本机 multica issue create。运行前须 multica login 且 multica 在 PATH。"""

import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.request
from typing import Optional

from dingtalk_stream import AckMessage
import dingtalk_stream

# [AgentMltc Task] 开始时间: 2026-04-18
# [AgentMltc Task] 任务目标: multica-dingtalk-bridge Task3-4 Stream 派单桥

PREFIX = "#派单"
LOG = logging.getLogger("multica-bridge")


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
    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__()
        self._log = logger or LOG

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        tc = incoming.text
        raw = ((tc.content if tc else "") or "").strip()
        if not raw.startswith(PREFIX):
            self.reply_text(
                "未建单。请以 `#派单 一行标题` 开头；第二行起为描述（可选）。",
                incoming,
            )
            return AckMessage.STATUS_OK, "OK"

        body = raw[len(PREFIX) :].lstrip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if not lines:
            self.reply_text("标题不能为空。", incoming)
            return AckMessage.STATUS_OK, "OK"

        title = lines[0][:500]
        description = "\n".join(lines[1:]) if len(lines) > 1 else "（钉钉派单，无额外描述）"

        cmd = [
            "multica",
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
        ]
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
            self.reply_text(
                "Multica 建单失败。请检查本机：`multica auth status`、default workspace、`multica issue create` 手工是否正常。",
                incoming,
            )
            return AckMessage.STATUS_OK, "OK"

        self.reply_text(
            "已创建 Multica Issue（todo / medium）。CLI 输出：\n```\n" + out[:1200] + "\n```",
            incoming,
        )
        _notify_webhook(
            "Multica 新单",
            "### Multica 钉钉派单\n\n" + title + "\n\n```\n" + out[:800] + "\n```\n",
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
