# 策划周计划工作台 — 设计规格（Spec）

- **状态**：已获制作人「设计认可」（brainstorming 收口）
- **日期**：2026-04-20
- **范围**：PmSystem（`pm-system/`）内新增模块；MVP **不包含**卡片拖拽排周

---

## 1. 产品定义与边界

### 1.1 一句话

制作人视角的策划团队 **周排兵工作台**：本周 / 下周谁在干什么、未排期有哪些；**不**替代版本规划、设计到落地看板、策划个人 Todo。

### 1.2 用户与权限

- **仅制作人**使用；与权限模块对接后按角色控制可见性。
- 在权限未全量接好前，开发环境依赖既有 `dev_mode` / 角色约定，不扩大暴露面。

### 1.3 成功标准（MVP）

- **排盘**：每周约 **15 分钟**内可把「未排期」条目分配到本周/下周并指定负责人。
- **日常**：打开后 **10 秒内**能回答：本周各策划承载、谁空/谁满、有无明显停滞。

### 1.4 明确不做

- 不做策划个人任务系统；不替代版本规划；不替代设计到落地精细流转；**不做自动排期**。
- **MVP 不做**看板内 **HTML5 拖拽** 改周；改 `target_week` 仅在 **弹窗/表单** 中完成（brainstorming 选项 **A**）。

---

## 2. 总体方案（已定案）

在「无拖拽」前提下采用 **周列看板 + 弹窗编辑**：

- 横轴：本周 / 下周 / 未排期（可扩展「再下周」等，交互上滚动或 Tab，实现阶段再定）。
- 卡片：展示标题、负责人、阶段、分类、优先级；**点击**打开弹窗修改字段（含目标周）。
- 与「首版纯表格 MVP」「卡片行内下拉改周」相比，**优先保留排兵视觉**，交互成本用弹窗吸收。

---

## 3. 数据模型

### 3.1 实体：`WorkItem`

| 字段 | 说明 |
|------|------|
| `id` | 自增主键 |
| `title` | 标题，粗颗粒 |
| `category` | 枚举，见下表 |
| `assignee` | 成员 id，可空表示待分配 |
| `stage` | 当前阶段，**合法值依赖 category** |
| `target_week` | 目标周，**可空**表示未排期；格式 `YYYY-Www`（ISO 周），与 PM 版本规划周对齐的换算在实现阶段读取现有「周」数据源后固定算法 |
| `priority` | `P0` / `P1` / `P2` |
| `note` | 自由文本 |
| `status` | `active` / `done` / `parked` / `cancelled` |
| `linked_feature_id` | 可选；与 `version_delivery` 搭配 |
| `linked_pool_item_id` | 可选；存 **pool_items.id**，与 `pre_design` 搭配 |
| `created_at` / `updated_at` | 时间戳 |

### 3.2 `category` 与 `stage` 集合

| category | 说明 | stage 集合 |
|----------|------|--------------|
| `pre_design` | 前置设计 | 萌芽 / 探索 / 成型(WHAT) / UE方案 / 进入管线 |
| `version_delivery` | 版本交付 | **展示**以关联 Feature 的管线节点为准；WorkItem 本地 `stage` 可与展示合并策略在实现时二选一：**仅展示远端** 或 **缓存+刷新**，**禁止**写回 Feature |
| `data_analysis` | 数据分析 | 待启动 / 进行中 / 结论产出 |
| `ops_maintenance` | 日常运维 | 待处理 / 处理中 / 已解决 |
| `tool_automation` | 工具自动化 | 调研 / 开发中 / 已上线 |
| `learning` | 学习体验 | 进行中 / 已沉淀 |

### 3.3 与现有系统关系（只读关联）

```
需求池(Pool) ----可选----> WorkItem(pre_design)
Feature --------可选----> WorkItem(version_delivery)
设计到落地(design_landing) ---- 读取 WHAT-HOW 等展示用 ----
```

- 从 Pool / Feature **创建** WorkItem 时写入对应 `linked_*`。
- WorkItem 界面提供跳转至 Pool / Feature / 设计到落地详情。
- **不**通过本模块 API **修改** Feature 或 Pool 本体数据。

### 3.4 持久化

- 与现有 PmSystem 后端一致：使用 **SQLAlchemy + SQLite**（`backend/data/gamedev_pm.db`），新表随迁移或 `create_all` 策略与现有工程保持一致（实现阶段对齐现有 `Feature` 等表的迁移方式）。

---

## 4. API  surface（前缀 `/api/planner/`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/items` | 列表；支持 `week`、`assignee`、`category`、`status` 筛选 |
| POST | `/items` | 创建 |
| PUT | `/items/{id}` | 更新（**含在弹窗中修改 `target_week`**） |
| DELETE | `/items/{id}` | 见 §4.1 |
| GET | `/weekly-summary` | 按周聚合（人 × 条数 × 分类分布等，字段实现阶段细化） |
| POST | `/items/from-feature/{feature_id}` | 创建并关联 Feature，默认 `version_delivery` |
| POST | `/items/from-pool/{pool_id}` | 创建并关联需求池，默认 `pre_design` |

### 4.1 删除语义（MVP）

- **推荐**：界面「从看板移除」默认映射为 **`status = cancelled`**，保留审计与误操作恢复空间。
- **DELETE**：保留为**物理删除**能力（可选仅管理员或二期）；若 MVP 仅实现 `cancelled`，则 DELETE 可延后，但须在路由层与文档中二选一并避免「前端调 DELETE 却未实现」的悬空约定。实现阶段 **择一写死**并在本 Spec 更新一句最终结论。

### 4.2 校验与错误

- `target_week` 格式非法 → `400`。
- `linked_feature_id` 与 `category` 不一致 → `400`，或自动归一为 `version_delivery`（实现阶段选一种并写进路由单测）。
- 认证失败沿用全局 OIDC / dev 行为。

---

## 5. 前端（MVP）

### 5.1 入口

- 顶栏导航 + hash 路由（如 `#planner`），与现有 `index.html` 模式一致。

### 5.2 主视图

- 三列：**本周**、**下周**、**未排期**；列内卡片排序规则：**优先级**再 **标题**（实现可微调）。
- **无拖拽**；变更周次 → 弹窗内 `target_week` 控件（周选择器或下拉）。

### 5.3 弹窗字段

标题、分类、负责人、`target_week`、阶段、优先级、备注、关联对象只读展示与跳转链接。

### 5.4 分期（允许砍 scope）

- **MVP 必须**：主视图 + 弹窗 + CRUD + `from-feature` / `from-pool` + 列表筛选。
- **MVP 建议**：按人视图 + 顶部信号（停滞 / 未分配 / 负载）。
- 若工期紧：**按人视图与信号**可放入 **下一迭代**，本 Spec 仍保留其需求描述供 writing-plans 拆里程碑。

### 5.5 信号（目标行为）

- 超过 **N** 周未更新阶段：`N` 默认 **2**，可配置（实现阶段定存储位置）。
- 本周有条目但无负责人：分配缺口。
- 某人本周条目数 **> 3**：负载预警（阈值可配置）。

---

## 6. 与 Feature 管线同步（`version_delivery`）

- **只读**：打开页面或用户触发「刷新」时从 Feature 读取管线阶段用于展示；**不**写回 Feature。
- MVP **不依赖** WebSocket；轮询间隔若有，默认仅在进入模块时请求，避免刷爆接口。

---

## 7. 测试与验收（实现阶段）

- API：`POST/GET/PUT`、筛选、`from-feature` / `from-pool` 各至少一条 happy path；错误体 `400` 覆盖。
- 前端：三列正确分桶、弹窗保存后卡片移动到正确列、`version_delivery` 展示与 Feature 只读一致。
- 权限：制作人可见（对接权限模块后的用例）。

---

## 8. 后续流程（Superpowers）

1. 制作人审阅本 Spec 文件正文，确认无歧义后进入 **writing-plans** 生成实施计划。
2. 实现阶段禁止跳过：**WORK_LOG** 与仓库 **提交/推送** 仍遵守 `MyAgents` 根目录规则（仅用户明确要求时 commit/push）。

---

## 9. Spec 自检记录（2026-04-20）

- **占位符**：无 `TBD`；§4.1、§3.3 周对齐算法标注为「实现阶段固定」，属有界开放项。
- **一致性**：MVP 无拖拽与 §1.4、§2 一致；只读不写 Feature 与 §3.3、§6 一致。
- **范围**：单模块可单计划实施；按人/信号允许二期，已标明。
- **歧义**：`DELETE` vs `cancelled` 已显式要求实现时二选一并回填本句最终策略。
