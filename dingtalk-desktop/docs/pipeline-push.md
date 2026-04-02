# 管线推送说明（钉钉）

本文聚焦 **管线专项 / 定时管线提醒** 与 **版本汇总里和管线相关的段落**，作为 [`版本与管线推送说明.md`](../版本与管线推送说明.md) 的补充。总览与排错仍以根目录那份为准。

---

## 当前运行态（2026-04-02）

- 管线专项定时任务 `MyAgents_PipelineNotify_0915` / `MyAgents_PipelineNotify_1945` 当前为 **Disabled**。
- 早间四类汇总推送由 `VersionDigest` 单任务触发（详见上游文档）。
- 若需要恢复管线专项自动推送，重新启用上述两个任务即可。

---

## 1. 配置三件套职责

| 文件 | 职责 |
|------|------|
| **`digest_config.json`** | PM 服务地址与 API Key、版本汇总 Webhook 键名与 `@` 策略、晚间管线跟进阈值（如 `version_evening_pipeline_followup_max_days_remaining`）、运营姓名列表等。**不**在此文件写机器人 URL 全文时，应配合 `webhook_config.json` 的键名解析。 |
| **`webhook_config.json`** | 各场景机器人 **access_token URL** 的稳定键名（如 `version_digest_pmo`、`default`）。**键名**需与 `digest_config` 中引用一致；改群机器人时通常改 URL，键名保持不变。 |
| **`message_templates.json`** | 版本汇总与晚间「今日变化」的文案：`version_digest`、`version_change`、`version_release`、`version_online` 等。调整 **「早间关注暂无进展」**、**安静日**、**发布/上线一次性通知** 等话术时改此文件，无需改 Python。 |

**约定**：钉钉侧机器人若开启「自定义关键词」，须与模板 footer / title 一致（常见为 **小秘书提醒**）。

---

## 2. 两条推送链路（管线相关）

### 2.1 管线专项 / 定时（`_push_versions_webhook_at_dm.py`）

- **用途**：按版本单独推一条 Markdown，正文含 **版本状态 + 管线节点待办**（与 PM 渲染链一致）。
- **定时**：`run_pipeline_notify_scheduled.ps1` → `py _push_versions_webhook_at_dm.py --auto-scheduled`（原计划为周一至周六 09:15 / 19:45；当前计划任务已停用）。
- **版本筛选（`--auto-scheduled`）**：`phase` 非已发布、管线发版节点未完成、非 `demand_pool`；**规划截止** 仅用 `pipelineDdls.planning`，且该日期距今 **≤28 天**（含已过期）。**不用** `startDate` 推算规划截止，避免与界面不一致。
- **Webhook**：优先该版本 **`progressNotifyWebhooks`**；为空则用 **`webhook_config.json` 的 `default`**。
- **正文来源**：拉 PM 数据后，**管线节点待办** 会用本机 `pm-system` 的 `render_pipeline_node_checklists_markdown` **覆盖**接口返回块，避免服务端未部署新代码时标题仍过旧。

### 2.2 工作日「版本日报」包装（`run_daily_version.ps1`）

与 **日报 digest** 分离，建议在日报任务之前或并行排程：

| 步骤 | 行为 |
|------|------|
| 默认 | `version_digest.py --mode snapshot`（早间快照）→ 间隔约 10s → `_push_versions_webhook_at_dm.py`（专项远端推送，默认任务列表见脚本 `_default_jobs`）。 |
| `-EveningChange` | 仅执行 `version_digest.py --mode change`（傍晚「今日变化」），**不**跑 `_push_versions_webhook_at_dm.py`。 |

专项推送依赖 `digest_config.pm_system_url` 与版本上的 `progressNotifyWebhooks` / 默认 Webhook。

---

## 3. PM 侧：管线标题「发布推进」vs「阶段待办」与 DDL 预警

实现：`pm-system/backend/app/services/pipeline_node_checklist_render.py`；**与界面共用的合并 DDL** 见 **`pipeline_ddl_resolve.resolve_effective_pipeline_ddls`**（与 `version-planning-view.js` 的 `PIPELINE_STAGES` 一致）。强提醒小节标题为 **【发布推进】**（原「阻塞发布」），远发版软化时仍为 **【阶段待办】**。

- **距发版** 与 **首未完成阶段** 的 **有效** `pipelineDdls`（手写 + 默认推算）共同决定标题与「当前卡点」DDL 提示行；避免仅数据库里写了部分键时与 UI 时间轴不一致。
- **「远发版」软化**：默认距发版 **> 30 天** 时小节标题可用 **【阶段待办】**；数值来自 PM 配置 **`backend/data/pipeline_ddl_alert.json`** 的 `blocking_label_far_days`（可改）。
- **DDL 预警窗口**：相邻节点 DDL 间距 **不均匀** 时，用配置里的 **比例 + 上限**（`span_based`）；无间距可用时按阶段分组 **long / short / default**（`fallback_no_ddl`）回退。
- **Feature 卡点摘要（轻量）**：在管线节点块中增加 **「Feature 卡点摘要」**，按优先级列出最多 5 条（阻塞 → DoR 未过 → 开发中/测试中），与版本级节点待办分工。
- **首未完成阶段**：管线待办默认只列 **当前卡点阶段**（`stage_lookahead=0`），不再默认带出下一关（如验收），避免开发期【发布推进】下同时出现开发与验收两段。

专项脚本会把 **距发版天数** 传入渲染（`_push_versions_webhook_at_dm.py` 中 `days_to_release`）。

**配置说明（权威）**：[`pm-system/docs/pipeline-ddl-alert-config.md`](../../pm-system/docs/pipeline-ddl-alert-config.md)

---

## 4. 版本汇总晚间：`version_digest.py --mode change`

- **早间**：`--mode snapshot`，全量现状。
- **傍晚**：`--mode change`，对比 **早间基线**，输出短消息：今日进展、行动提醒、连续无变化、安静日等。
- **晚间「早间关注暂无进展」**（`message_templates.json` → `version_change.followup_*`）：当 PLD/PM/管线块相对早间基线 **无变化** 时列出提醒；其中 **管线段落** 受配置 **`version_evening_pipeline_followup_max_days_remaining`** 约束：仅当 **距发版剩余天数 ≤ 该值**（或未定发版日）时才输出管线无进展句，更远则省略，减少远发版期噪音（默认常见为 45，以实际 `digest_config.json` 为准）。

**一次性通知（停推逻辑）**：

- **`version_release`**：版本 **首次** 检测到 `released` 等已发布态时发送；之后该版本在早晚汇总中按逻辑停推（模板见 `line_3_snapshot` / `line_3_change`）。
- **`version_online`**：发版流程引导（release 分支）**整组完成** 时发「版本已上线」；文案中含对 PM / PLD 的复盘提示。

状态持久化在本地 digest 状态文件中（与 `version_digest.py` 同目录约定），避免重复轰炸。

---

## 5. 相关代码与脚本（管线推送）

| 路径 | 说明 |
|------|------|
| `dingtalk-desktop/_push_versions_webhook_at_dm.py` | 专项 / 定时管线推送、Markdown 拼装、覆盖管线块 |
| `dingtalk-desktop/version_digest.py` | 版本汇总早晚模式、基线对比、发布/上线通知、晚间 followup |
| `dingtalk-desktop/run_daily_version.ps1` | 早间快照 + 专项推送；`-EveningChange` 仅傍晚变化 |
| `dingtalk-desktop/run_pipeline_notify_scheduled.ps1` | `--auto-scheduled` 定时包装 |
| `pm-system/backend/data/pipeline_ddl_alert.json` | 管线 DDL 预警比例、远发版天数、无 DDL 时阶段分组回退 |
| `pm-system/.../pipeline_node_checklist_render.py` | 管线 Markdown 标题与 DDL 提示（读上表 JSON） |

---

## 6. 延伸阅读

- [`版本与管线推送说明.md`](../版本与管线推送说明.md) — 功能对照、Webhook/@、计划任务、排错表  
- [`digest-fulltext-refactor.md`](./digest-fulltext-refactor.md) — 日报全文链路重构（与管线专项推送不同题，必要时可查）

配置或调度变更时，请同步更新 **`WORK_LOG.md`** 与上述文档中的对应条目。
