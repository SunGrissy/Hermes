---
name: cursor-to-dingtalk
description: 在 Cursor 会话结束或任务收尾时，把结果摘要通过钉钉发给自己。调用本机 dingtalk-desktop daemon 的 /send 接口。Use when the user asks to "把结果发钉钉" / "收工后发钉钉" / "会话结束发我"，或会话收尾时用户希望收到本轮交付摘要。
---

# Cursor 结果发钉钉

在会话结束或任务收尾时，把本轮的结论、交付物摘要通过钉钉发给自己（或指定群/人）。依赖本机已运行的 **dingtalk-desktop daemon**（端口 19200）。

## 何时使用

- 用户说「把结果发钉钉」「收工后发钉钉」「会话结束发我」等
- 会话收尾（验收通过、收工、先这样）且用户希望收到摘要时
- 无需用户再开钉钉复制粘贴，Agent 主动推送

## 前置条件

- 本机已启动 **dingtalk-desktop** 的 daemon（默认 `http://127.0.0.1:19200`）
- 已配置发送目标：群 CID 或会话名称（见下方「发送目标」）

## 发送方式

### 方式一：用脚本（推荐）

工作空间根目录执行：

```powershell
# 从标准输入读内容并发送
"本次完成：xxx 已验收，commit abc123" | py .cursor/skills/cursor-to-dingtalk/scripts/send_result.py

# 或直接传参
py .cursor/skills/cursor-to-dingtalk/scripts/send_result.py "本次完成：xxx"
```

脚本会读取 `dingtalk-desktop/digest_config.json` 的 `notify_target` 作为默认接收方（群 CID）；若配置了 `DINGTALK_SEND_TARGET` 环境变量（CID 或会话名），则优先使用。

### 方式二：HTTP 直接调

```powershell
$body = @{ cid = "73216314617"; message = "会话摘要：..." } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:19200/send" -Method POST -Body $body -ContentType "application/json; charset=utf-8"
```

按姓名解析会话时用 `name` 代替 `cid`，例如 `name = "助理通知群"`（需 daemon 侧 contacts 能解析）。

### 方式三：Webhook（机器人）

使用钉钉群机器人 Webhook 发送 Markdown，**无需本机 daemon**。机器人若开启了「关键词」校验，需在正文中包含关键词；本脚本将关键词 **「小秘书提醒」作为 footer 放在最后一行**，正文可自由排版。

```powershell
$env:DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=..."
"## 本轮摘要`n- 完成 xxx" | py .cursor/skills/cursor-to-dingtalk/scripts/send_result_webhook.py
```

- 环境变量 `DINGTALK_WEBHOOK_URL`：完整 webhook URL（勿提交到仓库）
- 脚本会在正文末尾自动追加 `---` 和 `小秘书提醒`

## 发送目标

| 来源 | 说明 |
|------|------|
| `dingtalk-desktop/digest_config.json` 的 `notify_target` | 默认群 CID（如助理通知群） |
| 环境变量 `DINGTALK_SEND_TARGET` | 覆盖默认，可为 CID 或会话名称 |
| 环境变量 `DINGTALK_DAEMON_URL` | 覆盖 daemon 地址，默认 `http://127.0.0.1:19200` |

## 摘要建议

发送前由 Agent 整理为一小段可读摘要，建议包含：

- 本轮做了什么（任务/需求简述）
- 关键交付（文件/接口/结论）
- 验收状态或后续建议（如有）

单条消息不宜过长；若内容很多，可只发摘要 + 「详情见本地 / 文档链接」。

## 与 dingtalk-desktop 的关系

- 本 Skill 只负责「调用 daemon 发一条消息」，不依赖 dingtalk-desktop 的轮询或其它 skill。
- daemon 需在本机运行且已 attach 钉钉客户端，否则 `/send` 会失败。
