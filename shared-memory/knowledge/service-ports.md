# 服务端口与配置

| 服务 | 端口 | 说明 |
|------|------|------|
| dingtalk-desktop daemon | 19200 | 钉钉桌面消息通道 API |
| OpenClaw Gateway | 18789 | 本地网关 HTTP 接口 |
| performeval backend | 8112 | 绩效评价后端 |
| task_reminder server | 8000 | 任务提醒服务 |

## 重启方式

| 服务 | 命令 |
|------|------|
| Hermes Gateway | `hermes gateway run --replace` |
| dingtalk-desktop | `cmd //c "start py -u daemon.py"` |
| OpenClaw Gateway | 检查 PID 文件 `D:/OpenClaw/gateway.pid` 后 `taskkill //F //PID <pid>`，再用 Python subprocess 重启 |
