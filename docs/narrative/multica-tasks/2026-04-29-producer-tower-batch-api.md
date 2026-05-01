# Producer Tower 批量操作接口需求文档

> 日期：2026-04-29
>

---

## 1. 背景与痛点

当前 Producer Tower 仅支持单条操作（`POST /{id}/complete`、`POST /{id}/dismiss`）。TR（TaskReminder）批量导入后，过期/已完成条目清理效率极低。今天手动改 `producer_tower.json` 处理 20 条数据，暴露两个缺口：

1.  **无批量状态变更**：无法一次选中 N 条标记 `done` / `dismissed`。
2.  **无按条件批量清理**：无法按"截止日期 + 来源"批量归档 TR 噪音。

---

## 2. 新增接口清单

| 序号 | 接口 | 说明 |
|------|------|------|
| 1 | `POST /api/producer-tower/batch-update` | 按 ID 列表批量更新状态 |
| 2 | `POST /api/producer-tower/bulk-dismiss` | 按条件批量 dismiss（清理 TR 过期项） |
| 3 | `GET /api/producer-tower/items` 增强 | 增加 `source` / `status` / `dueBefore` 组合筛选 |

---

## 3. 接口详细定义

### 3.1 批量更新状态

```http
POST /api/producer-tower/batch-update
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**

```json
{
  "ids": ["pt_xxx", "pt_yyy", "pt_zzz"],
  "status": "done",
  "note": "批量标记完成"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ids` | `string[]` | 是 | 待办 ID 列表，最大 100 条 |
| `status` | `string` | 是 | 目标状态：`done` / `dismissed` / `active` |
| `note` | `string` | 否 | 操作备注，写入 `metadata.batchNote` |

**Response 200:**

```json
{
  "success": true,
  "updated": 3,
  "failed": 0,
  "details": [
    {"id": "pt_xxx", "oldStatus": "active", "newStatus": "done"}
  ],
  "trSyncErrors": [],
  "partialTrSyncFailed": false
}
```

`trSyncErrors`：对 `source=task_reminder` 且已变更的条目，若回写 TR 失败则追加 `{ "id", "sourceId", "error" }`；与单条 `complete`/`dismiss` 的 `trSyncError` 语义对齐。`partialTrSyncFailed` 为 `true` 表示至少一条 TR 回写失败（本地 JSON 已成功保存）。

**错误码:**

| HTTP | 含义 |
|------|------|
| 400 | `ids` 为空或超过 100 条；`status` 非法 |
| 401 / 403 | 未登录 / 只读 viewer 禁止 |

**边界规则:**

*   部分 ID 不存在时**仍返回 HTTP 200**，在 `details` 中标记 `error: "not_found"`（不计入 `updated`）。
*   状态无变化（如已是 `done`）不计入 `updated`，也不报错。
*   修改时同步更新 `updatedAt`；若变为 `done`/`dismissed`，同步写 `completedAt`。

---

### 3.2 按条件批量 dismiss（清理）

```http
POST /api/producer-tower/bulk-dismiss
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**

```json
{
  "source": "task_reminder",
  "status": "active",
  "dueBefore": "2026-04-20",
  "dryRun": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | `string` | 否 | 筛选来源：`task_reminder` / `manual` / `signal` |
| `status` | `string` | 否 | 筛选当前状态，默认 `active` |
| `dueBefore` | `string` | 否 | 截止日期上限（含），`YYYY-MM-DD` |
| `dryRun` | `boolean` | 否 | 默认 `false`；`true` 时只返回影响条数，不真正修改 |

**Response 200 (dryRun=true):**

```json
{
  "dryRun": true,
  "wouldUpdate": 18
}
```

**Response 200 (dryRun=false):**

```json
{
  "dryRun": false,
  "updated": 18,
  "ids": ["pt_xxx", "pt_yyy", "..."],
  "trSyncErrors": [],
  "partialTrSyncFailed": false
}
```

**Response 200 (dryRun=true):** 另含 `"trSyncErrors": []`、`"partialTrSyncFailed": false`（预估阶段不写盘、不调 TR）。

**错误码:**

| HTTP | 含义 |
|------|------|
| 400 | `dueBefore` 格式错误；条件组合结果可能误伤，需至少传 `source`、`dueBefore`、`status` 之一 |
| 401 / 403 | 未登录 / 只读 viewer 禁止 |

**边界规则:**

*   必须至少指定 `source`、`dueBefore`、`status` 中的一个，防止空条件全表更新。
*   `dryRun` 为 `true` 时，先做完整查询但不写文件，返回预估影响条数供确认。
*   只操作 `items` 数组中的数据，不动 `archivedItems`。

---

### 3.3 列表查询增强

现有 `GET /api/producer-tower/items` 增加查询参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `source` | `string` | 精确匹配来源 |
| `status` | `string` | 精确匹配状态，支持 `active,done` 多值（逗号分隔） |
| `dueBefore` | `string` | 截止日期 <= 该值 |
| `dueAfter` | `string` | 截止日期 >= 该值 |

**示例:**

```http
GET /api/producer-tower/items?source=task_reminder&status=active&dueBefore=2026-04-20
```

**鉴权：**须登录且**非 viewer**（`require_not_viewer`）；非法 `dueBefore` / `dueAfter` 返回 **400**。

**说明：**`ids` 为空时请求体校验返回 **400**（与 OpenAPI 对空数组的 422 二选一，实现统一为 400）。

---

## 4. 数据模型补充

`TowerItem` 新增可选字段（向后兼容）：

```python
class TowerItem(BaseModel):
    # ... 现有字段 ...
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # 新增：批量操作审计
    # metadata.batchNote   # 批量操作时写入的备注
    # metadata.batchOpAt   # 批量操作时间（ISO 8601）
```

---

## 5. 验收标准（AC）

| 编号 | 验收项 |
|------|------|
| AC-01 | `batch-update` 传入 20 个 ID 批量标记 `done`，接口返回 `updated=20`，JSON 文件中对应条目 `status=done` 且 `completedAt` 有值。 |
| AC-02 | `batch-update` 传入 1 个不存在的 ID，返回 200，`details` 中该条标记 `error=not_found`，其余正常更新。 |
| AC-03 | `bulk-dismiss` JSON 体 `dryRun: true` 且 `source`+`dueBefore` 同上，返回预估条数，文件未被修改。 |
| AC-04 | `bulk-dismiss` 相同条件 `dryRun=false`，返回实际更新条数及 ID 列表，文件中对应条目 `status=dismissed`。 |
| AC-05 | `GET /items?source=task_reminder&status=active` 仅返回 `active` 的 TR 导入项。 |
| AC-06 | 所有新增接口复用现有 `_load_tower_data` / `_save_tower_data`，保持原子写（先写 `.tmp` 再 `replace`）。 |
