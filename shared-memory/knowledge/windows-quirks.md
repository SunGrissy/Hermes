# Windows 环境特殊处理

## 终端与路径

| 问题 | 解法 |
|------|------|
| Git Bash 下 `taskkill /F` 失败 | 使用 `taskkill //F //PID <pid>` ，因为 `/F` 会被解析为 `F:/` |
| Python 字符串中 `	` 被解释为 Tab | 路径统一用正斜杠 `/` 或原始字符串 `r'...'` |

## 排空逻辑

- Windows 上 select 不能等待子进程管道，排空线程需使用 `stdout.read` 而非 select
- 若 hermes update 覆盖了此逻辑，需检查恢复

## 进程管理

- `dingtalk-desktop/daemon.py` 是持久服务，前台运行会阻塞并超时
- 正确重启方式：`subprocess.Popen(..., creationflags=CREATE_NEW_CONSOLE)` 或 `cmd //c "start py -u daemon.py"`
