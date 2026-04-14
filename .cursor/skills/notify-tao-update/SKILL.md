---
name: notify-tao-update
description: 在 Cursor 会话里说「请涛哥更新」「让涛哥更新」时，直接调本机钉钉 daemon 私聊杨玉涛（不经过助理群 Webhook、不依赖群内 tao-update-scope）。Use when the user asks to 请涛哥更新 / 让涛哥更新 / 通知涛哥拉代码 / 让主程更新 from Cursor.
---

# Cursor 内「请涛哥更新」→ 私聊涛哥

## 与助理群口令的区别

| 场景 | 行为 |
|------|------|
| **在 Cursor 里对 Agent 说** | 走本 Skill：**直接** `POST` 本机 `DINGTALK_DAEMON_URL/send` 私聊杨玉涛；**不要**再调助理群机器人说明「未找到锚点」。 |
| **在助理通知群发「请涛哥更新」** | 由 `dingtalk-desktop` 路由：从群内最近消息里找 Cursor 收工 Webhook 里的 `tao-update-scope:xxx`；找不到才在群里回执说明。 |

## 执行方式（Agent 必做）

1. **确定子模块名** `xx`：优先用户口述；否则看本轮主要改动目录；再否则 `git status --short` 推断（与 `scripts/notify_tao_daemon.py` 一致）。
2. **本机执行**（需 daemon 与钉钉已登录）：

```powershell
cd "d:\MyAgents"
py scripts/notify_tao_daemon.py <子模块名>
```

可选环境变量：

- `TAO_UPDATE_SCOPE`：与传参二选一。
- `TAO_RECIPIENT_CID`：若已采集涛哥 CID（如 `75569139709`），优先用 cid，避免姓名歧义。
- `TAO_RECIPIENT_NAME`：默认 `杨玉涛`。
- `DINGTALK_DAEMON_URL`：默认 `http://127.0.0.1:19200`。

3. **禁止**：用助理群 Webhook 发「未找到 tao-update-scope」来回应 **Cursor 内**的这条指令（那是群内链路用的）。

## 私聊文案规则

与 `dingtalk-desktop/skills/taoge_update.py` 一致：

- `涛哥，{xx}求更新~`
- 若 `xx` 落在常见需重启子模块集合内，追加 `需要重启`
- 末尾 ` [忙疯了]`（不用裸 🤖：JS 注入易乱码；钉钉里方括号词**可能被显示成表情**，属正常）

## 收工发钉钉（Webhook）仍建议带锚点

若本轮收工仍用 `cursor-to-dingtalk` Webhook 发助理群，可继续带 `tao-update-scope:xx`，便于你**稍后在钉钉里**再发一次「请涛哥更新」走群内链路；与 Cursor 直发私聊互不冲突。
