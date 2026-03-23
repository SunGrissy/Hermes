# Work Log - MyAgents Root

## 2026-03-23 - pm-system 子模块：数据源/dashboard/配置修复推 tygit

**状态**: 已推送 tygit（子模块 `origin main` + 父仓同步子模块指针）

**内容**:
- `pm-system`：`feat(pm-system): 数据源统一、dashboard 与版本摘要对齐、配置加载修复`（commit `46ffc1d` 起）

---

## 2026-03-20 - dingtalk-desktop 通道/路由与备忘提醒脚本；ue-review 规则；子模块推送

**状态**: 已提交推送 tygit

**内容**:
- 父仓：`dingtalk-desktop/lib/monitor.py`、`utils.py`、`skill_router.py`；`memo_reminder.py`、`register_memo_reminder_task.ps1`、`run_memo_reminder.ps1`、`skills/status_check.py`；`.cursor/rules/ue-review.mdc`
- `md-reader` 子模块：`index.html`、`server.py` 大块更新已提交并推 tygit
- `performeval`：将未推送的 `master` 提交推至 tygit `origin`

---

## 2026-03-20 - Git：默认仅推 tygit；novel 独立 GitHub 仓；规范与 Skill 同步

**状态**: 已完成（已 `git push origin main` → tygit）

**内容**:
- 父仓及 pm-system / performeval / cci_system / task_reminder / teamscore：`origin` 去掉 GitHub 双 push，仅 tygit；保留 `github` remote
- `novel/`：独立仓库 `https://github.com/SunGrissy/novel.git`，父仓 `.gitignore` 忽略并从索引移除跟踪
- 更新：`dual-git-sync` Skill、`shell-git.mdc`、`acceptance-checklist.mdc`、`git-workflow.mdc`、`github-ops` Skill、`workspace-map.mdc`、`.cursor/skills/README.md`

---

## 2026-03-20 - performeval 子模块：陈子豪面试材料（简历 PDF + 初试清单 + 初审报告）

**状态**: 已提交推送 tygit（显式 URL，未推 GitHub）

**内容**:
- 同步 `performeval` 子模块指针：`面试/陈子豪_运营策划/`（含 `陈子豪_简历.pdf`）、`面试/简历初筛/初审报告_陈子豪_运营策划.md`，子模块内 `WORK_LOG.md` 已记一笔

---

## 2026-03-21 - dingtalk-desktop：日报拉取/定时/自检与简历轮询超时

**状态**: 验收通过（已提交推送 tygit origin）

**内容**:
- `report_digest.py`：`import time`；`_report_body` 与全文拉取策略；`--fetch-only`/`--window overnight-morning`/`--after`/`--before`；`--full-content`+fetch-only 钉钉全文；`--notify-default` 进度精简；Markdown 分片推送
- `run_daily_digest.ps1`：子进程超时、进度/失败 webhook（ASCII 安全）、关键词「小秘书提醒」
- `restart_daemon.ps1`：ASCII 输出；`daemon_health_notify.py`、`run_daemon_health_notify.ps1`：health+可选重启+default 通知
- `skill_router.py`：简历轮询 `/fetch` 超时 75s
- `message_templates.json`、`digest_config.json`：`report_digest` LLM 字数等
- `db/store.py`、`skills/memo_tracker.py`：与 03-20 备忘/选题/运维同期改动一并入库

---

## 2026-03-20 - dingtalk-desktop：快捷指令（人员筛选/选题独立号/运维/双发去重）

**状态**: 验收通过

**内容**:
- `db/store.py`：`topic_items` 选题独立编号；选题 CRUD/同步辅助
- `skills/memo_tracker.py`：人员关键词筛选；选题走 `topic:#N`；备忘改描述/指派去重锁与文本归一；`_consume_edit_cmd_dedup` 原子化
- `skills/desk_ops.py`：检查大门、重启大门、拉日报（含 `--notify-default`）
- `desk_ops_restart.py`、`daemon_health_notify.py`（`--no-webhook`）
- `skill_router.py`：desk_ops 与人员节流锁 `_MEMO_THROTTLE_LOCK`
- `digest_config.json`、`message_templates.json`
- `report_digest.py` / `run_daily_digest.ps1` / `version_digest.py`：与日报进度通知、定时任务说明等同期调整（见 dingtalk-desktop/WORK_LOG）

---

## 2026-03-20 - pm-system 子模块：ApiClient 版本级权限 shim（恢复版本发布按钮）

**状态**: 已推送 tygit（`origin`）；子模块 `main` 指向 `06f173a`

**内容**:
- `pm-system/api-client.js`: 补充 `hasVersionPermission` / `requireVersionPermission` 兼容实现，与 `hasPermission` 默认放行一致；修复版本列表发布/编辑/删除按钮因方法缺失不渲染的问题

---

## 2026-03-19 - dingtalk-desktop 手机 push 备忘补水与 /fetch 稳定性

**状态**: 已推送 tygit（`origin` → `http://tygit.tuyoo.com/...`）；GitHub 同次 push 被拒（远端超前，需另 `pull --rebase` / `merge` 后再推）

**内容**:
- `lib/monitor.py`: 本人消息在手机仅 push、无 send 时仍 `memo_callback` 入队；push 时间戳毫秒化与发送者字段兜底
- `skill_router.py`: push 正文为空且 `content_type==1` 时调 `/fetch` 按时间对齐补全文；补水超时 75s + 失败重试 1 次（缓解 `_fetch_lock` 排队）
- `daemon.py`: `_json_response` 写响应时忽略客户端已断开（避免 WinError 10053 刷屏）

---

## 2026-03-19 - dingtalk-desktop 备忘延期与关注列表读 TR

**状态**: 已推送 tygit（`origin`）

**内容**:
- `skills/memo_tracker.py`: 「N、M推到明天」类延期；今日/明日/本周关注优先从 TaskReminder 拉取，失败回退 SQLite；`_get_pending_memos_from_tr`
- `skill_router.py`: 延期指令路由；明日关注正则支持「明天要关注啥」
- `db/store.py`: `update_memo_due`
- `message_templates.json`: `defer_*` 模板
- `WEBHOOK_消息来源说明.md`: 备忘延期与日志说明

---

## 2026-03-19 - dingtalk-desktop 备忘按群 Webhook、footer 分割线

**状态**: 已推送 tygit（`origin` → `http://tygit.tuyoo.com/...`）；GitHub `main` 远端超前，本次未快进合入，需另 `fetch github` + `merge/rebase` 后再推

**内容**:
- `skills/memo_tracker.py`: 备忘/TR/完成删除/关注等回复与许愿共用 `wish_reply_webhook_by_cid`；自动 footer 前插入分割线（模板 `separator`/`footer_separator`）；`_send_webhook` 统一选 Webhook
- `skill_router.py`: 今日/明日/本周关注传入 `group_cid`
- `digest_config.json`: `wish_reply_webhook_by_cid` 与白名单群说明、关键词说明
- `message_templates.json`: memo_tracker footer 分割线说明
- `skills/doc_review.py`、`db/store.py`: 预审与数据库配套（本轮一并提交）

---

## 2026-03-19 - pm-system 子模块：UE 预审与 Boss 对齐（tygit 已推送）

**状态**: 已推送

**内容**:
- `pm-system`（子模块 `main` df5a4fb）: `backend/main.py` UE 预审 API、`/upc` 与 `upc-ctrl` 路由；`ue-precheck/*`；`boss-precheck/list` 互链

---

## 2026-03-19 - dingtalk-desktop 文档预审进度心跳与完成摘要样式

**状态**: 验收通过

**内容**:
- `skills/doc_review.py`: 预审长流程后台按间隔 webhook 推送阶段与已等待秒数（可配置，0 关闭）；完成摘要重构为分层 Markdown、清单数与 issues 列表对齐、原文/报告短链、截断与展示条数可配
- `message_templates.json`: `doc_review` 新增 `progress_update`、摘要分段/统计/链接等模板键

---

## 2026-03-19 - dingtalk-desktop 备忘/预审推送与文档预审

**状态**: 验收通过

**内容**:
- `daemon.py`: 助理群 `memo_callback` 入队不再依赖 `MY_UID` 与本人判定，避免本人指令被误丢
- `skill_router.py`: 预审强制重跑口令（再预审/强制预审等）；推送路径缓存最近文档 URL，优先免 `/fetch`；推送侧时间窗与路由调整
- `skills/doc_review.py`: 新增文档预审技能（AliDocs + Palace）；`force_bypass_recent_window` 跳过短时去重
- `message_templates.json`: 预审相关模板与说明
- `lib/monitor.py`、`lib/utils.py`、`db/store.py`、`digest_config.json`、`memo_tracker.py`、`resume_screen.py`: 备忘推送、去重与配置配套

---

## 2026-03-19 - cursor-to-dingtalk Webhook 发送日志

**状态**: 验收通过

**内容**:
- `send_result_webhook.py`: 成功发送后向 `dingtalk-desktop/logs/cursor_webhook_sends.log` 追加一行（时间、DINGTALK_TITLE、正文长度），便于按钉钉收到时间反查是哪个 Agent 发的
- `SKILL.md`: 新增「事后查是哪个 Agent 发的」一节，说明 log 路径与对照方式

---

## 2026-03-19 - dingtalk-desktop 稳定性修复（AgentFix）

**状态**: 验收通过

**内容**:
- `daemon.py`: 引入 `_frida_call` 超时包装（3s），防止 Frida `exports_sync` 卡死导致 `_fetch_lock` 永久持有；`_wait_for_fetch_beacon` timeout 从 30s 压缩至 8s；HTTP handler 正确传递 `max_seconds` 参数；`fetch_history`/`fetch_reports_paginated` 加锁前预检 JSAPI 可用性
- `report_digest.py`: `fetch_full_contents` 加防腐层 `_looks_like_error_page`，URL 过期返回 400 时不覆盖原文本；stdout 强制 utf-8（防 GBK 崩溃）；`_daemon_request` timeout 75s；fetch 失败后 3s 缓冲
- `run_daily_digest.ps1`: 日志写入从 `Add-Content` 改为 `.NET AppendAllText`（解决 GBK 乱码）；加失败告警（输出 <3 行时发 webhook 通知）
- `digest_config.json`: 新增「思奕汇报直通车」「数值小分队」两个日报群
- `message_templates.json`: 所有补充平面 emoji 替换为 BMP 安全字符
- `skill_router.py`: 支持 `cid_names` 映射、`source_name` 上下文传递
- `db/store.py`: 数据层工具函数补充

---

## 2026-03-19 - 策划岗简历初筛规则迭代 + 团队人数 93→80

**状态**: 已提交

**内容**:
- 简历初筛：新增钉钉AI审查要求文档，通用清单补充品类匹配度/稳定性/游戏经验/多维度叠加降档；SKILL 与 README 同步；团队人数表述 93 人→80 人（根目录、performeval、palace、producer-context、会议材料等）

---

## 2026-03-18 - 新增活动界面 UE 审核规则

**状态**: 验收通过

**内容**:
- 新增 `.cursor/rules/ue-review.mdc`：固化活动界面 UE 审核视角与方法，覆盖 WHAT→HOW 审核边界定义、功能清晰度/信息层级/玩家心理视角三个核心维度、活动驱动力审核要点、反馈写作规范、常见判断陷阱五个模块
- 更新 `.cursor/rules/growth-advisor.mdc`：新增与 ue-review 的相关规则索引，明确两者边界（买量素材 vs 游戏内活动界面）

---

## 2026-03-10 - Palace Engine 预审报告质量迭代（冗余去重 + 可读性优化）

**状态**: 验收通过

**内容**:
- report.py: Feature 报告跨视角去重（_dedup_comments_with_labels）；P0/P1 标题显示判定依据替代矛盾的状态图标；下游传递诊断子标题提级为 ## 级；建议前置 + 诊断文字拆 bullet；编号 1) 2) 自动换行；P0 区块加明确标题（⚡ 必须处理）；pass 级冗余评论过滤；Generated by 移到顶部 + 字数统计
- engine.py: Assessment prompt 增加跨角色去重指令；block 判定标准收紧为「下游完全无法启动 / 安全风险」；incomplete 状态给 0.5 权重改善评分；layer_focus 机制支持角色层级边界控制
- what_precheck.yaml: PLE/PLT 增加 layer_focus 约束（WHAT 预审不展开 HOW/BUILD 方案）
- boundary.yaml: 新增替代关系过渡 / 跨Feature耦合 / 长期生态影响 review_dimensions；分层识别优先级指引
- DOC_SPEC.md: 单文档层级标记规范（[WHAT]/[HOW]/[BUILD] 章节标记）

---

## 2026-03-10 - MD Reader 导出 PDF 完整内容且不分页

**状态**: 验收通过

**内容**:
- index.html：增强 @media print 样式，使导出 PDF 时输出完整内容（解除 height/overflow 限制），并对标题/段落/列表等设置 break-inside: avoid 减少分页断裂

---

## 2026-03-10 - Palace Engine 文档类型检测 + Feature 模式降级

**状态**: 验收通过

**内容**:
- layout_analyst.yaml: 新增第零步文档类型前置检测，自动识别版本规划 vs 单 Feature 文档
- schemas.py: extraction 输出新增 detected_doc_type 字段
- engine.py: 检测到 Feature 文档时自动切换评审维度（版本级维度跳过，Feature 级维度替代）
- version_layout.yaml: review_dimensions 标注 [版本级]/[通用]，增加 review_dimensions_feature 替代集
- report.py: Feature 模式渲染适配（标题后缀、disclaimer、dashboard 标题、维度表跳过、区块解释文案）
- report.py: Feature 完备度速查表截断从 35→80 字符 + 增加编号列
- llm_client.py: JSON 解析增强，处理 Claude 的 code fence 包裹和 thinking 前缀
- DOC_SPEC.md: 扩展版本规划模板、扩展标签体系、交互需求四要素、数值框架增强
- run.py: 增加 --publish 参数支持 Palace Web 推送
- requirements.txt: 新增 fastapi/uvicorn/httpx 依赖

---

## 2026-03-10 - PerformEval 新增面试文档目录

**状态**: 已提交

**内容**:
- performeval 下新建「面试」目录，存放复试考察清单、初试评价等面试相关文档
- 子模块提交并推送后，根仓库更新 performeval 指针并推送

---

## 2026-03-09 - Palace Engine v0.6 报告渲染迭代

**状态**: 已提交

**内容**:
- report.py: P1 图标改为红旗(🚩)、去掉"额外发现"标签、Feature 报告重构（下游传递诊断/BUILD 层风险独立分区）
- report.py: 版本报告跨层观察与风险项同级渲染、P0 必解项加醒目标记、去掉"本项无角色评估"占位文本
- report.py: 相关原文防御（需含引号且长度>15才渲染）
- engine.py: 诊断语句区分事实与判断的 prompt 引导、Feature 报告 passed 项过滤修复、doc_completeness_score 移植
- llm_client.py: 新增 ops/shop/contest 三类 mock 数据、extracted_text 改为文档引用格式
- run.py: 标题自动从文件名推断（不再必须传 --title）

---

## 2026-03-09 - DOC_SPEC 全面升级 + 7 份预审报告重跑

**状态**: 已提交

**内容**:
- 用真实 LLM 重跑 3 份版本内容规划预审（0318 v6 / 0401 v5 / 0422 v5）
- 用真实 LLM 重跑 4 份功能预审（锦标赛 v2 / 四象角力 v2 / 开火挑战 v2 / 神君随心购 v2）
- 分析 7 份报告的共性缺口（版本级 11 项共性 + Feature 级 15 项共性）
- 更新 DOC_SPEC.md（302行 → 464行）：
  - 新增：版本内容规划文档模板（4.4 节）
  - 新增：8 个扩展标注标签 + 跨层标注规则
  - 增强：全新设计模板（功能范围、分层体验目标表、交互四要素、决策清单增强）
  - 增强：运营活动模板（体验意图必填、分层目标、交互四要素）
  - 新增：版本规划快速对照表
  - 新增：FAQ 问题 4（版本规划为什么需要正式文档）
  - 审查档位表增加"版本排布预审"

---

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


## [2026-03-18] - [dingtalk-desktop 日报摘要+版本巡检推送]

**状态**: 验收通过

**内容**:
- daemon.py: ThreadedHTTPServer 避免死锁、bf 结构化数据优先解析、fetch_report_content 改用 readyState 轮询替代固定 sleep、card_ext 正文提取、文件下载触发
- lib/utils.py: psutil 优先获取钉钉主进程 PID，fallback 到 wmic
- report_digest.py: Monitor 日志补充 JSAPI 遗漏消息、角色差异化 LLM prompt、技术动态提取、同人去重、消息模板外部化
- version_digest.py (新): PmSystem 版本状态巡检推送，支持定时+手动触发
- message_templates.json: 三套消息模板(版本巡检/日报摘要/简历筛选)统一到一个文件，emoji 安全处理
- run_daily_digest.ps1: --full-content 模式 + 完成后自动重启钉钉恢复 UI
- 定时任务: 日报 09:00、版本巡检 15:00

**备注**:
- digest_config.json 含 webhook token 和 api_key，已 track（历史遗留，后续考虑迁入 .env）
- 钉钉 markdown 对 surrogate pair emoji (🔴🟡🟢🤖) 渲染有 bug，已替换为 BMP 安全 emoji


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

## [2026-03-19] - [dingtalk-desktop 指令去重修复与调试清理]

**状态**: 验收通过

**内容**:
- `skill_router.py`：新增 `msg_id` 原子预占（`_reserve_msg_id_once` + `_MEMO_SEEN_LOCK`），避免并发下同一消息被重复处理
- `lib/monitor.py`：去除 send/push 回显侧的实验性抑制分支，统一交由路由层内容键去重
- `lib/utils.py`：移除仅用于实验分支的 `DedupTracker.contains` 接口
- 清理本轮调试埋点代码，保留已验证生效的修复逻辑
- `digest_config.json`：补充人员别名 `杨琳`

**备注**:
- 本次仅提交 dingtalk-desktop 相关改动，不包含工作区其他项目与未跟踪文件