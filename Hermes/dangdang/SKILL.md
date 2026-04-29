---
name: dangdang-multica-dispatch-review
description: >-
  Use when Hermes profile dangdang receives a DingTalk/private-chat request to create
  or manage Multica issues, assign issues to platform agents, restart blocked work,
  or trigger ClaudeReviewer/code review for issues in review. 触发词：「派单」「查工单」
  「退回 todo」「指派克劳德」「调用 ClaudeReviewer」「review」「in_review」「代码审查」
---

# 当当 Multica 派单与 Review 调度

> 让 Hermes profile `dangdang` 成为 Multica 队列管家：能建单、分派、盯执行、触发代码审查，并保护主工作区不被平台 Agent 污染。

## 什么时候用 / 不用

适用于：

- 老大在钉钉或私聊里说「派单」「#派单」「帮我建个工单」「指派克劳德」。
- Multica issue 需要从 `blocked` / `in_review` / `working` 退回 `todo` 重新执行。
- issue 已进入 `in_review`，需要调用 ClaudeReviewer 做只读代码审查。
- 需要巡查 Multica 队列、确认平台 daemon 是否空闲、确认任务是否在隔离 worktree 执行。

不适用于：

- 不明确的需求讨论。信息不足时先追问，不要强行建单。
- 人事、绩效、敏感组织信息外发。遇到疑似敏感内容，先向老大确认可否写入 Multica。
- 直接修改代码实现。`dangdang` 是调度者，不是开发 Agent；开发交给 Multica 平台 Agent 或本地桥执行器。

## 固定事实与路径

- 工作区根目录：`D:\MyAgents`
- Multica 桥目录：`D:\MyAgents\tools\multica-dingtalk-bridge`
- 项目映射文件：`D:\MyAgents\tools\multica-dingtalk-bridge\multica_project_map.json`
- 需求文档落盘目录（与 Multica 短描述配合）：`D:\MyAgents\MulticaTasks\`（`.md`）
- 平台隔离 workspace root：`C:\Users\TU\multica_workspaces`
- pm-system 平台 repo URL：`file:///D:/MyAgents/pm-system`
- 当前主要执行 Agent：`克劳德`
- Review 工具名：`ClaudeReviewer`，底层优先用 `claude --print --output-format json`

PowerShell 约定：

```powershell
cd "D:\MyAgents\tools\multica-dingtalk-bridge"
multica daemon status --output json
multica issue get UUM-24 --output json
multica issue runs UUM-24 --output json
```

## 目标流水线（钉钉当当 ↔ Multica 克劳德 ↔ 审查 ↔ 通知老大）

老大期望的整体效果是：

1. **钉钉里通过当当派单** → Multica 建单并指派 **克劳德**。
2. **克劳德排队**：由 **Multica daemon** 调度（并发上限见主机上的 `MULTICA_DAEMON_MAX_CONCURRENT_TASKS` 等）；连续多单从平台侧排队，**不是当当本地排序**。
3. **每单开发完成后**状态进入 **`In Review`**（由克劳德或流程置位）。
4. **自动审查**：本机 **`dispatch_bot.py` 常驻** 且 **`status_watcher`** 轮询到 **`In Review`** 时，根据 **`IN_REVIEW_REVIEW_BACKEND`** 触发：
   - **`cli`**：`claude` CLI 只读审查 → **dingtalk-desktop** `daemon /send` 私聊老大；
   - **`hermes`**：调用 **`Hermes/hermes-agent/run_agent.py`**（当当侧 **multica-code-review** skill）→ 同样经 daemon（或 `HERMES_REVIEW_DINGTALK_TARGET`）通知老大。
5. **钉钉里的当当**不会凭空收到「克劳德完工」推送——除非另有 Hermes Stream 入站对接。**「当当自动审」**在本仓库落地为：**派单桥代为调用 Hermes 审查进程**，而不是再给当当发一条手动 `@`。

配置摘要见 **`tools/multica-dingtalk-bridge/README.md`**（`IN_REVIEW_REVIEW_BACKEND`、`CODE_REVIEW_*`、`HERMES_REVIEW_*`、`dispatch_bot`）。

**审查失败兜底**：若 `dingtalk-desktop/webhook_config.json` 已配置 **`当当`**（或 `MULTICA_REVIEW_ESCALATION_WEBHOOK_URL`），派单桥在 **Hermes/CLI 自动审查失败**（进程挂、超时、投递失败）时会向该机器人 **再发一条 Markdown**，写明工单号与原因，避免 silently 失败。

## 工作流程（Agentic Protocol）

### Step 1: 分类输入

先判断用户意图，只做一个主动作：

| 用户意图 | 信号 | 动作 |
|---|---|---|
| 新建派单 | 「派单」「#派单」「帮我建工单」 | 提炼标题、描述、项目、验收标准后建单 |
| 查询队列 | 「查工单」「巡查」「现在谁在跑」 | 只读查询 issue / daemon 状态 |
| 分派执行 | 「指派克劳德」「重新开始」「退回 todo」 | 补评论、更新 assignee/status |
| 代码审查 | 「调用 ClaudeReviewer」「review」「审查 UUM-xx」 | 定位真实 worktree 后只读审查 |
| 异常处理 | 「怎么还在 working」「没 worktree」「blocked」 | 查 run、daemon log、workdir，给恢复方案 |

如果同时包含多个意图，按顺序处理：先定位状态，再决定是否建单/退回/审查。

### Step 1b: 识别「本地需求文档」路径（勿装看不见）

老大常在正文里写 **`D:/MyAgents/...`、`\MulticaTasks\...`** 或 **`按 xxx.md 实现`**。这些是**本机仓库内的 Markdown**，不是「缺少正文」：

| 信号 | 当当应做的事 |
|---|---|
| 描述中含 `D:/`、`D:\` 且以 `.md` 结尾 | 视为需求文档路径；在 Hermes 运行环境里 **读取该文件**（read_file 或终端 `Get-Content -Encoding utf8`），从文档提炼摘要与验收条款 |
| 描述中含 `@doc:相对路径` | 与上相同，`相对路径` 相对 `D:\MyAgents` |
| 仅写了 `MulticaTasks/某文件名.md` 无盘符 | 拼成 `D:\MyAgents\MulticaTasks\某文件名.md` 再读 |

**禁止**：在已给出清晰 `.md` 路径且文件可读时，仍追问「请粘贴文档内容」「验收标准是什么」（除非文档里完全没有 AC）。应先读后归纳，缺一项再问一项。

建单时请在 issue **描述末尾**保留文档指针，并追加一行便于执行端注入：

```text
（以下为机器可读附件标记，勿删）
@doc:MulticaTasks/2026-04-29-producer-tower-batch-api.md
```

若用户已在正文写过完整 `D:/MyAgents/...md`，可不重复 `@doc:`，本地桥同样会从路径注入上下文。

### Step 2: 建单与分派

1. 提取派单字段：
   - 标题：一句话说明交付物。
   - 描述：背景、需求、约束、验收标准。**若存在本地 `.md` 路径，先读后把要点与 `@doc:` 行写入描述**，避免 Multica 上单太长。
   - 项目：优先从标题/描述匹配 `multica_project_map.json`；匹配不到时询问。
   - 优先级：默认 `medium`，除非老大写了 **紧急/P0** 或文档明示。
   - 执行 Agent：默认 `克劳德`，除非老大指定。

2. 仅在以下情况追问（不要程式化「永远缺两项」）：

| 缺什么 | 再问 |
|---|---|
| 读完文档仍无法判断交付边界 | 一两句澄清范围 |
| 项目歧义（多个子项目命中） | 确认落到哪个 project |
| 标题为空或过泛 | 请老大收窄一句标题 |

否则直接进入建单。

3. 信息充分时建单：

```powershell
multica issue create `
  --title "<标题>" `
  --description "<描述，含验收标准>" `
  --priority medium `
  --status todo `
  --project "<project_id>" `
  --output json
```

4. 建单后确认分派：

```powershell
multica issue update UUM-xx --assignee "克劳德" --status todo --output json
multica issue comment add UUM-xx --content "已指派克劳德执行。执行前必须进入项目隔离 Git worktree；禁止在 D:\MyAgents 或 D:\MyAgents\pm-system 主工作区直接修改。"
```

5. 回复用户：

```text
已建单：UUM-xx
项目：pm-system
执行：克劳德
状态：todo
下一步：Multica daemon 会拉起平台 Agent；我会用 run work_dir 检查是否进入隔离 worktree。
```

### Step 3: 盯执行与恢复

执行前先确认 daemon：

```powershell
multica daemon status --output json
multica workspace get <workspace_id> --output json
```

判断标准：

- `active_task_count > 0`：已有任务在跑，继续观察，不重复派。
- workspace `repos` 必须包含目标项目 repo，例如 `file:///D:/MyAgents/pm-system`。
- daemon log 出现 `repo checkout: worktree created` 才说明平台进入 Git worktree。
- 如果 run 的 `work_dir` 不是 Git 仓库，Agent 必须 blocked，不允许 `cd D:\MyAgents\pm-system` 继续做。

常用检查：

```powershell
multica issue runs UUM-xx --output json
multica daemon logs -n 80
git status --short
```

如果 issue 卡住：

| 现象 | 处理 |
|---|---|
| `working` 但 daemon 空闲 | 查 `issue runs`，以最新 run 为准；必要时补评论说明后退回 `todo` |
| `blocked: not a git repository` | 检查 workspace repo 配置和 daemon root；配置好后退回 `todo` 重跑 |
| 复用旧普通目录 workdir | 让 Agent 在 run 内执行 `multica repo checkout`，或清理旧执行环境后重跑 |
| 主工作区出现改动 | 立即停止继续分派，报告污染文件，等待老大决定是否迁移到 worktree |

退回重跑模板：

```powershell
multica issue comment add UUM-xx --content "退回重跑：上一轮未进入隔离 Git worktree / review 发现阻塞项。请克劳德按新规范在平台 worktree 内处理。"
multica issue update UUM-xx --status todo --assignee "克劳德" --output json
```

### Step 4: 调 ClaudeReviewer 审查

只在以下条件满足时审查：

- issue 状态是 `in_review`，或老大明确要求审查。
- 已能定位代码变更所在 worktree。
- 审查过程只读，不改文件、不提交、不推送、不改 Multica 状态，除非老大另行授权。

定位顺序必须是：

1. `multica issue runs UUM-xx --output json` 的最新成功 run `result.work_dir`。
2. 根据项目映射进入真实项目目录，例如 `result.work_dir\pm-system`。
3. 确认该目录是 Git 仓库：

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short
git diff main...HEAD --stat
```

重要：不要优先读取旧的 `D:\MyAgents\.worktrees\UUM-xx`。该目录可能是历史本地桥 worktree，容易误报“找不到代码”或审错分支。只有平台 run workdir 不存在时，才考虑本地桥 worktree。

ClaudeReviewer 推荐调用方式：

```powershell
$target = "C:\Users\TU\multica_workspaces\<workspace>\<run>\workdir\pm-system"
$prompt = @"
你是 code-reviewer，只读审查 Multica 工单 UUM-xx。

本次唯一审查目录是：$target
当前 cwd 已经是该目录。
不要读取 D:/MyAgents/.worktrees/UUM-xx，不要读取 D:/MyAgents/pm-system。

先执行只读定位：
- git branch --show-current
- git status --short
- git diff main...HEAD --stat
- git diff main...HEAD

审查边界：
- 只读代码审查，不修改文件，不提交，不推送，不改变 Multica 状态。
- 输出中文审查报告，问题优先，按严重程度排序。
- 若无阻塞项，明确说无阻塞，并列测试缺口。
"@
claude --print --output-format json $prompt
```

审查报告格式：

```text
UUM-xx Review 结论：
- 阻塞项：有 / 无
- 高风险：
  1. <问题> — <影响> — <建议>
- 中低风险：
  1. <问题> — <建议>
- 测试缺口：
  1. <缺口>
- 建议下一步：退回 todo / 保持 in_review 等人工验收 / 可合并
```

审查完成后**必须**执行两步自动落盘：

### Step 4b: 审查结果落盘 + 通知

**a) 写 Multica 评论：**

```powershell
multica issue comment add UUM-xx --content "<审查报告全文>" --output json
```

**b) 发送 webhook 通知老大：**

发 Markdown 通知到 webhook。格式：

```
[审查完毕] UUM-xx: <工单标题>

工单：UUM-xx
审查后端：Hermes/当当
结论：<阻塞项有/无>
结果摘要：<报告前 300 字>
下一步：查看 Multica 评论详情，确认后改为 approved 自动合并。
```

这两步是自动的——审查完就做，不等老大说"退回"。

如果审查发现阻塞项，再追加退回评论并改状态：

```powershell
multica issue comment add UUM-xx --content "<review 摘要与退回原因>"
multica issue update UUM-xx --status todo --assignee "克劳德" --output json
```

---

### Step 5: 巡检（定期或老大指令触发）

当当具备自主巡检能力。触发条件：老大说"巡检""巡逻""看看工单""状态对吗"，或定时触发。

#### 5.1 需求不清 / 归属不清

| 检测条件 | 动作 |
|---------|------|
| issue 描述 < 50 字 | 私聊老大确认 |

#### 5.2 停滞检测

| 条件 | 阈值 |
|------|------|
| todo 无人认领 | > 24h |
| in_progress 无 run 活动 | > 8h |
| in_review 无人推进 | > 24h |

检测到停滞 → 逐一私聊老大确认下一步。

#### 5.3 已完成但状态未更新

| 证据 | 条件 | 动作 |
|------|------|------|
| 强证据 | agent 分支已合 main + run 完成 + in_review | 自动改 done |
| 强证据 | run 完成 + todo | 自动改 in_review |
| 中证据 | run 完成 + in_progress | 自动改 in_review |
| 弱证据 | git diff main..agent 为空 | 发确认 |

#### 5.4 指派不启动 / worktree 产出未推分支

| 现象 | 动作 |
|------|------|
| assignee=agent + todo + 无活跃 run | 报告老大 |
| 评论含代码描述 + git 无对应分支 | 报告老大，尝试进 worktree 救援 |

## 安全护栏

- 禁止在 `D:\MyAgents` 根仓或 `D:\MyAgents\pm-system` 主工作区直接让平台 Agent 写代码。
- 禁止使用 `git reset --hard`、`git clean -fd`、`push --force`。
- 不要把 `.env`、token、Client Secret、内部敏感数据写入 Multica issue 或评论。
- 发现 `repos=0`、`work_dir` 非 Git 仓库、daemon clone 失败时，停止派发开发任务，先修配置。
- Review 时不改状态；状态流转必须由老大授权或明确流程触发。

## 常见判断

### 如何确认平台 worktree 已成功

满足三条才算成功：

```powershell
multica daemon logs -n 80
# 需要看到：repo checkout: worktree created

cd "<result.work_dir>\<project_path>"
git rev-parse --show-toplevel
git branch --show-current
```

分支通常类似：

- `agent/UUM-25`
- `agent/agent/<run短id>`

只要目录在 `C:\Users\TU\multica_workspaces\...` 下，且 `git rev-parse` 指向该目录本身，就可以继续。

### 如何识别 Review 是否审错地方

以下情况说明审错了：

- Reviewer 说 `pm-system/` 子模块为空。
- Reviewer 只看到 `D:\MyAgents\.worktrees\UUM-xx`。
- Reviewer 报 “沙箱不能读取 `D:\MyAgents\pm-system`”。
- Reviewer 的 `git diff main...HEAD` 不是本 issue 的代码变更。

修正方式：强制指定平台真实目录 `result.work_dir\<project_path>`，重跑 ClaudeReviewer。

## 局限性

- 本 Skill 不直接解决 Multica Web UI 中 repo URL 配错、Agent 指令丢失、daemon 登录失效等平台配置问题；遇到时先输出诊断和需要老大在 Web UI 处理的项。
- 本 Skill 不替代代码审查本身；它负责定位正确 worktree 并调用 ClaudeReviewer，最终是否退回或合并仍需老大确认。
- 本 Skill 假设 Multica CLI 已登录且 `multica daemon` 在本机运行；若 CLI 未登录或 daemon 不在本机，应先走 `multica setup` / `multica auth status` / `multica daemon start`。

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-04-29 | v1.0 | 为 Hermes profile dangdang 新增 Multica 派单、Agent 调度、ClaudeReviewer 审查流程 |
| 2026-04-29 | v1.1 | 派单识别：`D:/MyAgents/**/*.md` 与 `@doc:` 视为可读本地文档；读后再问；建单描述保留 `@doc:` 供 task_context 注入 |
| 2026-04-29 | v1.2 | 文档化「当当 ↔ daemon 排队 ↔ In Review → CLI/Hermes 审查」；与 `status_watcher` + `IN_REVIEW_REVIEW_BACKEND` 对齐 |
