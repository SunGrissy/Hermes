# Multica × 钉钉 Stream 派单桥

> **与 Hermes 互斥**：若钉钉机器人已由 **Hermes 网关**（`hermes gateway`）占用 Stream，且已开启 **`HERMES_INBOUND_ROUTER_ENABLED` + `HERMES_ROUTER_MULTICA_ENABLED`**，则 **不要** 用**同一 Client ID** 再启动本桥，否则抢线、双方不稳定。目标态见 `docs/superpowers/specs/2026-04-21-hermes-inbound-command-router-design.md` §0 / §9.2。

本目录实现：**钉钉企业机器人（Stream 模式）** 收 `#派单` 建单 → 本机子进程执行 **`multica issue create`**；收 **`删除派单` / `#删除派单`**（及 **`取消派单`** 别名）→ **`multica issue status … cancelled`**（Multica 无物理删除，等同取消工单）。与 `docs/superpowers/specs/2026-04-18-multica-integration-design.md` §5–§6 一致。

## 前提

- 本机已安装 Multica CLI，且 `multica auth status` 为已登录；`multica issue create` 手工可成功。
- 钉钉开放平台：企业自建应用已开启 **机器人** 且接入 **Stream 模式**（非传统 HTTP 回调）；记录 **Client ID** / **Client Secret**。
- 运行桥的主机须能访问钉钉与 Multica Cloud（公司网络策略自行放行）。

## 凭据（本机 `.env`，勿提交）

1. 复制 `.env.example` 为同目录下的 `.env`。
2. 填入 `DINGTALK_CLIENT_ID`、`DINGTALK_CLIENT_SECRET`。仓库根 `.gitignore` 已忽略 `.env`，**不要**把 Secret 贴进 Git 或群聊。
3. `dispatch_bot.py` 启动时会自动 `load_dotenv`；已设置的环境变量优先于 `.env`。

**可选**：`MULTICA_PROJECT_ID` — 强制所有新单落到指定项目。若不设置，派单桥会读取同目录 `multica_project_map.json`，按标题/描述关键词自动选择 project。

**可选**：`MULTICA_PROJECT_MAP_FILE` — 自定义 project 映射文件路径。默认使用 `tools/multica-dingtalk-bridge/multica_project_map.json`，当前已包含 `pm-system`、`performeval`、`cci_system`、`task_reminder`、`teamscore`、`md-reader`。

**可选**：`MULTICA_BIN` — 若机器人提示找不到 `multica`，多半是派单桥进程 **PATH 里没有安装目录**；可写绝对路径到 `multica.exe`，或始终用 **`run_bridge.ps1`** 启动（脚本会合并系统与用户 PATH）。

**可选**：`MULTICA_WORKSPACE_WEB_PATH` — 浏览器里工单 URL 中 workspace 段，例如 `https://multica.ai/uu-myagents/issues/UUM-12` 中的 **`uu-myagents`**。建单成功回复里的「点击查看」会拼成 `{MULTICA_APP_URL 或 https://multica.ai}/{该段}/issues/{identifier}`。若 CLI 返回的 JSON 里已含 `html_url` / `url` 等字段，则优先用接口 URL。

**可选**：`MULTICA_BOT_MEMORY_DB` — Brain 记忆库路径，默认写入本目录下 `data/memory.db`。

**可选**：`MULTICA_BOT_LLM_PROVIDER` — 默认 `mock`，不访问外部 LLM。设为 `openai` 时必须显式配置 `MULTICA_BOT_LLM_API_KEY`，并按需配置 `MULTICA_BOT_LLM_BASE_URL`、`MULTICA_BOT_LLM_MODEL`；脚本不会读取全局 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`，也不会读取旧的 `MULTICA_BOT_OPENAI_API_KEY`，避免误把用户消息发到未确认的外部服务。用户消息与上下文会发送到配置的 LLM endpoint，请只接可信服务。

**可选**：`MULTICA_WEBHOOK_NOTIFY_SCOPE` — 控制 `DEV_AGENT_NOTIFY_WEBHOOK`（或 `webhook_config.json` 的 `cursor_session`）上哪些事件会推 Markdown。默认 **`review_and_failures`**：只推 **审查完毕**、**运行/工单失败**、**自动合并冲突** 等需要介入的；不推 Claude 工作中/完成、待审查、已完成、审查通过，也不推 Agent 启动/规划/子任务进度（避免 AgentWork 一类机器人刷屏）。需要恢复此前「状态与 run 全量通知」时设为 **`all`**。

**可选**：`MULTICA_AUTO_MERGE_TRIGGER_STATUS` — `status_watcher` 在检测到 Multica 工单进入某状态后，尝试把本仓库 **`agent/{工单号}`** 合并进 **`main`** 并 `git push origin main`（无该分支则跳过）。默认 **`approved`**（与早期脚本一致）；若 Multica 工作区**没有** `approved` 状态、只能选 **Done** 关单，请设为 **`done`**，改为「关单即尝试合并」。合并成功后仍会调用 `multica issue update … --status done`（已是 Done 时等价幂等）。

## 能力与安全边界

- 固定命令继续保留：`派单` / `#派单` 创建工单，`查工单` / `#查工单` 查看队列，`删除派单` / `#删除派单` / `取消派单` / `#取消派单` 取消工单。
- 自然语言 Brain 路由只处理明确的派单/队列意图：信息不足时先做需求澄清；信息足够时输出派单建议卡；老大回复 `就按这个派`、`确认派单`、`按这个派`、`可以派` 后才创建工单。
- 记忆规则：低风险 `knowledge` 自动写入；`preference`、`rule`、`acceptance`、`permission`、`classification` 进入 `pending` 等待人工确认；疑似密钥、token、密码等敏感信息直接 reject。
- 只读巡查命令：`巡查`、`队列巡查`、`巡查工单`、`multica巡查`，只读取并汇总 Multica 队列，不会自动改状态、分派、评论或创建工单。
- Phase 1 安全边界：不自动执行代码，不自动分派或改状态；确认后才创建工单；巡查始终只读。

## Multica 试点配置（Task 2，填好后勿提交密钥）

在 Multica Web（Cloud：`https://multica.ai/app`）完成 **pm-system 试点** 项目与 Agent 后，把下面占位符换成你环境里的值，便于 CLI 与派单一致。

| 项 | 占位 | 说明 |
|----|------|------|
| 默认 `workspace_id` | `<在此粘贴 multica config show 中的 workspace>` | `multica config show`；若不对：`multica config set workspace_id <uuid>` |
| 试点项目名 | `pm-system 试点` | Projects 中创建 |
| 项目 ID（`--project`） | `<在此粘贴 project id>` | Web 或 CLI 可见，用于扩展脚本时过滤 |
| 常用 Agent 名 | 例：`pm-cursor` | Settings → Agents，与 `multica agent list` 对齐 |

首条试跑 Issue 示例（在项目与 workspace 正确时执行）：

```bash
multica issue create \
  --title "pm-system 试点：Multica 首单" \
  --description "范围仅限 pm-system/；关单时补 WORK_LOG 并互链 Multica。" \
  --priority medium \
  --status todo \
  --project "<上一步-project-id>"
```

**CLI 安装与校验（Task 1，macOS）**

```bash
brew install multica-ai/tap/multica
multica version
multica setup
multica auth status
multica daemon status
multica workspace list
```

停用：`multica daemon stop`；退出登录：`multica auth logout`。

## 运行

**Windows（推荐）**：在同目录已存在 `.venv` 且 `pip install -r requirements.txt` 之后：

```powershell
cd d:\MyAgents\tools\multica-dingtalk-bridge
.\run_bridge.ps1
```

**单实例（只保留一组 bridge）**：`run_bridge.ps1` 会先结束命令行里带本目录路径的 **`watchdog.py` / `dispatch_bot.py`** 残留进程，再拉起一组；`watchdog.py` 还会对同目录下的 **`.multica_bridge_watchdog.lock`** 加独占锁，若已有守护进程在跑则第二次启动会直接退出并提示，避免双开抢 Stream、重复发 webhook。

也可从 **`pm-system/quick_start.bat`** 无参启动：会顺带拉起派单桥（独立窗口标题 `Multica_Bridge`）；菜单 **[7]** 单独重启，**[8]** 全部关闭，**[9]** 全部重启。

**通用**：

```bash
cd tools/multica-dingtalk-bridge
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python dispatch_bot.py --client_id "<Client ID>" --client_secret "<Client Secret>"
```

已配置 `.env` 时可直接：

```bash
python dispatch_bot.py
```

推荐用环境变量或 `.env` 注入密钥，避免把 Secret 写进 shell history。

## 群内 / 私聊发单格式

以 **`派单`** 或 **`#派单`** 开头，紧跟标题；从第二行起为描述（可选）。  
其它无明确派单/队列意图的消息**不会**收到机器人回复（避免刷屏）；包含需求、派单、工单、Multica、队列管家等意图的自然语言会进入 Brain 路由。

**取消工单**：以 **`删除派单`** 或 **`#删除派单`**（或 **`取消派单` / `#取消派单`**）开头，写 **`UUM-10`**、**短号 `10`**（在最多 **500** 条 `issue list` 里按 `number` 匹配）或 **Issue UUID**。**多个引用**可用 **顿号 `、`**、中英文逗号/分号或空白分隔，例如 `删除派单 1、2、6` 或 `删除派单1、2、6`（最多 **50** 条）；会按解析结果逐条调用 `issue status … cancelled`，并在一条回复里汇总成功 / 解析失败 / 接口失败。

**查工单**：仅发 **`查工单`** 或 **`#查工单`**（勿跟其它文字），机器人回复 **状态分布**（与各 `issue list --status` 的 `total` 一致，**仍含已取消条数**）+ **按优先级前 10 条**（**不含 `cancelled`**；`urgent` > `high` > `medium` > `low`，未知优先级殿后；同档按 **`created_at` 由早到晚**）。列表数据来自一次 **`issue list --limit 500`** 后再过滤；若 `has_more` 为真，文末会有说明。

示例：

```text
派单 测试来自钉钉
第二行描述
```

```text
#派单 测试来自钉钉
第二行描述
```

```text
删除派单 UUM-10
```

```text
删除派单 10
```

```text
删除派单 1、2、6、7、8、9、10
```

## 建单成功回复版式

机器人按固定版式回复：**编号**置顶 → 分隔线 → **工单已写入** / **标题** / **描述**（与钉钉正文一致）→ **点击查看**（工单直链，见上节 `MULTICA_WORKSPACE_WEB_PATH`）→ 分隔线 → **工单总览** 仅一行 **`待办：N`**（`todo` 状态条数，与 `issue list --status todo` 的 `total` 一致）。若配置了 `MULTICA_PROJECT_ID`，该待办数限定在该项目。

## 可选出站

设置环境变量 `DINGTALK_WEBHOOK_URL` 后，建单成功会向该 Webhook 发一条 Markdown；取消工单成功时也会发送取消摘要（与仓库 `cursor-to-dingtalk` 机器人格式兼容）。

## 可选：In Review 自动触发审查（CLI / Hermes 当当）

`status_watcher.py`（由 `dispatch_bot.py` 启动）会监听工单状态变化：进入 **`In Review`** 时除 Webhook 外，可按配置触发 **审查链**。

### Multica 排队（克劳德「按规则排队」）

平台 **`multica daemon`** 按 workspace 配置执行任务；并发上限见环境变量（示例脚本中的）**`MULTICA_DAEMON_MAX_CONCURRENT_TASKS`**（例如 `2` 表示同时最多跑 2 个）。连续派 3 单时，多出来的会在 daemon 队列里等待，**不由当当本地排序**——这是 Multica 的执行语义。

### 审查后端：`IN_REVIEW_REVIEW_BACKEND`

| 值 | 行为 |
|----|------|
| **`cli`**（默认） | 仅 **`code_review_dispatcher`**：`claude --print ...` 只读审查 + `DINGTALK_DAEMON_URL` / `CODE_REVIEW_DAEMON_CID` 私聊投递 |
| **`hermes`** | 仅 **`hermes_review_dispatcher`**：调用本机 **`Hermes/hermes-agent/run_agent.py`**，提示词走当当侧的 **multica-code-review** skill，结果同样经 daemon 私聊（或 `HERMES_REVIEW_DINGTALK_TARGET`） |
| **`both`** | 两套各跑一次（易重复报告，通常不建议） |

配合开关：**`cli`** 路径需 **`CODE_REVIEW_ENABLED=1`**；**`hermes`** 路径需 **`HERMES_REVIEW_ENABLED=1`** 且 **`HERMES_REVIEW_DAEMON_CID`**（或发送目标）配置正确。

> 「钉钉里当当收到完工通知再自动审」：**钉钉侧并无通用回调把消息送进 Hermes**。自动化依赖 **本机 `dispatch_bot` + status_watcher** 扫到 **`In Review`** 后拉起 **`hermes`** 审查链；你在钉钉里对当当说的派单仍是在 **Multica 建单**，与这条链路衔接。

旧版文档下文描述 **`CODE_REVIEW_*`**（CLI）细节；若选用 **`hermes`**，请同步阅读 **`hermes_review_dispatcher.py`** 顶部环境与 **`Hermes/dangdang/SKILL.md`**。

自动开发 Agent 会为每个工单创建独立工作区：`.worktrees/{issue_id}`，对应分支仍为 `agent/{issue_id}`。Claude 执行、diff 收集和后续审查都优先在这个 worktree 内完成，避免多个工单在同一个仓库目录里互相切分支。

### 平台 Agent 与本地桥的执行边界

当前存在两条链路：

1. **本地桥执行器**：`dev_agent_runner.py` 明确创建 `D:\MyAgents\.worktrees\{issue}`，这是默认安全执行路径。
2. **Multica 平台 daemon**：会创建 `work_dir`，但只有 workspace 配置了 repo 时才会自动准备 Git worktree。若 `multica workspace get ... --output json` 里 `repos` 为空，daemon 日志会显示 `repos=0`，此时平台 workdir 只是普通目录，不能直接作为代码执行主通道。

推荐启动平台 daemon 时使用仓库外的 workspace root：

```powershell
cd d:\MyAgents\tools\multica-dingtalk-bridge
.\run_multica_daemon_isolated.ps1
```

脚本会设置：

```powershell
MULTICA_REPOS_ROOT=D:\MyAgents
MULTICA_WORKSPACES_ROOT=%USERPROFILE%\multica_workspaces
MULTICA_DAEMON_MAX_CONCURRENT_TASKS=2
MULTICA_KEEP_ENV_AFTER_TASK=1
```

注意：不要把 `MULTICA_WORKSPACES_ROOT` 放在 `D:\MyAgents` 内部。普通平台 workdir 位于仓库子目录时，`git rev-parse` 会向上命中根仓 `.git`，误判为共享工作区。

`克劳德` Agent 已加护栏：如果当前 `work_dir` 不是隔离 Git worktree，必须直接回复 blocked，禁止 `cd D:\MyAgents\pm-system` 后修改共享目录。平台 Agent 只有在 Multica workspace 配置 repo 且 smoke run 验证 `repos_available > 0` / `work_dir` 是 Git worktree 后，才能重新作为代码执行主通道。

### 配置

```env
CODE_REVIEW_ENABLED=1
CODE_REVIEW_COMMAND=claude
CODE_REVIEW_MULTICA_BIN=multica
CODE_REVIEW_ARGS=--print --output-format json
CODE_REVIEW_REPO_ROOT=D:\MyAgents
CODE_REVIEW_TIMEOUT=1800
CODE_REVIEW_SEND_TIMEOUT=90
```

结果投递走本机钉钉桌面通道：

```env
CODE_REVIEW_DAEMON_CID=
DINGTALK_DAEMON_URL=http://127.0.0.1:19200
```

### Reviewer 行为

1. 只读代码审查，不修改文件、不提交、不推送、不改变 Multica 状态。
2. 优先审查 `.worktrees/{issue_id}`；找不到时查询 `multica issue runs {issue_id}`，优先使用平台 run result 的 `work_dir`；最后才回退到 `CODE_REVIEW_REPO_ROOT` 并按 `agent/{issue_id}` 分支线索报告阻塞原因。
3. Claude CLI 输出建议使用 JSON：`--print --output-format json`，便于脚本提取 `result`。
4. `CODE_REVIEW_DAEMON_CID` 为空时只运行审查并记日志，不投递私聊。

关闭 `CODE_REVIEW_ENABLED` 且 `HERMES_REVIEW_ENABLED` 未开（或 `IN_REVIEW_REVIEW_BACKEND` 未指向对应后端）时，仅保留状态变更 Webhook。仍可手动在钉钉对当当发 **`审查 UUM-xx`**。

### 「完工 → 通知当当」在当前架构下的含义

- **通知**：Webhook（若配置）会推送 **状态变为 `In Review`**；这不是单独再给当当发一条 IM，除非你在群里对接了 Hermes 入站。
- **当当自动审**：即 **`IN_REVIEW_REVIEW_BACKEND=hermes`** + **`HERMES_REVIEW_ENABLED=1`** + **`dispatch_bot` 常驻**，由派单桥代为调用 Hermes `run_agent`，**不等你在钉钉里再打一遍「审查」**。

### 审查失败兜底 Webhook（Hermes 挂了也能通知老大）

若 **`dingtalk-desktop/webhook_config.json`** 配置了 **`当当`** 键（机器人 URL），或环境变量 **`MULTICA_REVIEW_ESCALATION_WEBHOOK_URL`** 非空，则 `status_watcher` 在触发 **CLI / Hermes 审查**时会在后台线程内 **同步**跑完 `dispatch`；**任一端返回失败**（含 `run_agent.py` 不存在、超时、空报告、daemon 投递失败）时，向该 webhook 再发一条 **Markdown**，标明工单号与失败原因，便于介入。

未配置兜底 URL 时行为与旧版一致（仅异步触发审查线程，失败只写日志）。

> Token 敏感：生产环境可只用 **`MULTICA_REVIEW_ESCALATION_WEBHOOK_URL`** 指向本机私密 `.env`，避免把机器人 URL 提交到 Git。

## 安全

- 勿在 Issue 正文写密钥、内网未公开数据；见 spec §3.1 脱敏。
- `Client Secret` 仅用环境变量或本地私密配置，勿提交到 Git。

## 排障

- 机器人回复「Multica 建单失败」：本机执行 `multica auth status`、`multica issue create`（同标题）是否成功；`multica` 是否在运行桥的同一 shell 的 `PATH` 中。
- Stream 连不上：检查本机出网、钉钉应用是否 Stream 模式、Client ID/Secret 是否对应同一应用。
- **钉钉里出现「已收录」卡片、正文却不像本脚本返回的「已在 Multica 创建工单」长文**：多半是**其它钉钉应用/技能**在同群抢答；同一机器人 Client ID 也应避免多台电脑同时跑 `dispatch_bot.py`（会抢 Stream 连接）。以本脚本回复中的 **Issue 编号 / `multica issue get …`** 为准核对 Multica。
- **日志里 `Card.Instance.Write` / `create card instance failed` 403**：互动 Markdown 卡片需要开放平台为应用开通 **`Card.Instance.Write`**（报错里会给申请链接）。开通后重新发布应用并重启桥。  
  若暂不开权限：在 `.env` 设 `DISPATCH_SKIP_MARKDOWN_CARD=1`，脚本会**直接**用 `reply_markdown`（带标题栏的 Markdown，仍支持 emoji），不再调卡片接口。  
  当前版本在卡片创建失败（含返回空实例）时会 **自动降级** session Markdown，不应再出现「建单成功但钉钉无回复」。**同一派单桥进程内**首次失败后会把「互动卡片不可用」记下来，后续派单**直接**走 session Markdown，不再重复请求卡片接口（避免刷屏 403）；开通 `Card.Instance.Write` 后需 **重启桥** 才会再尝试卡片。
