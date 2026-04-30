# Multica 自动化工作流设计文档

> 最后更新：2026-04-29 21:25  
> 维护者：Agent 数字分身  
> 入口：`tools/multica-dingtalk-bridge/dispatch_bot.py`

---

## 1. 工作流全景

```
派单（钉钉/DWS/手动）
  │
  ▼
[todo] ─── Multica Daemon 分配 Agent ─── [in_progress]
                                               │
                                     Claude 开始工作
                                     [Claude 工作中] 通知
                                               │
                                               ▼
                                        代码生成 + 提交
                                     agent/{id} 分支
                                               │
                                     Claude 完成工作
                                     [Claude 完成] 通知
                                               │
                                               ▼
                           Multica 自动推进 ─── [in_review]
                                               │
                                     [待审查] 通知 →
                                     ┌─ Claude CLI 审查 (code_review_dispatcher)
                                     │  审查结果 → Multica 评论
                                     │  审查成功 → [审查完毕] 通知
                                     │  审查失败 → [审查兜底] 通知
                                     │
                                     └─ Hermes/当当 审查 (hermes_review_dispatcher)
                                        审查结果 → Multica 评论
                                        审查成功 → [审查完毕] 通知
                                        审查失败 → [审查兜底] 通知
                                               │
                                               ▼
                                  人审通过 → 改为 [approved]
                                               │
                                     [审查通过] 通知
                                     git merge agent/{id} → main
                                     git push origin main
                                     Multica 状态 → [done]
                                               │
                                               ▼
                                          [done]
                                     [已完成] 通知
```

---

## 2. 通知格式规范

### 2.1 标题格式

```
[标签] ISSUE-ID: ISSUE标题
```

示例：`[Claude 完成] UUM-24: PmSystem Planner WorkItems 批量管理 API`

### 2.2 审查状态说明

Claude 完成通知正文中附带审查状态：

- **已自动进入 In Review：** `审查状态：已自动进入 In Review 状态。代码审查由 Claude CLI 自动执行。审查结果将写入 Multica 评论，并伴发 [审查完毕] 通知。`
- **未自动进入 In Review：** `审查状态：未自动进入 In Review。如需审查：在 Multica 将工单状态改为 In Review，或告诉当当 审查 {issue_id}。`

### 2.3 通知矩阵

| 事件 | 触发方式 | 通知标签 | 内容 |
|------|---------|---------|------|
| 工单进入 In Review | 状态过渡检测 | `[待审查]` | 工单信息 + 分支 + 自动审查提示 |
| Claude 开始工作 | run 过渡检测 | `[Claude 工作中]` | 已开始处理 |
| Claude 完成工作 | run 过渡检测 | `[Claude 完成]` | 已完成 |
| Claude 工作失败 | run 失败兜底 | `[运行失败]` | 失败原因 + 错误详情 |
| 审查完成 | dispatcher 回调 | `[审查完毕]` | 审查后端 + 结果摘要 |
| 审查失败兜底 | dispatcher 异常 | `[审查兜底]` | 失败原因 + 可手动审查提示 |
| 审查通过 | 状态过渡检测 | `[审查通过]` | approved → merge → done |
| 合并冲突 | merge 异常 | `[合并冲突]` | 冲突工单 + 处理建议 |
| 工单完成 | 状态过渡检测 | `[已完成]` | 完成通知 |
| 工单取消 | 状态过渡检测 | `[已取消]` | 取消通知 |

---

## 3. 已实施

### 3.1 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `StatusWatcher` | `status_watcher.py` | 后台轮询工单状态，检测过渡 → webhook |
| `CodeReviewDispatcher` | `code_review_dispatcher.py` | 调用 Claude CLI 做只读代码审查 |
| `HermesReviewDispatcher` | `hermes_review_dispatcher.py` | 调用 Hermes/当当 run_agent 做审查 |
| `ReviewEscalation` | `review_escalation.py` | 审查失败时发兜底通知 |

### 3.2 通知链路 ✓

- **状态过渡通知**：`poll_once()` 对比新旧缓存，`inreview/done/cancelled/failed/approved` 五种状态进入时自动发 webhook
- **Run 过渡通知**：`_check_run_transitions()` 检测 run id 变化，Claude 开始/完成自动通知
- **Run 失败兜底**：`_check_run_failures()` 检测 run 失败但 issue status 未变的情况，防漏报
- **审查完毕通知**：两个 dispatcher 审查成功后调用 `notify_review_done()`
- **冷启动补发**：`_check_run_transitions` 发现 run 完成且工单在 in_review 时，自动补发 `[待审查]`

### 3.3 审查结果 → Multica ✓

- Claude CLI 审查完成后，`_post_review_comment()` 自动写回工单评论
- Hermes/当当审查完成后，同样写回工单评论

### 3.4 审查链触发 ✓

- `_invoke_review_chain()` 在工单进入 in_review 时触发
- 支持 `IN_REVIEW_REVIEW_BACKEND` 切换：`cli` / `hermes` / `both`
- 支持同步执行 + 失败兜底 escalation

### 3.5 自动合并 ✓

- 工单进入 `approved` 后：检测 agent 分支 → merge 到 main → push → 改 Multica 状态为 done
- 若 merge 冲突：webhook 通知冲突，不自动处理
- UUM-24（Planner WorkItems API）已手动先行合入 main

---

## 4. 待完成

### 4.1 审查触发时机优化

**当前问题：** 工单进入 `in_review` 后立即触发审查，此时审查者可能在审查前没有足够的上下文缓冲。

**待定：** 是否需要引入"审查延迟"或"审查就绪确认"机制。

### 4.2 审查通过自动判定

**当前：** `approved` 需要人为手动在 Multica 上改状态。

**设想：** 若审查报告结论为"未发现阻塞项"，自动推进到 `approved`。但这需要：
- 审查报告结构化输出（JSON 格式，含 `verdict: pass/reject` 字段）
- 可信度阈值（初期不建议全自动，先保持人工确认）

### 4.3 Multica issue status 字段标准化

**当前：** `_normalize_status()` 做了 lowercase + strip 处理，但 Multica 的 status 值尚未完全收敛。

**建议：** 确认并文档化 Multica 的标准 status 枚举值（todo / in_progress / in_review / approved / done / cancelled / failed）。

### 4.4 Webhook 去重增强

**当前：** 通过缓存文件（`multica-run-fail-cache.json`、`multica-run-transition-cache.json`）去重同 run 的通知。但不防：
- 多进程并发写同一缓存
- 缓存损坏导致重复通知

**建议：** 加文件锁或 SQLite 本地去重。

### 4.5 UUM-25 权限守卫（已知缺口）

UUM-25（OPS Push to Version API）缺 `require_not_viewer` 权限守卫，write 端点未做外圈保护。

### 4.6 UUM-26 乐观锁（已知缺口）

UUM-26（OPS 维度标签管理 API）的 `operation_matrices` JSON blob 更新缺乐观锁。

---

## 4.X 当当巡检职能（待实施）

当当具备独立巡检能力，不依赖 Claude 或其他 Agent 的在线状态。通过 Multica API + git 命令自主完成。

### 4.X.1 需求不清 / 归属不清 / 过于复杂

| 检测条件 | 检测方式 | 动作 |
|---------|---------|------|
| 描述 < 50 字 | `issue.description` 长度 | 私聊老大确认：是否补文档？还是直接派？ |
| `project_id` 为空 | `issue.project_id` | 同上 |
| 描述 > 2000 字 或 标题含多个并行诉求 | 描述长度 / 标题分词 | 建议拆成 2~3 个工单，等老大确认后执行 |

当当独立执行，不依赖其他组件。

### 4.X.2 停滞检测

| 停滞条件 | 阈值 | 动作 |
|---------|------|------|
| `todo` 无人认领 | > 24h | webhook 通知 + 私聊老大 |
| `in_progress` 无 run 活动 | > 8h | 同上 |
| `in_review` 无人推进 | > 24h | 同上 |

用法：
- `status_watcher` 的 `poll_once()` 额外附带 `_check_stalled_issues()`，发现停滞 → webhook 预警
- 当当巡逻时读取停滞列表 → 逐一私聊老大确认下一步动作

### 4.X.3 已实际完成但状态未更新（核心难点）

| 证据等级 | 条件 | 动作 | 执行者 |
|---------|------|------|--------|
| 强证据 | agent 分支已合 main + run 已完成 + 工单在 in_review | 自动改 done + 发通知 | 当当 |
| 中证据 | run 已完成但工单在 in_progress，未见 merge | 发 "[待确认]" 等老大回复 | 当当 |
| 弱证据 | `git diff main..agent` 为空 | 发 "[待确认]" | 当当 |

检测手段：
- `git branch --list agent/{issue_id}` — 分支存在性
- `git merge-base --is-ancestor agent/{issue_id} main` — 是否已合入
- `multica issue runs {issue_id}` — run 完成状态
- 对比 issue status vs run status + git 状态

强证据时当当独立决策（自动改 done），减少人工追问。中/弱证据时让老大确认。

### 4.X.4 与 status_watcher 的关系

```
当当巡检（独立线程/模块）
├─ 数据来源
│   ├─ multica issue list（全量工单 + status）
│   ├─ multica issue runs（run 状态 + work_dir）
│   ├─ git branch/merge-base（合并检测）
│   └─ status_watcher cache（停滞时长）← 只读
├─ 决策
│   ├─ 需求澄清 → 私聊老大
│   ├─ 停滞预警 → webhook + 私聊
│   └─ 完成关闭 → 强证据自动，弱证据确认后
└─ NOT 依赖
    ├─ code_review_dispatcher
    └─ hermes_review_dispatcher
```

status_watcher 是**数据提供者**，当当是**巡检决策者**。两者协作但不耦合。

### 4.X.5 指派后不启动 / run 完成后状态不推进（新缺口）

UUM-27 暴露了两类新问题。

**场景 A：指派给 Agent 后 Daemon 未自动启动**

| 检测条件 | 动作 |
|---------|------|
| `assignee_type = agent` + `status = todo` + 无活跃 run | 当当检测 → webhook + 私聊老大 "UUM-XX 已指派但未启动，是否手动触发？" |

注：Daemon 为什么不启动可能是 Multica 平台的调度问题，不在本侧可控，但至少能发现并报告。

**场景 B：run 已完成但 issue 仍停在 todo**

| 检测条件 | 动作 |
|---------|------|
| 最新 run = completed + issue status 仍为 `todo`（非 in_progress / in_review） | 强证据：当当自动推进为 `in_review`（代码已产出，没理由停在 todo） |

UUM-27 就是典型案例：run 完成了 → 代码已产出 → 但 Multica 还是 `todo`。这种情况可以直接推进。

**检测优先级（按 urgency）：**

| 现象 | 决策 | 原因 |
|------|------|------|
| run 完成 + todo | 自动 → in_review | 代码已产出，直接推进 |
| run 完成 + in_progress | 自动 → in_review | 同上 |
| 指派后 > 30min 无 run | 报告老大 | 可能 Daemon 调度问题 |

---

## 5. 配置项速查

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `STATUS_WATCHER_INTERVAL` | 300 | 轮询间隔（秒） |
| `DEV_AGENT_NOTIFY_WEBHOOK` | — | 钉钉 webhook URL（必填） |
| `IN_REVIEW_REVIEW_BACKEND` | cli | 审查后端：cli / hermes / both |
| `CODE_REVIEW_ENABLED` | 0 | 启用 Claude CLI 审查 |
| `CODE_REVIEW_DAEMON_CID` | — | 审查结果 daemon 私聊目标 |
| `CODE_REVIEW_TIMEOUT` | 1800 | Claude 审查超时（秒） |
| `HERMES_REVIEW_ENABLED` | 0 | 启用 Hermes 审查 |
| `HERMES_REVIEW_DAEMON_CID` | — | Hermes 审查结果 daemon 私聊目标 |
| `MULTICA_REVIEW_ESCALATION_WEBHOOK_URL` | — | 审查兜底 webhook |
| `MULTICA_WEBHOOK_NOTIFY_SCOPE` | review_and_failures | 主 webhook 投递范围：`review_and_failures` 仅 **审查完毕** + **失败类**（含 run 失败兜底、工单 `failed`、合并冲突）；`all` 恢复此前全量状态与 run 过渡通知 |

---

## 6. 测试

```powershell
cd tools/multica-dingtalk-bridge
py -m pytest tests/ -v
```

141 测试全部通过（2026-04-29 后补跑）。

---

## 7. 启动

```powershell
cd tools/multica-dingtalk-bridge
.venv\Scripts\python.exe watchdog.py
```

后台启动 watchdog（守护）→ dispatch_bot 子进程（自动拉起 StatusWatcher + DingTalk Stream）。

---

## 8. 2026-04-29 实际落地记录（本轮）

### 8.1 已落地

- **通知格式升级**：`[标签] ISSUE-ID: ISSUE标题`，并在 `[Claude 完成]` 正文明确写出“审查是否已自动开始 / 如何手动触发”。
- **审查结果自动落盘**：CLI/Hermes 两路审查结果都自动写入 Multica 评论，并发送 `[审查完毕]` 通知。
- **approved 自动合并**：`approved` 进入后自动 merge `agent/{issue}` 到 `main`，push 成功后自动改 `done`。
- **run 过渡通知**：补齐 `[Claude 工作中]` / `[Claude 完成]` / run failure 兜底。
- **守护进程上线**：`watchdog.py` 上线，dispatch_bot 崩溃可自动重启（30s 健康检查、5s 重启、1h 最多 3 次）。
- **启动入口切换**：实际运行入口改为 `pm-system/quick_start.bat` -> `run_bridge.ps1` -> `watchdog.py`。

### 8.2 本轮案例闭环

- **UUM-24**：代码已合并但工单未更新 -> 已修正为 `done`。
- **UUM-27**：指派后未自动跑 + run 完成后状态停滞 -> 已推进 `in_review`、完成审查、代码提取并合入 main、状态更新 `done`。

### 8.3 新增巡检规则（当当）

- 指派后未启动（`assignee=agent` + `todo` + 无活跃 run）-> 报告老大。
- run 已完成但状态仍 `todo`/`in_progress` -> 自动推进 `in_review`。
- “代码在平台 worktree 产出但未推分支” -> 触发救援流程（提取代码、建分支、推送、再审查）。

### 8.4 主 Webhook 防刷屏 + 审查摘要可读性（后补）

- 默认 **`MULTICA_WEBHOOK_NOTIFY_SCOPE=review_and_failures`**：`[审查完毕]` 使用去表格、口语化短摘要；Agent 流水线成功类通知不再占用同一条机器人。
- 需要恢复「每条状态都推」时设为 **`all`**。

---

## 9. 实时任务双轨机制（Hermes / OpenClaw，新增）

> 本节用于「非 Multica 即时任务」：例如老大发起“立刻写文档/立刻跑脚本/立刻排查”的消息。  
> 目标：尽快有反馈、不刷屏、有保活、失败必达；复杂任务可升舱 Claude。

### 9.1 双轨定位

- **轨道 A（现有）**：Multica 工单流，适合非实时、可排队、可验收的任务。
- **轨道 B（新增）**：Hermes/OpenClaw 实时流，适合突发即时处理。
- 两轨都允许调用 Claude，但触发条件和通知节奏不同。

### 9.2 分级处理（L0 / L1 / L2）

| 层级 | 执行者 | 适用任务 | 说明 |
|------|--------|----------|------|
| L0 快响 | Hermes/OpenClaw 本模型 | 快问快答、状态查询、短摘要 | 秒级反馈，不强依赖 Claude |
| L1 轻编排 | 本模型 + 工具 | 单文件小改、只读命令、轻量脚本 | 先本地闭环，必要时再升舱 |
| L2 升舱 | Claude（CLI/API） | 长文档、多文件改动、复杂推理、L1 不稳 | 可写仓库（遵守 git 安全红线） |

升舱触发（命中任一）：
- 老大显式要求“用 Claude / 指派 Claude 处理”
- 任务复杂度达到 L2（长上下文、多步骤、多文件）
- L1 超时、失败、或 Agent 自检不确定

### 9.3 通知策略（不刷屏）

#### A. 首条即时响应（必发）
- 收到任务后立即发一条 `doing` 状态（可带 emoji），不等待 Claude 完成。

#### B. 进展有变才更新（核心）
- 使用 **AI 卡片单条刷新**（同一任务固定一条卡片，更新同一条消息）。
- 仅在“阶段变化/关键里程碑变化”时更新卡片，不按固定秒数刷消息。
- 若当前通道不支持卡片更新，降级为“合并文本更新”，仍保持低频。

#### C. 保活心跳（确保活着）
- 当无阶段变化达到阈值（建议 3~5 分钟）时，发一次简短心跳：  
  `仍在处理：<当前阶段>，已耗时 <xx 分钟>`。

#### D. 异常必达
- Claude 超时、进程失败、工具失败、通知投递失败：必须单发异常通知（含 `task_id`、原因、下一步建议）。

### 9.4 双上限治理（必须同时启用）

> 仅有“时间上限”或仅有“轮数上限”都不够，必须双保险。

| 控制项 | 建议默认值 | 作用 |
|--------|------------|------|
| `REALTIME_TASK_MAX_MIN` | 45 | 墙钟时间上限，防止长时间悬挂 |
| `REALTIME_MAX_AGENT_TURNS` | 24 | Agent 内部轮数上限，防止空转 |
| `REALTIME_MAX_CLAUDE_CALLS` | 8 | 单任务 Claude 调用上限，防止成本失控 |

触发任一上限后：
- 停止自动推进
- 发“上限触发”通知（含已耗时、已轮数、已调用次数）
- 提示老大选择：继续 / 收窄范围 / 转入 Multica 工单

### 9.5 可观测性（与本次遥测对齐）

- 每条即时任务生成稳定 `task_id`（由入口在接单时生成）。
- 同一任务内每次 Claude 调用写入 `call_index`（1,2,3...）。
- 统计口径：
  - **任务数** = `distinct(task_id)`
  - **调用数** = 日志总行数
  - **任务均调用** = 调用数 / 任务数
- 日志默认落盘：`shared-memory/claude-calls/calls-YYYY-MM-DD.jsonl`

### 9.6 落地顺序（建议）

1. 先在 Hermes / OpenClaw 入口加 `task_id` 生成与透传。
2. 再接入 Claude 调用封装（含 JSONL 遥测）。
3. 接入 AI 卡片单条刷新；不支持更新的通道走文本降级。
4. 最后开启双上限硬门禁（时间 + 轮数 + Claude 调用数）。

### 9.7 OpenClaw2 运维备忘（端口 / CLI / 钉钉 runtime）

> 与 Multica 工单流独立；本节记录本机排查结论，便于换机或复现时对照。

- **实例与端口**：`D:/OpenClaw2/openclaw.json` 为 OpenClaw2 配置；gateway 常用 **18790**。与虾叔侧 OpenClaw（如 **18789**）并存时务必区分 `OPENCLAW_STATE_DIR` / `OPENCLAW_CONFIG_PATH`，避免混用状态目录。
- **全局 CLI 损坏**：若 `openclaw` 命令缺失或 shim 指向不存在的 `openclaw.mjs`，执行 `npm i -g openclaw@latest` 重装全局包后再试。
- **拉起顺序**：先设环境变量指向 OpenClaw2 配置与状态目录，再 `openclaw gateway --port 18790`（或配置文件内端口）。
- **`openclaw health` 超时但端口已 Listen**：多为 WebSocket 握手未就绪或子通道未连上；并行查看 `%TEMP%\openclaw\` 下当日日志。
- **`DingTalk runtime not initialize` / `startAccount` 失败**：`dingtalk-connector` 未成功 `setDingtalkRuntime`。日志若出现 **`ERR_UNSUPPORTED_ESM_URL_SCHEME`（`protocol 'd:'`）**，多为 Windows 下把 `D:\...` 当非法 ESM URL 导入；需对齐 OpenClaw / connector 版本或重装 `plugins.installs` 中钉钉相关条目。
- **`schtasks` 拒绝访问**：`openclaw doctor --repair --force` 写计划任务失败时，用**管理员** PowerShell 执行，或改用手动/自建启动脚本，不依赖计划任务。
