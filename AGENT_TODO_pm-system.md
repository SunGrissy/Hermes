# Agent 任务书：pm-system

> 本文档供独立会话中的 Agent 使用，包含完整上下文和任务清单。

---

## 上下文（必读）

- **北极星**：单位成本产出的用户价值最大化（详见 `PLAYBOOK.md` §零）
- **核心决策**：D40-D58（详见 `PLAYBOOK.md` 附录 + `performeval/DESIGN.md` 讨论记录）
- **四层模型**：WHAT / HOW / BUILD / MAKE（详见 `PLAYBOOK.md` §四）
- **战斗**是纵向贯穿职能（WHAT→HOW→BUILD→MAKE），资产装配导向
- **视频/创意** = HOW + MAKE（BUILD 层逻辑接入由战斗策划负责）
- **生态**由数值接管，process_map 中已移除独立生态职能
- **PLD 候选池** = 所有策划职能，不封死工种

## 必读文件

- [ ] `PLAYBOOK.md`（通读 §零~§七，重点 §四职权边界）
- [ ] `pm-system/process_map.html`（已完成四层泳道重构，熟悉数据结构）
- [ ] `pm-system/docs/pipeline-evolution-plan.md`（6-1 到 6-4c 开发计划）
- [ ] `pm-system/collaboration_guide.html`（现有流程指南）
- [ ] `pm-system/pm_config.js`（管线配置）

## 已完成（本轮）

- ✅ `process_map.html` 四层泳道重构（WHAT/HOW/BUILD/MAKE）
- ✅ 新增职能：程序、3D、设定、TA、视频、QA
- ✅ 移除"生态"独立职能（由数值接管）
- ✅ 战斗改为纵向贯穿（4 个泳道各有方块）
- ✅ 修复 13 个 stage item 缺失背景色的 CSS bug
- ✅ 修复 "DoR" vs "DoR检查" 命名不匹配
- ✅ PLD 描述更新（所有策划可担任）
- ✅ 生产/交付/发布阶段补全缺失 items（内容、资源、功能验证、监控）

## 任务清单

### P0（阻塞性）

| # | 任务 | 验收标准 | 依赖 |
|---|------|---------|------|
| 6-3a | Version 数据模型：新增 `pleUserId`、`pltUserId`、`pipelineWeight` 字段 | 版本创建/编辑弹窗可选 PLE/PLT 人员和管线重量 | 无 |
| 6-4a | PM DoR 落库 + 重命名为"内容就绪(Content Ready)" | Feature 弹窗中 4 项 DoR checkbox 带 id 落库到 `feature.contentReadiness` | 无 |

### P1（重要）

| # | 任务 | 验收标准 | 依赖 |
|---|------|---------|------|
| 6-2 | `pm_config.js` 角色配置：新增 PLE/PLT 定义、更新 `pipelineNodeTasks` 各节点角色 | 所有管线节点正确包含 PLE/PLT 角色 | 无 |
| 6-4b | 新增"体验就绪(Experience Ready)"：`feature.experienceReadiness`（PLE 侧 2 项检查） | Feature 弹窗新增体验就绪区块 | 6-3a |
| 6-4c | DoR 分层逻辑（按 `pipelineWeight`）：慢轨三把锁，快轨一把半锁 | 快轨 Feature 不要求交付就绪，慢轨要求全部通过 | 6-3a, 6-4a, 6-4b |
| 6-3b | Feature 数据模型：新增 `contentTier`（S/A/B 内容体量） | Feature 弹窗可选内容体量 | 无 |
| 6-2+ | 前端 pipeline 组件适配 PLE/PLT | 版本详情页展示 PLE/PLT 信息，pipeline 组件正确渲染新角色 | 6-2, 6-3a |
| 6-1 | `collaboration_guide.html` 更新：PLE/PLT 角色定义、轮值机制、快慢轨差异 | 文档完整反映四层模型和三角色轮值 | 无 |

### P2（可延后）

| # | 任务 | 验收标准 |
|---|------|---------|
| PM-P2-1 | `process_map.html` 交互增强：点击泳道层级标签筛选该层所有职能 | 点击 WHAT/HOW/BUILD/MAKE 标签可筛选 |
| PM-P2-2 | 版本级效能仪表盘（pipeline-evolution-plan.md 中描述的人效/时效/质效/成本/转化） | 复盘页面展示效能对比 |

**建议执行顺序**：6-3a → 6-4a → 6-2 → 6-4b → 6-4c → 6-1 → 6-3b → 6-2+

## 设计约束

- WHAT/HOW/BUILD/MAKE 四层模型是核心框架，所有改动必须与之一致
- 战斗 = 纵向贯穿，不归入单一层
- 视频不进 BUILD 层（逻辑接入由战斗策划负责）
- PLD 候选 = 所有策划（运营/战斗/系统/数值），不封死
- 快轨系统策划不参与
- DoR 分层：慢轨三锁（内容+体验+交付），快轨一把半锁（内容+PLE 确认）
- 效能导向：每个改动回答"省了什么？快了多少？"

## 不要做的事

- 不要修改 `process_map.html` 的四层泳道结构（已完成验收）
- 不要恢复"生态"为独立职能
- 不要修改 `PLAYBOOK.md`（那是根仓库管理的）
- 不要处理 performeval 相关任务
