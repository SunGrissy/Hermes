# Hermes 接通钉钉（Stream 机器人）

Hermes 通过钉钉 **Stream 模式**（本机 WebSocket 出站）收消息，**不需要**公网域名或自建 Webhook 服务器。配置落在 **`HERMES_HOME`**（本机为 **`D:\hermes`**）：`.env` + `config.yaml`。

官方文档：<https://hermes-agent.nousresearch.com/docs/user-guide/messaging/dingtalk>

## 1. 钉钉开放平台（开发者后台）

1. 创建应用（名称随意，例如 Hermes）。
2. **添加能力 → 机器人**，打开机器人。
3. **消息接收模式**选 **Stream 模式**（推荐）。
4. 在 **凭证与基础信息** 复制 **Client ID（AppKey）**、**Client Secret（AppSecret）**（Secret 只显示一次，丢失需重置）。

## 2. 写入 Hermes 环境变量（`D:\hermes\.env`）

参考仓库内示例（勿把真实密钥提交到 Git）：

- 模板文件：**`D:\hermes\env.dingtalk.example`**

至少 **`DINGTALK_CLIENT_ID`**、**`DINGTALK_CLIENT_SECRET`**。第三项与**谁有权走网关**有关（见下表）。

| 变量 | 含义 |
|------|------|
| `DINGTALK_CLIENT_ID` | 应用 AppKey |
| `DINGTALK_CLIENT_SECRET` | 应用 AppSecret |
| `DINGTALK_ALLOWED_USERS` | 允许使用机器人的钉钉 **UserId**（与日志里 `sender_id` / `staff_id` 一致），多个用英文逗号；写 `*` 表示不校验用户（仅适合本机调试） |
| `GATEWAY_ALLOW_ALL_USERS` | 若**未**配置任何平台/全局白名单，网关默认**拒绝**所有人；本机调试可设为 `true`（生产勿用） |

**两层门禁（易混）**：钉钉适配器里「未配 `DINGTALK_ALLOWED_USERS`」会放行所有人；但消息进入网关后还会走 **`_is_user_authorized`**——在**未**配置 `DINGTALK_ALLOWED_USERS`、`GATEWAY_ALLOWED_USERS` 且**未**设 `GATEWAY_ALLOW_ALL_USERS=true` 时，**一律未授权**。群内常见表现是**静默无回复**；单聊可能收到配对码提示（视 `unauthorized_dm_behavior`）。因此要么在 `.env` 里写上自己的 UserId，要么调试期开 `GATEWAY_ALLOW_ALL_USERS=true` / `DINGTALK_ALLOWED_USERS=*`。

## 3. 交互配置（可选）

在已安装 Hermes 的终端执行：

```powershell
cd D:\MyAgents
$env:HERMES_HOME = "D:\hermes"
hermes gateway setup
```

按提示选择 **DingTalk**，可用 **扫码** 或 **手动粘贴** Client ID / Secret 与允许的用户 ID（向导会把结果写入 `D:\hermes\.env`）。

## 4. 启动网关

```powershell
cd D:\MyAgents
$env:HERMES_HOME = "D:\hermes"
hermes gateway
```

**必须先**在同一终端里设好 `HERMES_HOME`（或做成**用户级环境变量**）。`hermes` 会优先加载 **`%HERMES_HOME%\.env`**；若未设 `HERMES_HOME`，会读 **`%USERPROFILE%\.hermes\.env`**，**不会**自动读 `D:\hermes\.env`，导致钉钉凭证未加载、网关根本不连钉钉。

保持该进程常驻（或以后用计划任务 / 服务包装）。连接成功后，**单聊**可直接发消息；**群内**若配置了 `require_mention`，需 **@机器人**（或配 `free_response_chats` / `mention_patterns`）。

## 5. 本仓库已改的 Hermes 侧默认值

- **`D:\hermes\config.yaml`**：`platform_toolsets.dingtalk` → `hermes-dingtalk`；`display.platforms.dingtalk` 为钉钉端展示默认（与官方文档一致思路）。
- 依赖：`hermes-agent[all]` 已包含 `dingtalk-stream` 等（若报未安装，在 `D:\hermes\hermes-agent` 下执行 `uv pip install -e ".[all]"`）。

## 6. 与现有「钉钉桌面 / Webhook」的关系

- **Hermes 钉钉机器人**：对话式 Agent，走 Stream，适合「和 Hermes 聊天」。
- **仓库内 dingtalk-desktop、群机器人 Webhook**：适合固定模板推送；二者可并存，职责分开即可。

## 6b. 入站命令路由器（Multica 派单短路）

设计说明与割接清单：**`docs/superpowers/specs/2026-04-21-hermes-inbound-command-router-design.md`**（§0 现网 Stream 单活、§9.2 配置切换）。

| 变量 | 含义 |
|------|------|
| `HERMES_INBOUND_ROUTER_ENABLED` | `1` / `true` / `yes` / `on` 时，在进主 Agent **之前**尝试「入站命令路由器」（当前含 Multica 适配器）。 |
| `HERMES_ROUTER_MULTICA_ENABLED` | 同上语义；为 `on` 时 Multica 适配器才会解析 `#派单` / `查工单` / `删除派单` 等并调本机 `multica`。 |

**与 `tools/multica-dingtalk-bridge/dispatch_bot.py` 互斥**：同一钉钉应用 **Client ID** 在任一时刻只能有一条 **Stream** 连接。启用 Hermes 收消息并打开上述开关时，**不要**再启动派单桥；详见 spec §9.2。

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 发消息完全无回复 | 1）确认启动前 **`HERMES_HOME=D:\hermes`**，且 **`D:\hermes\.env`** 里已有 Client ID/Secret。2）确认 **`DINGTALK_ALLOWED_USERS`** 含你的 UserId，或调试期 **`GATEWAY_ALLOW_ALL_USERS=true`** / **`DINGTALK_ALLOWED_USERS=*`**。3）**群内**是否 **@机器人**（若开了 `require_mention`）。4）看 **`D:\hermes\logs`**（如 `agent.log`）是否有 `Unauthorized user`、模型/Ollama 报错。 |
| 不回复 | 查机器人能力、Stream 模式、开放平台应用是否已发布/可见范围包含对话对象。 |
| 缺包 | `uv pip install "dingtalk-stream" httpx alibabacloud-dingtalk`（在 venv 中）。 |
| 扫码页显示 openClaw | 官方说明为钉钉侧展示文案，应用仍是你租户下的。 |
