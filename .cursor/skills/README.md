# Agent Skills 体系

本目录为工作空间**唯一 skill 来源**，换设备拉仓库即可恢复完整 Agent 能力。

**与 Cursor 用户目录同步**：全局技能在 `%USERPROFILE%\.cursor\skills\`。以本仓库 `.cursor/skills` 为权威副本；新增或改版 skill 后，将同名目录复制到用户目录，避免全局旧版与项目不一致。详见 `digital-twin-voice` Skill 末节。

**给人读的叙事文档（非 Skill）：** `docs/DOC_HUB.md`、`docs/narrative/`（工单附件、面试材料、会议议程、需求/JD、人在回路计划）。

---

## Pack 总览（6 组，40+ 个 Skill）

### Core Pack（基础能力，每次都可能用）

| Skill | 用途 |
|-------|------|
| structured-communication | **结构化表达教练**——表达纪律（先结论后展开、说人话、密度控制）+ **管理沟通有效信息公式**（谁/时间/事/程度 + 受众优先）+ 三种协作模式 + 高效反馈指南，Agent 自己的输出也遵守 |
| digital-twin-voice | 数字分身措辞与主人翁立场（禁用「你们」）；含双目录同步说明 |
| leadership-report-craft | 向上汇报结构化方法（思考作业 vs 成果汇报、受众校准、敏感信息处理） |
| ai-content-collaboration | ⚠️ **已废弃**，合并至 `structured-communication`（文案与反馈节奏；**不**承担 HTML/视觉交付——幻灯见 `html-slide-deck`，界面见 `frontend-design`） |
| producer-dialogue | ⚠️ **已废弃**，表达纪律迁入 `structured-communication`，同步规则见 `digital-twin-voice` |
| preflight-checks | 门禁失败修复指南（敏感信息、引用一致性；**Windows .bat CRLF / .gitattributes**；详见 Skill 正文） |

### Thinkers Pack（思考伙伴，按需加载单个）

| Skill | 一句话定位 |
|-------|-----------|
| munger-perspective | 多元模型格栅 + 反向思考 + 误判心理 |
| bezos-perspective | 飞轮 + 逆向工作法 + Day One |
| naval-perspective | 杠杆 + 特定知识 + 判断力资本化 |
| inamori-perspective | 阿米巴 + 利他心 + 以心为本 |
| taleb-perspective | 反脆弱 + 非对称 + 肥尾风险 |
| zhangxiaolong-perspective | 用完即走 + 简约克制 + 人性驱动 |
| jobs-perspective | 红队挑战者——品味 + 直觉 + 极致标准 |
| gelman-perspective | 贝叶斯工作流 + Type S/M + 花园分叉路径 |

### Game Design Pack（游戏设计 + 认知科学）

| Skill | 用途 |
|-------|------|
| cognitive-design | 认知设计引擎——6 模块 20+ 机制（含 reference/foundations.md 学术底座） |
| design-council | 设计智囊团——Boss 模式 / Game 模式双切换 |
| design-review | 设计审核——通用方案(6引擎) / Boss预审(三道门) / Feature WHAT(四条件) |
| survey-analysis | 问卷 CSV 分析、跨版本对比、HTML 报告 |

### Dev Pack（开发工具）

| Skill | 用途 |
|-------|------|
| data-investigation-playbook | 指标异常协作式探查（五步、查询卡片、统计陷阱与 Gelman 检查） |
| gelman-perspective | **Andrew Gelman 认知 OS**——分叉路径、Type S/M、模型检查、测量优先 |

### 思维工具（概念 / 写作 / 辩证，源自 ljg-skills 改造）
| Skill | 用途 |
|-------|------|
| concept-anatomy | 概念八维解剖（定锚→八刀→内观→压缩），含白话表达铁律 |
| drill-to-root | 追本之箭——纵向深钻到不可再分的本质 |
| plain-speak | 白话引擎——聪明十二岁能懂，九条红线 |
| rank-reducer | 降秩引擎——领域不可再少的独立生成器（四判据） |
| roundtable-debate | 圆桌讨论——真实人物多视角辩证 + ASCII 框架图 |
| writing-engine | 写作引擎——找核→攻核→脚手架→展开→磨（约千字散文） |

### 数字思考伙伴
| Skill | 用途 |
|-------|------|
| producer-mind | **制作人（孙懿）认知 OS**——7 个心智模型 + 10 条决策启发式 + 表达 DNA，用制作人的思维方式分析问题 |
| munger-perspective | **查理·芒格认知 OS**——多元思维模型格栅 + 反向思考 + 人类误判心理学，跨学科交叉分析 |
| bezos-perspective | **贝索斯认知 OS**——飞轮效应 + 逆向工作法 + Day One 文化，存量中找增量 |
| naval-perspective | **Naval 认知 OS**——四种杠杆 + 特定知识 + 判断力资本化，个人效能极致化 |
| inamori-perspective | **稻盛和夫认知 OS**——阿米巴经营 + 利他心 + 人生方程式，机制之外的人心经营 |
| taleb-perspective | **塔勒布认知 OS**——反脆弱 + 非对称风险 + 肥尾分布，挑战确定性假设 |
| zhangxiaolong-perspective | **张小龙认知 OS**——用完即走 + 简约克制 + 人性驱动设计，产品直觉的可言说化 |
| jobs-perspective | **乔布斯 · 红队挑战者**——品味暴政 + 直觉决断 + 非共识赌注，当全员共识时提供对冲压力测试 |

### 开发工具
| Skill | 用途 |
|-------|------|
| coding-execution-discipline | **写码中与收尾**——方案过重先收敛/回检查点；只清理本次改动引入的孤儿符号；与 `agentx`「事前路径选择」配套，单仓正本 |
| fastapi-router | FastAPI 路由与 CRUD、鉴权、Pydantic 模型 |
| frontend-design | 高区分度前端 + **HTML 通用视觉交付**（SAFE/RISK、Anti-Slop、DESIGN.md；含「Claude Design」式需求门禁与固定画幅纪律）；与 `html-slide-deck` **互补不合并** |
| vanilla-js-ui-patterns | 原生 JS 弹窗、Toast、表格等 UI 模式 |
| webapp-testing | Playwright 本地 Web 应用测试 |
| html-slide-deck | HTML 演示文稿（深色主题、打印 PDF、叙事密度与内嵌组件库）；审美与落地页反套路见 `frontend-design` |
| pm-data-sync | PmSystem 数据同步与冲突合并 |
| multi-service-orchestration | 端口、启动命令、健康检查 |
| token-usage-analysis | Cursor token 用量分析 |

### Ops Pack（运维 & 自动化）

| Skill | 用途 |
|-------|------|
| git-ops | 双 remote 工作流 + gh CLI + GitHub PR |
| dingtalk-actions | 发钉钉（Webhook 摘要 + 涛哥更新私聊） |
| dingtalk-meeting-room | 钉钉 MCP 预约会议室 / 创建日程（需本机配置 Streamable HTTP MCP） |
| work-report-assistant | 日志助手定时汇总（早报/周报/体验/AI周报） |
| pm-work-calendar | 工作日与 PM 假日/调休一致 |

### Recruitment Pack（招聘工具链 ①→②→③）

| Skill | 用途 |
|-------|------|
| resume-screening | ① 简历初筛 |
| interview-checklist | ② 从简历生成面试清单 |
| interview-checklist-dingtalk | ②附 清单发钉钉助理群 |
| interview-evaluation | ③ 面试评价报告 |

### Thinking Pack（深度思维 + 写作）

| Skill | 用途 |
|-------|------|
| thinking-tools | 概念解剖 / 追本之箭 / 降秩引擎（三合一） |
| writing-engine | 散文式写作（找核→攻核→展开→磨） |
| plain-speak | 白话引擎（12 岁能懂） |
| roundtable-debate | 圆桌多人物辩证 |

### Meta Pack（Agent 体系自治）

| Skill | 用途 |
|-------|------|
| skill-guide | Skill 写作指南（面向 Agent + 人类） |
| cognitive-furnace | 认知炼化炉——从素材蒸馏思维 OS |
| claude-self-serve-skills | **Claude 自助装载**：把仓库 `.cursor/skills` 同步到 `%USERPROFILE%\.cursor\skills`，可选 Claude Code 目录 |

---

每个 skill 目录含 `SKILL.md`（必选），部分带 `scripts/`、`reference/` 或 `references/`。

**招聘工具链**：①→②→③ 详见 [`_recruitment-toolkit-README.md`](_recruitment-toolkit-README.md)。

**路由规则**见 `.cursor/rules/partner-router.mdc`（五域分流，域内自治）。
