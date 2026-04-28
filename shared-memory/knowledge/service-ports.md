# 服务端口与配置

> 完整版见 `D:/OpenClaw2/workspace/PORT_MAP.md`
> 本文件为共享摘要，供军团其他 Agent 快速查阅

## 端口区间

| 区间 | 用途 |
|------|------|
| 18780–18799 | OpenClaw Gateway |
| 19200–19299 | 钉钉桌面通道 |
| 3000–3999 | 前端静态服务 |
| 8000–8099 | PM 系统后端 |
| 8100–8199 | 工具类系统 |
| 8300–8399 | Palace 系列 |
| 8800–8899 | 阅读/文档 |
| 10000–10999 | Multica / 调度 |

## 当前在用端口

| 服务 | 端口 | 启动命令 | 备注 |
|------|------|---------|------|
| 虾叔 OpenClaw | 18789 | `D:\OpenClaw\gateway.cmd` | |
| 小马 OpenClaw2 | 18790 | `D:\OpenClaw2\gateway.cmd` | |
| 虾叔内部RPC | 18791 | 跟随18789 | |
| 小马内部RPC | 18792 | 跟随18790 | |
| 钉钉桌面通道 | 19200 | `quick_start.bat 6` | dingtalk-desktop/daemon.py；有可观测窗口 |
| 钉钉内部信标 | 18899 | 跟随19200 | |
| PM系统后端 | 8000 | `quick_start.bat 1` | |
| PM系统前端 | 3005 | `quick_start.bat 2` | 无窗后台 |
| MD Reader | 8899 | `quick_start.bat 3` | 无窗后台 |
| Palace Web | 8300 | `quick_start.bat 5` | 无窗后台 |
| 绩效评价 | 8112 | `D:\MyAgents\performeval\run.bat` | 独立启动 |
| Multica派单桥 | 10001 | `quick_start.bat 7` | dispatch_bot.py；有可观测窗口 |
| Multica Daemon | — | `quick_start.bat 8` | multica daemon start；无窗后台；检查：`multica daemon status` |

## Agent Webhook（启动报道用）

| Agent | 用途 |
|-------|------|
| 小马 | 巡检报告、双挂告警、启动报道 |
| 满满 | 总管启动报道 |
| 当当 | Multica库管启动报道 |
| 虾叔 | Guard启动报道 |
| 妙妙 | HR/关怀启动报道 |
| 阿茶 | PM Advisor启动报道 |
| 小美 | 设计Advisor启动报道 |

token 详情见 `D:/OpenClaw2/workspace/report_startup.py` 的 `AGENT_WEBHOOKS` 字典。
