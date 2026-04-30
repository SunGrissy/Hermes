# PmSystem API 设计文档 #2 — OPS Push to Version 运营规划推送版本

# PmSystem API 设计文档 #2 — OPS Push to Version 运营规划推送版本

> 对应工作流：阿茶「OPS 维度标签 → 版本推送」（组版本核心动作）。 当前野路子：直连 SQLite 执行 features INSERT + operation\_matrices UPDATE JSON blob。 目标：后端提供原子性 API，前端业务逻辑 + 阿茶 Agent 统一调用，不再绕过业务层。

---

## 接口清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/operations/push-to-version` | 单条维度标签推送到版本 |
| `POST` | `/api/operations/bulk-push` | 批量维度标签推送到版本（月度组版本用） |

---

## 1. POST /api/operations/push-to-version

### 请求头

```plaintext
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

### 请求体

```json
{
  "tagId": "val_1745737600000x1a2b",  // 维度标签 ID
  "versionId": "ver_aaaabbbb",          // 版本 ID
  "assignee": "u061",                   // 可选；若提供，Feature.assignee 填此值
  "priority": "P2"                      // 可选；默认 P2
}
```

### 校验规则

1.  `tagId` 必须在 `operation_matrices.data.dimensionValues[ ].id` 中存在
    
2.  `versionId` 必须在 `versions` 表中存在
    
3.  该维度标签的 `metadata.sentToVersions` 中**已经包含**当前 `versionId` → **幂等返回**（见下方）
    
4.  `versionId` 对应版本的 `scope_locked`，无论它是什么值这个 API 都允许推送（暂不做 scope 大门校验）
    
5.  `priority` 只能传 `P0`/`P1`/`P2`
    

### 核心业务逻辑（单事务原子包裹）

```plaintext
Step 1: 读取 operation_matrices global 记录
Step 2: 读取 versions 表取 version_name

Step 3: 在 dimensionValues[ ] 中找到目标 tagId → 提取 tag 全量数据

Step 4: 检查 tag.metadata.sentToVersions 是否包含 versionId
         → 已包含: 直接跳 Step 7，返回幂等响应
Step 5: 创建 Feature 记录（见下方字段映射）
Step 6: 更新 operation_matrices JSON:
         - tag.metadata.sentToVersions.push({versionId, versionName, featureId, sentAt})
         - tag.metadata.sentToVersionId = versionId
Step 7: UPDATE operation_matrices SET data = ?
Step 8: COMMIT
```

### Feature 创建字段映射（精确对应前端 pushToVersion）

| Feature 表字段 | 值 | 说明 |
| --- | --- | --- |
| `id` | `feat_${timestamp}_${suffix}` | 新生成唯一 ID |
| `version_id` | `versionId` | 参数传入 |
| `name` | `tag.name` | 维度标签名 |
| `priority` | `priority` 或 `P2` | 参数传入，默认 P2 |
| `estimate` | `0` | 默认 0 |
| `description` | `""` | 空字符串 |
| `assignee` | `assignee` 或 `""` | 参数传入，默认空 |
| `strategic_value` | `5` | 默认 5 |
| `notes` | `"来源: 运营规划 - {tag.groupName}"` | groupName 从 dimensions 反查 |
| `"group"` | `tag.groupName` | ⚠️ SQLite 保留字，SQLAlchemy 需双引号 |
| `module_name` | `None` | null |
| `effective_points` | `0` | 默认 0 |
| `source` | `"ops"` | 固定 |
| `source_id` | `tag.id` | 维度标签 ID |
| `readiness` | `{"spec":false,"tech":false,"art":false}` | JSON 字符串 |
| `status` | `"draft"` | 固定 draft |
| `is_blocked` | `0` | 无阻塞 |
| `blocked_reason` | `""` | 空 |
| `status_history` | `[{"from":null,"to":"draft",...}]` | JSON 数组 |
| `created_at` | `now_iso` | UTC iso |
| `updated_at` | `now_iso` | UTC iso |

### 幂等行为

```json
{
  "tagId": "val_xxx",
  "targetVersionId": "ver_xxx",
  "sentToVersions": [{"versionId":"ver_xxx","versionName":"端午","featureId":"feat_xxx","sentAt":"2026-04-28T08:43:00Z"}]
}
```

### 200 成功响应

```json
{
  "success": true,
  "data": {
    "featureId": "feat_1745737600000_a1b2c3",
    "tagId": "val_1745737600000x1a2b",
    "versionId": "ver_aaaabbbb",
    "versionName": "端午",
    "sentAt": "2026-04-28T08:43:00+08:00",
    "idempotent": false
  }
}
```
---

## 2. POST /api/operations/bulk-push 批量推送

### 请求体

```json
{
  "tagIds": ["val_1", "val_2", "val_3"],
  "versionId": "ver_aaaabbbb",
  "assignee": "u061",
  "priority": "P2"
}
```

### 返回

```json
{
  "success": true,
  "data": {
    "processed": 3,
    "created": 2,
    "idempotentSkipped": 1,
    "features": ["feat_xxx", "feat_yyy", "feat_zzz"],

    "errors": [ ]

  }
}
```

### 原子性选项

*   **推荐方式 A（默认）**：每个 tag 各自事务独立 — 部分成功、部分失败，返回成功和失败列表
    
*   **可选方式 B（参数控制）**：`"atomic": true` → 全部成功或全部失败（任一 tag 失败则全部 rollback）
    

```json
{
  "tagIds": ["val_1", "val_2", "val_3"],
  "versionId": "ver_xxx",
  "atomic": false  // 默认 false，按需开启
}
```
---

## 3. 相关读端点（已存在，列出来方便定位）

| 端点 | 说明 |
| --- | --- |
| `GET /api/versions` | 版本列表 |
| `GET /api/versions/{id}` | 版本详情（含 pipeline\_ddls） |
| `GET /api/planner/items?week=YYYY-Www` | 策划工作台 |
| `GET /api/producer-tower/signals` | 制作人 Tower 信号 |

### OPS 矩阵读端点（当前缺失，可选补充）

若前端和阿茶都需要读 OPS 全局矩阵，建议新增：

*   `GET /api/operations/matrix` → 返回全局运营矩阵完整 JSON（替代前端直连 SQLite）
    
*   `GET /api/operations/dimension-values?versionId=ver_xxx` → 查询某版本已分配/未分配的标签
    

---

## 4. 实施约束与风险

1.  **operation\_matrices 是单条 JSON blob**（id="global"）：
    
    *   必须先 `SELECT` 取出完整 data → Python dict 内存修改 → `UPDATE` 回写
        
    *   并发冲突风险低（当前单用户操作），但建议加行级乐观锁（version/timestamp）
        
2.  **group 是 SQLite 保留字**：
    
    *   SQLAlchemy ORM 层若已做自动转义则安全；
        
    *   若后端手写 SQL，必须用 `"group"`（双引号）包裹列名
        
3.  **特征良性累积**：
    
    *   `status_history` 中 `reason` 统一写 `"pushed from operations"`
        
    *   后续若支持前端点击完成 feature，reason 写 `"manual status change"`
        
4.  **二次幂等判定窗口**：
    
    *   判定依据：`tag.metadata.sentToVersions[ ].versionId == versionId`
        
    *   即使上次是手动 SQL 写的（我闯过野路子），只要 JSON 里有记录就视为"已推送"
        

---

_文档版本：v1.0_

_阿茶 | 2026-04-28_