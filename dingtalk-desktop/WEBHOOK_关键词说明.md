# 钉钉机器人「自定义关键词」说明

## 关键字为什么必须匹配？

钉钉群机器人的**安全设置**里若选择了「**自定义关键词**」，则只有**消息内容**里包含你配置的任一关键词时，钉钉才会接受该条 Webhook 请求，否则会返回错误、消息发不出去。

**「关键字都失效了」** 常见原因：

1. **钉钉端**：该群的机器人被改成了「加签」、或关键词被改/删，当前我们发的「小秘书提醒」不再命中。
2. **多群多机器人**：不同群用了不同机器人，有的群关键词已改，我们仍按旧词发。

---

## 我们当前使用的关键词

| 关键词       | 用途说明                     | 消息里出现位置 |
|-------------|------------------------------|----------------|
| **小秘书提醒** | 备忘、状态检查、简历、日报、Cursor 发钉钉、**文档预审 (doc_review)** 等 | Markdown `title` 或正文 footer：`###### ※ 小秘书提醒` |

说明：预审推送正文里可仍写「PM助理 …」做人设，但**机器人关键词校验**依赖 title/footer 中的「小秘书提醒」（与同群其它小秘书机器人一致）。

请在各使用到的钉钉群里，检查：

- 群设置 → 智能群助手 → 对应机器人 → **安全设置**
- 选择「**自定义关键词**」，在关键词列表中**至少包含**：`小秘书提醒`

若你改成了「**加签**」：要么改回「自定义关键词」并填上上述词，要么需要在本项目里实现加签逻辑后再发 Webhook。

---

## 若要在钉钉里改用「新关键词」

例如把「小秘书提醒」改成「助理提醒」，需要在下面位置**统一替换**（建议先搜 `小秘书提醒` 再逐个确认）：

### 配置/模板（改一处即可被多处读取）

- **dingtalk-desktop/message_templates.json**
  - `version_digest.footer`、`memo_tracker.keyword` / `footer`、`resume_screen.footer`、`status_check.keyword` / `footer`、`doc_review.keyword` / `footer` 等
- **dingtalk-desktop/digest_config.json**
  - 若有 `footer` / 关键词相关字段

### 代码写死的关键词（需同步改）

- **.cursor/skills/dingtalk-actions/scripts/send_result_webhook.py**  
  - `FOOTER = "\n\n###### ※ 小秘书提醒"`
- **dingtalk-desktop/skills/memo_tracker.py**  
  - 默认 `webhook_keyword` / `footer`：`'[小秘书提醒]'`、`'###### ※ 小秘书提醒'`
- **dingtalk-desktop/skills/status_check.py**  
  - `send_via_webhook(..., keyword='小秘书提醒')`，以及模板默认 footer
- **dingtalk-desktop/skills/resume_screen.py**  
  - footer 默认 `*小秘书提醒*`
- **dingtalk-desktop/memo_reminder.py**  
  - footer、title 中的「小秘书提醒」
- **dingtalk-desktop/report_digest.py**  
  - 文本类型消息 content 前缀 `小秘书提醒\n`
- **dingtalk-desktop/version_digest.py**  
  - footer 中的「小秘书提醒」
- **dingtalk-desktop/skills/doc_review.py**  
  - `_DOC_WEBHOOK_KEYWORD` / `_DOC_WEBHOOK_FOOTER`（小秘书提醒）

**建议**：在钉钉里尽量保留「小秘书提醒」，与当前代码一致；若必须换词，用编辑器全局搜索 `小秘书提醒` 再统一替换并自测一条发送。
