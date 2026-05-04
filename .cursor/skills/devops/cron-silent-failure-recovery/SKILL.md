---
name: cron-silent-failure-recovery
description: |
  当定时 cron job 触发后没有产生输出、没有送达用户，或 last_status 为 error 时，
  通过检查 cron 输出文件定位根因，并手动在本会话中补执行任务、交付结果。
  覆盖：任务状态核验 → 输出文件诊断 → 手动重试 → 会话内 fallback 执行 → Windows 环境坑点。
trigger: |
  - 用户问"定时任务没执行？"
  - cron job last_status 为 error 或输出为 (No response generated)
  - 预期中的定时扫描/日报/巡检没有送达
---

# Cron Job Silent Failure Recovery

## 1. 核验任务是否真的触发了

调用 `cronjob(action='list')`，检查目标 job 的字段：

| 字段 | 含义 |
|------|------|
| `last_run_at` | 上次实际触发时间 |
| `last_status` | `error` = 已触发但执行失败；`null` = 尚未执行 |
| `next_run_at` | 下次计划触发时间 |

**常见误区：** 用户说"没执行"，实际可能是触发了但失败了，不要只凭用户描述就下结论。

## 2. 读取 cron 输出文件 + Hermes 日志

输出文件路径规律（固定）：
```
/d/hermes/cron/output/<job_id>/<YYYY-MM-DD_HH-MM-SS>.md
```

列出最近输出：
```bash
find /d/hermes/cron/output/<job_id> -type f -mmin -120 | sort
```

用 `read_file` 读取最新一份。重点看最后的 `## Response` 区块：
- 正常：有实际生成的报告/消息内容
- **失败特征**：`(No response generated)` —— Agent 被调起但没有产生任何输出

> 如果输出文件不存在，说明 cron 调度器本身没有成功派生任务，需检查 Hermes 后端日志。

### 诊断线索：`cronjob(action='run')` 返回 success 但 `last_run_at` 不更新

如果手动触发 run 后 `last_run_at` 仍然没变，说明 tick 被跳过了。立即检查：
```bash
ls -la D:/hermes/cron/.tick.lock
```
如果锁文件存在，参见第 5a 节。

### 2a. 关键：同时读 Hermes 日志定位根因

当输出为 `(No response generated)` 时，不要只盯着输出文件，一定要去读 `errors.log` 和 `agent.log`：

```bash
grep -n "cron\|<job_id>\|Non-retryable\|model" D:/hermes/logs/errors.log | tail -30
grep -n "cron\|<job_id>\|failed to load config" D:/hermes/logs/agent.log | tail -30
```

**典型根因模式 A — API 400 未指定模型：**
```
Non-retryable client error: Error code: 400 - {'error': {'message': '未指定模型名称，模型名称不能为空'}}
```
→ 模型名丢失，继续追查「模型名从哪来」。

**典型根因模式 B — config.yaml 编码加载失败：**
```
WARNING cron.scheduler: failed to load config.yaml, using defaults: 'gbk' codec can't decode byte...
```
→ scheduler.py 用默认编码（Windows 为 GBK）打开 UTF-8 的 config.yaml，解码失败，回退到空配置。详见第 6 节。

## 3. 尝试手动重跑

```
cronjob(action='run', job_id='<hash_id>')
```

**必须用 hash job_id**（如 `69a457d64d8c`），不能用 `name`（如 `daily-focus-21`）。

重跑后再次检查输出文件。如果仍然是 `(No response generated)`，说明 **cron 执行环境有系统性问题**（模型 API 超时、工具在 cron 上下文不可用、网络不通等），不要反复重跑，直接进入第 4 步。

## 4. 会话内手动 fallback 执行

从输出文件顶部提取 `## Prompt` 区块的内容，在本会话中按原 prompt 的逻辑手动执行：

1. **采集相同数据源**（API、日程、git log、memory 文件）
2. **按原格式生成输出**
3. **直接交付给用户**（cron 的 `DELIVERY` 机制失效时，由当前会话代为交付）

## 5. Windows / Git Bash 环境坑点（血泪经验）

当前终端底层是 **Git Bash**，不是 PowerShell/cmd：
- ❌ `if exist D:\file (type file) else (...)` —— 这是 cmd 语法，bash 会报 syntax error
- ✅ 用 bash 语法：`cat D:/file 2>/dev/null || echo "not found"`

临时文件路径：
- ❌ `/tmp/` —— Git Bash 有 `/tmp` 但某些场景下权限或映射有问题，且 Python 可能解析不到
- ✅ 用 `D:/hermes/cron/` 或 `D:/temp/` 等明确路径

Python 文件编码：
- ❌ `open('file')` —— Windows 默认用 GBK，读取 UTF-8 JSON 会报 `UnicodeDecodeError`
- ✅ `open('file', encoding='utf-8')`

Python 命令：
- ❌ `python3 -c` —— 系统可能没有 `python3` 别名
- ✅ `py -c` —— Windows 标准入口

### 5a. 文件锁残留：`.tick.lock` 导致 tick 永远跳过

Cron scheduler 使用跨进程文件锁（`D:/hermes/cron/.tick.lock`）防止并发 tick。如果旧 Hermes 进程被**强制终止**（`Stop-Process -Force` / `taskkill /F`），锁可能不会被操作系统立即释放，新进程每次 tick 都拿不到锁，所有 cron job 被静默跳过。

**诊断：**
```bash
ls -la D:/hermes/cron/.tick.lock
# 如果文件存在且时间戳持续更新，说明有进程在尝试获取锁但失败
```

**修复：**
```bash
rm -f D:/hermes/cron/.tick.lock
```

**验证锁释放后：**
```bash
grep "Cron ticker started" D:/hermes/logs/agent.log | tail -3
# 确认只有一个 cron ticker 实例在运行
```

### 5b. 多 Hermes 实例竞争

Windows 上重启 Hermes 时，旧进程如果没被干净杀掉，会出现多个实例同时运行。表现为：
- 日志中出现 `Another gateway instance is already running (PID xxxx)`
- cron 行为异常（一个实例执行，另一个实例抢锁）

**排查：**
```bash
py -c "import psutil; [print(p.info['pid'], p.info['exe']) for p in psutil.process_iter(['pid','name','exe']) if p.info['name']=='python.exe' and p.info['exe'] and 'hermes' in p.info['exe'].lower()]"
```

**处理：** 保留最新启动的实例，杀掉旧的（及其子进程），然后删除 `.tick.lock`。

## 5a. 专项：scheduler.py 编码问题导致模型名丢失

这是一个已在现场中实际出现过的典型根因链路，引发所有 cron job 集体失败。

### 根因链路

1. `scheduler.py` 中 `open(_cfg_path)` 未指定 `encoding='utf-8'`
2. Windows 上 Python 默认用 GBK 打开文件
3. `config.yaml` 含有 UTF-8 中文字符，解码失败
4. config 回退到空配置，读不到 `model.default`
5. cron job 未设置 per-job model，环境变量 `HERMES_MODEL` 也为空
6. 传给 LLM API 的模型名为空字符串，途游 relay 返回 400："未指定模型名称"
7. Agent 内部吞掉错误没有抛异常，`final_response` 为空
8. scheduler 判定为 `Agent completed but produced empty response`

### 修复方案

打开 `scheduler.py`，找到读取 config.yaml 的位置（通常在 `run_job` 函数内），给 `open()` 补上编码参数：

```python
# 修复前
with open(_cfg_path) as _f:
    _cfg = yaml.safe_load(_f) or {}

# 修复后
with open(_cfg_path, encoding="utf-8") as _f:
    _cfg = yaml.safe_load(_f) or {}
```

修复后验证：
```bash
py -c "import py_compile; py_compile.compile('D:/hermes/hermes-agent/cron/scheduler.py', doraise=True)"
```

同时建议确认 `config.yaml` 中有正确的 `model` 配置：
```yaml
model:
  provider: tuyoo
  default: kimi-k2.6
```

## 6. 事后修复

手动补偿完成后，视情况：
- 重启 Hermes gateway 或 cron 服务（如果判断为系统性故障）
- 将根因和绕法更新到 `memory`
- 若该 cron job 频繁失败，考虑把任务逻辑改为 heartbeat 驱动而非精确 cron