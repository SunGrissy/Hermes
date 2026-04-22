# Multica 巡查认领 + 钉钉验收通知（工作流设计 spec）

> **状态**：设计 spec（待实现/待对齐现网能力）。  
> **日期**：2026-04-22  
> **依据**：本会话与制作人对齐的结论；Multica 上游 `CLI_AND_DAEMON.md`（`multica-ai/multica`）；`2026-04-18-multica-integration-design.md`、`2026-04-21-hermes-inbound-command-router-design.md`、`docs/hermes-dingtalk-gateway.md`、`tools/multica-dingtalk-bridge/README.md`。

---

## 0. 背景与定位

目标是在 **公网 Multica 个人实例** 上，由本机 **具名 Agent**（示例名「小橘」）周期性或事件驱动地 **发现可做的简单任务 → 认领 → 实施 → 推进状态机 → 必须外呼钉钉群通知制作人验收**。

本 spec 描述 **工作流契约与边界**；**不**绑定具体代码仓库（可在 Hermes 网关内、独立 Windows 计划任务脚本、或小服务中实现）。与「Hermes 入站命令路由器 + Multica 适配器」**互补**：后者解决 **钉钉 Stream 入站指令短路调 `multica`**；本 spec 解决 **出站自动化闭环（巡查/认领/改库/通知）**。

---

## 1. 目标与非目标

### 1.1 目标

| # | 目标 |
|---|------|
| G1 | **工单真源**为 Multica Issue；制作人可在 Web 上看到 **Assignee = 小橘**（或实际注册的 Agent 名）及状态变化。 |
| G2 | **平时（C）**：以 **事件驱动** 为主——若 Multica/自建实例提供 **可用的 Issue 出站 Webhook**，则消费事件入队；否则 **轮询（poll）** 作为同等优先级的实现手段（仍记为「C 路径」，与下条 B 区分的是触发粒度，而非是否实时）。 |
| G3 | **每日（B）**：由 **操作系统级计划任务**（如 Windows 任务计划程序）触发 **全量对账**，与 C 路径共享同一套幂等与状态规则，用于防漏、纠偏、补偿失败通知。 |
| G4 | **认领**：Agent 通过 `multica issue assign <id> --to "<AgentName>"` 将 Issue **指派给自己**（`AgentName` 与 Web **Settings → Agents** / `multica agent list` 一致）。 |
| G5 | **状态机**：认领后随真实进度更新状态（`multica issue status`）；进入「待制作人验收」时进入约定状态（默认建议 **`in_review`**，可在实现前另行约定）。 |
| G6 | **通知**：**仅** 更新 Multica 状态 **不算** 已通知；必须 **成功发出一条** 指向 **已接入钉钉机器人的目标群聊** 的消息（**主动发会话消息**能力，下文「钉钉能力 ②」）。 |
| G7 | **真源阶段策略**：当前阶段以 **公网个人 Multica** 为工单真源；内网团队实例后续 **切换 endpoint 与凭据** 复用同一契约（见 §8）。 |

### 1.2 非目标（本期 spec 不展开实现细节）

- 定义「简单任务」的完整自动分类器（需另 spec：规则表 + 可选 LLM 门控 + 人工标签）。
- 替代 Multica 自带 **daemon 轮询领任务** 模型；若未来完全托管在 Multica 执行管线，可与本工作流 **合并或退役** 其一，另行决策。
- 解决 **同一钉钉应用 Stream 单活** 的运维细则（见 §7 与既有 `hermes-inbound-command-router-design.md` §0）；本 spec **要求** 实施前单独做 **割接清单**，但不在此重复全文。

---

## 2. 术语

| 名称 | 含义 |
|------|------|
| **小橘** | 示例 **Workspace Agent 显示名**；实施时替换为实际名。 |
| **巡查器（Patrol）** | 执行「发现候选 Issue → 过滤 → 认领 → 调度执行体」的逻辑主体；可由定时脚本、Hermes 侧载任务、或独立进程承担。 |
| **C 路径** | 事件驱动主路径：Webhook **或** 高频 poll（以现网能力为准）。 |
| **B 路径** | 每日全量对账：与 C 共用规则，扫描遗漏与僵尸状态。 |
| **外呼** | 向钉钉群发送 **一条** 可读消息（Markdown/文本），内容至少含 **Issue 标识、标题、链接、待验收说明**。 |
| **钉钉能力 ②** | 机器人 **主动向群会话发消息**（非「仅在被 @ 时被动回复」）。制作人在本会话确认已具备。 |

---

## 3. Multica 侧能力边界（查证结论）

以下以 Multica 上游文档 **`CLI_AND_DAEMON.md`（main）** 为准，实施前仍应以本机 `multica … --help` 与实例版本核对。

- **支持**：`issue assign`、`issue status`、`issue update`、`issue comment add/list`、`issue list`（含 `--assignee`、`--status`、`--project` 等）、建单时 `--assignee`。
- **未在 CLI 文档中承诺**：Issue 自由 **labels** 作为认领主键；若需标签须在目标实例上 **实测**。
- **Autopilot Webhook**：文档写明数据模型存在 `webhook` / `api` 类 trigger，但 **「尚无会触发它们的服务端端点」、CLI 未暴露**——**不得**将「Multica 出站 Webhook 已可用」作为唯一前提；**必须**实现 **poll 降级**（或实例控制台实测通过后再收窄）。

---

## 4. 认领与状态机契约

### 4.1 认领（Assign）

1. 候选 Issue 通过 §5 的规则筛选后，巡查器调用：  
   `multica issue assign <id> --to "<AgentName>"`  
   其中 `<AgentName>` 与 Multica Web 中 Agent 名 **完全一致**（含中英文、空格、全半角）。
2. **不抢指派**：若 Issue **已有 assignee** 且 **不是** `<AgentName>`，默认 **跳过**（可 `comment add` 说明「已有人负责」），除非后续另 spec 约定「覆盖规则」。
3. **幂等**：若 assignee 已是 `<AgentName>`，重复 assign 应视为成功路径（若 CLI 报错则实现侧须先 `issue get` 再分支）。

### 4.2 状态（Status）

- 合法状态集合与现网派单桥对齐：`backlog`、`todo`、`in_progress`、`in_review`、`done`、`blocked`、`cancelled`（见 `tools/multica-dingtalk-bridge/dispatch_bot.py` 中 `_ISSUE_STATUS_ORDER`）。
- **建议映射**（可在实施前微调文案，但须在实现中写死）：

| 阶段 | Multica `status` |
|------|------------------|
| 已认领、正在改代码 | `in_progress` |
| 已提交结果、等待制作人验收 | `in_review` |
| 验收通过 | `done` |
| 无法完成 / 放弃 | `blocked` 或 `cancelled`（二选一规范另表） |

### 4.3 审计

- 关键节点 **建议** `multica issue comment add` 写入短摘要：`run_id`、分支名、相关 commit、外呼成功/失败标记（失败时便于 B 路径补偿）。

---

## 5. 候选任务发现（C + B 共用规则）

### 5.1 输入源

- **C**：Webhook 收到的事件 **或** poll 得到的增量列表（按 `updated_at` / 列表顺序 + 本地游标，具体实现自定）。
- **B**：`multica issue list` 全量或分页拉取（建议 `--output json`），在本地与 **已处理表**（SQLite/JSONL/任意持久化）对账。

### 5.2 过滤（占位）

- 至少包含：**状态 ∈ 可认领集合**（如 `todo`）、**assignee 为空或已为小橘**、**优先级/标签/标题关键词**（待定）、**项目/Workspace 范围**。
- 「简单」定义：**本 spec 不锁死**；实施最小集可为 **人工在标题或描述加约定前缀**（如 `[auto]`）+ 状态过滤。

### 5.3 执行体

- 实际改代码可由 **`multica daemon` 拉起 Hermes / cursor-agent**、或由巡查器 **子进程调用本机 Agent CLI** 等实现；须满足：**工作目录、分支策略、Git 规范** 与 `2026-04-18-multica-integration-design.md` 及根目录 `.cursor/rules` 中 **分支守卫、提交门禁** 一致（默认 **不** 自动 `git commit`，除非制作人明确口令）。

---

## 6. 外呼通知（硬门禁）

### 6.1 定义

- **通知成功** 的充要条件：**钉钉目标群** 中出现一条满足模板的外呼消息，且 HTTP/SDK 返回成功（实现侧应记录 message id 或等价 trace）。
- **Multica 状态变为 `in_review` 但外呼失败**：视为 **半失败态**——必须 **重试队列** 或 **B 路径补偿**，且 Issue 上应有 **评论** 说明「待验收通知失败」，避免制作人误以为已通知。

### 6.2 消息最小内容

- Issue **人类可读编号**（如 `UUM-n`）与 **标题**（截断规则自定）。
- **Multica 网页链接**（`MULTICA_APP_URL` + workspace 路径规则与现桥一致）。
- **一句明确动作**：如「请验收」；可选附带 **分支名 / PR 链接 / 本地路径**（注意 **不在群内泄露密钥**）。

### 6.3 通道

- 使用已具备 **钉钉能力 ②** 的机器人，向 **该机器人已接入的群聊** 发送。
- 若与 **Stream 入站** 共用同一钉钉应用，须遵守 **Stream 单活** 与变更窗口（交叉引用 `2026-04-21-hermes-inbound-command-router-design.md` §0、`docs/hermes-dingtalk-gateway.md`）。

---

## 7. 与 Hermes / 钉钉架构的交叉风险

| 风险 | 缓解 |
|------|------|
| Stream 与主动发群 **权限/应用分裂** | 实施前核对开放平台「机器人可调用发消息 API」与 Stream 是否同一应用；若分裂，在运维文档中 **显式画拓扑**。 |
| 事件风暴导致重复外呼 | Webhook / poll 消费采用 **幂等键**（`issue_id + 目标状态 + 通知类型`）；外呼前查本地 **已通知表**。 |
| 本机离线 | Multica 状态仍更新但外呼失败 → §6.1 半失败态 + B 补偿。 |

---

## 8. 部署与迁移（公网 → 内网）

| 阶段 | Multica | 说明 |
|------|----------|------|
| 现阶段 | **公网个人实例** | 工单真源；Webhook URL 若需公网可达，按实例控制台配置。 |
| 后续 | **内网团队实例** | **同一套** 巡查/认领/状态/外呼契约；切换 `server_url` / `app_url` / token / `MULTICA_PROJECT_ID`；**不混单**（迁移策略另议）。 |

---

## 9. 验收与后续文档

- 制作人侧 **验收口令与 Git 流程** 仍以根目录 `acceptance-checklist.mdc`、`git-workflow.mdc` 为准；本工作流 **不** 改变「仅口令触发提交/推送」的铁律。
- 实现落地后建议新增：**运行手册**（Windows 计划任务 cron 表达式、环境变量表、失败排障）、**与 Stream 单活割接表** 一页纸。

---

## 10. 修订记录

| 日期 | 修订 |
|------|------|
| 2026-04-22 | 初版：会话结论固化（C+B、公网真源、assign+状态机、钉钉群外呼为硬门禁、Multica Webhook 能力边界与 poll 降级）。 |
