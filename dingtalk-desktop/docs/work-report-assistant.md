# 日志助手定时汇总（work-report Chat API）

本机计划任务调用 `work_report_assistant_run.py`，向 `zxty.tuyoo.com/work-report` 的 Chat 接口发送结构化提示词，将返回的 Markdown 经钉钉 Webhook 推送。

## 配置文件

| 文件 | 说明 |
|------|------|
| `work_report_assistant_config.json` | **勿提交**（已在 `.gitignore`）。含 `api_key`、`base_url`、`webhook_key`、`default_timeout_sec` |
| `work_report_assistant_config.json.example` | 示例 |
| `work_report_assistant_roster.json` | 汇总人员名单与口径说明（可提交） |

密钥也可用环境变量：`WORK_REPORT_API_KEY`、`WORK_REPORT_BASE_URL`。

## Webhook

`send_result_webhook.py` 读取 `webhook_config.json`。默认 **`webhook_key` 为 `hr`**，与 **`resume_notify`（简历/HR 通知）同一套 HR 机器人 URL**；本地 `webhook_config.json` 中已用同名键 `hr` 指向该机器人。若要改群，只改 `hr` 的 URL，或把 `work_report_assistant_config.json` 里的 `webhook_key` 改成其他已有键（如 `default`）。

## 计划任务（注册后）

| 任务名 | 触发 | 场景 ID |
|--------|------|---------|
| `MyAgents_WorkReportAssist_Morning` | 周一至周五 09:00 | `morning_digest` |
| `MyAgents_WorkReportAssist_WeeklyMaterial` | 周日 16:00 | `weekly_material` |
| `MyAgents_WorkReportAssist_PxInsight` | 周一 10:30 | `weekly_px_insight` |
| `MyAgents_WorkReportAssist_AiPx` | 周五 17:00 | `weekly_ai_px_report` |

注册（当前用户，无需管理员）：

```powershell
cd D:\MyAgents\dingtalk-desktop
.\register_work_report_assistant_tasks.ps1
```

## 手动执行与调试

```powershell
cd D:\MyAgents\dingtalk-desktop
py work_report_assistant_run.py --scenario morning_digest --dry-run
py work_report_assistant_run.py --scenario morning_digest
```

`--date YYYY-MM-DD` 可覆盖「今天」用于验证日期窗口。

## 依赖

- 本机可访问 `https://zxty.tuyoo.com/work-report`
- Python 3.9+，无需额外 pip 包（标准库 `urllib`）
- 与 [`cursor-to-dingtalk`](../.cursor/skills/cursor-to-dingtalk/scripts/send_result_webhook.py) 同仓库路径

## 排错

- **401**：检查 `api_key` 是否有效、是否与员工绑定。
- **超时**：增大 `default_timeout_sec`（接口可能 10–60s+）。
- **钉钉未收到**：检查 `webhook_config.json` 对应键、`logs/work_report_assistant_*.log`、`logs/cursor_webhook_sends.log`。

## Agent Skill

详见仓库 [`.cursor/skills/work-report-assistant/SKILL.md`](../../.cursor/skills/work-report-assistant/SKILL.md)。
