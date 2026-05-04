---
name: dingtalk-actions
description: |
  从 Cursor 会话往钉钉发消息——两种场景统一入口：
  1. 会话结果摘要发群（Webhook 机器人）
  2. 通知涛哥更新（daemon 私聊）
  默认用 Webhook，禁止用 daemon /send 发摘要。

  触发词：「把结果发钉钉」「收工后发钉钉」「会话结束发我」「请涛哥更新」「让涛哥更新」
---

# 钉钉消息操作

从 Cursor 发钉钉的统一入口。Agent 根据意图自动选择发送方式。

## 场景路由

| 用户说 | 方式 | 执行 |
|--------|------|------|
| 把结果发钉钉 / 收工后发钉钉 | **Webhook**（机器人） | `scripts/send_result_webhook.py` |
| 请涛哥更新 / 让涛哥更新 | **daemon 私聊** | `scripts/notify_tao_daemon.py` 或仓库根 `scripts/notify_tao_daemon.py` |
| 用我的身份发 | daemon /send | 仅此场景才用用户身份 |

---

## A. 会话结果发群（Webhook）

用 Webhook 机器人发消息到群里，带「小秘书提醒」footer。

### 发送方式（推荐：文件方式，避免中文乱码）

```powershell
$env:DINGTALK_TITLE = "AgentXxx-工作摘要"
$summary = "## 本轮摘要`n- 完成 xxx"
[System.IO.File]::WriteAllText("$env:TEMP\dt_summary.md", $summary, [System.Text.Encoding]::UTF8)
py .cursor/skills/dingtalk-actions/scripts/send_result_webhook.py "$env:TEMP\dt_summary.md"
```

### 中文渲染铁律

1. **首选**：写入 UTF-8 临时文件，传文件路径
2. **次选**：管道 + `$OutputEncoding = [System.Text.Encoding]::UTF8`
3. **禁止**：大段中文作为命令行参数

### 摘要必须包含

- **本会话 Agent 代号**（必带）
- 本轮做了什么
- 关键交付
- 验收状态或后续建议

### Webhook 配置

`dingtalk-desktop/webhook_config.json` 的 key **cursor_session**；或环境变量 `DINGTALK_WEBHOOK_URL`。

### 涛哥更新锚点（可选）

收工发 Webhook 时在正文末尾加 `tao-update-scope:pm-system`（换成实际子目录名），便于之后在群内触发涛哥更新链路。设置 `TAO_UPDATE_SCOPE` 环境变量可自动追加。

---

## B. 通知涛哥更新（daemon 私聊）

在 Cursor 内说「请涛哥更新」→ 直接调 daemon 私聊杨玉涛，不经过助理群 Webhook。

```powershell
cd "d:\MyAgents"
py scripts/notify_tao_daemon.py <子模块名>
```

私聊文案：`涛哥，{xx}求更新~`；需重启的子模块追加 `需要重启`；末尾 ` [忙疯了]`。

### 环境变量

- `TAO_UPDATE_SCOPE`：子模块名
- `TAO_RECIPIENT_CID`：涛哥单聊 cid（优先）
- `DINGTALK_DAEMON_URL`：默认 `http://127.0.0.1:19200`

---

## 发送日志

Webhook 成功后记录到 `dingtalk-desktop/logs/cursor_webhook_sends.log`：时间、标题、长度。

## 安全

Webhook URL 只存本机配置文件（已 .gitignore），勿提交到 Git。

## 变更记录

| 日期 | 版本 | 变更 | 来源 |
|------|------|------|------|
| 2026-03-19 | v1.0 | cursor-to-dingtalk 创建 | AgentDing |
| 2026-04-06 | v1.1 | notify-tao-update 创建 | AgentTao |
| 2026-04-14 | v2.0 | 合并为 dingtalk-actions | AgentSkil |
