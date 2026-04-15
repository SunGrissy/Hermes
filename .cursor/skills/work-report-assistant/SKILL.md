---
name: work-report-assistant
description: 日志助手定时汇总系统：4 场景自动化（工作日早报 / 周报素材 / 产品体验提炼 / AI 应用周报），通过 Chat API + 钉钉 Webhook 定时推送。Use when the user mentions 日志助手、work_report_assistant、早报、周报素材、产品体验提炼、AI周报、定时汇总。
---

# 日志助手定时汇总（work-report-assistant）

## 定位

制作人管理 80 人团队，每天手动翻日报耗时 30-60 分钟。本系统通过 Windows 计划任务定时触发，调用日志助手 Chat API（可全文检索团队日报），AI 生成结构化汇总后经钉钉 Webhook 自动推送。

## 架构

```
Windows 计划任务（schtasks）
  → run_work_report_assistant.ps1 -Scenario <id>
    → py work_report_assistant_run.py --scenario <id>
      1. 读 roster.json（人员名单）+ config.json（API 密钥）
      2. （早报）读 PM 主数据 `holidays`/`workdays`，与「假日与调休」一致后算「上一工作日」
      3. 构造提示词（含硬约束 + 格式铁律 + 日期窗口）
      4. POST /api/v1/chat → 日志助手 Chat API
      5. 回复 Markdown → send_result_webhook.py → 钉钉群
```

**工作日口径**：与 PmSystem 版本规划工作日历一致，详见 [`pm-work-calendar/SKILL.md`](../pm-work-calendar/SKILL.md)。

## 四场景

| ID | 触发 | 用途 | 输出结构 |
|----|------|------|----------|
| `morning_digest` | **每日** 09:00（脚本内按 PM 工作日过滤，非工作日不推） | 前一工作日日报提交情况 + 信息不对称风险 | 提交率、未交名单、分人风险点 |
| `weekly_material` | 周日 16:00 | 按 UE/运营/数据/技术 四组合并周报初稿 | 分组产出 → 管线进展 → 卡点 → AI 应用 |
| `weekly_px_insight` | 周一 10:30 | 上一自然周产品体验洞察聚类 + 人均条数 | 体验时长 → 洞察聚类 → 贡献统计 |
| `weekly_ai_px_report` | 周五 17:00 | 当周 AI 使用场景聚类 + 人均条数 | AI 聚类（按主题） → 各组统计 |

所有场景提示词含 **全文硬约束**（禁止仅用摘要）+ **格式铁律**（Markdown 列表，禁表格/大段叙述）。

## 关键文件

| 文件 | 作用 | 入库 |
|------|------|------|
| `dingtalk-desktop/work_report_assistant_run.py` | 主脚本：构造提示词、调 API、推送 | ✅ |
| `dingtalk-desktop/work_report_assistant_roster.json` | 汇总人员名单 + 技术组口径 + 模板路径 | ✅ |
| `dingtalk-desktop/work_report_assistant_config.json` | API 密钥、base_url、webhook_key | ❌ .gitignore |
| `dingtalk-desktop/work_report_assistant_config.json.example` | 配置示例 | ✅ |
| `dingtalk-desktop/run_work_report_assistant.ps1` | PS 包装（日志、错误处理） | ✅ |
| `dingtalk-desktop/register_work_report_assistant_tasks.ps1` | 注册 4 个 Windows 计划任务 | ✅ |
| `dingtalk-desktop/pm_work_calendar.py` | 与 PM `isWorkday` 一致的工作日 / 上一工作日 | ✅ |
| `.cursor/skills/dingtalk-actions/scripts/send_result_webhook.py` | Webhook 发送（读 webhook_config.json） | ✅ |
| `dingtalk-desktop/webhook_config.json` | 钉钉机器人 URL（默认键 `hr`） | ❌ .gitignore |

## 配置与密钥

- `work_report_assistant_config.json`：从 `.example` 复制，填 `api_key`；`pm_calendar_base_url` 填 **PmSystem** 根地址（如 `http://192.168.20.160:8112`），脚本会请求其 `/api/pm-calendar`；失败再用本地 `pm_data_json_path`
- 环境变量可覆盖：`WORK_REPORT_API_KEY`、`WORK_REPORT_BASE_URL`
- 钉钉推送优先用 `webhook_config.json` 的 `work_report_assistant` 键；未配置时回退 `hr` 键（与简历通知共用 HR 机器人）。两个键均在 `webhook_config.json.example` 中有定义。

## 运维

```powershell
# 注册计划任务（当前用户，无需管理员）
cd D:\MyAgents\dingtalk-desktop
.\register_work_report_assistant_tasks.ps1

# 手动执行（dry-run 只打印提示词，不调 API）
py work_report_assistant_run.py --scenario morning_digest --dry-run
py work_report_assistant_run.py --scenario morning_digest

# 覆盖日期（测试）
py work_report_assistant_run.py --scenario weekly_material --date 2026-04-06
```

日志：`dingtalk-desktop/logs/work_report_assistant_YYYYMMDD.log`

## 排错

| 症状 | 排查 |
|------|------|
| 401 | `api_key` 无效或未绑定员工 |
| 超时 | 增大 `default_timeout_sec`（API 可能 10-60s+） |
| 钉钉未收到 | 检查 `webhook_config.json` 对应键 + logs |
| 回复内容空 | Chat API 可能未索引到日报数据，确认日期窗口 |
| 计划任务未跑 | `schtasks /query /tn MyAgents_WorkReportAssist_Morning` 查看状态 |

## 可定制项

- **人员名单**：改 `roster.json` 的 `groups`，无需改 Python
- **触发时间**：改 `register_*.ps1` 中的 `-At` 参数，重跑注册
- **推送群**：改 `webhook_config.json` 中对应键的 URL
- **提示词口径**：改 `work_report_assistant_run.py` 的 `build_message` 函数
- **汇总模板**：改 `roster.json` 的 `pmo_template_ref`

## 展示与迁移文档

供 VP 或其他团队参考的完整方案说明与迁移指南：[`workspace-docs/REPORT-ASSISTANT-SHOWCASE.md`](../../../workspace-docs/REPORT-ASSISTANT-SHOWCASE.md)

## 同步副本

改版后将本目录复制到 `%USERPROFILE%\.cursor\skills\work-report-assistant`（以仓库为正本）。
