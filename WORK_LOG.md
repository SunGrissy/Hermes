# Work Log - MyAgents Root

## 2026-03-09 - MD Reader 轻量 Markdown 阅读器

**状态**: 已提交

**内容**:
- 新建 `md-reader/` 工具：轻量 Markdown 阅读器（Python 标准库 + 单页 HTML）
- 后端 `server.py`：文件扫描、内容读取、全文搜索 API
- 前端 `index.html`：文件树侧边栏、GitHub 风格渲染（marked.js + highlight.js）、全文搜索、收藏（localStorage）、导出 PDF
- 启动方式：`python3 md-reader/server.py` → `http://localhost:8899`

---

## 2026-03-09 - Palace 版本预审 v0.4 迭代 + 版本规划文档入库

**状态**: 开发完成，待验收

**内容**:
- 版本预审报告大幅重构：异常优先总览、版本级问题速查表、Feature 状态速查、passed feature 过滤
- engine.py：新增 severity_hint 校准机制、passed feature 判定、emoji 剥离、reminder 关键词扩充
- report.py：版本报告渲染器重写（_version_summary / _version_issue_table / _merge_role_comments）
- schemas.py：checklist 新增 severity_hint 字段
- layout_analyst.yaml：品类特征注入、分类与严重度规则、VERSION 层归类指导
- llm_client.py：MockProvider 版本预审数据同步更新
- 入库 3 份版本规划文档（0318/0401/0422）和 6 份预审报告
- 入库 1 份管线 PM 评价文档

**备注**:
- 审查发现 P0 级 verdict-vs-P0 矛盾问题，待下轮修复
- 子模块指针变更非本次改动，未纳入提交

## 2026-03-05 - Palace 预审引擎 v0.4 全量入库 + 文档规范

**状态**: 验收通过

**内容**:
- Palace 预审引擎 v0.4 完整代码入库：两步流程架构（提取→评估→合成）、4 个审查角色、6 个场景配置
- 新建 `DOC_SPEC.md`：策划 Feature 文档规范（标注协议、文档分类、结构模板、审查档位说明）
- 更新 `DESIGN_NOTES.md`：新增 v0.5 三大方向——文档分类感知+审查档位、标注协议、审查角色定位
- 三份真实文档审查报告（四象角力、开火挑战、神君随心购礼包）
- robust JSON 解析：处理 LLM 输出中的未转义引号、markdown 围栏等异常格式
- issue grouping：语义相关检查项自动合并，减少报告冗余

**备注**:
- .env 含 API 密钥，已通过 .gitignore 排除
- 中间迭代产物（v2-v9 报告、debug 输出、测试 JSON）已排除
- 已暂存的 PLAYBOOK.md 和 PLAN_双Git工作流迁移.md 一并提交（前序会话的改动）

## 2026-03-05 - Bridge 对接规范文档

**状态**: 已完成

**内容**:
- 新建 `BRIDGE_SPEC.md`：智能管理工具体系与 Ultra 的对接技术方案（12 章节）
- 架构设计：三层编排模型（意图编排/业务编排/投递编排）、三种通信流向
- MVP 接口契约：PmSystem 版本管理 + Feature 管理 + 仪表盘（完整出入参）
- 能力发现机制：`/bridge/capabilities` 兼容 Function Calling 格式
- 事件系统：订阅/推送协议、8 种 MVP 事件类型
- 职责边界：Bridge 管"办事记录"，Ultra 管"理解人通知人"
- 待确认清单：U1-U8 共 8 个问题需 Ultra 方回复
- 新建 `BRIDGE_PM_API_REQUIREMENTS.md`：PmSystem 细粒度 API 改造需求（供 pm-system Agent 执行）
- Bridge 采用两阶段适配策略：短期厚适配（基于现有 /api/data），长期薄代理（等 PmSystem 补接口）

**备注**:
- 子模块为私有仓库，云环境无法检出，API 契约基于 pm_requirements.md 和 AGENT_TODO_pm-system.md 推导
- Bridge 项目代码尚未开始，本次仅输出设计文档
- 推送通道原则上交给 Ultra，Bridge 保留应急直连钉钉 webhook

## 2026-03-03 - Palace Instructor 集成方案文档

**状态**: 方案文档已输出，待 Palace Agent 评审

**内容**:
- 新建 `palace/INSTRUCTOR_INTEGRATION.md`：Instructor 集成的完整技术方案
- 改造范围：schemas.py（新增 Pydantic 模型）+ llm_client.py（Instructor 路径 + fallback）+ requirements.txt
- 不改动文件：engine.py / report.py / MockProvider / config.py / knowledge.py / run.py / 所有 YAML
- 7 项已识别风险及应对措施
- 完整字段一致性验证清单（engine.py 中所有 .get() 访问点 vs Pydantic 字段名）
- 6 项测试验证计划

**备注**:
- 方案核心思路：Provider 内部消化类型转换，对外接口返回 dict 不变
- _robust_json_parse 保留为 fallback，Instructor 是增强层不是替代层
- 待 Palace Agent 评审后执行

## 2026-03-03 - 工作室会议体系架构设计

**状态**: v2 已完成，待验收

**内容**:
- 新建 `MEETING_SYSTEM.md`：工作室全局会议体系架构文档（12 章节）
- 双轴设计：事轴（版本仪式 / Feature 质控 / 管线运营 / 经营决策）+ 人轴（全员触达 / 职能组 / 个人发展）
- Feature 级质控：设计审核、内容审核、战斗审核、体验走查、Feature 数据复盘，均为 Feature 维度 event-driven
- 工具门禁：DoR / DoD / 滞留预警 / 返工追踪，PmSystem 强制
- 会前清单制替代传统会议纪律
- 版本 Retro 拆分为流程 Retro(+1 周)和数据 Retro(+1 月)
- 新增专题数分报告机制（按需触发）
- 问责闭环三层机制：会议内归因 → 问责追踪表 → 绩效挂钩（正负强化）
- 委托路径：制作人退出各会议的条件和优先级排序
- 工具化路线：当前人工 vs 目标自动化对照，含度量指标
- 制作人保护时段：每周 2 个半天不可预约
- 季度会议审计自审机制
- 紧急状态协议：P0 事故 / 关键人离职 / VP 升级 / 版本紧急
- 附录：通用框架 vs 本项目参数标注（对齐 PLAYBOOK 结构）
- 初级管理者指引调整为"硬性要求 + 合理性背书"风格

**备注**:
- APM 角色明确：聚焦版本级 PMO 职能，不做全工作室会议秘书
- 数值组以协作者身份纳入 WHAT 层月度同步，不改变 VP 直管汇报关系
- M12 / 七星互评不入会议体系，在闭门战略会常设议题池中按需讨论
- 制度建设期沟通风格：硬性要求 + 合理性背书（阶段性策略）

## 2026-03-03 - Agent 门禁检查体系 + Skill 生态建设 + 双 Git 工作流

**状态**: 验收通过

**内容**:
- 重构 `agent-core.mdc`：用四道可执行门禁（post-edit / pre-commit / pre-push / on-accept）替换原"三层自测"
- 新建 `preflight-checks` Skill：门禁检查失败时的详细修复指南
- 安装 3 个社区 Skill：frontend-design、webapp-testing、fastapi-router
- 自建 3 个项目 Skill：vanilla-js-ui-patterns、pm-data-sync、multi-service-orchestration
- 新建 `dual-git-sync` + `github-ops` Skill：GitLab↔GitHub 双 remote 协作流程
- 更新 `git-workflow.mdc`：验收流程加入合并冲突处理和合并后测试
- 新建 `git-branch-guard.mdc`：SESSION_BRANCH 绑定 + 操作前验证 + worktree 推荐
- 新建 `worktree-workflow.mdc`：多任务并行创建/命名/合并/清理规范
- 完善 `.gitignore`（根仓库 + pm-system + performeval）
- `.gitmodules` 改为相对路径，支持双 remote 子模块 clone

**备注**:
- 双 Git 首推等待 P-1 密钥外置化完成后执行
- Skill 安装在 `~/.cursor/skills/`（个人级，跨项目可用）

## 2026-03-03 - 版本管理合规化：pm-system + performeval API 规范对齐

**状态**: 已完成，待验收

**内容**:
- pm-system: `/api/version` 响应字段 `version`→`app_version`、`server_start_time`→`server_start`，新增 `last_update`/`last_update_ts`
- pm-system: `/api/health` 补齐 `app`、`version` 字段
- pm-system: `FastAPI()` 构造器注册 `version=APP_VERSION`
- pm-system: `version-tracker.js` 适配新字段名，兼容新旧两种 API 格式
- performeval: 静态文件 Cache-Control 从 3 个显式路由改为 HTTP 中间件统一覆盖
- task_reminder: 跳过（server.py 非真实 FastAPI 后端）

**备注**:
- 版本号未递增，仅做格式合规化（pm-system v1.0.0、performeval v2.1.0 不变）
- version-tracker.js 做了向后兼容处理，同时支持 `app_version`/`version` 和 `server_start`/`server_start_time`

## 2026-03-02 - Git 工作流增强：会话分支安全检查 + Worktree 多任务并行规范

**状态**: 验收通过

**内容**:
- 更新 `git-workflow.mdc`：新增"会话启动分支安全检查"章节，Agent 首次写操作前必须检查分支状态和未提交改动
- 更新 `git-workflow.mdc`：重构"验收通过"流程，加入合并冲突处理流程（Agent 分析+建议，用户决策）和合并后测试流程（Agent 自测报告）
- 新建 `worktree-workflow.mdc`：定义 worktree 创建/命名/合并/清理的完整规范，支持多会话并行开发

**备注**:
- worktree 清理改为事件驱动（验收时 + 会话启动时 + 数量超限时），不依赖用户主动记得
- stash vs commit 选择权交给用户，Agent 负责说明区别

## 2026-03-02 - Rules 规范体系重构：通用化 AgentX / 回归测试 / 版本管理

**状态**: 验收通过

**内容**:
- 新建根目录通用 `agentx.mdc`：工作流、三层自测、任务注释、并行隔离等通用规则
- 新建根目录通用 `regression-testing.mdc`：L0/L1/L2 分层回归、问题分级（P0/P1/P2）
- 升级 `version-management.mdc` 为强制规范：新增 /api/health、VersionTracker 模块模式、扩充接入清单
- 提升 `shell-git.mdc`（从 cci_system）和 `git-branch-guard.mdc`（从 performeval）到根目录
- 精简 pm-system 和 performeval 的 `agentx.mdc`，仅保留项目专用部分
- 删除 `pmsystem-regression.mdc`（已被通用版替代）

**备注**:
- 根目录 rules 从 7 个增至 10 个（新增 agentx、regression-testing、shell-git、git-branch-guard；删除 pmsystem-regression）
- 子项目专用 rules 不变（cci_system 5 个、pm-system 1 个、performeval 2 个）

## 2026-03-02 - 多项目服务启动修复 + Git submodule 状态修复

**状态**: 验收通过

**内容**:
- pm-system: 修复 backend/main.py 中 6 处 emoji 导致 Windows GBK 终端 UnicodeEncodeError 崩溃
- pm-system: 修复 quick_start.bat 后端绑定 127.0.0.1 导致局域网设备无法访问，改为 0.0.0.0
- performeval: 修复 run.bat 启动脚本——改为前台运行防服务丢失、移除不存在的 watchdog.bat 引用、补充 --reload
- 修复 4 个子模块（cci_system、performeval、task_reminder、teamscore）的 detached HEAD 状态，全部归位到主分支

**备注**:
- pm-system/backend/main.py 中钉钉消息体内的 🤖 emoji 保留（非 print 输出，不触发 GBK 问题）
- data-manager.js 有未提交修改，属于其他会话产物，未纳入本次提交

## 2026-03-02 - PmSystem 数据导入两阶段预览 + UI 优化

**状态**: 验收通过

**内容**:
- 重构 `importJSON` 为两阶段流程：先展示预览对比，用户确认后才实际写入数据
- 提取 `_executeImport` 方法封装数据写入逻辑，与预览计算解耦
- 预览弹窗 UI 从表格布局改为卡片式布局：Pill 标签展示增/删/保留数量，紧凑且一目了然
- 运营标签变更改为箭头对比（`12 → 15 (+3)`）
- 弹窗宽度收窄至 480px，圆角加大，按钮风格统一

**备注**:
- 导入确认前不会修改任何应用状态和 localStorage

## 2026-03-02 - PmSystem 冲突合并字段级修复

**状态**: 验收通过

**内容**:
- 修复 `_doConflictMerge` 中用户选择后"整条替换"导致三方自动合并结果丢失的核心 Bug
- 将 `_smartMerge` 的三方上下文（`_conflictFields`/`_autoMerged`）注入弹窗数据源 `dialogItems`
- 用户选择"本地"时改为字段级替换（仅替换冲突字段），保留自动解决的字段
- 用户选择"服务器"时利用 `smartMerged` 已默认取 server 值的特性，无需额外操作

**备注**:
- 延迟处理路径（当前页面无关冲突时 apply localData）留作已知限制，需独立架构改造
- 死代码 `_applyConflictChoices`/`_mergeByChoices` 未清理，待后续统一整理

## 2025-12-04 - My Army Git工作流架构初始化

**状态**: 验收通过

**内容**:
- 初始化根仓库作为"总司令部"
- 添加5个子模块（gamedev-pm-system, align-flow, central-console, llm-plotter, workspace-docs）
- 创建 `GIT_WORKFLOW_GUIDE.md` 工作流指南
- 配置 `.gitignore` 排除临时文件
- 建立 Root Repo + Submodules 架构

**备注**: 
- 采用 Gitlink 方式追踪各子模块的版本（Commit Hash）
- 根仓库代表系统的"Total Score"（总进度）
- 各子模块保持独立的 Git 历史


## [2026-03-03] - [规则体系/子模块 Git 操作规范补全]

**状态**: 验收通过

**内容**:
- `shell-git.mdc`：新增"推送"口令流程，触发 pre-push P1-P3 门禁 + 子模块先推序列
- `agentx.mdc`：入场快照增加 `git submodule status`，区分 m/M/+ 子模块标记
- `git-workflow.mdc`：新增"子模块 commit 闭环"铁律，commit 后必须回根检查指针

**备注**:
- 补的是 acceptance-checklist 未覆盖的 3 个边缘场景（单独推送、入场识别、非验收 commit）
- 同会话还更新了 palace/PLAN.md（9 角色图谱），已在前一个 commit 提交


## [2026-03-01] - [规则体系/验收流程统一 + 会议体系对齐]

**状态**: 验收通过

**内容**:
- 新建 `acceptance-checklist.mdc`：验收流程唯一入口，8 步从分支检查到推送完成
- 统一 push 策略为"验收即推送"，消除根目录/pm-system 的不一致
- 显式子模块→根仓库推送序列，解决 Agent 遗漏根仓库更新的问题
- `MEETING_SYSTEM.md` 与 `PMO_章程.md` 双向对齐（组织数据、PM/APM 分工、问责引用）
- 更新 5 个规则文件加入 checklist 引用指针

**备注**:
- 涉及 6 个 .mdc 文件 + 2 个 .md 文件

## [2025-12-09] - [Task Reminder/增加优先级]

**状态**: 验收通过

**内容**:
- 任务增加优先级
- 任务卡片支持编辑
- 分组展示改为横向泳道形式
- 增加checked mark

**备注**: 
- 分组展示的横向泳道过长的情况未测试