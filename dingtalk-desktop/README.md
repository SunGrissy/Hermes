# dingtalk-desktop

钉钉桌面端消息通道（Frida + daemon + 技能路由），并为 PM 版本/管线状态提供 **Webhook 推送**。

## 文档

- **[版本与管线推送说明.md](./版本与管线推送说明.md)** — 版本汇总（VersionDigest）与管线定时/专项推送的配置、脚本与排错  
- **[docs/version-digest-morning.md](./docs/version-digest-morning.md)** — **早间版本汇总**：受众差异、发版过滤、PLD/版本快报条数、文末 footer、近期变更（新开会话可先读此篇）  
- **注册早间定时任务（09:40）**：双击 **[register_version_digest_task_elevated.cmd](./register_version_digest_task_elevated.cmd)**（UAC），或管理员 PowerShell 执行 `register_version_digest_task.ps1`  
- **[docs/pipeline-push.md](./docs/pipeline-push.md)** — 管线推送专篇：配置三件套、`run_daily_version`、PM 侧阻塞/阶段待办阈值、晚间 followup 与一次性通知  
- **[docs/work-report-assistant.md](./docs/work-report-assistant.md)** — 日志助手 Chat API 定时汇总（早报/周报素材/体验提炼/周五 AI 与体验）、`register_work_report_assistant_tasks.ps1`  
- 工作日志：`WORK_LOG.md`

## 常用入口

- Daemon：`daemon.py`（HTTP，默认端口见项目内约定）  
- 版本汇总手动推送：`py version_digest.py`（目录 `dingtalk-desktop`）  
- 管线定时：`run_pipeline_notify_scheduled.ps1`（由计划任务调用；当前机器上两条 PipelineNotify 任务已停用）
