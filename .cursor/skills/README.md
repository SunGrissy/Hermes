# Agent Skills 体系

本目录为工作空间**唯一 skill 来源**，换设备拉仓库即可恢复完整 Agent 能力。

**与 Cursor 用户目录同步**：全局技能在 `%USERPROFILE%\.cursor\skills\`。以本仓库 `.cursor/skills` 为权威副本；新增或改版 skill 后，将同名目录复制到用户目录，避免全局旧版与项目不一致。详见 `digital-twin-voice` Skill 末节。

## 清单

### 沟通 & 身份
| Skill | 用途 |
|-------|------|
| producer-dialogue | 对制作人说人话、少技术黑话、产品思维组织回答；Skills 仓库与用户目录同步维护 |
| digital-twin-voice | 数字分身措辞与主人翁立场（禁用「你们」）；含双目录同步说明 |
| ai-content-collaboration | 与 Agent 协作做内容创作的方法论（给方向而非给答案，三种协作模式） |
| leadership-report-craft | 向上汇报结构化方法（思考作业 vs 成果汇报、受众校准、敏感信息处理） |

### Agent 体系自治
| Skill | 用途 |
|-------|------|
| skill-authoring-guide | **元 Skill**——指导 Agent 创建高质量 Skill，含 Agentic Protocol 模板、质量检查清单 |
| cognitive-furnace | **认知炼化炉**——从人物素材蒸馏思维操作系统，产出可对话的数字思考伙伴（六阶段流水线 + 三重验证） |

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
| fastapi-router | FastAPI 路由与 CRUD、鉴权、Pydantic 模型 |
| frontend-design | 高区分度前端界面设计（v2.0：SAFE/RISK 框架、Anti-Slop 清单、字体三级分类、DESIGN.md 集成） |
| vanilla-js-ui-patterns | 原生 JS 弹窗、Toast、表格等 UI 模式 |
| webapp-testing | Playwright 本地 Web 应用测试 |
| html-slide-deck | HTML 演示文稿生成（深色主题，浏览器打印为 PDF） |
| pm-data-sync | PmSystem 数据同步与冲突合并 |

### Git & 部署
| Skill | 用途 |
|-------|------|
| dual-git-sync | tygit 主仓 + GitHub 可选镜像、子模块 |
| github-ops | GitHub 仓库、分支保护、PR、gh CLI |
| preflight-checks | 门禁失败修复（敏感信息、引用一致性等） |
| multi-service-orchestration | 端口、启动命令、依赖、健康检查 |

### 钉钉 & 自动化
| Skill | 用途 |
|-------|------|
| cursor-to-dingtalk | 会话结束把结果发钉钉（Webhook 机器人，footer 小秘书提醒） |
| work-report-assistant | 日志助手 Chat API 定时汇总（早报/周报素材/体验提炼/AI 与体验） |

### 游戏业务
| Skill | 用途 |
|-------|------|
| cognitive-design-engine | **认知设计引擎**（实战版）——认知科学翻译为设计操作语言，6 模块 20+ 机制，回答"怎么用" |
| cognitive-science-foundations | **认知科学基础文献库**（学术版）——《思考快与慢》《助推》《体验引擎》完整蒸馏 + 7 篇前沿论文，回答"原理是什么" |
| boss-design-council | **Boss 设计智囊团**——6 位认知科学视角的智囊围绕 Boss 加分表演方案讨论，引导策划自检 |
| game-design-council | **游戏设计智囊团**——6 位认知科学视角的智囊围绕通用玩法/系统/经济/社交方案讨论，引导策划自检 |
| game-review | **策划方案审核** 6引擎检查（目的/节奏/红线/价值/分层/经济）+ 制作人决策问题 |
| boss-precheck-review | Boss 表演预审三道门（概念门/结构门/制作门）自检与预审意见 |
| feature-what-review | Feature WHAT 层设计质量审查（想没想清楚，而非文档写没写） |
| survey-analysis | 问卷调研 CSV 分析、跨版本对比、HTML 报告 |
| token-usage-analysis | Cursor 用量 CSV 分析、优化建议 |

### 招聘工具链（①→②→③）
| Skill | 用途 |
|-------|------|
| resume-screening | **①** 简历初筛（规则正本：本 SKILL；`.cursor/rules/resume-screening.mdc` 仅保留触发词） |
| interview-checklist | **②** 从简历生成标准化面试清单（初面执行清单） |
| interview-checklist-dingtalk | **②附** 面试清单生成后发 md-reader 局域网链接到钉钉助理群 |
| interview-evaluation | **③** 从面试记录生成结构化面试评价报告 |

每个 skill 目录含 `SKILL.md`（必选），部分带 `scripts/` 或 `reference/`。

**招聘工具链**：①→②→③ 三个 SKILL 构成完整链路（简历初筛→面试清单→面试评价），详见 [`_recruitment-toolkit-README.md`](_recruitment-toolkit-README.md)。
