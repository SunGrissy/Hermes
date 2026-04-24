# 项目路径与关键目录

## 核心路径

| 路径 | 说明 |
|--------|------|
| `D:/MyAgents` | 工作空间根目录 |
| `D:/hermes` | Hermes 配置与运行时目录 |
| `D:/OpenClaw` | OpenClaw Gateway 配置目录 |

## 子项目速查

| 目录 | 说明 |
|------|------|
| `pm-system/` | 游戏项目管理（PmSystem） |
| `performeval/` | 乘法绩效评价 |
| `cci_system/` | 素材竞争力 CCI |
| `task_reminder/` | 任务提醒 + 钉钉推送 |
| `dingtalk-desktop/` | 钉钉桌面消息通道 |
| `tools/` | 桥接脚本、第三方工具 |

## 路径铁律

- Windows 环境下所有路径使用正斜杠 `/`
- 禁用反斜杠 `，避免 Python 字符串转义问题
