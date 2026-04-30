# PmSystem API 设计文档 #4 — Feature 批量维护

# PmSystem API 设计文档 #4 — Feature 批量维护

> 对应工作流：阿茶策划工作诊断中的"版本 Feature 指派率修复"、人员交接 Feature 批量转派。 阿茶当前策略：读出 → 报给老大 → 等老大手动在前端逐个点。效率差。 目标：提供安全的批量维护 API，让阿茶经老大确认后直接代操作，不走 SQLite。

---

## 接口清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/features` | 扩展查询能力（见下方） |
| `PATCH` | `/api/features/batch` | 按 featId 列表精确批量更新 |
| `POST` | `/api/features/conditional-update` | 按条件过滤批量更新（不指定 featIds） |

---

## 1. GET /api/features（扩展查询）

当前已有 `GET /api/features?version_id=xxx`，阿茶实测可用。但缺少以下过滤能力：

### 建议扩展的查询参数

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `versionId` | string | 已有 |
| `assignee` | string | 按负责人过滤（支持 u0xx 或中文名） |
| `status` | string | draft / in\_progress / in\_acceptance / testing / done |
| `group` | string | 分组名（如"高价物上新&外显"） |
| `source` | string | ops / maintenance / manual |
| `priority` | string | P0 / P1 / P2 |
| `isBlocked` | boolean | 1 / 0 |
| `blockedReason` | string | 支持部分匹配 |
| `scopeLocked` | boolean | 关联版本的 scope\_locked |
| `limit` | int | 分页，默认 50 最大 200 |
| `offset` | int | 分页 |
| `orderBy` | string | `created_at` / `updated_at` / `priority` / 默认 `created_at desc` |

### 响应

```json
{
  "success": true,
  "data": {
    "total": 29,
    "limit": 50,
    "offset": 0,
    "items": [
      {
        "id": "feat_xxx",
        "versionId": "ver_xxx",
        "name": "赛季养成｜神君特别版",
        "assignee": "u062",               // 或中文名，保持后端数据原样
        "status": "draft",
        "stage": null,
        "priority": "P0",
        "group": "机制&生态",
        "source": "ops",
        "isBlocked": 0,
        "delivery": {...},
        "readiness": {...},
        "createdAt": "2026-04-01T10:00:00Z",
        "updatedAt": "2026-04-26T14:35:00Z"
      }
    ]
  }
}
```
---

## 2. PATCH /api/features/batch（按 featId 精确批量更新）

### 请求体

```json
{
  "updates": [
    {
      "id": "feat_xxx",
      "assignee": "u061",
      "priority": "P1",
      "group": "机制&生态",
      "notes": "[2026-04-28 阿茶] 人员交接：u062 → u061"
    },
    {
      "id": "feat_yyy",
      "assignee": "u061"
    }
  ]
}
```

### 可更新字段白名单

| 字段 | 说明 | 阿茶使用场景 |
| --- | --- | --- |
| `assignee` | 负责人 | 人员交接、版本指派 |
| `priority` | P0/P1/P2 | 版本评审后统一调整 |
| `group` | 分组名 | 分组迁移 |
| `notes` | 备注 | 阿茶追加操作记录，方便追溯 |

**以下字段不在白名单内：**

*   `status` → 走前端状态机点击，不开放批量修改
    
*   `stage` → 同理
    
*   `delivery` 各维度 → 验收结果，不走此 API
    
*   `readiness` → DoR 评审结果，不走此 API
    

### 校验规则

1.  `id` 必须在 `features` 表中存在
    
2.  `assignee` 非空时，必须在 `members` / `users` 映射中存在
    
3.  `priority` 只能是 `P0`/`P1`/`P2`
    
4.  `group` 非空时，长度限制 255 字符
    
5.  `updates` 数组最大 100 条，超限 `413`
    

### 级联逻辑

*   `assignee` 变更 → **不**自动同步 `planner_work_items` 的 `assignee`。两条线解耦，防止意外覆盖策划前台填写的每周计划。
    
*   但返回体中可额外提供 `advisory` 字段，提示"以下 planner\_items 可能需手动同步：..."
    

### 原子性

*   同一事务包裹所有 `updates` 数组
    
*   全部成功或全部失败
    
*   返回 `200` + 修改详情，或 `422` + 首条错误
    

### 响应 200

```json
{
  "success": true,
  "data": {
    "updated": 2,
    "items": [
      {
        "id": "feat_xxx",
        "before": {"assignee": "u062", "priority": "P2"},
        "after": {"assignee": "u061", "priority": "P1"}
      }
    ],
    "advisory": {
      "plannerItemsToCheck": ["plnr_xxx", "plnr_yyy"]
    }
  }
}
```

### 错误响应 422

```json
{
  "success": false,
  "errors": [
    {
      "index": 1,
      "id": "feat_yyy",
      "field": "assignee",
      "message": "Assignee 'u999' not found in member registry."
    }
  ]
}
```
---

## 3. POST /api/features/conditional-update（条件过滤批量更新）

### 使用场景

阿茶在诊断报告中写道："端午版 29 条 Feature 仅 1 条指派"，老大回复"全部未指派的分给 u061"。阿茶不想再先 GET 出 28 个 featId 再一条条 PATCH，需要一键按条件改。

### 请求体

```json
{
  "filter": {
    "versionId": "ver_xxx",
    "assignee": null,       // null 表示"所有未指派的"
    "group": null,
    "status": "draft",
    "priority": "P0",
    "source": "ops"
  },
  "set": {
    "assignee": "u061",
    "notes": "[2026-04-28 阿茶] 端午版组版本统一分配"
  },
  "dryRun": true            // 可选；先预览
}
```

### filter 字段语义

| filter 字段 | 语义 |
| --- | --- |
| `versionId` | 精确匹配版本 |
| `assignee` | `null` 或 `{"$null": true}` 表示"未指派"；字符串表示匹配该人；数组表示匹配多个人 |
| `group` | 精确匹配分组名；数组表示多选 |
| `status` | 精确匹配 |
| `priority` | 精确匹配 |
| `source` | 精确匹配 |

### dryRun 模式

返回"将要修改什么"但不真正执行：

```json
{
  "success": true,
  "data": {
    "wouldUpdate": 28,
    "items": [
      {"id": "feat_1", "name": "黄金城1", "before": {"assignee": ""}, "after": {"assignee": "u061"}}
    ],
    "dryRun": true
  }
}
```

*   `wouldUpdate > 0` 且 `dryRun=false` → `400` + 要求确认：`"Use dryRun=true first to preview, then set dryRun=false to execute"`
    
*   或者后端直接拒绝无 preview 就执行的大批量更新（>5 条），强制 preview → confirm 流程
    

### 正式执行（dryRun=false）

```json
{
  "success": true,
  "data": {
    "updated": 28,
    "items": [ /* 修改明细，最多前 20 条 */ ],
    "advisory": {
      "plannerItemsToCheck": ["plnr_xxx"]
    }
  }
}
```

### 安全上限

*   `conditional-update` 的单次实际修改上限 **100 条**
    
*   超过则 `413` + `{"message": "Matched 156 items, exceeds batch limit 100. Please narrow filter."}`
    

---

## 4. 禁止项

以下操作**不在本 API 支持范围内**，如有需求走前端单独处理：

| 操作 | 原因 |
| --- | --- |
| 修改 `Feature.status` | 状态流转涉及状态机规则、时间戳记录、验收检查点，只允许前端单条操作 |
| 修改 `Feature.stage` | 同状态机 |
| 修改 `Feature.delivery` 各子项 | 验收结果是人工/测试流程确认的结果，不能批量"点完成" |
| 删除 Feature | 通过 Task B（OPS 删除）或前端单个处理 |
| 创建 Feature | 通过 Task B（push-to-version）或前端新建 |

---

## 5. 权限建议

*   当前系统只有 admin / manager / member 角色
    
*   阿茶将使用一个固定 Service Account 或 dev\_token 调用
    
*   后端可对 `PATCH /api/features/batch` 增加最小权限验证：`assignee` 字段修改需要 `pm:assign` 权限（或直接用 admin 权限通用化）
    
*   对于 `notes` 字段，后端自动追加调用者身份前缀，防止伪造备注
    

---

_文档版本：v1.0_

_阿茶 | 2026-04-28_