# Work Log - MyAgents Root

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


## [2025-12-09] - [Task Reminder/增加优先级]

**状态**: 验收通过

**内容**:
- 任务增加优先级
- 任务卡片支持编辑
- 分组展示改为横向泳道形式
- 增加checked mark

**备注**: 
- 分组展示的横向泳道过长的情况未测试