# PmSystem 权限与机读主体设计规格（Spec）

- **状态**：草案（制作人确认「落盘」需求后首版；实现前可修订）
- **日期**：2026-04-22
- **范围**：`pm-system/` 后端认证与授权、**自动化任务**（甘特/进度表对接、管线同步、资源符合、风险预警等）、**LLM**（智能推送、诊断）的访问边界与演进路线
- **关联文档**：`pm-system/docs/planner-track-ai-design.md`（策划周计划与 AI 试点边界）
- **会话代号**：AgentPerm（便于验收与跨会话引用）

---

## 1. 背景与目标

### 1.1 业务目标（已对齐制作人表述）

| 维度 | 期望 |
|------|------|
| 人类使用 | **少数**核心用户：运营矩阵中长期规划、分配版本、管理策划周计划、管理需求池等 |
| 自动化 | 与现有**进度表/甘特**等对接；数据同步到**管线节点**；自动生成**资源符合**、**风险预警**等 |
| LLM | **智能推送**、**诊断**等；默认试点范围与 Planner 文档一致（制作人/PM 先试点） |

### 1.2 本 Spec 要解决的问题

在「人少、机多、模型可读」的前提下，定义：

1. **谁**能调用哪些 **API**（人类角色 vs 服务主体 vs LLM 调用链）。
2. **写操作**必须在服务端可校验、可审计，**不能**长期依赖「前端隐藏按钮 + 客户端默认放行」。
3. 与现有实现 **可渐进落地**，避免一次性大重构阻塞业务。

### 1.3 成功标准（权限视角）

- 任意 **mutating**（POST/PUT/PATCH/DELETE）接口在 **生产配置** 下均有明确主体身份与授权结论（允许/拒绝）。
- **自动化与 LLM** 使用独立凭证维度（不与「把脚本当 admin 用户」混用）；默认 **最小权限**。
- 关键误操作路径（删版本、不可逆管线推进、覆盖主数据等）具备 **可查询审计**（至少：主体、时间、资源标识、请求追踪 id）。

### 1.4 明确不做（本 Spec 范围外）

- 不定义具体甘特文件格式、ETL 调度器产品选型。
- 不定义 LLM 模型选型与 Prompt 工程细节（见 Planner AI 专项文档）。
- **不**承诺首版即上线「设置页全量动态 RBAC 配置」；若未来需要，作为独立阶段扩展，与本 Spec 的「机读 scope」层兼容即可。

---

## 2. 现状摘要（仓库事实，实现时以此为基线）

### 2.1 后端

- **认证**：`get_current_user` 支持 `dev_mode`、Debug 下占位 token、loopback 特例、`X-Api-Key`（与 `service_api_key` 匹配时注入 **service 用户**）、正常 JWT 等（`pm-system/backend/app/routers/auth.py`）。
- **用户模型**：`users.role` 为单列字符串（如 `admin` / `pmo` / `user`），见 `pm-system/backend/app/models/user.py`。
- **RBAC 占位**：`main.py` 尝试加载 `permissions` 路由与 `Role`/`Permission` 模型；当前目录中 **不存在**对应路由/模型文件时走降级分支，运行时等价于 **无表结构级 RBAC**。

### 2.2 前端

- UI 已广泛依赖 `ApiClient.hasPermission(...)`、`hasVersionPermission` 等；`api-client.js` 在 **无后端权限模块** 时为 **兼容 shim：默认一律放行**。
- 设置中存在权限/角色相关 UI 壳；后端 404 时接口返回空结构，避免页面崩溃。

### 2.3 差距（本 Spec 要收敛的）

- **授权**未与 **服务端写路径** 系统性绑定；生产若关闭 `dev_mode`，仍可能存在「已认证但无细粒度约束」的灰区。
- **自动化与 LLM** 若长期共用「高权限用户」或宽松 dev 策略，会放大事故面。

---

## 3. 设计原则

1. **服务端为准**：所有写操作以服务端校验为最终裁决；前端权限仅改善体验。
2. **主体分轨**：**人类**、**自动化服务**、**LLM 调用链** 分轨建模，禁止用同一套「模拟人类 admin」糊弄机读场景。
3. **默认收紧**：生产环境 **禁止** 依赖「无 token / 占位 token / 过宽 loopback」完成写操作；与 `planner-track-ai-design` 中「不扩大暴露面」一致。
4. **YAGNI**：人类角色保持 **少量档位**；细粒度能力字符串可与前端对齐，但 **存储与配置** 可阶段性「代码表 + DB 扩展」而非一步到位动态 UI。
5. **可观测**：每次授权失败与关键写成功均应能关联到 **主体类型 + 主体标识 + 追踪 id**。

---

## 4. 主体模型（三类）

```text
┌─────────────┐     JWT / 密码登录      ┌──────────────────┐
│  HumanUser  │ ───────────────────────>│  HumanAuthz      │
│  (users 表) │                         │  role + extras   │
└─────────────┘                         └──────────────────┘

┌─────────────┐     X-Api-Key 或 m2m    ┌──────────────────┐
│  ServiceJob │ ───────────────────────>│  ServiceScope    │
│  (无自然人)  │                         │  资源类 × 动作    │
└─────────────┘                         └──────────────────┘

┌─────────────┐     内部网关签发        ┌──────────────────┐
│  LLMWorker  │ ───────────────────────>│  LLMPolicy        │
│  (编排器)   │                         │  只读为主 + 窄写  │
└─────────────┘                         └──────────────────┘
```

### 4.1 HumanUser（人类）

- 认证保持现有 JWT 路径；`dev_mode` 仅用于本地开发，**生产关闭**。
- 授权首版推荐：**3～4 个角色档位** 即可（示例命名，实现时可对齐现有 `role` 枚举）：
  - `admin`：系统配置、用户管理、危险写操作。
  - `pmo`：版本/发布/运营矩阵/需求池/策划周计划等 **PM 域** 主路径。
  - `planner` 或 `contributor`（可选）：周计划与需求池 **编辑**，但限制删除类/全局配置类接口。
  - `viewer`：**只读**（聚合报表、只读导出）。
- **关键写路径**（删除版本、不可逆节点、批量覆盖）在角色之上可增加 **显式策略**（例如仅 `admin+pmo` 或二次确认头；具体列表在实现计划的「路由清单」中列全）。

### 4.2 ServiceJob（自动化）

- 凭证：`X-Api-Key` 或未来 **m2m JWT**（claims 含 `sub=service:<name>`）。
- **不得**默认等价于 `admin` 用户；应使用独立 **service 用户行** 或 **不落 users 表、仅在 auth 层解析的 subject**（二选一，实现阶段定稿；须统一审计字段写法）。
- 授权模型：**Scope 列表**，例如：
  - `read:versions`、`read:features`、`read:planner-items`
  - `write:pipeline-node`（限定为「由同步规则允许的转换」）
  - `write:alerts`（仅写入预警/通知队列表，不写业务主表）
- **甘特/进度表 → 管线节点**：写入范围应绑定到 **允许的实体类型 + 幂等键**（避免一次同步扫全库乱写）。

### 4.3 LLMWorker（大模型编排）

- 默认策略：**强只读** 于业务主表；允许读取 **聚合 API**（周汇总、风险信号输入等）。
- **窄写**：仅允许写入 **派生物**（简报草稿、诊断记录、钉钉推送队列表），与 `planner-track-ai-design` 中「第一版日报不纳入上下文」等决策兼容。
- 若未来存在「模型直接提议修改主数据」：**必须**人机闸门——先落「建议」表，再由具备 `HumanAuthz` 的用户 **显式确认 API** 合并。

---

## 5. 与现有 `get_current_user` 的并存规则

| 入口 | 用途 | 生产约束 |
|------|------|----------|
| Bearer JWT | 人类浏览器 / 官方客户端 | 唯一通用人类写路径 |
| `X-Api-Key` | 内部脚本、同步任务 | 必须配置 **独立 key**；映射到 `ServiceScope`，禁止宽放行 |
| `dev_mode` / 占位 token / debug loopback | 本地开发 | **生产环境关闭**；部署检查纳入清单 |

**迁移注意**：在逐步关掉「默认可写」的过程中，需同步替换所有依赖「无权限 shim」的集成测试与内网脚本，改为使用带 scope 的 service key。

---

## 6. 前端 `ApiClient` 与后端一致性

- 后端落地授权后：`hasPermission` / `hasVersionPermission` 应改为 **以服务端返回的权限集合或 403 为准**（登录后拉取一次 + 变更时刷新），**禁止**生产环境长期 `return true`。
- `data-permission` 与按钮显隐继续保留，作为 UX；**禁止**作为唯一安全层。

---

## 7. API 分层建议（便于机读与 LLM）

| 层级 | 说明 | 人类 | Service | LLM |
|------|------|:----:|:-------:|:---:|
| L0 主数据写 | Feature/版本/矩阵单元格等 | 按角色 | 按窄 scope | 默认禁止 |
| L1 管线推进写 | 节点状态迁移 | 按角色 | 仅同步任务 scope | 默认禁止 |
| L2 聚合只读 | 周汇总、风险输入视图 | 按角色 | 允许读 scope | 允许读 scope |
| L3 派生物写 | 简报、告警队列、诊断记录 | 按角色 | 允许 alerts scope | 允许窄写 |

**版本级权限**：`hasVersionPermission` 的语义保持为「在某版本上下文下的附加约束」（例如 PLD/制作人）；实现时应在 **L0/L1** 接口上同时校验 **全局角色 + 版本级策略**。

---

## 8. 审计与观测

- **最低字段**：`actor_type`（human|service|llm）、`actor_id`（username 或 service 名或 llm run id）、`route`、`resource_id`（若有）、`timestamp`、`result`（allow/deny）、`trace_id`（可与网关/request id 对齐）。
- **拒绝日志**：生产应记录 **拒绝原因枚举**（便于排障，避免泄露敏感 token）。

---

## 9. 分阶段落地（建议）

| 阶段 | 内容 | 验收要点 |
|------|------|----------|
| Phase 0 | 梳理所有 mutating 路由清单；标注「人类 / 可服务 / 禁 LLM」 | 清单无遗漏大类模块 |
| Phase 1 | 人类角色硬编码或轻量表驱动 + 关键路径服务端校验；生产关闭宽松 dev | 未授权 JWT 无法写；回归通过 |
| Phase 2 | `X-Api-Key` → `ServiceScope`；甘特/同步任务专用 key | 换 key 可立刻停同步；scope 越界 403 |
| Phase 3 | LLM 只读聚合 + 派生物写表 + 可选「确认合并」API | 与 Planner AI 试点范围一致 |

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 关 shim 导致内网脚本全挂 | Phase 2 先发 **scoped service key** 与迁移说明；并行窗口期 |
| 人类角色过粗 | 用「关键写路径白名单」补细；不急于上动态 RBAC UI |
| LLM 提示注入诱导写接口 | LLM 侧仅用 **受限客户端**；网络层禁止 LLM 直连 L0 |

---

## 11. 开放问题（实现计划前需拍板）

1. **Service 主体**是否落 `users` 表：若落表，需约定 `username` 命名空间与密码字段占位策略；若不落表，审计与 ORM 外键如何统一。
2. **版本级策略**的数据来源：配置表、JSON 字段还是代码常量首版。
3. **与钉钉/外部推送**的回调入口是否走同一 `ServiceScope` 体系（建议：是）。

---

## 12. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-22 | AgentPerm 首版：人类/服务/LLM 分轨、与现状差距、分阶段落地 |
| 2026-04-22 | AgentPerm：附录 A「影响面清单」、附录 B「验收清单（Agent 测试用例）」 |

---

## 附录 A：影响面清单（按现有代码模块）

> 说明：**类型** 与正文 §9 阶段对应——实现权限收紧时，优先处理 **C 类**，再在 **B 类** 上加授权粒度；**A/D** 为横切。**路径** 相对于 `pm-system/backend/`（前端相对于 `pm-system/`）。

### A.1 类型图例

| 类型 | 含义 |
|------|------|
| **A** | 横切：统一鉴权依赖、角色/scope 判定、（可选）审计、配置开关（`dev_mode` 等）。 |
| **B** | 已挂 `Depends(get_current_user)` 的写路径：以**增加授权判定**为主，业务逻辑尽量不动。 |
| **C** | 写接口使用 `get_current_user_optional` 或**无** Depends：**收口优先级最高**（或明确标注为仅内网 + `X-Api-Key` + scope）。 |
| **D** | 前端：`api-client.js` 权限 shim、设置页、`data-permission` 与真实后端对齐。 |

### A.2 后端 — B 类（已有强制登录，以加授权为主）

| 模块 | 文件 | 典型 HTTP 写操作 |
|------|------|------------------|
| 版本 / Feature / 任务 / 团队 / 里程碑 / 成员 | `app/routers/versions.py`, `features.py`, `tasks.py`, `teams.py`, `milestones.py`, `members.py` | CRUD |
| 配置 | `app/routers/config.py` | `PUT /api/config/{key}`（GET 中日历键等可保留 optional 策略） |
| 发布计划 | `app/routers/published_plans.py` | POST/PUT/DELETE |
| 策划周计划 | `app/routers/planner.py` | items CRUD、import、clear-all 等 |
| 数据交换 | `app/routers/data_exchange.py` | 含 `POST .../tasks/estimation/import`；实现前须核对是否仍存在「为测试去掉 auth」的分支 |
| 认证 | `app/routers/auth.py` | register/login/logout；可扩展返回权限集或解析 service |
| 看板 | `app/routers/dashboard.py` | 当前以 GET 为主；若后续增加写接口归入同类 |
| 内部 digest（部分） | `app/routers/internal_digest.py` | `GET .../version-checklist-blocks` 已强制登录；可按角色或 key 收紧 |

### A.3 后端 — C 类（optional 或无鉴权的写路径，优先收口）

| 模块 | 文件 / 位置 | 说明 |
|------|-------------|------|
| 需求池 | `app/routers/pools.py` | 池与条目 CRUD、`POST .../import/all` 等均为 `get_current_user_optional` |
| 设计到落地 | `app/routers/design_landing.py` | 多处 PATCH/POST 为 optional |
| 设计评审 | `app/routers/design_reviews.py` | POST/PUT/DELETE 为 optional |
| 池子晋升 | `app/routers/pool_promotions.py` | POST 等为 optional |
| 需求池看板 | `app/routers/pool_dashboard.py` | 以读为主；若有写须同样收口 |
| 主存盘 | `main.py` | `POST /api/data`：整包写 SQLite + JSON，**无** `Depends(get_current_user)` |
| 备份恢复 | `main.py` | `POST /api/backups/restore/{backup_name}` **无**登录依赖 |
| KV | `main.py` | `POST /api/storage/{key}` **无**登录依赖 |
| 钉钉代理 | `main.py` | `POST /api/dingtalk/send` **无**鉴权（另有 `app/routers/dingtalk.py`，以实际挂载为准） |
| 制作人中控台 | `app/routers/producer_tower.py`、`main.py` 中 `POST /api/producer-tower/clear-tr-imports` | 待办 CRUD、TR 导入等**无** Depends |
| Boss / UE 预审 | `main.py` | 多条 `PUT`/`POST`/`DELETE` 创建与保存**无**强制登录（部分 `mine`/submit 使用 optional） |

### A.4 后端 — 只读或低风险（通常晚于 C 类收口）

| 模块 | 路径或说明 |
|------|------------|
| 只读 API | `GET /api/data`, `/api/data/meta`, `/api/pm-calendar`, `/api/health`, `/api/version` 等；若外网暴露可再加可选鉴权或限流 |
| 历史文件 | `app/routers/data.py`（`POST /api/data` 等）当前 **未** `include_router`；若将来启用须纳入同一套权限 |

### A.5 启动与占位

| 位置 | 说明 |
|------|------|
| `main.py` | `HAS_RBAC`、`permissions` 路由占位；落地 RBAC 或 scope 表时调整注册与初始化 |
| `app/models/user.py` 或新表 | 扩展 `role` 或新增 service / scope 存储（取决于正文 §11 拍板） |
| 可选 `app/init_rbac.py` 等 | 从占位到实装时新增或调整 |

### A.6 前端 — D 类

| 区域 | 路径 | 说明 |
|------|------|------|
| API 客户端 | `api-client.js` | `hasPermission`、`loadUserPermissions`、`applyPermissionVisibility` 等须与后端一致；禁止生产长期恒 `true` |
| 壳与开发开关 | `index.html` | 设置「权限/角色」子页、`data-permission`、dev 角色切换与真实策略对齐 |
| 运营视图 | `ui/components/operations-view.js`（及同路径副本若存在） | 大量 `hasPermission('...')`：数据源改为后端即可 |
| 版本管理 | `business/version-manager.js` 等 | `hasVersionPermission` 与后端版本级策略对齐 |

### A.7 自动化 / LLM（当前代码未必已有，属扩展面）

| 方向 | 说明 |
|------|------|
| 只读聚合 API | 供甘特、LLM 上下文；新路由或扩展现有 `internal_*` |
| 派生物写入 | 简报、告警队列：新表 + 新路由 + **独立 scope** |
| 甘特到管线 | 可能落在 `data_exchange` 或新 sync 路由；与 L0/L1 及 service scope 一并设计 |

### A.8 建议落地顺序（与修改面一致）

1. `main.py` 中无鉴权写接口：`/api/data`、backups restore、storage、dingtalk、producer-tower、预审写。  
2. `pools` / `design_landing` / `design_reviews` / `pool_promotions`：optional 改为强制 + 角色（或 key + scope）。  
3. 已在 B 类的 CRUD 路由上叠加细粒度或角色矩阵。  
4. 前端 `ApiClient` 与设置页。  
5. 自动化与 LLM 专用路由及 scope。

---

## 附录 B：验收清单（供 Agent 编写测试用例）

> **目标**：权限相关改动合并前，可由 Agent 在 `pm-system/backend/tests/` 下补充 **pytest** 用例（推荐 `test_permissions_security.py` 或与模块拆分的多文件），与现有 `test_planner_api.py` 风格一致：**FastAPI TestClient** + 必要时 **独立 SQLite/配置覆盖**。  
> **环境约定**（实现 fixtures 时遵循）：  
> - 子集测试使用 **`DEV_MODE=0`**、**`DEBUG=0`**、`ACCEPT_DEV_BROWSER_TOKEN=0`（或等价配置），避免 loopback/占位 token 误判为已授权。  
> - 提供 **匿名客户端**、**带 JWT 的各角色客户端**、**带合法/非法 `X-Api-Key` 的客户端**（与 `service_api_key` 配置对齐）。  
> - 若现有工程无 `conftest.py`，由实现 Agent **新增** `tests/conftest.py` 集中定义上述 fixtures，避免每个文件重复造轮子。

### B.1 清单表（Agent 逐条实现为 `test_*` 或参数化用例）

| ID | 优先级 | 类型 | 验收描述 | 期望 HTTP / 行为 | 备注 |
|----|--------|------|----------|------------------|------|
| AC-P0-01 | P0 | C | 匿名 `POST /api/data`（合法最小 body 或空对象，按实现定） | **401**（或 **403**，项目统一一种语义后写死断言） | 须不破坏现有 `baseRevision` 等业务错误码约定 |
| AC-P0-02 | P0 | C | 匿名 `POST /api/backups/restore/{name}` | **401/403** | 使用不存在的 backup 名时仍应先被鉴权拦截 |
| AC-P0-03 | P0 | C | 匿名 `POST /api/storage/{任意 key}` | **401/403** | |
| AC-P0-04 | P0 | C | 匿名 `POST /api/dingtalk/send`（最小非法体即可） | **401/403** | 若产品决定「仅内网 IP 白名单」则改为双断言：匿名 + 非白名单 |
| AC-P0-05 | P0 | C | 匿名 `POST /api/producer-tower/items` | **401/403** | |
| AC-P0-06 | P0 | C | 匿名 `POST /api/producer-tower/clear-tr-imports` | **401/403** | |
| AC-P0-07 | P0 | C | 匿名 `POST /api/boss-precheck` / `PUT /api/boss-precheck/{name}` / `DELETE`（择一代表写） | **401/403** | 可与 UE 预审择一套参数化 |
| AC-P0-08 | P0 | C | 匿名 `POST /api/ue-precheck` 或等价写路径 | **401/403** | |
| AC-P0-09 | P0 | C | 匿名 `POST /api/pools`（或创建池的最小 POST） | **401/403** | 收口 optional 后生效 |
| AC-P0-10 | P0 | C | 匿名 `PATCH` design_landing 任一路径（最小合法 id，可为 404 但须先过鉴权） | **401/403** | id 不存在时 **不得** 在鉴权前返回 404 |
| AC-P1-01 | P1 | B | `viewer` JWT `DELETE /api/versions/{id}`（存在版本） | **403** | 角色矩阵落地后启用 |
| AC-P1-02 | P1 | B | `pmo` JWT `DELETE /api/versions/{id}` | **204** 或业务约定成功码 | 正向用例 |
| AC-P1-03 | P1 | B | `viewer` JWT `POST /api/planner/items` | **403** | |
| AC-P1-04 | P1 | B | `planner` JWT `POST /api/planner/items` | **200** | 正向 |
| AC-P1-05 | P1 | Service | 无 header 匿名访问仅允许 **L2** 聚合只读接口之一（实现后点名路径） | **401** | |
| AC-P1-06 | P1 | Service | 合法 `X-Api-Key` 访问只读聚合 | **200** | 与 `service_api_key` 一致 |
| AC-P1-07 | P1 | Service | 合法 `X-Api-Key` 调用 **无** `write:pipeline-node` scope 的管线写接口 | **403** | Phase 2 起启用 |
| AC-P1-08 | P1 | Service | 错误 `X-Api-Key` 调用任意写接口 | **401** | |
| AC-P2-01 | P2 | A | `GET /api/health` 在匿名下仍可 **200**（运维探活） | **200** | 不改变现有 health 行为 |
| AC-P2-02 | P2 | D | （可选）前端 E2E 或契约测试：`/api/permissions/me` 或等价接口返回的权限集与 `hasPermission` 一致 | 按实现 | 若暂无该 API 则本项推迟到 ApiClient 改造完成 |
| AC-P2-03 | P2 | A | 审计：关键写成功或拒绝时日志/结构化字段含 `actor_type`（若已实现） | 快照或 caplog 断言 | 与 §8 对齐时启用 |

### B.2 实现注意事项（写给 Agent）

1. **与现有测试共存**：当前 `test_planner_api.py` 可能在 `dev_mode` 下依赖无鉴权；权限用例须使用 **独立 fixture** 或 `pytest.mark` 分组，避免一次性破坏全量 CI。必要时用 `pytest.ini` 的 `markers` 区分 `permissions` 与默认套件。  
2. **401 vs 403**：在代码中统一约定（未登录 401、已登录无权限 403）后，上表「401/403」列改为精确状态码。  
3. **数据隔离**：版本删除等破坏性用例使用 **临时 id** 或事务回滚，禁止依赖生产数据路径。  
4. **子模块**：若 `pm-system` 为 git submodule，测试文件仍提交在子模块内；父仓只更新指针。

### B.3 合并门禁建议

- PR  labeled 权限/安全：至少 **AC-P0-01～P0-10** 全绿方可合并（在对应功能已实现的 PR 上）。  
- Phase 2 合并时：**AC-P1-05～P1-08** 纳入 CI 必跑。

---

**文档结束**
