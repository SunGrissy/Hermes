# PmSystem API 改造需求

> 来源：Bridge 对接项目（BRIDGE_SPEC.md）
> 创建日期：2026-03-05
> 状态：待执行
> 执行方：pm-system Agent

---

## 背景

Bridge 作为外部系统（Ultra）与 PmSystem 之间的网关，需要对版本、Feature 等资源做细粒度的增删改查。

PmSystem 当前后端 API 为全量模式：

| 现有接口 | 行为 |
|---------|------|
| `GET /api/data` | 返回所有数据（版本、Feature、任务、团队、用户） |
| `POST /api/data` | 覆盖写入所有数据 |

Bridge 短期内通过"全量读 → 内存操作 → 全量写回"的厚适配层运作，但存在并发冲突和性能问题。需要 PmSystem 补充 RESTful 细粒度接口。

---

## 需要新增的接口

### 1. 版本管理

#### GET /api/versions

查询版本列表。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| phase | query | string | 否 | 按阶段筛选：planning / estimation / execution |

**返回：** 版本数组，每项包含：
```json
{
  "id": "v1234567890",
  "name": "v2.5.0 春节版本",
  "versionType": "major_expansion",
  "releaseDate": "2026-02-01",
  "phase": "planning",
  "capacity": 800,
  "pipelineWeight": "slow",
  "featureCount": 5,
  "totalEstimate": 320,
  "createdAt": "2026-01-01T00:00:00Z"
}
```

`featureCount` 和 `totalEstimate` 为计算字段，由后端聚合。

#### GET /api/versions/{version_id}

查询版本详情，含 Feature 列表概览、里程碑、容量汇总。

**返回：** 完整版本对象 + 嵌套的 features（摘要）+ milestones + capacity_summary。

```json
{
  "id": "v1234567890",
  "name": "v2.5.0 春节版本",
  "versionType": "major_expansion",
  "releaseDate": "2026-02-01",
  "phase": "planning",
  "capacity": 800,
  "pipelineWeight": "slow",
  "pleUserId": "u002",
  "pltUserId": "u003",
  "features": [
    {
      "id": "f001",
      "name": "新英雄-雷恩",
      "assignee": "张三",
      "stage": "design",
      "priority": "P0",
      "strategicValue": 8,
      "estimate": 40
    }
  ],
  "milestones": [
    {"name": "Feature Freeze", "date": "2026-01-02", "status": "pending"}
  ],
  "capacitySummary": {
    "total": 800,
    "allocated": 320,
    "remaining": 480,
    "usagePct": 40.0,
    "alertLevel": "normal"
  }
}
```

#### POST /api/versions

创建版本。

**请求体：**
```json
{
  "name": "v2.6.0 五一版本",
  "versionType": "major_expansion",
  "releaseDate": "2026-05-01",
  "capacity": 800,
  "milestoneTemplate": "standard_30d"
}
```

**行为：**
1. 创建版本记录
2. 如果指定了 `milestoneTemplate`，自动生成里程碑
3. 返回创建结果（含 id 和生成的里程碑数量）

**返回：**
```json
{
  "id": "v_new_001",
  "name": "v2.6.0 五一版本",
  "milestonesGenerated": 6
}
```

**校验规则：**
- `name` 不能为空，不能与已有版本重名
- `releaseDate` 必须是未来日期
- `versionType` 必须是 `major_expansion` / `monthly_event` / `minor_update` / `hotfix` 之一

---

### 2. Feature 管理

#### GET /api/features

按条件查询 Feature。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| version_id | query | string | 否 | 按版本筛选 |
| stage | query | string | 否 | pending/design/dev/qa/done/blocked |
| priority | query | string | 否 | P0/P1/P2 |
| assignee | query | string | 否 | 负责人姓名 |

**返回：** Feature 数组。

#### GET /api/features/{feature_id}

Feature 详情，含完整字段和任务列表。

#### POST /api/features

创建 Feature。

**请求体：**
```json
{
  "versionId": "v1234567890",
  "name": "春节限时礼包",
  "assignee": "刘泊霆",
  "priority": "P1",
  "strategicValue": 6,
  "estimate": 20,
  "description": "面向付费用户的限时7天礼包",
  "contentTier": "A"
}
```

**行为：**
1. 创建 Feature 记录
2. 自动计算 `effectivePoints = strategicValue × estimate`
3. 将 Feature ID 加入对应版本的 `features` 数组
4. 返回创建结果

**校验规则：**
- `versionId` 必须存在
- `name` 不能为空
- `priority` 必须是 P0/P1/P2
- `strategicValue` 范围 1-10
- `estimate` > 0

#### PATCH /api/features/{feature_id}

部分更新 Feature。只更新请求体中提供的字段。

**请求体（示例，只传需要改的字段）：**
```json
{
  "stage": "dev",
  "actualHours": 15
}
```

**特殊逻辑：**
- 更新 `strategicValue` 或 `estimate` 时，自动重算 `effectivePoints`
- 更新 `stage` 时，记录状态变更时间（用于后续流转分析）

---

### 3. 仪表盘

#### GET /api/dashboard

版本仪表盘摘要。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| version_id | query | string | 否 | 指定版本，不传则返回所有非归档版本 |

**返回：**
```json
{
  "activeVersions": [
    {
      "id": "v1234567890",
      "name": "v2.5.0 春节版本",
      "phase": "execution",
      "releaseDate": "2026-02-01",
      "daysRemaining": 15,
      "featureSummary": {
        "total": 10,
        "done": 3,
        "inProgress": 5,
        "blocked": 1,
        "notStarted": 1
      },
      "capacitySummary": {
        "usagePct": 85.0,
        "alertLevel": "warning"
      },
      "risks": [
        "P0 Feature '新英雄-雷恩' 处于 blocked 状态",
        "容量使用率 85%，接近超载"
      ],
      "nextMilestone": {
        "name": "Code Complete",
        "date": "2026-01-22",
        "daysUntil": 3
      }
    }
  ]
}
```

`risks` 为后端根据规则自动生成的风险项：
- 任何 P0 Feature 处于 blocked → 生成风险
- 容量使用率 > 80% → 生成风险
- 最近里程碑 < 3 天且有未完成的前置 Feature → 生成风险

---

## 实现建议

### 数据层

现有的 `GET/POST /api/data` 全量模式可以保留（前端仍在用），新增的细粒度接口与之并存。

两种实现路径：

| 方案 | 做法 | 优劣 |
|------|------|------|
| **A. 内存操作** | 新接口仍读写同一份 JSON 数据，在内存中做增删改查 | 改动小，但有并发问题 |
| **B. 真正拆表** | 将 Version/Feature/Task 拆为独立的 SQLAlchemy 模型和数据库表 | 架构干净，长期方案 |

建议 MVP 走 A（与现有前端兼容），后续迁移到 B。

### 兼容性

- 新接口的数据格式与现有前端数据模型保持一致（字段名用 camelCase）
- `GET/POST /api/data` 继续工作，前端无需改动
- 新接口可以和旧接口读写同一份底层数据

### 接口前缀

建议新接口统一用 `/api/` 前缀，与现有接口一致：

```
GET  /api/versions
GET  /api/versions/{id}
POST /api/versions
GET  /api/features
GET  /api/features/{id}
POST /api/features
PATCH /api/features/{id}
GET  /api/dashboard
```

---

## 验收标准

1. 所有新接口返回格式统一为 `{"code": 0, "data": ..., "message": "ok"}`
2. 错误返回包含有意义的 message（如"版本名称已存在"）
3. 新接口与 `GET/POST /api/data` 数据一致（同一份底层数据）
4. 创建版本时里程碑自动生成逻辑与前端创建版本行为一致
5. Feature 的 `effectivePoints` 在创建和更新时自动计算
6. Dashboard 的 `risks` 字段能正确识别至少 3 种风险场景
