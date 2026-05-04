---
name: pm-work-calendar
description: 本工作空间内「工作日」的统一定义——与 PM 系统「假日与调休管理」及版本规划工作日历一致；供日志助手早报、排期、剩余工作日等场景引用。Use when the user mentions 工作日、假日、调休、工作日历、是否与 PM 一致、或 work_report / morning_digest 日历口径。
---

# PM 工作日历（单一事实源）

## 定义

在本仓库内，**「工作日」** 不是「周一到周五」的口语含义，而是与 **PmSystem「版本规划 → 假日与调休管理」** 相同的判定：

1. 落在 **法定假日区间**（`holidays[].start`～`end`）→ **非工作日**
2. 在 **调休上班日列表**（`workdays` 中的 `YYYY-MM-DD`）→ **工作日**（即使为周末）
3. 否则 **周六、周日** → **非工作日**
4. 其余 → **工作日**

逻辑与 `pm-system/ui/components/version-planning-view.js` 的 `isWorkday()` 对齐。

## 数据从哪来

- **权威数据**：PM 主数据里的 `holidays`、`workdays`（与 `/api/data` 同源）。
- **给脚本用的接口**：PmSystem 后端提供 **`GET /api/pm-calendar`**，只返回这两项，方便日志助手等内网服务拉取。实现见 `pm-system/backend/app/routers/data.py`。
- 内网部署示例：`http://192.168.20.160:8112` 指向的是 **PmSystem 后端**（端口按你们实际部署即可，不一定是 8000）。

## 日志助手怎么取日历（人话）

1. **先看配置里写的 PM 根地址**（例如 `http://192.168.20.160:8112`）。脚本会自动去要 **`/api/pm-calendar`**，拿到的就是 PM 里当前保存的假日和调休，和你在网页里改的是同一套。
2. **要不到的时候**（没配地址、断网、服务没起）：就改读**本机仓库里那份** `gamedev_pm_data.json`（路径在配置里能改）。
3. **上面两步都没有**：才按「周一到周五算上班、周末不算」这种粗办法凑合，并在发给 AI 的提示里写明——这时候和真实日历可能对不齐。

## 本仓库消费方

| 位置 | 行为 |
|------|------|
| `dingtalk-desktop/pm_work_calendar.py` | 工作日判定；`fetch_pm_calendar_http` 请求 PmSystem |
| `dingtalk-desktop/work_report_assistant_run.py` | 早报：先试 HTTP，再试本地文件；非工作日不推送 |
| 计划任务 `MyAgents_WorkReportAssist_Morning` | 每天到点跑一次，推不推由脚本按日历决定 |

## 配置（日志助手）

- `pm_calendar_base_url`：PmSystem 根地址，脚本会访问 `{base}/api/pm-calendar`
- `WORK_REPORT_PM_CALENDAR_URL`：完整 URL（可代替 base）
- `WORK_REPORT_PM_CALENDAR_BASE_URL`：与 base 同义
- `pm_calendar_timeout_sec`：请求超时秒数
- 回退：`pm_data_json_path` / `WORK_REPORT_PM_DATA_JSON`

## 与其它「工作日」表述

- **排期 / 剩余工作日**：PM 前端已用同一套 `isWorkday`。
- **写文案或脚本**：别默认「工作日 = 周一到周五」，除非明确说明是降级。

## 同步副本

改版后将本目录复制到 `%USERPROFILE%\.cursor\skills\pm-work-calendar`（以仓库 `.cursor/skills` 为正本）。
