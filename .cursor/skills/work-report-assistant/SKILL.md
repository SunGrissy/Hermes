---
name: work-report-assistant
description: 工作汇报「日志助手」Chat API 定时场景：工作日早报、周日周报素材、周一产品体验提炼、周五 AI 与产品体验汇总；名单与提示词口径见 dingtalk-desktop/work_report_assistant_roster.json。Use when the user mentions 日志助手定时、work_report_assistant、早报周报素材、产品体验提炼自动化。
---

# 日志助手定时汇总（work-report）

## 能力

通过本机脚本 `dingtalk-desktop/work_report_assistant_run.py` 调用 `POST /api/v1/chat`（与钉钉内日志助手同源能力），按场景生成提示词，将回复推送到钉钉 Markdown（Webhook）。

## 权威口径

- 汇报模板：[`performeval/PMO_管线汇报模板.md`](../../../performeval/PMO_管线汇报模板.md)（路径写入提示词，供服务端检索）
- 人员名单：`dingtalk-desktop/work_report_assistant_roster.json`
- **技术组**：不要求 PMO 全文结构化检核，以「在做什么、关键事项、依赖与风险」为主（见 roster 中 `tech_focus_note`）

## 四场景

| ID | 调度 | 用途 |
|----|------|------|
| `morning_digest` | 工作日 09:00 | 前一工作日提交情况 + 信息不对称风险 |
| `weekly_material` | 周日 16:00 | 按 **UE / 运营 / 数据 / 技术 / 管线** 五块合并汇总（非按人头分节） |
| `weekly_px_insight` | 周一 10:30 | 上一自然周产品体验洞察，聚类 + 按组每人条数 |
| `weekly_ai_px_report` | 周五 17:00 | 当周工作日 AI 使用 + 产品体验时长，聚类 + 按组每人 |

所有场景的 `message` 均含**全文硬约束**（禁止仅用摘要）。

## 配置与密钥

- `dingtalk-desktop/work_report_assistant_config.json`：**不入库**，见 `.gitignore`
- 环境变量可覆盖：`WORK_REPORT_API_KEY`、`WORK_REPORT_BASE_URL`
- 钉钉：`webhook_config.json` 键名默认 **`hr`**（与 `resume_notify` 同源 HR 机器人；可在 `work_report_assistant_config.json` 改 `webhook_key`）

## 运维入口

- 注册计划任务：`dingtalk-desktop/register_work_report_assistant_tasks.ps1`
- 运行包装：`dingtalk-desktop/run_work_report_assistant.ps1 -Scenario <id>`
- 文档：[`dingtalk-desktop/docs/work-report-assistant.md`](../../../dingtalk-desktop/docs/work-report-assistant.md)

## 同步副本

改版后将本目录复制到 `%USERPROFILE%\.cursor\skills\work-report-assistant`（以仓库为正本）。
