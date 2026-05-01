# API 设计文档：删除 OPS 顶层维度标签（dimensionValues[]）

> 文档编号：API-OPS-005
> 关联文档：API #3（PATCH/DELETE /dimension-values/batch）
> 状态：待后端实现

---

## 1. 背景与问题

当前 `DELETE /api/operations/dimension-values/batch`（API #3）只能删除存储在 `data.dimensions[].values[]` 中的维度标签，**无法触及顶层 `data.dimensionValues[]` 中的标签**。

实际业务中，大量维度标签（尤其是通过前端早期导入或批量创建的标签）只存在于 `dimensionValues[]` 中，而在 `dimensions[].values[]` 里根本找不到。这导致：
- 调用 API #3 删除时返回 `notFound`，实际数据仍在系统中
- 前端运营矩阵主视图（读取 `dimensionValues[]`）仍显示已"删除"的标签
- 阿茶（Agent）无法通过正规 API 清理这类孤儿标签

## 2. 目标

新增一个批量删除接口，支持从**顶层 `dimensionValues[]`** 中移除维度标签，同时保持与 `dimensions[].values[]` 的一致性，并级联清理已生成的 Feature。

## 3. 接口设计

### 3.1 基本信息

| 项目 | 内容 |
|------|------|
| 方法 | `DELETE` |
| 路径 | `/api/operations/dimension-values/flat/batch` |
| 认证 | `Bearer dev_token` + `require_not_viewer` |
| Content-Type | `application/json` |

### 3.2 请求体

```json
{
  "valueIds": ["val_xxx", "val_yyy"],
  "expectedUpdatedAt": "2026-04-29T08:00:00.000Z",
  "cascadeDeleteFeatures": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `valueIds` | `string[]` | 是 | 待删除的维度标签 ID 列表，至少 1 个 |
| `expectedUpdatedAt` | `string` | 否 | 乐观锁时间戳。若提供，需与矩阵当前 `updated_at` 严格匹配 |
| `cascadeDeleteFeatures` | `boolean` | 否 | 是否级联删除由这些标签推送生成的 Feature。默认 `true` |

### 3.3 响应体

**成功（200）**

```json
{
  "success": true,
  "data": {
    "deletedFromFlat": 11,
    "deletedFromNested": 0,
    "featuresDeleted": 0,
    "notFound": [],
    "newUpdatedAt": "2026-05-01T09:15:00.000Z"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `deletedFromFlat` | `int` | 从 `dimensionValues[]` 中实际删除的数量 |
| `deletedFromNested` | `int` | 从 `dimensions[].values[]` 中同步清理的数量 |
| `featuresDeleted` | `int` | 级联删除的 Feature 数量 |
| `notFound` | `string[]` | 在 `dimensionValues[]` 中未找到的 ID 列表 |
| `newUpdatedAt` | `string` | 更新后的矩阵时间戳 |

**冲突（409）**

当 `expectedUpdatedAt` 与数据库不一致时：

```json
{
  "detail": {
    "message": "Matrix已被他人修改，请刷新后重试",
    "serverUpdatedAt": "2026-04-29T08:05:00.000Z"
  }
}
```

**权限不足（403）**

当调用者为 viewer 角色时，返回 `403 Forbidden`。

## 4. 业务规则与实现要点

### 4.1 数据一致性：两边一起删

实现必须**同时操作两个存储位置**：

1. **顶层数组**：`data.dimensionValues[]`
2. **嵌套数组**：遍历 `data.dimensions[].values[]`，移除相同 ID

> 原因：前端不同视图读取的数据源不同。只删一边会导致另一侧仍显示标签，用户刷新后数据"复活"。

### 4.2 Feature 级联清理

当 `cascadeDeleteFeatures` 为 `true`（默认）时：

1. 遍历 `valueIds`，对每个 ID 查询 `features` 表：`WHERE source_id = ? AND source = 'ops'`
2. 执行 `DELETE FROM features WHERE source_id IN (...)`
3. 同步清理 `planner_work_items` 中 `linked_feature_id` 指向这些 Feature 的记录（设为 `NULL`）

> 注意：SQLite 默认 `PRAGMA foreign_keys = OFF`，数据库级 `ON DELETE SET NULL` 不会自动触发，必须在代码层手动清理。

### 4.3 乐观锁

与 API #3 一致，支持可选的 `expectedUpdatedAt`：

```python
if expected_updated_at:
    stored_ts = _to_iso(matrix_row.updated_at)
    if stored_ts and stored_ts != expected_updated_at:
        raise HTTPException(status_code=409, detail={...})
```

### 4.4 与现有 API 的关系

| 场景 | 推荐接口 |
|------|---------|
| 标签在 `dimensions[].values[]` 中 | `DELETE /api/operations/dimension-values/batch`（API #3） |
| 标签在 `dimensionValues[]` 中（本接口目标） | `DELETE /api/operations/dimension-values/flat/batch` |
| 不确定标签在哪 | 先调用 `GET /api/operations/dimension-values`，根据返回判断 |

### 4.5 幂等性

对同一组 `valueIds` 多次调用，第二次应返回：
- `deletedFromFlat: 0`
- `notFound: ["val_xxx", ...]`（因为第一次已删除）

这是预期行为，不视为错误。

## 5. 参考实现（Python/FastAPI）

```python
@router.delete("/dimension-values/flat/batch")
async def batch_delete_dimension_values_flat(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_not_viewer),
):
    value_ids = payload.get("valueIds") or []
    expected_updated_at = str(payload.get("expectedUpdatedAt") or "").strip()
    cascade = bool(payload.get("cascadeDeleteFeatures", True))

    if not isinstance(value_ids, list) or not value_ids:
        raise HTTPException(status_code=400, detail="valueIds must be a non-empty list")

    matrix_row = db.query(OperationMatrix).filter_by(id="global").first()
    if not matrix_row or not matrix_row.data:
        raise HTTPException(status_code=404, detail="Operation matrix not found")

    # optimistic lock
    if expected_updated_at:
        stored_ts = _to_iso(matrix_row.updated_at)
        if stored_ts and stored_ts != expected_updated_at:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Matrix已被他人修改，请刷新后重试",
                    "serverUpdatedAt": stored_ts,
                },
            )

    matrix = dict(matrix_row.data)
    ids_to_delete = {str(v).strip() for v in value_ids}

    # 1) delete from dimensionValues[]
    flat_vals = matrix.get("dimensionValues") or []
    if isinstance(flat_vals, list):
        original_flat_len = len(flat_vals)
        matrix["dimensionValues"] = [
            v for v in flat_vals
            if not (isinstance(v, dict) and str(v.get("id") or "").strip() in ids_to_delete)
        ]
        deleted_flat = original_flat_len - len(matrix["dimensionValues"])
    else:
        deleted_flat = 0

    # 2) delete from dimensions[].values[] (sync)
    deleted_nested = 0
    for dim in (matrix.get("dimensions") or []):
        if not isinstance(dim, dict):
            continue
        dim_vals = dim.get("values") or []
        if isinstance(dim_vals, list):
            original = len(dim_vals)
            dim["values"] = [
                v for v in dim_vals
                if not (isinstance(v, dict) and str(v.get("id") or "").strip() in ids_to_delete)
            ]
            deleted_nested += original - len(dim["values"])

    # 3) cascade delete features
    features_deleted = 0
    if cascade:
        # clear planner references first
        db.execute(
            text("UPDATE planner_work_items SET linked_feature_id = NULL "
                 "WHERE linked_feature_id IN (SELECT id FROM features WHERE source_id IN :ids AND source = 'ops')"),
            {"ids": tuple(ids_to_delete)},
        )
        result = db.execute(
            text("DELETE FROM features WHERE source_id IN :ids AND source = 'ops'"),
            {"ids": tuple(ids_to_delete)},
        )
        features_deleted = result.rowcount

    now = _now_iso()
    matrix_row.data = matrix
    matrix_row.updated_at = datetime.fromisoformat(now)
    db.commit()

    not_found = [
        vid for vid in ids_to_delete
        if vid not in {str(v.get("id") or "").strip() for v in flat_vals if isinstance(v, dict)}
    ]

    return {
        "success": True,
        "data": {
            "deletedFromFlat": deleted_flat,
            "deletedFromNested": deleted_nested,
            "featuresDeleted": features_deleted,
            "notFound": sorted(not_found),
            "newUpdatedAt": now,
        },
    }
```

## 6. 测试用例

| # | 场景 | 输入 | 预期结果 |
|---|------|------|---------|
| 1 | 正常删除顶层标签 | `valueIds: ["val_S5", "val_S6"]` | `deletedFromFlat: 2`, `featuresDeleted: 0`（未推送） |
| 2 | 标签同时存在于嵌套数组 | `valueIds: ["val_x"]`（两边都有） | `deletedFromFlat: 1`, `deletedFromNested: 1` |
| 3 | 级联删除 Feature | `valueIds: ["val_pushed"]`（已推送生成 Feature） | `deletedFromFlat: 1`, `featuresDeleted: 1`, planner 关联字段被清空 |
| 4 | 部分 ID 不存在 | `valueIds: ["val_exist", "val_notexist"]` | `deletedFromFlat: 1`, `notFound: ["val_notexist"]` |
| 5 | 乐观锁冲突 | `expectedUpdatedAt` 与数据库不一致 | `409` |
| 6 | Viewer 角色调用 | — | `403` |
| 7 | 空 valueIds | `valueIds: []` | `400` |

## 7. 前端配合

- 前端在删除成功后，应刷新 `window.app.operationMatrix` 内存数据（或整页 `Ctrl+F5`）
- 策划工作台 `_autoSyncOpsTags()` 依赖内存中的 operationMatrix，需确保刷新顺序：先刷新 OPS 页，再打开工作台

## 8. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-05-01 | v1.0 | 初始创建 |
