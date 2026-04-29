# Claude 调用遥测（JSONL）

用于统计：**老大发布的任务数**（按 `task_id` 去重）与 **实际 Claude 调用次数**（日志行数），以及成本/风险相关信号。

## 落盘位置

默认目录：`shared-memory/claude-calls/`（与仓库根并列，勿提交 `*.jsonl`）。

可通过环境变量覆盖：

- `CLAUDE_CALL_LOG_DIR`：绝对路径，指向自定义日志目录

按日滚动文件名：`calls-YYYY-MM-DD.jsonl`（日期为东八区自然日）。

## 字段说明（每行一条 JSON）

| 字段 | 含义 |
|------|------|
| `task_id` | 一次「任务」的稳定 ID；同一任务下多次调用共用此 ID |
| `call_index` | 该任务当日内第几次调用（从 1 递增） |
| `caller` | 调用来源，如 `multica-dingtalk-bridge.code_review_dispatcher` |
| `task_title` | 可选，人类可读标题（截断 200 字） |
| `prompt_sha256_16` | 主 prompt 的 SHA256 前 16 位（不落全文） |
| `prompt_chars` | prompt 字符数 |
| `duration_ms` | 子进程耗时 |
| `status` | `ok` / `error` / `timeout` |
| `exit_code` | 子进程退出码（超时为 `null`） |
| `dangerous_keywords_hit` | prompt 中命中的高危短语标签列表 |
| `prompt_tokens` / `output_tokens` | 若 `claude --print --output-format json`  stdout 中含 `usage` 则填充 |

## 上游约定

- **task_id**：在任务入口生成一次（如钉钉 `conversationId + messageId`、或业务前缀 `code-review:UUM-24`），同一任务内所有 `call_claude_with_telemetry` 调用复用。
- **call_index**：可省略，模块会扫描当日文件对该 `task_id` 自动 +1；高并发时建议调用方显式传入。

## Python API

仓库内任一脚本将 `MyAgents/tools` 加入 `sys.path` 后：

```python
from claude_call_telemetry.telemetry import call_claude_with_telemetry

result = call_claude_with_telemetry(
    cmd=["claude", "--print", "--output-format", "json", prompt],
    cwd=r"D:\MyAgents",
    env=os.environ.copy(),
    timeout=600,
    task_id="dingtalk-msg-abc",
    caller="hermes.openclaw",
    task_title="突发现场排查",
)
```

## 按日汇总

在 `MyAgents` 根目录执行（需已安装依赖无额外要求）：

```powershell
cd D:\MyAgents\tools
$env:PYTHONPATH = "D:\MyAgents\tools"
py -m claude_call_telemetry.aggregate --date 2026-04-29
```

或直接：

```powershell
py D:\MyAgents\tools\claude_call_telemetry\aggregate.py --date 2026-04-29
```

输出含：`distinct_tasks`、`total_calls`、`avg_calls_per_task`、`dangerous_keyword_rows`、`by_caller`、`status` 分布等。

## 已接入调用点

- `tools/multica-dingtalk-bridge/code_review_dispatcher.py`：`task_id` 形如 `code-review:{issue_id}`，每条工单审查为一条任务维度；若同一工单重试审查，`call_index` 递增。

Hermes / OpenClaw 其他入口接入时复用同一 API 即可。
