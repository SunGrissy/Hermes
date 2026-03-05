# Bridge 对接规范文档

> 智能管理工具体系 × Ultra 对接技术方案
> 创建日期：2026-03-05
> 状态：草案，待双方确认

---

## 一、背景与目标

### 1.1 双方系统概述

**我方（智能管理工具体系）** 包含多个独立运行的内部管理系统：

| 系统 | 用途 | 技术栈 | 端口 |
|------|------|--------|------|
| **PmSystem** | 游戏研发项目管理（版本/Feature/任务/团队/里程碑） | FastAPI + SQLAlchemy + 原生 JS | 待定 |
| **PerformEval** | 乘法绩效评价（公式/标尺/评价工作台） | FastAPI + SQLite + 原生 JS | 8112 |
| **Palace** | AI 多角色审查引擎（PLD/PLE/PLT 并行审查） | Python + asyncio + LLM API | 待定 |
| **TaskReminder** | 任务提醒 | FastAPI + 钉钉 Webhook | 8000 |

**Ultra 方** 是一个面向钉钉的智能助手（类 OpenClaw），具备自然语言理解和对话能力，运行在钉钉生态中。

### 1.2 对接目标

1. 用户在钉钉通过与 Ultra 对话，即可操作我方管理系统（查数据、建版本、提审查等）
2. 我方系统产生的事件（里程碑预警、审查结果等）可通过 Ultra 自动推送到钉钉
3. **纯调用关系**——Ultra 不修改我方系统逻辑，我方不侵入 Ultra 的意图理解

### 1.3 设计原则

- **单一入口**：Ultra 只与 Bridge 通信，不直连各子系统
- **职责分离**：Ultra 管"理解人"和"通知人"，Bridge 管"办事"和"记录"
- **渐进接入**：先跑通 PmSystem 管线管理，再扩展其他系统

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          钉钉（用户侧）                              │
│  用户 @Ultra → Ultra 理解意图 → 调 Bridge API → 结果回传钉钉         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                        ┌──────▼──────┐
                        │    Ultra    │  意图理解 + 投递编排
                        │  （Ultra 方）│  "理解人、找人"
                        └──────┬──────┘
                               │ HTTPS REST
                        ┌──────▼──────┐
                        │   Bridge    │  鉴权 + 业务编排 + 日志
                        │  （我方）    │  "办事、记录"
                        │  端口 8900  │
                        └──────┬──────┘
                               │ 内部 HTTP（localhost）
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
       PmSystem          PerformEval          Palace
       版本/任务            绩效/组织           AI 审查
```

### 2.1 三层编排模型

| 层次 | 归属 | 职责 | 举例 |
|------|------|------|------|
| **意图编排** | Ultra | 自然语言 → 拆解为 Bridge API 调用序列 | "帮我建个春节版本" → 调 `pm.create_version` |
| **业务编排** | Bridge | 一个 API 调用内部 → 多个子系统操作 + 校验 + 日志 + 事件 | `create_version` → 调 PmSystem + 写日志 + 发事件 |
| **投递编排** | Ultra | 收到 Bridge 事件 → 决定通知谁、用什么形式 | 收到 `version.created` → 推送到项目钉钉群 |

### 2.2 三种通信流向

```
流向 A：人工触发（同步请求-响应）
  钉钉用户 → Ultra → Bridge → 子系统 → Bridge → Ultra → 钉钉用户

流向 B：系统事件推送（异步回调）
  子系统事件 → Bridge 事件总线 → Ultra 回调端点 → 钉钉推送

流向 C：纯 Web 操作（不经过 Bridge/Ultra）
  用户直接访问 PmSystem/PerformEval 网页 → 与 Ultra 无关
```

---

## 三、鉴权与通信协议

### 3.1 认证方式

```
请求头: X-Bridge-Key: <双方约定的 API 密钥>
```

Bridge 中间件校验每个请求的 API Key。后续可升级为 JWT 或 OAuth。

### 3.2 操作者标识

Ultra 在每个请求中传入操作者信息，用于审计日志和权限校验：

```
请求头: X-Operator-Id: <钉钉 UID>
请求头: X-Operator-Name: <姓名>
```

### 3.3 统一响应格式

**成功：**
```json
{
  "code": 0,
  "data": { ... },
  "message": "ok"
}
```

**失败：**
```json
{
  "code": 40001,
  "data": null,
  "message": "版本名称已存在"
}
```

**错误码规划：**

| 范围 | 含义 |
|------|------|
| 0 | 成功 |
| 400xx | 请求参数错误 |
| 401xx | 认证/权限错误 |
| 404xx | 资源不存在 |
| 500xx | 内部服务错误（子系统不可用等） |

### 3.4 异步任务协议

对于耗时操作（如 Palace AI 审查），采用异步模式：

**提交任务：**
```
POST /bridge/palace/review
→ 202 Accepted
{
  "code": 0,
  "data": {
    "task_id": "review-20260305-001",
    "status": "processing",
    "estimated_seconds": 30
  }
}
```

**结果通知（二选一，待确认）：**

- **方案 A：回调**——Bridge 完成后 POST 到 Ultra 提供的 `callback_url`
- **方案 B：轮询**——Ultra 定时 GET `/bridge/palace/review/{task_id}`

---

## 四、能力发现接口

### 4.1 GET /bridge/capabilities

Ultra 通过此接口发现 Bridge 当前支持的所有能力，可直接用于 LLM Function Calling。

**响应结构：**

```json
{
  "code": 0,
  "data": {
    "bridge_version": "0.1.0",
    "capabilities": [
      {
        "id": "pm.list_versions",
        "name": "查询版本列表",
        "description": "获取项目管理系统中的所有版本，支持按阶段筛选",
        "endpoint": "GET /bridge/pm/versions",
        "parameters": {
          "phase": {
            "type": "string",
            "required": false,
            "enum": ["planning", "estimation", "execution"],
            "description": "按阶段筛选"
          }
        },
        "async": false,
        "permission": "read"
      },
      {
        "id": "pm.create_version",
        "name": "创建版本",
        "description": "在项目管理系统中创建新版本，可选择里程碑模板自动生成里程碑",
        "endpoint": "POST /bridge/pm/versions",
        "parameters": {
          "name": {
            "type": "string",
            "required": true,
            "description": "版本名称，如 v2.5.0 春节版本"
          },
          "version_type": {
            "type": "string",
            "required": true,
            "enum": ["major_expansion", "monthly_event", "minor_update", "hotfix"],
            "description": "版本类型：大版本/月度活动/小更新/热修复"
          },
          "release_date": {
            "type": "string",
            "required": true,
            "format": "date",
            "description": "目标发布日期 YYYY-MM-DD"
          },
          "capacity": {
            "type": "number",
            "required": false,
            "default": 800,
            "description": "可用团队工时容量（小时）"
          },
          "milestone_template": {
            "type": "string",
            "required": false,
            "enum": ["standard_30d", "fast_10d", "custom"],
            "default": "standard_30d",
            "description": "里程碑模板"
          }
        },
        "async": false,
        "permission": "write"
      }
    ],
    "events": [
      {
        "type": "version.created",
        "description": "新版本创建成功",
        "payload_example": {
          "version_id": "v1234567890",
          "name": "v2.5.0 春节版本",
          "created_by": "张三"
        }
      }
    ]
  }
}
```

此结构兼容 OpenAI Function Calling 的 JSON Schema 风格，Ultra 可直接解析为工具定义。

### 4.2 GET /bridge/health

```json
{
  "code": 0,
  "data": {
    "bridge": "ok",
    "subsystems": {
      "pm_system": {"status": "ok", "version": "1.0.0", "url": "http://localhost:80xx"},
      "perform_eval": {"status": "ok", "version": "1.0.0", "url": "http://localhost:8112"},
      "palace": {"status": "unavailable", "reason": "not deployed"}
    },
    "uptime_seconds": 86400
  }
}
```

---

## 五、MVP 接口契约（PmSystem 管线管理）

首期只对接 PmSystem，跑通管线管理的智能化工作流。

### 5.1 版本管理

#### GET /bridge/pm/versions

查询版本列表。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| phase | query | string | 否 | 按阶段筛选：planning / estimation / execution |

**响应 data：**
```json
[
  {
    "id": "v1234567890",
    "name": "v2.5.0 春节版本",
    "version_type": "major_expansion",
    "release_date": "2026-02-01",
    "phase": "planning",
    "feature_count": 5,
    "total_estimate": 320,
    "capacity": 800,
    "capacity_usage_pct": 40.0,
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

#### GET /bridge/pm/versions/{version_id}

查询版本详情，含 Feature 概览、里程碑、容量。

**响应 data：**
```json
{
  "id": "v1234567890",
  "name": "v2.5.0 春节版本",
  "version_type": "major_expansion",
  "release_date": "2026-02-01",
  "phase": "planning",
  "capacity": 800,
  "pipeline_weight": "slow",
  "pld_user": {"id": "u001", "name": "崔忠仁"},
  "ple_user": {"id": "u002", "name": "某体验"},
  "plt_user": {"id": "u003", "name": "某客户端"},
  "features": [
    {
      "id": "f001",
      "name": "新英雄-雷恩",
      "assignee": "张三",
      "stage": "design",
      "priority": "P0",
      "strategic_value": 8,
      "estimate": 40
    }
  ],
  "milestones": [
    {
      "name": "Feature Freeze",
      "date": "2026-01-02",
      "status": "pending"
    }
  ],
  "capacity_summary": {
    "total": 800,
    "allocated": 320,
    "remaining": 480,
    "usage_pct": 40.0,
    "alert_level": "normal"
  }
}
```

#### POST /bridge/pm/versions

创建版本。

**请求体：**
```json
{
  "name": "v2.6.0 五一版本",
  "version_type": "major_expansion",
  "release_date": "2026-05-01",
  "capacity": 800,
  "milestone_template": "standard_30d"
}
```

**响应 data：**
```json
{
  "id": "v_new_001",
  "name": "v2.6.0 五一版本",
  "milestones_generated": 6,
  "message": "版本创建成功，已生成 6 个里程碑"
}
```

### 5.2 Feature 管理

#### GET /bridge/pm/features

按条件查询 Feature。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| version_id | query | string | 否 | 按版本筛选 |
| stage | query | string | 否 | 按阶段筛选：pending/design/dev/qa/done/blocked |
| priority | query | string | 否 | 按优先级筛选：P0/P1/P2 |
| assignee | query | string | 否 | 按负责人筛选 |

**响应 data：**
```json
[
  {
    "id": "f001",
    "version_id": "v1234567890",
    "version_name": "v2.5.0 春节版本",
    "name": "新英雄-雷恩",
    "assignee": "张三",
    "stage": "design",
    "priority": "P0",
    "strategic_value": 8,
    "estimate": 40,
    "effective_points": 320,
    "content_tier": "S",
    "task_count": 3,
    "actual_hours": 0,
    "dor_status": {
      "content_ready": false,
      "experience_ready": false,
      "tech_ready": false
    }
  }
]
```

#### GET /bridge/pm/features/{feature_id}

Feature 详情，含完整任务列表和 DoR 状态。

#### POST /bridge/pm/features

创建 Feature。

**请求体：**
```json
{
  "version_id": "v1234567890",
  "name": "春节限时礼包",
  "assignee": "刘泊霆",
  "priority": "P1",
  "strategic_value": 6,
  "estimate": 20,
  "description": "面向付费用户的限时7天礼包",
  "content_tier": "A"
}
```

#### PATCH /bridge/pm/features/{feature_id}/status

更新 Feature 状态。

**请求体：**
```json
{
  "stage": "dev",
  "note": "设计评审通过，进入开发"
}
```

### 5.3 仪表盘

#### GET /bridge/pm/dashboard

版本仪表盘摘要，适合快速了解全局状态。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| version_id | query | string | 否 | 指定版本，不传则返回所有活跃版本 |

**响应 data：**
```json
{
  "active_versions": [
    {
      "id": "v1234567890",
      "name": "v2.5.0 春节版本",
      "phase": "execution",
      "release_date": "2026-02-01",
      "days_remaining": 15,
      "feature_summary": {
        "total": 10,
        "done": 3,
        "in_progress": 5,
        "blocked": 1,
        "not_started": 1
      },
      "capacity_summary": {
        "usage_pct": 85.0,
        "alert_level": "warning"
      },
      "risks": [
        "P0 Feature '新英雄-雷恩' 处于 blocked 状态",
        "容量使用率 85%，接近超载"
      ],
      "next_milestone": {
        "name": "Code Complete",
        "date": "2026-01-22",
        "days_until": 3
      }
    }
  ]
}
```

---

## 六、事件系统（Bridge → Ultra 推送）

### 6.1 事件注册

Ultra 向 Bridge 注册事件接收端点：

```
POST /bridge/events/subscribe
{
  "callback_url": "https://ultra.example.com/bridge-events",
  "events": ["version.*", "feature.*", "patrol.*"],
  "secret": "<用于签名验证>"
}
```

### 6.2 事件推送格式

Bridge 向 Ultra 的 callback_url 发送 POST 请求：

```json
{
  "event_type": "feature.status_changed",
  "event_id": "evt-20260305-001",
  "timestamp": "2026-03-05T10:30:00Z",
  "source": "pm_system",
  "payload": {
    "feature_id": "f001",
    "feature_name": "新英雄-雷恩",
    "version_name": "v2.5.0 春节版本",
    "old_stage": "design",
    "new_stage": "dev",
    "operator": "张三"
  }
}
```

请求头包含签名用于校验：
```
X-Bridge-Signature: sha256=<HMAC(secret, body)>
```

### 6.3 MVP 事件清单

| 事件类型 | 触发条件 | 典型用途 |
|---------|---------|---------|
| `version.created` | 新版本创建 | 通知项目组 |
| `version.phase_changed` | 版本阶段切换 | 通知管线角色 |
| `version.milestone_approaching` | 里程碑到期前 N 天（可配置） | 提前预警 |
| `feature.created` | 新 Feature 创建 | 通知相关人员 |
| `feature.status_changed` | Feature 状态变更 | 同步进度 |
| `feature.blocked` | Feature 进入 blocked 状态 | 紧急预警 |
| `feature.dor_passed` | DoR 检查全部通过 | 通知可以开工 |
| `patrol.daily_summary` | 每日定时（时间可配置） | 日报推送 |

### 6.4 谁决定推送给谁

**Bridge 只描述"发生了什么"，不决定"通知谁"。**

推送目标的映射关系由 Ultra 侧维护。例如：
- `version.*` 事件 → 推送到项目核心群
- `feature.blocked` 事件 → 推送给 Feature 负责人 + PLD
- `patrol.daily_summary` → 推送给制作人

Bridge 在事件 payload 中提供足够的上下文（负责人、版本、角色等），Ultra 据此决定投递目标。

---

## 七、操作日志

Bridge 记录所有经由其处理的操作，用于审计追溯。

### 7.1 日志结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 自增主键 |
| timestamp | datetime | 操作时间 |
| source | string | 来源：`ultra` / `scheduled` / `web`（预留） |
| operator_id | string | 操作者钉钉 UID |
| operator_name | string | 操作者姓名 |
| capability_id | string | 调用的能力 ID，如 `pm.create_version` |
| request_summary | json | 请求关键参数（脱敏） |
| response_code | int | Bridge 响应码 |
| response_summary | string | 结果摘要 |
| duration_ms | int | 处理耗时 |
| target_system | string | 目标子系统：`pm` / `palace` / `eval` |

### 7.2 日志查询接口（可选，供管理后台）

```
GET /bridge/logs?start=2026-03-01&end=2026-03-05&operator_id=xxx
```

---

## 八、后续扩展路径（非 MVP，架构预留）

### 8.1 Palace AI 审查对接

文档预审场景：用户通过钉钉提交文档 → Ultra 转发给 Bridge → Bridge 调用 Palace 引擎做 PLD/PLE/PLT 多角色并行审查 → 结果异步回调 Ultra → Ultra 推送到钉钉。

```
POST /bridge/palace/review
{
  "scenario": "dor_review",
  "text": "春节限时礼包活动方案：...",
  "callback_url": "https://ultra.example.com/review-callback"
}
→ 202 { "task_id": "review-001", "status": "processing" }

（30秒后）
Bridge POST → ultra callback_url
{
  "task_id": "review-001",
  "result": {
    "overall_verdict": "concern",
    "summary": "PLD pass, PLE concern（交互稿待补充）, PLT pass",
    "action_items": [
      {"priority": "P1", "owner": "UX", "action": "补充交互稿"}
    ]
  }
}
```

### 8.2 PerformEval 组织/绩效查询

只读接口，脱敏处理：

```
GET /bridge/org/members?team=client
GET /bridge/org/structure
GET /bridge/eval/summary/{member_id}   ← 需权限校验，仅管理者可查
```

### 8.3 复合工作流（编排示例）

"创建春节版本并启动规划" 的 Bridge 内部编排：

```
Bridge 收到 pm.create_version 请求
  1. 调 PmSystem 创建版本 → 拿到 version_id
  2. 调 PmSystem 根据模板生成里程碑
  3. 写操作日志
  4. 发出 version.created 事件
  5. 返回结果给 Ultra
```

Ultra 只调了一个接口，Bridge 内部完成了 5 步。

---

## 九、部署与网络

### 9.1 开发环境

```
同一台机器（开发者电脑）
├── PmSystem      localhost:80xx
├── PerformEval   localhost:8112
├── Palace        localhost:8xxx
├── TaskReminder  localhost:8000
├── Bridge        localhost:8900
└── Ultra         ??? （Ultra 方部署环境待确认）
```

### 9.2 生产环境

```
内网服务器（同一 IP）
├── 各系统各占一个端口
├── 可选：nginx 反向代理统一入口
└── Ultra 方服务 → 需确认网络连通方式
```

### 9.3 网络连通待确认

- Ultra 部署在哪里？能直连内网 Bridge 端口吗？
- 如果 Ultra 在外网/云端，是否需要内网穿透或 VPN？
- 是否需要 nginx 反代做 HTTPS 终止？

---

## 十、职责边界总结

| 职责 | 归属 | 说明 |
|------|------|------|
| 自然语言理解 | Ultra | 把用户的话变成结构化 API 调用 |
| 能力发现 | Bridge 提供，Ultra 消费 | `/capabilities` 接口 |
| 请求鉴权 | Bridge | API Key 校验 |
| 参数校验 | Bridge | 校验必填字段、格式、业务规则 |
| 业务编排 | Bridge | 一个请求内部的多步操作 |
| 子系统调用 | Bridge | Bridge 内部，Ultra 不感知 |
| 操作日志 | Bridge | 全链路记录 |
| 事件产生 | Bridge | 描述"发生了什么" |
| 事件订阅 | Ultra | 注册关心哪些事件 |
| 推送目标决策 | Ultra | 决定"通知谁" |
| 推送投递 | Ultra | 通过钉钉 API 发消息 |
| 权限粒度管理 | **待讨论** | 是否需要按用户区分操作权限？ |

---

## 十一、待双方确认事项

| # | 问题 | 我方倾向 | 需要 Ultra 方回复 |
|---|------|---------|------------------|
| U1 | Ultra 调用协议 | HTTP REST + JSON | Ultra 是否有自己的工具注册规范？`/capabilities` 的格式需要适配吗？ |
| U2 | 异步结果通知方式 | 回调优先（Bridge POST → Ultra callback_url） | Ultra 能提供 callback endpoint 吗？还是只支持轮询？ |
| U3 | 事件推送协议 | Bridge POST → Ultra 注册的 endpoint，HMAC 签名校验 | Ultra 的事件接收 endpoint 地址和签名方式？ |
| U4 | 推送目标映射 | Ultra 侧维护"事件→接收人"的规则 | Ultra 是否有现成的通知路由机制？ |
| U5 | 权限粒度 | Bridge 按 API Key 做读写分级 | 是否需要按钉钉用户做细粒度权限？（如：某些人只能查不能建） |
| U6 | 网络连通 | 开发环境同一台机器；生产环境同内网 | Ultra 部署位置？能直连 Bridge 端口吗？ |
| U7 | Ultra 的能力发现协议 | 我方提供 `/capabilities` JSON | Ultra 是否有类似 OpenAI Function Calling 的工具定义格式要求？ |
| U8 | 对话上下文 | Bridge 无状态，每个请求独立 | Ultra 如果需要多轮对话上下文（如"上个版本"指代消歧），由 Ultra 侧维护 |

---

## 十二、MVP 实施计划

### 第一阶段：Bridge 骨架

- [ ] Bridge FastAPI 项目搭建（端口 8900）
- [ ] 鉴权中间件（API Key）
- [ ] 操作日志模块（SQLite）
- [ ] `GET /bridge/health`
- [ ] `GET /bridge/capabilities`
- [ ] 统一响应格式封装

### 第二阶段：PmSystem 读接口

- [ ] PmSystem 适配器（内部 HTTP Client）
- [ ] `GET /bridge/pm/versions`
- [ ] `GET /bridge/pm/versions/{id}`
- [ ] `GET /bridge/pm/features`
- [ ] `GET /bridge/pm/features/{id}`
- [ ] `GET /bridge/pm/dashboard`

### 第三阶段：PmSystem 写接口

- [ ] `POST /bridge/pm/versions`
- [ ] `POST /bridge/pm/features`
- [ ] `PATCH /bridge/pm/features/{id}/status`
- [ ] 写操作的参数校验和错误处理

### 第四阶段：事件系统

- [ ] 事件总线（内存队列，后续可换 Redis）
- [ ] `POST /bridge/events/subscribe`
- [ ] 写操作自动产生事件
- [ ] 事件回调投递（含重试）

### 子系统适配策略

PmSystem 当前后端 API 为全量读写模式（`GET/POST /api/data`），不具备细粒度操作接口。

**Bridge 采用两阶段适配策略：**

| 阶段 | 适配方式 | 说明 |
|------|---------|------|
| **当前（厚适配）** | Bridge 适配器通过 `/api/data` 全量读取 → 内存筛选/修改 → 全量写回 | 零依赖，Bridge 独立上线 |
| **目标（薄代理）** | PmSystem 补充 RESTful 细粒度接口后，Bridge 适配器切换为直接转发 | 性能优、逻辑清晰 |

厚适配的已知限制：
- 并发写入有冲突风险（两个请求同时读→改→写回）
- 全量读写有性能开销（数据量大时）
- Bridge 需要理解 PmSystem 的完整数据结构

这些限制在 MVP 阶段（单用户低频操作）可以接受。PmSystem 细粒度 API 改造需求已输出为独立文档：`BRIDGE_PM_API_REQUIREMENTS.md`。

---

## 附录 A：PmSystem 数据模型参考

### Version

```json
{
  "id": "v1234567890",
  "name": "v2.5.0 春节版本",
  "versionType": "major_expansion",
  "releaseDate": "2026-02-01",
  "capacity": 800,
  "phase": "planning",
  "pipelineWeight": "slow",
  "pleUserId": "u002",
  "pltUserId": "u003",
  "features": [],
  "milestones": [],
  "teamAllocations": {},
  "createdAt": "2026-01-01T00:00:00Z"
}
```

### Feature

```json
{
  "id": "f1234567890",
  "versionId": "v1234567890",
  "name": "新英雄-雷恩",
  "assignee": "张三",
  "stage": "dev",
  "priority": "P0",
  "strategicValue": 8,
  "estimate": 40,
  "effectivePoints": 320,
  "contentTier": "S",
  "contentReadiness": {
    "requirement_complete": false,
    "data_validated": false,
    "asset_spec_ready": false,
    "reward_reviewed": false
  },
  "experienceReadiness": {
    "interaction_draft": false,
    "ple_confirmed": false
  },
  "description": "",
  "notes": "",
  "tasks": [],
  "actualHours": 0,
  "createdAt": "2026-01-05T00:00:00Z"
}
```

### 其他模型（Task / Team / User）

见 `pm_requirements.md` §数据模型。

---

## 附录 B：术语表

| 术语 | 含义 |
|------|------|
| **Bridge** | 我方的 API 网关/外交部，Ultra 的唯一对接点 |
| **Ultra** | 对方的钉钉智能助手 |
| **PmSystem** | 游戏研发项目管理系统 |
| **Palace** | AI 多角色审查引擎 |
| **PerformEval** | 乘法绩效评价系统 |
| **PLD/PLE/PLT** | 管线轮值角色：主策/体验/技术 |
| **DoR** | Definition of Ready，准入标准 |
| **Feature** | 版本中的一个功能点/需求 |
| **管线重量** | 快轨(fast)/慢轨(slow)，决定流程密度 |
| **内容体量** | S/A/B 分级，决定用户影响面和资源投入 |
