# Agent Skills 体系

本目录为工作空间**唯一 skill 来源**，换设备拉仓库即可恢复完整 Agent 能力。

**与 Cursor 用户目录同步**：全局技能在 `%USERPROFILE%\.cursor\skills\`。以本仓库 `.cursor/skills` 为权威副本；新增或改版 skill 后，将同名目录复制到用户目录，避免全局旧版与项目不一致。详见 `digital-twin-voice` Skill 末节。

## 清单

| Skill | 用途 |
|-------|------|
| producer-dialogue | 对制作人说人话、少技术黑话、产品思维组织回答；Skills 仓库与用户目录同步维护 |
| digital-twin-voice | 数字分身措辞与主人翁立场（禁用「你们」）；含双目录同步说明 |
| cursor-to-dingtalk | 会话结束把结果发钉钉（daemon /send 或 Webhook，footer 小秘书提醒） |
| dual-git-sync | tygit 主仓 + GitHub 可选镜像、子模块、novel 独立仓 |
| fastapi-router | FastAPI 路由与 CRUD、鉴权、Pydantic 模型 |
| frontend-design | 高区分度前端/落地页/组件设计 |
| github-ops | GitHub 仓库、分支保护、PR、gh CLI |
| interview-checklist | **招聘工具链②** 从简历生成标准化面试清单（初面执行清单） |
| interview-checklist-dingtalk | 面试清单生成后发 md-reader 局域网链接到钉钉助理群 |
| interview-evaluation | **招聘工具链③** 从面试记录生成结构化面试评价报告 |
| multi-service-orchestration | 端口、启动命令、依赖、健康检查 |
| pm-data-sync | PmSystem 数据同步与冲突合并 |
| preflight-checks | 门禁失败修复（敏感信息、引用一致性等） |
| resume-screening | **招聘工具链①** 简历初筛（规则双写：`.cursor/rules/resume-screening.mdc` 同步维护） |
| survey-analysis | 问卷调研 CSV 分析、跨版本对比、HTML 报告 |
| token-usage-analysis | Cursor 用量 CSV 分析、优化建议 |
| vanilla-js-ui-patterns | 原生 JS 弹窗、Toast、表格等 UI 模式 |
| webapp-testing | Playwright 本地 Web 应用测试 |
| work-report-assistant | 日志助手 Chat API 定时汇总（早报/周报素材/体验提炼/AI 与体验） |

每个 skill 目录含 `SKILL.md`（必选），部分带 `scripts/` 或 `reference/`。

**招聘工具链**：①→②→③ 三个 SKILL 构成完整链路（简历初筛→面试清单→面试评价），详见 [`_recruitment-toolkit-README.md`](_recruitment-toolkit-README.md)。
