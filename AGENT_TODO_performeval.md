# Agent 任务书：performeval

> 本文档供独立会话中的 Agent 使用，包含完整上下文和任务清单。

---

## 上下文（必读）

- **北极星**：单位成本产出的用户价值最大化（详见 `PLAYBOOK.md` §零）
- **核心决策**：D40-D58（详见 `PLAYBOOK.md` 附录 + `performeval/DESIGN.md` 讨论记录）
- **评价公式**：`最终得分 = 业务结果分 × 进化系数 × 摩擦系数 - 事故扣分 + 行为加分`
- **标尺设计原则**：整体评判 + 打分参考清单，不拆子维度加权（D45）
- **效能导向**：卓越档应可量化为效能指标（"省了多少、快了多少"）
- **AI 进化纲领**：无 AI 成果 → 进化系数上限 80%
- **四层模型**：WHAT/HOW/BUILD/MAKE，战斗纵向贯穿
- **生态**由数值接管（D55），数值在 WHAT 层参与决策
- **TeamScore** 功能考虑融入 PerformEval（D57）

## 必读文件

- [ ] `PLAYBOOK.md`（通读 §零~§七，重点 §六评价哲学、§七AI进化纲领）
- [ ] `performeval/DESIGN.md`（系统设计全文，重点 §十八 TODO）
- [ ] `performeval/rubric_ops.json`（运营策划标尺）
- [ ] `performeval/rubric_system_planning.json`（系统策划标尺）
- [ ] `performeval/rubric_tech.json`（技术标尺）
- [ ] `performeval/rubric_art.json`（美术标尺v2·含5子工种）
- [ ] `performeval/rubric_ue.json`（体验组标尺·含4子工种）
- [ ] `performeval/rubric_video.json`（视频标尺）
- [ ] `performeval/rubric_qa.json`（QA标尺）
- [ ] `performeval/共创工作表-L级标尺.html`（标尺模板结构）
- [ ] `performeval/会议材料-绩效方案启动会.html`（产品思路背景）

## 已完成

- ✅ 运营策划标尺 `rubric_ops.json`（L2/L3/L4 × 业务/进化/摩擦）
- ✅ 系统策划标尺 `rubric_system_planning.json`（L2/L3/L4 × 业务/进化/摩擦）
- ✅ 技术标尺 `rubric_tech.json`（L2/L3/L4 × 业务/进化/摩擦，MAKE层）
- ✅ 美术标尺 `rubric_art.json` v2（85条·共享底座+5子工种·animation/vfx/concept/modeling/ta）
- ✅ 体验组标尺 `rubric_ue.json`（73条·HOW层·4子工种·ux/ui/motion/audio）
- ✅ 视频标尺 `rubric_video.json`（37条·HOW+MAKE双层）
- ✅ QA标尺 `rubric_qa.json`（L2/L3/L4 × 业务/进化/摩擦，MAKE层）
- ✅ 标尺查看器 `标尺总览.html`（支持sub_function筛选）+ 共创工作表预览面板更新
- ✅ DESIGN.md 讨论记录同步至 D58，附录 A 更新
- ✅ 效能导向融入标尺 KPI（单活动人力成本、每 Feature 研发人天等）
- ✅ VP通气提纲 `VP通气-数值协作方案.html`
- ✅ 面谈准备材料 `面谈准备-数值主管协作.html`

## 任务清单

### P0-制度（Phase 0 阻塞项）

| # | 任务 | 验收标准 | 状态 |
|---|------|---------|------|
| P0-B | 编写各职能标尺 | 7职能346条完成（ops/system_planning/tech/art·v2/ue/video/qa）。**待补充**：`rubric_battle.json`（战斗·纵向四层）、`rubric_numerical.json`（数值·含生态·WHAT层） | 🔧 核心完成，战斗+数值待讨论 |
| P0-C | 校准成长窗口期参数 | 各 L 级在位时长 → 标尺递增系数确定 | 待开始 |
| P0-D | 确定组织蓝图（F3 目标编制） | 每个职能组的目标人数和 L 级分布 | 待开始 |

### P0-系统（Phase 2 核心开发）

| # | 任务 | 优先级 | 依赖 | 验收标准 |
|---|------|--------|------|---------|
| D-1 | 公式升级 + SystemConfig (F0) | P0 | — | 新公式上线，参数可配置 |
| D-2 | Member 模型升级（L 级、职能组） | P0 | — | 成员支持 L 级和职能组属性 |
| D-3 | 行为事件目录 + 录入 + 审核 (F5) | P0 | — | 行为事件 CRUD + 审核流程 |
| D-4 | 评分标尺存储 + 评价工作台集成 + RatingCap (F6) | P0 | P0-B 完成 | 标尺数据可导入，工作台展示标尺参考 |
| D-5 | 事故模块改造：IncidentRecord + IncidentMember (T0-T3 + 多责任人) | P0 | — | 事故支持多责任人和 T 级分类 |

### P1（重要）

| # | 任务 | 优先级 | 依赖 |
|---|------|--------|------|
| D-6 | 花名册导入 (F2) | P1 | 样表 |
| D-7 | 事故表导入 (F1) | P1 | 样表 |
| D-8 | 组织蓝图 (F3) | P1 | P0-D |
| D-9 | 个人发展追踪 (F4) | P1 | — |
| D-15 | 打分参考清单（Yes/No 检查项） | P1 | D-4 |
| D-17 | 职能组扩展：新增 `system_planning` 并分离 | P1 | — |
| D-18 | 标尺数据批量导入（从 `rubric_*.json`） | P1 | D-4 |

### P2（可延后）

| # | 任务 |
|---|------|
| D-10 | 红线预警 (F7) |
| D-11 | 钉钉机器人采集 API 预留 |
| D-12 | 管理员配置页面 |
| D-13 | 导入中心前端 UI |
| D-16 | 侧边栏外部链接到 `process_map.html` |
| PE-P2-1 | TeamScore 功能融入（M12 管理自评 + 七星互评数据导入/分析） |

## 标尺编写指南（P0-B）

战斗标尺需要体现纵向贯穿特性：
- L2 业务：各层基础执行（WHAT:资产清单准确 / HOW:体验配置无误 / BUILD:逻辑接入正确 / MAKE:装配按时交付）
- L3 业务：跨层协调能力（版本级资产规划 + 体验节奏优化 + 逻辑方案设计）
- L4 业务：全链路效能（定义装配标准框架，让 L2 工作可自动化）

数值标尺需要体现生态职能：
- L2 业务：配表准确、公式无误
- L3 业务：经济系统设计、玩法生态判断、数据驱动决策
- L4 业务：生态方向战略、AI 驱动数值自动化

## 设计约束

- 乘法层 = 管理者整体评判（主观），加法层 = 可举证行为事件（客观）
- 标尺档位：卓越(outstanding) / 达标(meets) / 待改进(developing) / 红线(red_line)
- 卓越档 = 指向下一 L 级基线，标尺随 tenure 递增
- 效能导向：高分 = 用更少资源产出更好结果
- 战斗标尺：纵向贯穿，不按单一层评价
- 数值标尺：含生态职能维度

## 不要做的事

- 不要修改 `PLAYBOOK.md`（根仓库管理）
- 不要修改 `pm-system/` 下的文件
- 不要处理 CCI 或 TaskReminder 相关任务
- 不要创建试点策略（D-P0-4 已定：全员直接上线）
