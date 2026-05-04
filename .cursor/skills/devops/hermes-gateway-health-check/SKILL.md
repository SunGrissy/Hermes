---
name: hermes-gateway-health-check
description: |
  排查 Windows 环境下 Hermes Gateway 实例（硅基军团多 Agent）是否真在线、
  是否存在残留旧进程、以及 PID 文件是否过期。
  解决「tasklist 搜不到 gateway」「PID 文件与实际进程对不上」等常见误判。
trigger:
  - "Agent 没反应"
  - "看看 XX 怎么了"
  - "gateway 挂了没"
  - "PID 文件对不上"
  - "hermes 进程好多"
platform: windows
---

# Hermes Gateway 实例健康排查（Windows）

## 适用场景

- 怀疑某个 Advisor / Agent Gateway 掉线或没响应
- `tasklist | findstr hermes` 结果与预期不符
- `gateway.pid` 里的 PID 在任务管理器里找不到
- 重启 gateway 后旧进程残留、系统越积越多

## 核心坑点（先记住，少走冤枉路）

1. **Gateway 主进程名是 `python.exe`，不是 `hermes.exe`**  
   Windows 上 `hermes.exe` 只是 Python 脚本包装器。实际运行时，Gateway 以 `python.exe D:\...\hermes-agent\venv\Scripts\hermes.exe gateway run` 的形式存在。用 `tasklist | findstr hermes` 只能找到子进程/残留进程，**找不到真正的 gateway**。

2. **PID 文件容易过期，且会锁死重启**  
   如果 gateway 崩溃或被强制 kill 后重启，新进程会拿到新 PID，但旧 `gateway.pid` 不会被自动更新。更麻烦的是：`gateway.pid` 里指向的 PID 已经不存在时，`hermes gateway run` 会报 "Gateway already running (PID X)" 并直接退出；`hermes gateway stop` 则会因为 `os.kill(pid, 0)` 对一个不存在的 PID 操作而抛出 `WinError 87` / `SystemError`。此时**必须用 Python 直接删除 `gateway.pid`**，CLI 命令失效。

3. **hermes launcher 会导致 PID 漂移**  
   `hermes.exe gateway run` 启动时，会先 spawn 一个短暂的中间进程，gateway.pid 记录的是这个中间进程的 PID。但该进程很快退出，真正的 gateway 进程是另一个新 PID。结果是：gateway.pid 里的 PID 与实际运行的 gateway 进程对不上。下次 `stop`/`replace` 时又会失败，需要手动修正 gateway.pid。

4. **Msys / Git Bash 环境下原生命令不可靠**  
   `rm gateway.pid`、`taskkill`、`hermes gateway stop` 在 Msys 终端里可能超时、乱码、或行为异常。排查和修复时应**优先用 Python 脚本**（`os.remove()`、`psutil.Process().terminate()`），而不是 shell 命令。

5. **残留进程会堆积**  
   每次 `gateway restart` 或 `start_army.bat` 如果没有先 `gateway stop` / `taskkill`，旧的 `python.exe` gateway 进程和它的 `hermes.exe` 子进程都会残留下来。

## 排查步骤

### 第一步：读取各实例 PID 文件

```bash
for dir in D:/hermes D:/hermes/acha D:/hermes/xiaomei D:/hermes/miaomiao D:/hermes/dangdang; do
  echo "=== $dir ==="
  cat "$dir/gateway.pid" 2>/dev/null | head -1
done
```

记录每个实例声明的 PID。

### 第二步：用 Python psutil 找真正的 gateway 进程

不要用 `tasklist`，直接用 psutil 按命令行内容过滤：

```python
import psutil
for p in psutil.process_iter(['pid','name','cmdline','create_time']):
    cmd = ' '.join(p.info['cmdline'][:5]) if p.info['cmdline'] else ''
    if 'hermes' in cmd.lower() and 'gateway' in cmd.lower():
        print(f"PID={p.pid} NAME={p.name()} CMD={cmd}")
```

这会列出所有含 `hermes gateway run` 的进程，包括 `python.exe` 和 `hermes.exe`。

### 第三步：匹配 PID 文件与存活进程

- 如果 PID 文件里的 PID **出现在** psutil 结果中 → gateway 很可能还活着。
- 如果 PID 文件里的 PID **不在** psutil 结果中 → PID 文件过期，需要用第四步确认真实状态。

### 第四步：验证网络连接（判断真假在线）

一个活着的 gateway 必须有对外的钉钉 Stream / WebSocket 连接（通常是 443 端口到钉钉 IP）。检查命令：

```python
import psutil
pids = [12856, 33112, 40368, 41156, 44968]  # 替换为实际 PID
for i in pids:
    p = psutil.Process(i)
    print(f"PID={p.pid} NAME={p.name()}")
    for c in p.net_connections(kind='inet'):
        if c.status == 'ESTABLISHED':
            print(f"  ESTABLISHED {c.laddr} -> {c.raddr}")
    print()
```

- **有 ESTABLISHED 外连（如 39.98.45.86:443）** → gateway 在线，Stream 正常。
- **只有 127.0.0.1 回环连接，没有外连** → gateway 进程存在但可能已经断网/重连中，需进一步看日志。
- **没有任何连接** → 大概率是僵尸/残留进程，可直接 kill。

### 第五步：看日志确认最后活跃时间

```bash
# 最后几条日志
tail -30 D:/hermes/<实例>/logs/agent.log

# 最近是否有错误
tail -20 D:/hermes/<实例>/logs/errors.log
```

- 如果最后日志时间距今几分钟到几小时 → 可能只是空闲，没收到消息。
- 如果最后日志时间是昨天/更早，而网络连接也存在 → 说明 gateway 活着但长时间没处理消息，需要检查钉钉 Stream 是否断开（errors.log 里常会有重连记录）。

### 第六步：识别并清理残留进程

对比「当前所有含 `gateway run` 的进程」和「PID 文件里声明的 5 个正确 PID」。多出来的就是残留。

```python
import psutil, datetime
# 正确的 5 个 PID
alive = {12856, 33112, 40368, 41156, 44968}

for p in psutil.process_iter(['pid','name','cmdline','create_time']):
    cmd = ' '.join(p.info['cmdline'][:5]) if p.info['cmdline'] else ''
    if 'hermes' in cmd.lower() and 'gateway' in cmd.lower():
        if p.pid not in alive:
            ct = datetime.datetime.fromtimestamp(p.create_time()).strftime("%m-%d %H:%M")
            print(f"STALE PID={p.pid} NAME={p.name()} create={ct}")
```

清理方式（谨慎，确认后再执行）：

```python
import psutil
stale = [27960, 29236, 40996, 42092, 45024]  # 实际残留 PID
for pid in stale:
    try:
        psutil.Process(pid).terminate()
    except psutil.NoSuchProcess:
        pass
```

> 注意：先 `terminate()`，等几秒仍不死的再用 `kill()`。

### 第七步：当 Gateway 完全起不来时 — 排查 GBK 编码崩溃

如果 `hermes.exe` / `python.exe` 进程根本不存在、`gateway_state.json` 没生成，但 `hermes doctor` 报告正常（config 存在、依赖齐全），很可能是 **emoji 字符在 Windows GBK 编码下导致 Python 崩溃**。

**症状：**
- `hermes gateway run` 执行后 **0.5 秒内退出**，不留任何日志，`gateway_state.json` 不生成
- 在 pwsh 终端中直接运行（`$env:PYTHONIOENCODING='utf-8'; ... hermes.exe gateway run`）能看到报错：
  ```
  UnicodeEncodeError: 'gbk' codec can't encode character '\u274c' in position 2: illegal multibyte sequence
  ```

**根因：**
Hermes 源码 `gateway/run.py` 在日志输出中使用了 emoji（`✓` / `✗`，U+2713 / U+274C）。Windows 默认编码 GBK 不支持这些字符，Python print/logger 直接抛异常退出。

**修复方法（两处都要做）：**

1. **修改 `gateway/run.py` 中的 emoji**（找到对应行，替换为 ASCII）：
   - `"✓ %s connected"` → `"[OK] %s connected"`（约 2098 行）
   - `"✗ %s failed to connect"` → `"[FAIL] %s failed to connect"`（约 2100 行）

2. **在启动脚本（bat/ps1）中添加 `PYTHONIOENCODING=utf-8`** 作为双重保障：
   ```bat
   set PYTHONIOENCODING=utf-8
   start "满满_Gateway" venv\Scripts\hermes.exe gateway run --accept-hooks
   ```

**快速定位文件中所有 emoji 的方法：**
```python
# 在 Python 中扫描 run.py 找到所有非 ASCII 字符
lines = open('D:/hermes/hermes-agent/gateway/run.py', encoding='utf-8').readlines()
emoji_ranges = [(0x1F300,0x1F9FF), (0x2702,0x27B0), (0x274C,0x274C)]
for i, line in enumerate(lines):
    for ch in line:
        cp = ord(ch)
        for lo, hi in emoji_ranges:
            if lo <= cp <= hi:
                print(f'Line {i+1}: emoji U+{cp:04X} -> {line.rstrip()[:200]}')
                break
        else:
            continue
        break
```

> ⚠️ 注意：Git Bash / Msys 环境下 `pwsh` 的 `&` 操作符会被 Hermes 框架误判为后台运行符号，导致命令无法正常执行。排查时应直接用 Windows 原生 cmd 或 PowerShell 窗口。

## 常见误判与纠正

| 误判 | 真相 |
|------|------|
| "tasklist 里没有 hermes.exe，所以 gateway 挂了" | gateway 主进程是 `python.exe`，`hermes.exe` 只是包装器 |
| "gateway.pid 里的 PID 找不到，所以挂了" | PID 文件可能过期，实际 gateway 已换 PID |
| "有 5 个 hermes.exe，说明 5 个 gateway 都在" | 这 5 个可能是残留子进程，真正的 gateway 是另外 5 个 `python.exe` |
| "agent.log 1 小时没新记录，所以挂了" | 可能只是没人发消息，看网络连接才能确认 |

## 快速健康检查脚本（一次性跑完）

```python
import psutil, json, datetime

INSTANCES = {
    'man': 'D:/hermes',
    'acha': 'D:/hermes/acha',
    'xiaomei': 'D:/hermes/xiaomei',
    'miaomiao': 'D:/hermes/miaomiao',
    'dangdang': 'D:/hermes/dangdang',
}

# 读 PID 文件
recorded = {}
for name, path in INSTANCES.items():
    try:
        with open(f"{path}/gateway.pid") as f:
            data = json.load(f)
            recorded[name] = data.get('pid')
    except:
        recorded[name] = None

# 扫描所有 hermes gateway 进程
gateways = {}
stale = []
for p in psutil.process_iter(['pid','name','cmdline','create_time']):
    cmd = ' '.join(p.info['cmdline'][:5]) if p.info['cmdline'] else ''
    if 'hermes' in cmd.lower() and 'gateway' in cmd.lower() and 'run' in cmd.lower():
        gateways[p.pid] = p

# 匹配
for name, pid in recorded.items():
    if pid and pid in gateways:
        p = gateways[pid]
        has_external = any(
            c.status == 'ESTABLISHED' and c.raddr and c.raddr.ip != '127.0.0.1'
            for c in p.net_connections(kind='inet')
        )
        print(f"{name}: PID={pid} OK (external_conn={has_external})")
    else:
        print(f"{name}: PID={pid} NOT FOUND (stale pid file?)")

# 报告残留
for pid, p in gateways.items():
    if pid not in recorded.values():
        ct = datetime.datetime.fromtimestamp(p.create_time()).strftime("%m-%d %H:%M")
        print(f"STALE: PID={pid} NAME={p.name()} since={ct}")
```

## 关联 Skill

- `cron-silent-failure-recovery`：如果排查后发现是 cron job 没输出或没送达，用这个继续处理。
- `multi-agent-dingtalk-workflow`：涉及多 Agent Stream 竞争、读写分离的架构问题。
