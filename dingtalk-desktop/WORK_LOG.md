# dingtalk-desktop WORK_LOG

## [2026-03-17] 日报摘要管线全面打通

### 状态：已验收

### 本次工作内容

#### 1. 日报采集与分析管线（report_digest.py）

- **时间窗口**：从"当天 00:00-23:59"改为"当天 18:30 → 次日 12:00"，覆盖晚间提交和隔夜补交，实际采集条数从 10 条提升至 21 条
- **完整内容抓取**（`--full-content`）：新增 `fetch_report_content` 调用，LLM 分析改为基于完整日报正文而非消息摘要
- **提交人数计算修正**：`submitted_count` 改为只统计 `team_members` 中的提交者，解决"7+17≠22"问题
- **LLM prompt 补充规则**：同一人在多个群提交日报属正常行为，不标记为重复提交
- **消息格式优化**：替换不渲染的 emoji，改用【总览】【关注】等文字标记
- **Webhook 支持**：新增 `send_via_webhook`，优先于 daemon 一人群发送；发送时自动添加安全关键词"小秘书提醒"
- **摘要标题加时间窗口**：显示"3/17 18:30 - 3/18 12:00"，收件人清楚覆盖范围

#### 2. daemon.py 稳定性修复

- **browser 隔离（关键修复）**：`fetch_report_content` 始终用 browser 1，用前读取当前 URL，用完恢复到 `about:blank`（不恢复到 advancedSearch.html，否则触发搜索栏 UI 弹出）
- **移除破坏性探测**：删除了对 browser 2~8 调用 `load_url(about:blank)` 进行测试的逻辑，防止破坏文档面板等可见 UI
- **`/debug/scan_browsers` 修复**：改为只列出 browser ID + browser 1 当前 URL，不再对所有 browser 做导航测试
- **report card 正则扩展**：`_normalize_report_card` 支持提取"周报""月报"发送人姓名
- **`send_digest` 支持 CID 直传**：`notify_target` 为纯数字时直接用 `cid` 参数，避免 emoji 群名解析失败

#### 3. 配置更新（digest_config.json）

- `team_members` 更新为 23 人（新增杨玉涛）
- `report_cids` 新增：崔哥日报直通车、鹏锐汇报直通车、君怡日报直通车、杨琳汇报直通车、涛哥日报直通车
- `notify_target` 改为直接 CID（73216314617）
- 新增 `webhook_url` 字段

#### 4. 定时任务（run_daily_digest.ps1）

- 每天 09:00 执行，自动检测 daemon 状态并在必要时重启
- 跑完后通过 webhook 发送到"🐱助理通知"群

### 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `report_digest.py` | 时间窗口、webhook、计算修正、格式优化 |
| `daemon.py` | browser 隔离、UI 保护、正则扩展 |
| `digest_config.json` | 成员列表、群 CID、webhook URL |
| `run_daily_digest.ps1` | 新增定时任务脚本 |
| `WORK_LOG.md` | 本文件 |
