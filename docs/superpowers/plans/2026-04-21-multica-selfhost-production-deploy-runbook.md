# Multica 内网生产环境 — 部署 Runbook

> **For agentic workers:** 可按 checkbox 逐项执行；不涉及本仓库业务代码改动时无需 subagent 流水线。  
> **Goal:** 在内网交付一套 **团队共用的 Multica 自托管实例**（含 Postgres、前后端），并接通 **单实例钉钉派单桥**；成员 CLI 指向内网后可正常建单、认领、daemon 注册。

**Architecture:** 官方 `docker-compose.selfhost.yml` 三件套；可选反向代理终止 TLS；钉钉桥独立进程调用本机 `multica` CLI 写内网 API。

**Tech Stack:** Docker / Docker Compose、PostgreSQL 17（pgvector）、Multica 上游镜像与 compose 文件、内网 Linux 服务器（推荐）；派单桥为 Python + `dingtalk-stream`（见 `tools/multica-dingtalk-bridge/requirements.txt`）。

**设计依据:** `docs/superpowers/specs/2026-04-21-multica-selfhost-production-design.md`

---

## 前置阅读（5 分钟）

- 上游：[SELF_HOSTING.md](https://github.com/multica-ai/multica/blob/main/SELF_HOSTING.md)
- 上游进阶（反代、邮件、环境变量）：[SELF_HOSTING_ADVANCED.md](https://github.com/multica-ai/multica/blob/main/SELF_HOSTING_ADVANCED.md)
- 本仓派单桥：`tools/multica-dingtalk-bridge/README.md`

---

### Task 1: 环境与账号准备

**交付物:** 服务器可 SSH、有 Docker 与 Compose v2；内网 DNS 或 hosts 规划就绪。

- [ ] **Step 1:** 确认目标机 OS（推荐 Linux x86_64）与磁盘（DB 与镜像增长预留）。
- [ ] **Step 2:** 安装 Docker Engine 与 Docker Compose Plugin（版本满足上游要求）。
- [ ] **Step 3:** 规划三个信息（可先占位，Task 3 落定）：  
  - 前端 URL，例：`https://multica-app.corp.local`  
  - API URL，例：`https://multica-api.corp.local`  
  - 派单桥宿主机：固定一台（可与 Multica 同机或不同机）

---

### Task 2: 获取并启动 Multica 自托管栈

**交付物:** `docker compose ps` 全绿；本机 curl 可访问 `localhost:3000` 与 `localhost:8080`（或 compose 映射端口）。

- [ ] **Step 1:** 克隆官方仓库（版本以团队锁定 commit 为准，便于 reproducible）：  
  `git clone https://github.com/multica-ai/multica.git`  
  `cd multica`
- [ ] **Step 2:** 生成运行配置（二选一）：  
  - `make selfhost`（自动生成 `.env`、JWT 等并拉起），或  
  - 手动：`cp .env.example .env`，设置强随机 `JWT_SECRET`，再  
    `docker compose -f docker-compose.selfhost.yml up -d`
- [ ] **Step 3:** 阅读容器日志，确认 backend 迁移无报错、frontend/backend health 正常。

---

### Task 3: 反向代理与 TLS（生产推荐）

**交付物:** 浏览器通过 **HTTPS** 打开前端；CLI 配置使用 **HTTPS API**；WebSocket 升级头透传无 404/502。

- [ ] **Step 1:** 按 `SELF_HOSTING_ADVANCED.md` 配置 Nginx / Caddy / 企业网关：  
  - `app_url` 域名指向前端服务  
  - `server_url` 域名指向 API（含 WebSocket 路径规则）
- [ ] **Step 2:** 用内网 CA 或企业证书加载 TLS；**禁止**在无网络隔离下使用 `APP_ENV=development` + 万能码对公网暴露。
- [ ] **Step 3:** 从 **另一台内网客户端** 访问 Web，完成一次页面加载与登录页打开（先不必全员账号）。

---

### Task 4: 登录与首账号策略

**交付物:** 至少一名管理员可登录 Web；团队知悉验证码获取方式（邮件或受控 dev 模式）。

- [ ] **Step 1:** 选定认证方式（推荐生产：`RESEND_API_KEY` + 真实邮箱域；或组织规定的 SMTP/IdP，以官方 advanced 为准）。
- [ ] **Step 2:** 若短期纯内网 PoC 使用 `APP_ENV=development`：**书面确认**网段 ACL，仅内网可达。
- [ ] **Step 3:** 创建 **正式 Workspace** 命名规范（例：与仓库/中心名一致），创建默认 **Project**（如 `pm-system` 或 `MyAgents`），记录 **workspace_id**、**project_id**（UUID）。

---

### Task 5: 成员 CLI 与 daemon（抽样验收）

**交付物:** 在一台 **Windows 或 macOS** 样本机上，`multica auth status` 成功、`multica workspace list` 可见内网 workspace、Settings → Runtimes 可见本机。

- [ ] **Step 1:** 在样本机安装官方 `multica` CLI（Windows 见上游 `CLI_AND_DAEMON.md`）。
- [ ] **Step 2:** 执行：  
  `multica setup self-host --server-url <HTTPS-API> --app-url <HTTPS-App>`  
  完成浏览器登录。
- [ ] **Step 3:** 安装至少一种受支持 Agent CLI（如 `cursor-agent`），执行 `multica daemon start`，在 Web **Settings → Runtimes** 确认在线。
- [ ] **Step 4:** 手工 `multica issue create` 一条测试 Issue，Web 可见；然后关闭或取消以免污染。

---

### Task 6: 钉钉派单桥（生产单实例）

**交付物:** 仅 **一台** 主机长期运行 `dispatch_bot.py`；群内 `#派单` 可在内网 Multica 看到新 Issue；机器人回复链接指向 **内网** `MULTICA_APP_URL`。

- [ ] **Step 1:** 选定主机；确认该主机 **不会**与他人重复启动同一钉钉 Client ID 的桥。
- [ ] **Step 2:** Clone 本仓库 `MyAgents`（或最小化同步 `tools/multica-dingtalk-bridge/` + 依赖文件），创建 `.venv`，`pip install -r tools/multica-dingtalk-bridge/requirements.txt`。
- [ ] **Step 3:** 在该机配置 `multica` 为 **内网** `setup self-host`（与 Task 5 一致），`multica issue create` 手工成功。
- [ ] **Step 4:** 复制 `tools/multica-dingtalk-bridge/.env.example` 为 `.env`，填入 `DINGTALK_CLIENT_ID`、`DINGTALK_CLIENT_SECRET`；设置 `MULTICA_APP_URL=<HTTPS-App>`；可选 `MULTICA_PROJECT_ID=<正式项目UUID>`。
- [ ] **Step 5:** Windows 用 `run_bridge.ps1` 或计划任务/ nssm 守护；Linux 用 systemd 调用 `python dispatch_bot.py`。详见 `README.md`。
- [ ] **Step 6:** 钉钉侧发一条 `#派单` 测试，Web 验证；机器人回复中链接打开为内网。

---

### Task 7: 网络与安全基线

**交付物:** 防火墙策略文档化；仅必需端口暴露。

- [ ] **Step 1:** DB 端口 **不对**办公网全局开放，仅 Docker 网络或本机 loopback。
- [ ] **Step 2:** 前端/API 仅从内网访问；若需 VPN，写明接入条件。
- [ ] **Step 3:** 派单桥主机：出站需钉钉 Stream 相关域名（以钉钉文档为准）+ 内网 Multica API。

---

### Task 8: 备份与恢复试跑

**交付物:** 一次成功的 Postgres 逻辑备份与还原演练记录（日期、命令、耗时）。

- [ ] **Step 1:** 为 `postgres` 容器卷或 DB 实例配置定时 `pg_dump`（策略由 DBA 定）。
- [ ] **Step 2:** 在测试环境或维护窗口做一次 **restore 演练**（不写进生产同名 volume 除非已停机切换）。

---

### Task 9: 上线验收清单（Go/No-Go）

- [ ] Web HTTPS 打开无混合内容错误。
- [ ] 非部署机浏览器可登录并完成一次 Issue 状态变更。
- [ ] 样本机 daemon 在线，可被指派测试 Issue（可选）。
- [ ] 钉钉 `#派单` 创建 Issue 成功，链接指向内网。
- [ ] **未**发现第二台机器同时跑同一钉钉 Client ID 桥。
- [ ] 全员可见协作指南：`docs/superpowers/specs/2026-04-21-multica-internal-collaboration-guide.md`

---

### 回滚与降级

| 场景 | 动作 |
|------|------|
| 仅前端不可用 | 保留 DB；回滚反代或镜像 tag；公告维护窗口。 |
| API 损坏但数据完好 | 停写流量；从备份恢复 DB 或回滚 backend 镜像；再启服务。 |
| 钉钉桥故障 | **不要**多台盲目起桥；单机修进程或切到「仅 Web 建单」临时纪律。 |
| 内网整体不可用 | 队列 Owner 公告临时用 **Web 外其他渠道** 派工；恢复后补录 Issue（纪律见协作指南）。 |

---

### 升级（常规）

```bash
cd multica
git fetch
git checkout <tag-or-commit>
docker compose -f docker-compose.selfhost.yml pull
docker compose -f docker-compose.selfhost.yml up -d
```

升级前阅读上游 release notes；维护窗口内执行；升级后重复 Task 9 中关键项烟测。

---

## Self-Review（Runbook）

- [x] 覆盖：安装、TLS、认证、抽样 CLI、单桥、网络、备份、验收、回滚、升级。
- [x] 无「TBD 密钥」类占位；具体密钥由现场 `.env` 管理。
