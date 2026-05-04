---
name: multica-dingtalk-bridge-hijack-diagnosis
description: |
  Hermes 和 multica-dingtalk-bridge 抢钉钉 Stream 导致「派单」指令失败的排查与修复。
  覆盖两种根因：1) Stream 互斥抢线；2) Hermes 入站路由器代码被 git reset 丢失。
triggers:
  - multica 派单没反应
  - 派单失败
  - 派单没响应
  - Hermes 和 multica 抢 Stream
  - 钉钉派单不工作
  - multica-dingtalk-bridge 排查
  - dispatch_bot 两个进程
  - python.exe 多个 dispatch_bot
---

# Multica 钉钉派单桥 / Hermes 入站路由 排查指南

## 现象

钉钉群里发「派单 xxx」后：
- 机器人没有任何回复；或
- 回复的内容不像派单桥返回的固定版式（如没有 Issue 编号、没有「工单已写入 Multica」）；或
- Hermes 主 Agent 把「派单」当成普通用户消息开始 Thinking。

## 根因分支（按优先级排查）

### 分支 A：同一 Client ID 多进程抢 Stream（最常见）

钉钉 Stream 模式**同一 Client ID 只能有一个连接**。如果同时存在两个进程：
- `hermes gateway run`（且 `HERMES_INBOUND_ROUTER_ENABLED=on`）
- `python dispatch_bot.py`（multica-dingtalk-bridge）

双方会互相踢下线，表现为「时灵时不灵」。

**排查命令**：

```bash
# 1. 检查是否同时有两个进程在跑
tasklist | grep -i "hermes\|dispatch_bot"

# 2. 检查环境变量
echo HERMES_INBOUND_ROUTER_ENABLED=$HERMES_INBOUND_ROUTER_ENABLED
echo HERMES_ROUTER_MULTICA_ENABLED=$HERMES_ROUTER_MULTICA_ENABLED
```

**修复（二选一）**：

| 模式 | 做法 |
|------|------|
| **Hermes 路由模式**（推荐，统一入口） | 确保 `HERMES_INBOUND_ROUTER_ENABLED=on` + `HERMES_ROUTER_MULTICA_ENABLED=on`；**停掉** `dispatch_bot.py`；重启 Hermes gateway |
| **独立桥模式**（ legacy ） | `HERMES_INBOUND_ROUTER_ENABLED=off`；单独启动 `tools/multica-dingtalk-bridge/run_bridge.ps1` |

### 分支 B：Hermes 入站路由器代码被 reset 丢失（本次排查新发现）

**特征**：
- 环境变量已设 `HERMES_INBOUND_ROUTER_ENABLED=on`
- Hermes gateway 日志显示「派单」消息被记录为普通 `inbound message`，没有走 `_route_inbound_commands_if_any`
- `D:/hermes/hermes-agent/gateway/inbound_command_router/` 目录**不存在**
- WORK_LOG 里明明记录过「Hermes 入站命令路由器（Multica）落地」

**排查命令**：

```bash
cd D:/hermes/hermes-agent

# 1. 确认目录是否存在
ls gateway/inbound_command_router/ 2>/dev/null || echo "目录不存在——代码可能被 reset"

# 2. 查 reflog，看是否有 inbound router 相关 commit 被 reset 掉
git reflog | grep -i "multica\|inbound\|router"

# 3. 如果有类似 4ec37e92 的 commit，查看改动文件列表
git show --stat <commit-hash>
```

**修复**：

```bash
# 方式 1：cherry-pick 恢复（如果 commit 还在 reflog 里）
git cherry-pick <commit-hash>

# 方式 2：从 reflog 切回旧分支再处理
git checkout <commit-hash>
# ... 手动备份代码后重新应用 ...
```

> 注意：Hermes 的 `origin` 通常是上游 GitHub 仓库，**无写权限**。本地 commit 后若执行 `git reset --hard origin/main` 或 `git pull` 冲突时选择接受远端，本地未推送的 commit 会进入 reflog 但不会出现在当前分支，极易被忽略。

### 分支 C：代码已恢复，但 gateway 进程未重启（cherry-pick 后常见漏步）

**特征**：
- cherry-pick / 手动恢复后，`gateway/inbound_command_router/` 目录存在、代码看起来正常
- 钉钉发「派单」仍然无响应
- `D:/hermes/gateway.pid` 里记录的 PID **在进程列表中找不到**
- agent.log 里最后一条 `gateway.run:` 日志停留在恢复之前的时间点

**排查命令**：

```bash
# 1. 看 gateway.pid 里的 PID 是否还活着
cat D:/hermes/gateway.pid
tasklist | grep <pid>

# 2. 看日志里有没有 gateway 启动/消息记录
grep "gateway.run:" D:/hermes/logs/agent.log | tail -10
```

**修复**：

```bash
# 清理残留 PID 文件，避免 "PID file race" 错误
rm D:/hermes/gateway.pid

# 重启 gateway（加载新代码）
cd D:/hermes/hermes-agent
venv/Scripts/hermes gateway run --replace
```

> 关键原则：**改 gateway 代码后必须重启 gateway 进程**，Python 不会热重载已导入的模块。

### 分支 D：multica-dingtalk-bridge 独立运行时的问题

如果决定走独立桥模式（不经过 Hermes），排查：

1. **桥进程是否在跑**：`tasklist | grep -i dispatch_bot`
2. **.env 配置**：`D:/MyAgents/tools/multica-dingtalk-bridge/.env` 是否有 `DINGTALK_CLIENT_ID` / `DINGTALK_CLIENT_SECRET`
3. **multica CLI 是否可执行**：在桥进程同一用户/PATH 下执行 `multica auth status`
4. **卡片权限**：如果日志里出现 `Card.Instance.Write` 403，去钉钉开放平台开通权限，或在 `.env` 设 `DISPATCH_SKIP_MARKDOWN_CARD=1`

### 分支 E：启动后出现两个 python.exe（正常行为，不是重复启动）

**现象**：用 `run_bridge.ps1` 或 `python dispatch_bot.py` 启动后，`tasklist` / WMI 里看到 **两个** `python.exe` 进程：
- 一个来自 `.venv\Scripts\python.exe .\dispatch_bot.py`
- 一个来自系统 Python（如 `C:\Users\...\Python311\python.exe .\dispatch_bot.py`）

**排查**：
```powershell
# 查进程父子关系
Get-WmiObject Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*dispatch_bot*' } | Select-Object ProcessId,ParentProcessId,CommandLine

# 查谁真正持有网络连接（连钉钉 Stream）
Get-NetTCPConnection -OwningProcess <PID> | Select-Object RemoteAddress,RemotePort,State
```

**结论**：
- **父进程**（.venv python）≈ launcher，通常**没有 Established 外网连接**
- **子进程**（系统 Python311）≈ worker，会显示 `Established` 到钉钉服务器（如 `39.98.45.86:443`）
- 这是 `dingtalk_stream` 库内部行为（Windows spawn / worker 机制），**不是配置错误，也不是重复启动**
- **不要单独杀子进程**，否则父进程也会退出；要停就停父进程

### 分支 F：bash 中启动 PowerShell 命令时 `$env:` 被提前解析（静默失败）

**现象**：在 bash（Git Bash / MSYS2）中执行：
```bash
powershell -Command "$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + ..."
```
bash 会提前把 `$env:Path` 解析为空字符串，导致 PowerShell 实际收到的是 `:Path = ...`，报错 `CommandNotFoundException: :Path`，但错误可能被吞掉。

**修复**：用**单引号**包裹 PowerShell 命令，阻止 bash 解析 `$`：
```bash
powershell -Command 'cd D:\MyAgents\tools\multica-dingtalk-bridge; .\run_bridge.ps1'
```

### 分支 G：外部 watchdog 自动重启（quick_start / 计划任务 / 其他脚本）

**现象**：杀掉 dispatch_bot 后，过几秒又自动出现新的进程。

**排查**：
```powershell
# 1. 观察 30 秒：全部杀掉后等半分钟，看是否有新进程自动冒出
taskkill /F /IM python.exe  # 或精确杀 dispatch_bot
# 等待 30 秒后再次 tasklist

# 2. 检查 quick_start.bat 是否仍在后台运行并自动拉起
Get-Process | Where-Object { $_.ProcessName -like '*quick_start*' }

# 3. 检查 Windows 计划任务
Get-ScheduledTask | Where-Object { $_.TaskName -like '*multica*' -or $_.Actions -match 'dispatch_bot' }
```

**注意**：当前版本 `pm-system/quick_start.bat` 的菜单 7 已是 **Hermes gateway**，**不再**顺带拉起 multica 桥。如果看到旧文档说「quick_start 会拉起派单桥」，以当前 `quick_start.bat` 实际内容为准。

## 验证修复

1. 钉钉发一条测试消息：`派单 测试工单`
2. 预期回复（Hermes 路由模式或独立桥模式版式一致）：
   - 包含 `📋 编号 \`XXX-N\``
   - 包含 `✅ 工单已写入 Multica`
   - 包含「点击查看」工单直链
3. 去 Multica Web 看板确认工单真的创建成功

## 相关文件

- `D:/MyAgents/tools/multica-dingtalk-bridge/dispatch_bot.py`
- `D:/MyAgents/tools/multica-dingtalk-bridge/README.md`
- `D:/MyAgents/WORK_LOG.md`（搜索 multica / 派单 / Hermes 入站路由）
- `D:/hermes/hermes-agent/gateway/run.py`（搜索 `_route_inbound_commands_if_any`）
- `D:/hermes/hermes-agent/gateway/inbound_command_router/` （若存在则路由代码还在）

## 附录：Windows Git Bash 显示陷阱

在 Windows Git Bash 下用 `sed`/`grep`/`cat` 查看含中文标点（顿号 `、`、全角逗号 `，`、全角分号 `；`）的行时，输出可能被截断显示为 `re.com...]+")`，误以为语法错误。

验证实际内容的可靠方法：
```bash
# 方法 1：用 od -c 看十六进制原文
sed -n '58p' dispatch_bot.py | od -c

# 方法 2：用 python 简单验证
python -c "import py_compile; py_compile.compile('dispatch_bot.py')"
```

如果 `py_compile` 通过则文件完全正常，只是终端显示层的编码问题。