# 策划周计划工作台 · 多选与批量操作（设计摘要）

- **日期**: 2026-04-22  
- **范围**: `pm-system/ui/components/planner-workbench.js` 仅前端；复用现有 `DataService.plannerUpdateItem` / `plannerDeleteItem`。

## 行为

- 每条卡片左侧 **复选框**；点击卡片正文区域仍打开编辑弹窗（与复选框互斥）。
- 列标题旁 **「全选本列」**：将该列当前展示条目的 id 全部加入选择集。
- **批量条**（有选中时显示）：已选数量；**移至下周**（`targetWeek` = 后端下发的 `nextWeek`）；**移至未排期**（`targetWeek: null`）；**彻底删除**（逐条调用与单条一致的矩阵同步抑制删除逻辑）；**取消选择**。
- 列表刷新后 **剔除已不存在 id** 的选择，避免幽灵选中。

## 未纳入（YAGNI）

- 后端批量事务 API（当前顺序 PUT/DELETE，失败条数 Toast 汇总即可）。
- 跨页/虚拟滚动（当前三列列表体量可接受）。

## 实现状态

已实现于 `planner-workbench.js`，与本文一致。
