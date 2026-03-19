# Agent Skills 体系

本目录为工作空间**唯一 skill 来源**，换设备拉仓库即可恢复完整 Agent 能力。

## 清单

| Skill | 用途 |
|-------|------|
| cursor-to-dingtalk | 会话结束把结果发钉钉（daemon /send 或 Webhook，footer 小秘书提醒） |
| dual-git-sync | GitLab ↔ GitHub 双远端同步、子模块镜像 |
| fastapi-router | FastAPI 路由与 CRUD、鉴权、Pydantic 模型 |
| frontend-design | 高区分度前端/落地页/组件设计 |
| github-ops | GitHub 仓库、分支保护、PR、gh CLI |
| multi-service-orchestration | 端口、启动命令、依赖、健康检查 |
| pm-data-sync | PmSystem 数据同步与冲突合并 |
| preflight-checks | 门禁失败修复（敏感信息、引用一致性等） |
| resume-screening | 简历筛选 |
| survey-analysis | 问卷调研 CSV 分析、跨版本对比、HTML 报告 |
| token-usage-analysis | Cursor 用量 CSV 分析、优化建议 |
| vanilla-js-ui-patterns | 原生 JS 弹窗、Toast、表格等 UI 模式 |
| webapp-testing | Playwright 本地 Web 应用测试 |

每个 skill 目录含 `SKILL.md`（必选），部分带 `scripts/` 或 `reference.md`。
