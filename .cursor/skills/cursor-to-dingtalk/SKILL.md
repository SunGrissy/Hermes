---
name: cursor-to-dingtalk
description: 在 Cursor 会话结束或任务收尾时，把结果摘要通过钉钉发给自己。**必须用 Webhook（机器人身份）**，禁止用 daemon /send；推送正文**必须带本会话 Agent 代号**（如「本会话代号：AgentFlow」）。Use when the user asks to "把结果发钉钉" / "收工后发钉钉" / "会话结束发我"，或会话收尾时用户希望收到本轮交付摘要。
---

# Cursor 结果发钉钉

在会话结束或任务收尾时，把本轮的结论、交付物摘要通过钉钉发给自己（或指定群/人）。

## 重要：用机器人发，不要用用户身份

| 方式 | 效果 | 何时用 |
|------|------|--------|
| **Webhook** | 群内**机器人**发，带「小秘书提醒」footer | **默认**。用户说「发钉钉」「会话结果发我」时必用 |
| daemon /send | 以**用户本人**身份在钉钉里发一条 | 仅当用户明确说「用我的身份发」「替我发到某群」时才用 |

**只要用户说的是「把结果/会话摘要发钉钉」，一律用 Webhook（send_result_webhook.py），不要调 daemon /send。**

## 何时使用

- 用户说「把结果发钉钉」「收工后发钉钉」「会话结束发我」等
- 会话收尾（验收通过、收工、先这样）且用户希望收到摘要时
- 无需用户再开钉钉复制粘贴，Agent 主动推送

## 前置条件（Webhook 默认）

二选一即可：

1. **统一配置（推荐）**：在 `dingtalk-desktop/` 下复制 `webhook_config.json.example` 为 `webhook_config.json`，填入各机器人 URL；本 Skill 使用 key **cursor_session**。该文件已加入 .gitignore，勿提交。
2. **环境变量**：设置 **DINGTALK_WEBHOOK_URL**（完整 webhook URL）。若同时存在，环境变量优先。

无需本机 daemon 运行。

## 发送方式

### 方式一：Webhook（默认，机器人发）

用户说「发钉钉」「会话结果发我」时**必须用此方式**，以机器人身份发。**标题**为「Agent代号-工作摘要」；**footer** 为 `###### ※ 小秘书提醒`。

**推荐两种方式（保证中文不乱码）：**

```powershell
# 方式 A：先写入 UTF-8 文件，再传文件路径（最稳，Agent 首选）
# 标题用本会话 Agent 代号，例如 AgentFlow-工作摘要
$env:DINGTALK_TITLE = "AgentFlow-工作摘要"
$summary = "## 本轮摘要`n- 完成 xxx"
[System.IO.File]::WriteAllText("$env:TEMP\dt_summary.md", $summary, [System.Text.Encoding]::UTF8)
py .cursor/skills/cursor-to-dingtalk/scripts/send_result_webhook.py "$env:TEMP\dt_summary.md"
```

```powershell
# 方式 B：管道 + 设控制台为 UTF-8（否则钉钉里中文会变成问号）
$env:DINGTALK_TITLE = "AgentFlow-工作摘要"
$OutputEncoding = [System.Text.Encoding]::UTF8
"## 本轮摘要`n- 完成 xxx" | py .cursor/skills/cursor-to-dingtalk/scripts/send_result_webhook.py
```

- **不要**在 Windows 下把长中文直接当命令行参数传入（如 `py send_result_webhook.py "很多中文..."`），易因 GBK 导致钉钉里显示为问号。
- **标题**：钉钉消息标题格式为「Agent代号-工作摘要」。发钉钉前请设置环境变量 **DINGTALK_TITLE** = 本会话代号-工作摘要（例如 `AgentFlow-工作摘要`）；未设置时脚本使用默认「Agent代号-工作摘要」。
- **Footer**：脚本会在正文末尾自动追加 `###### ※ 小秘书提醒`（满足机器人关键词校验）。
- URL 来源：`dingtalk-desktop/webhook_config.json` 的 **cursor_session**，或环境变量 `DINGTALK_WEBHOOK_URL`

## 保证中文渲染（必读）

钉钉消息正文若出现**中文变成问号**，是因为传给脚本的内容不是 UTF-8。Agent 发钉钉时必须遵守：

1. **首选**：把摘要写入**临时文件**（保存时用 **UTF-8 编码**），再执行 `py .../send_result_webhook.py <该文件路径>`。脚本会从文件按 UTF-8 读取。
2. **次选**：用管道时，在 PowerShell 里先执行 `$OutputEncoding = [System.Text.Encoding]::UTF8`，再 pipe 内容进脚本。
3. **禁止**：不要把大段中文作为命令行参数（`py script.py "中文..."`），在 Windows 下会按系统编码（如 GBK）传参，导致乱码。

**统一 webhook 配置**：`dingtalk-desktop/webhook_config.json.example` 列出全部 key（cursor_session / default / version_digest / resume_notify / memo_tracker / doc_review），与 `digest_config.json` 里现有 webhook 一一对应；后续可让 digest、简历、备忘等也从该文件读，实现一处配置多端复用。

### 方式二：daemon /send（仅当用户明确要求「用我的身份发」时）

以用户本人身份在钉钉里发，需本机 daemon 运行。**仅在用户明确说「用我的身份发」「替我发到某群」时使用。**

```powershell
"本次完成：xxx" | py .cursor/skills/cursor-to-dingtalk/scripts/send_result.py
```

脚本会读取 `dingtalk-desktop/digest_config.json` 的 `notify_target`；或设置 `DINGTALK_SEND_TARGET`（CID 或会话名）。

### 方式三：HTTP 直接调 daemon

```powershell
$body = @{ cid = "73216314617"; message = "会话摘要：..." } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:19200/send" -Method POST -Body $body -ContentType "application/json; charset=utf-8"
```

按姓名解析会话时用 `name` 代替 `cid`。

## 发送目标（仅 daemon 方式）

| 来源 | 说明 |
|------|------|
| `dingtalk-desktop/digest_config.json` 的 `notify_target` | 默认群 CID（如助理通知群） |
| 环境变量 `DINGTALK_SEND_TARGET` | 覆盖默认，可为 CID 或会话名称 |
| 环境变量 `DINGTALK_DAEMON_URL` | 覆盖 daemon 地址，默认 `http://127.0.0.1:19200` |

## 摘要建议

发送前由 Agent 整理为一小段可读摘要，**必须**包含：

- **本会话 Agent 代号**（必带）：在正文开头或结尾写明，格式如 `本会话代号：AgentFlow`，便于在钉钉里区分是哪个会话/任务。
- 本轮做了什么（任务/需求简述）
- 关键交付（文件/接口/结论）
- 验收状态或后续建议（如有）

单条消息不宜过长；若内容很多，可只发摘要 + 「详情见本地 / 文档链接」。**未带 Agent 代号的推送视为不符合本 Skill 要求。**

## 事后查是哪个 Agent 发的

每次通过 Webhook 成功发送后，脚本会往 **`dingtalk-desktop/logs/cursor_webhook_sends.log`** 追加一行，格式：

```
2026-03-19 14:32:01	AgentFlow-工作摘要	len=256
```

- **时间**：发送时刻，可与钉钉消息的收到时间对照。
- **第二列**：即 `DINGTALK_TITLE`，钉钉消息标题就是它（Agent代号-工作摘要），可直接对应。
- **len**：正文长度，便于区分不同摘要。

若钉钉里只看到「小秘书提醒」或旧格式标题，打开该 log，按时间倒序看最近几条，即可对应到是哪个会话/Agent 发的。

## 与 dingtalk-desktop 的关系

- **默认用 Webhook**：不依赖 daemon，不占用用户身份。
- 仅当用户明确要求「用我的身份发」时，才调 daemon `/send`；此时 daemon 需运行且已 attach 钉钉客户端。
