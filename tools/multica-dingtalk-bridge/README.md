# Multica × 钉钉 Stream 派单桥

本目录实现：**钉钉企业机器人（Stream 模式）** 收 `#派单` 建单 → 本机子进程执行 **`multica issue create`**；收 **`删除派单` / `#删除派单`**（及 **`取消派单`** 别名）→ **`multica issue status … cancelled`**（Multica 无物理删除，等同取消工单）。与 `docs/superpowers/specs/2026-04-18-multica-integration-design.md` §5–§6 一致。

## 前提

- 本机已安装 Multica CLI，且 `multica auth status` 为已登录；`multica issue create` 手工可成功。
- 钉钉开放平台：企业自建应用已开启 **机器人** 且接入 **Stream 模式**（非传统 HTTP 回调）；记录 **Client ID** / **Client Secret**。
- 运行桥的主机须能访问钉钉与 Multica Cloud（公司网络策略自行放行）。

## 凭据（本机 `.env`，勿提交）

1. 复制 `.env.example` 为同目录下的 `.env`。
2. 填入 `DINGTALK_CLIENT_ID`、`DINGTALK_CLIENT_SECRET`。仓库根 `.gitignore` 已忽略 `.env`，**不要**把 Secret 贴进 Git 或群聊。
3. `dispatch_bot.py` 启动时会自动 `load_dotenv`；已设置的环境变量优先于 `.env`。

**可选**：`MULTICA_PROJECT_ID` — 若 Web 上默认落在「无项目」视图不易看到新单，可在 `.env` 中设置项目 UUID，`issue create` 会自动带 `--project`。

**可选**：`MULTICA_BIN` — 若机器人提示找不到 `multica`，多半是派单桥进程 **PATH 里没有安装目录**；可写绝对路径到 `multica.exe`，或始终用 **`run_bridge.ps1`** 启动（脚本会合并系统与用户 PATH）。

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

也可从 **`pm-system/quick_start.bat`** 无参启动：会顺带拉起派单桥（独立窗口标题 `Multica_DT_Bridge`）；菜单 **[7]** 单独重启，**[8]** 全部关闭，**[9]** 全部重启。

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
其它消息**不会**收到机器人回复（避免刷屏）。

**取消工单**：以 **`删除派单`** 或 **`#删除派单`**（或 **`取消派单` / `#取消派单`**）开头，同一行写 **`UUM-10`** 这类标识，或写 **短号 `10`**（桥会在当前 Workspace 下最多 **500** 条 `issue list` 结果里按 `number` 匹配，再调用 CLI）。也可写 **Issue UUID**。

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

## 建单成功回复里的统计

机器人会拉取 **当前 Workspace 工单总数**（`issue list` 的 `total`）以及 **各状态条数**（对每个状态各执行一次 `issue list --status <状态> --limit 1` 读 `total`）。若配置了 `MULTICA_PROJECT_ID`，统计限定在该项目。

## 可选出站

设置环境变量 `DINGTALK_WEBHOOK_URL` 后，建单成功会向该 Webhook 发一条 Markdown（与仓库 `cursor-to-dingtalk` 机器人格式兼容）。

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
