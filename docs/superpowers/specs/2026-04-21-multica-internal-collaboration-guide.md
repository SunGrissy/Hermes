# Multica 内网生产环境 — 全员协作指南

> **读者**：使用内网 Multica + 钉钉派单的全体研发 / 制作人侧用户。  
> **配套**：部署由运维按 `docs/superpowers/plans/2026-04-21-multica-selfhost-production-deploy-runbook.md` 完成；架构边界见 `docs/superpowers/specs/2026-04-21-multica-selfhost-production-design.md`。

---

## 1. 我们有两套环境时怎么区分

| 环境 | Multica 地址 | 用途 |
|------|----------------|------|
| **个人调试**（可选） | `https://multica.ai` | 制作人/个人试流程、与正式数据 **隔离** |
| **团队正式** | 内网 `https://…`（运维公布） | 真实派工、认领、关单、统计 |

**纪律：** 正式交付、对同事的承诺、需要追溯的工单，**默认进内网**；个人 Cloud 板子不要当「正式真相源」。

---

## 2. 每人第一次要做什么（客户端）

1. 安装 **Multica CLI**（Windows / macOS 按官方 [CLI_AND_DAEMON.md](https://github.com/multica-ai/multica/blob/main/CLI_AND_DAEMON.md)）。
2. 向运维要两个 URL：**App**、**API**（均为内网 HTTPS）。
3. 执行：  
   `multica setup self-host --server-url <API> --app-url <App>`  
   按提示浏览器登录（验证码规则由运维配置）。
4. 若要用 **本机 Agent 跑任务**：安装至少一种受支持 CLI（如 Cursor 的 `cursor-agent`），再：  
   `multica daemon start`  
   在 Web **Settings → Runtimes** 确认自己的机器在线。
5. 验证：  
   `multica issue create --title "内网连通性测试" --description "可删"`  
   Web 能看到后，自行关单或请 Owner 清理。

---

## 3. 日常协作流（推荐）

1. **建单**：Web 新建 Issue，或钉钉发 **`#派单` + 标题**（第二行起为描述，格式见下节）。
2. **写清楚 DoD**：标题短、描述里一句可验收结果；敏感细节写 **「见内网 WORK_LOG 某日期」** 而非全文贴密钥。
3. **认领与状态**：负责人把状态从 `todo` 推到进行中/完成；需要协作用 **评论 @** 或指派。
4. **关单**：评论里写 **交付摘要**，并写 **`WORK_LOG: YYYY-MM-DD - 标题片段`**；同时在 `WORK_LOG.md`（或模块约定路径）对应条末尾加 **`Multica: #编号或链接`**。  
   （与 `2026-04-18-multica-integration-design.md` §7 一致。）
5. **拆单**：影响面大、可并行、多个独立验收点 → 拆成多条 Issue 或父子结构；细则见原 spec **§7.1**。

---

## 4. 钉钉派单（生产）

- **格式**：以 **`派单`** 或 **`#派单`** 开头，紧跟标题；从第二行起为描述。其它消息机器人不回复（防刷屏）。  
  完整说明与 **取消派单 / 查工单** 指令见：`tools/multica-dingtalk-bridge/README.md`
- **不要做的事**：  
  - 不要用 **同一套** 钉钉机器人让多台电脑「都试着跑一下」桥进程——会抢连接，工单表现异常。  
  - 不要把 `DINGTALK_CLIENT_SECRET` 发到聊天工具。

---

## 5. 队列 Owner（制作人 / 模块负责人）额外职责

- 固定 **正式 Workspace / Project** 的命名与归档习惯，避免「无项目」里堆单找不到。
- 派单时标 **优先级、是否允许执行中扩范围**；明显该拆的单在入队阶段就拆好。
- 桥或内网故障时发 **简短公告**：临时只用 Web 或只用某渠道，恢复后补录。

---

## 6. 常见问题（FAQ）

| 现象 | 建议 |
|------|------|
| `multica auth` 失败 | 检查 VPN、系统时间、API URL 是否误写成 App URL；问运维证书是否信任。 |
| daemon 起不来 | 看 `%USERPROFILE%\.multica\daemon.log`（Windows）或 `~/.multica/daemon.log`；确认至少一种 Agent CLI 在 PATH。 |
| 钉钉有回复但 Multica 没单 | 看回复是否本桥格式；是否有人起了第二台桥抢 Stream；桥那台 `multica issue create` 手工是否正常。 |
| 机器人链接跳到 multica.ai | 桥主机环境变量补 `MULTICA_APP_URL` 为内网 App；见 `README.md`。 |

---

## 7. 与 pm-system / 根仓库的关系

- **pm-system、PerformEval 等业务数据** 仍在各自系统；Multica 是 **派工与执行协作** 队列，不替代 PM 数据库。
- 代码与 Skill 真源仍在 **Git 仓库**；关单互链保持 **Git + WORK_LOG + Multica** 三角一致。

---

## 8. 修订记录

| 日期 | 变更 |
|------|------|
| 2026-04-21 | 初版。 |
