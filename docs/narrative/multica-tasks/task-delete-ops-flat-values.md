# 派单：新增顶层 dimensionValues[] 批量删除接口

## 背景

当前 `DELETE /api/operations/dimension-values/batch`（API #3）只能删除存储在 `data.dimensions[].values[]` 中的标签，无法触及顶层 `data.dimensionValues[]`。导致大量孤儿标签（仅存于顶层数组）无法通过正规接口清理。

## 需求

在 `app/routers/operations.py` 中新增一个 DELETE 接口：

- **路径**：`/api/operations/dimension-values/flat/batch`
- **功能**：从 `operation_matrices.data.dimensionValues[]` 中批量删除指定 ID 的维度标签
- **一致性**：同步从 `dimensions[].values[]` 中移除同样 ID 的标签（如果存在）
- **级联**：默认级联删除 `features` 表中 `source_id` 匹配且 `source='ops'` 的记录，并先清理 `planner_work_items.linked_feature_id` 引用
- **安全**：支持可选的 `expectedUpdatedAt` 乐观锁，与 API #3 一致
- **认证**：`Bearer dev_token` + `require_not_viewer`

## 请求体示例

```json
{
  "valueIds": ["val_1777545719349_1i6d4qjd2", "val_1777545719349_fret8qt5f"],
  "expectedUpdatedAt": "2026-05-01T01:00:00.000Z",
  "cascadeDeleteFeatures": true
}
```

## 响应体示例

```json
{
  "success": true,
  "data": {
    "deletedFromFlat": 2,
    "deletedFromNested": 0,
    "featuresDeleted": 0,
    "notFound": [],
    "newUpdatedAt": "2026-05-01T09:15:00.000Z"
  }
}
```

## 验收标准

1. 接口可以正确删除仅存在于 `dimensionValues[]` 中的标签
2. 同一标签若同时存在于 `dimensions[].values[]`，也被同步清理
3. 已推送生成 Feature 的标签被级联删除，且 planner_work_items 的引用先被清空（无孤儿记录）
4. 乐观锁不匹配时返回 409
5. viewer 角色调用返回 403
6. 空 `valueIds` 或不传则返回 400
7. 幂等调用不报错（已删除的标签返回 `deletedFromFlat: 0`, `notFound: [...]`）

## 参考

- 详细设计文档：`D:/MyAgents/docs/narrative/multica-tasks/api-delete-ops-dimension-values-flat.md`
- 现有 API #3 实现位置：`pm-system/backend/app/routers/operations.py`（约第 499 行起）
- 现有工具函数复用：`_to_iso()`, `_now_iso()`, `require_not_viewer`, `OperationMatrix`

## 当前紧急场景

需要删除的 11 条实体标签 ID：

```
val_1777545719349_1i6d4qjd2  (小R必买S5)
val_1777545719349_fret8qt5f  (小R必买S6)
val_1777545719349_vax2jyh91  (小R必买S7)
val_1777545719349_q41dvegzg  (小R必买S8)
val_1777545719349_e13tfms2z  (小R必买S9)
val_1777545719349_5r8c7r9ws  (小R必买S10)
val_1777545719349_df4hie69u  (小R必买S11)
val_1777545719349_qvuxuamo8  (小R必买S12)
val_1777545719349_la3o384tv  (小R必买S13)
val_1777545719349_vb65mgcdv  (小R必买S14)
val_1777545719349_ceg5botaz  (小R必买S15)
```

这 11 条均仅存在于 `dimensionValues[]`，不在任何 `dimensions[].values[]` 中。
