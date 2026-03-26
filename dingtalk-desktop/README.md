# dingtalk-desktop

钉钉桌面端消息通道（Frida + daemon + 技能路由），并为 PM 版本/管线状态提供 **Webhook 推送**。

## 文档

- **[版本与管线推送说明.md](./版本与管线推送说明.md)** — 版本汇总（VersionDigest）与管线定时/专项推送的配置、脚本与排错  
- 工作日志：`WORK_LOG.md`

## 常用入口

- Daemon：`daemon.py`（HTTP，默认端口见项目内约定）  
- 版本汇总手动推送：`py version_digest.py`（目录 `dingtalk-desktop`）  
- 管线定时：`run_pipeline_notify_scheduled.ps1`（由计划任务调用）
