# 日报全文拉取重构方案

> **本文档是执行约束文档**，供后续 Agent 会话按此执行代码改动。
> 不要偏离本文档描述的范围和方式。
> 本会话代号：AgentReport

---

## 1. 背景与目标

### 现状问题

`report_digest.py` 的日报全文获取依赖 **CEF 浏览器打开 H5 详情页**（`daemon.fetch_report_content`），链路为：

```
群消息(ct=2950卡片) → 提取 report_url → POST /fetch_report_content
  → daemon 用 browser 1 loadUrl → 等 SPA 渲染 → 注入 JS 抽 DOM → beacon 回传
```

此链路**极不稳定**：
- 页面登录态过期 → `no rpt_meta from page`
- SPA 渲染慢 → `timed out`
- 串行处理，一条卡住全队等
- 每条耗时 20-60 秒

### 目标

**用 daemon 已有的 `/fetch_reports` 接口从「日志收件箱」CID 拉取 ct=300 消息，直接解析 `bf`（`b_form`）JSON 表单获取全文，不再依赖 CEF。**

预期效果：
- 全文获取速度从 **分钟级** → **秒级**
- 不依赖 CEF / browser 1 / beacon / H5 页面渲染
- 稳定性与钉钉 JSAPI 一致（或回退到 monitor 日志扫描）

---

## 2. 关键概念对照

| 概念 | ct=2950（当前方式） | ct=300（目标方式） |
|------|---------------------|---------------------|
| **钉钉场景** | 群聊里的日报转发卡片 | 工作汇报频道（日志收件箱） |
| **数据来源** | `digest_config.json` 的 `report_cids`（各群 CID） | `config.json` 的 `report_cid`（收件箱 CID）；**需确认或新增配置** |
| **全文在哪** | 卡片只有摘要 + `report_url`；全文要靠 CEF 打开 URL | `bf` / `b_form` 字段 = JSON 数组 `[{k, v}, ...]`，就是完整表单 |
| **发送人** | 卡片标题 `[日志] 张三的日报` 解析 | `sender` 字段（UID），需通过通讯录解析为姓名 |
| **时间** | `ts` 毫秒时间戳 | 同 |

---

## 3. daemon 已有能力（不需要改 daemon）

以下接口**已存在且可直接使用**，本次改动**不修改 `daemon.py`**：

### 3a. `POST /fetch_reports`（daemon HTTP）

```json
{
  "cid": "日志收件箱CID",
  "count": 80,
  "after": "2026-03-31 18:30:00",
  "before": "2026-04-01 12:00:00",
  "max_pages": 30,
  "max_seconds": 60,
  "source": "log"
}
```

- 有 JSAPI browser 时走 `fetch_reports_paginated`（翻页拉取）
- JSAPI 不可用时自动降级到 `fetch_reports_from_log`（扫 `_msg_log.jsonl`）
- 传 `"source": "log"` 可强制走日志
- 返回消息包含 `bf` / `b_form` 等原始字段（JSAPI 路径由 JS 拼接 `_bf_raw`）

### 3b. monitor 日志中 ct=300 的结构

`lib/monitor.py` 在 `_process_push` 中对 ct=300 做了 `b_form` 解析：

```
monitor.py:240  b_form = body.get('b_form', [])
monitor.py:242  if isinstance(b_form, list) and b_form:
monitor.py:244      for item in b_form:  # [{k, v}, ...]
```

写入 `_msg_log.jsonl` 的 `text` 字段已拼接为 `标题 | key: value | key: value` 格式。

---

## 4. 需要改的文件和改法

### 只改一个文件：`report_digest.py`

**不改 `daemon.py`、不改 `lib/monitor.py`、不改 `skill_router.py`、不改 `run_daily_digest.ps1`。**

---

### 4a. 新增配置项（`digest_config.json`）

在 `digest_config.json` **顶层**新增：

```json
{
  "report_inbox_cid": "",
  "_note_report_inbox_cid": "钉钉「日志收件箱」会话 CID；非空时 report_digest 优先从此 CID 拉 ct=300 全文，不再依赖 CEF。留空则保持旧行为（群卡片 + CEF）。"
}
```

**执行者须向用户确认此 CID 的值**（可通过 `py mcp_server.py` 的 `dingtalk_find_conversation` 或 `daemon /contacts?name=日志` 查找）。

---

### 4b. 新增函数：`fetch_reports_from_inbox`

在 `report_digest.py` 中，**`fetch_reports` 函数之前**新增：

```python
def fetch_reports_from_inbox(target_date, inbox_cid, after_str=None, before_str=None):
    """从日志收件箱 CID 拉取 ct=300 日报，bf 字段即全文。"""
```

**函数逻辑**：

1. 计算时间窗口（与 `fetch_reports` 完全相同：默认 `target_date 18:30 → 次日 12:00`）
2. 调用 `_daemon_request('/fetch_reports', {...})`，**只传一个 CID**（`inbox_cid`），参数与现有 `fetch_reports` 一致
3. 返回值格式与 `fetch_reports` 相同：`list[dict]`，每个 dict 含 `ts`, `sender`, `text`, `bf`/`b_form` 等
4. **去重逻辑**与现有 `fetch_reports` 相同（`ts_sender` 键去重 + 内容前 80 字去重）
5. **不做任何 CEF 调用**

**约束**：
- 不要给这个函数加任何新的 daemon API 调用，只用 `/fetch_reports`
- 不要在函数内 import 新的库
- 打印日志格式与现有保持一致：`print(f'[inbox] ...', flush=True)`

---

### 4c. 修改 `main()` 函数中的主流程

**当前流程**（`main()` 约 1467-1486 行）：

```python
messages = fetch_reports(target_date, report_cids)           # 群卡片
messages = _enrich_from_monitor_log(messages, ...)            # monitor 补全
if args.full_content:
    messages = fetch_full_contents(messages)                  # CEF 全文 ← 要替换
```

**改为**：

```python
inbox_cid = config.get('report_inbox_cid', '').strip()
if inbox_cid:
    # 新路径：日志收件箱 ct=300，bf 字段即全文
    messages = fetch_reports_from_inbox(target_date, inbox_cid)
    print(f'[report-digest] inbox mode: {len(messages)} reports from {inbox_cid}', flush=True)
else:
    # 旧路径：群卡片 + monitor 补全 + CEF（保留兼容）
    messages = fetch_reports(target_date, report_cids)
    jsapi_count = len(messages)
    messages = _enrich_from_monitor_log(messages, target_date, report_cids)
    if args.full_content:
        messages = fetch_full_contents(messages)
```

**约束**：
- `inbox_cid` 为空字符串时，**完全走旧路径**，不改任何旧逻辑
- 旧路径的 `fetch_reports` / `_enrich_from_monitor_log` / `fetch_full_contents` **不删不改**
- 新路径**不调用** `fetch_full_contents`（不需要 CEF）
- 新路径**不调用** `_enrich_from_monitor_log`（inbox 本身就是完整来源）

---

### 4d. `_extract_report_text` 已兼容，不需要改

现有代码（约 528-558 行）：

```python
def _extract_report_text(m):
    full_body = (m.get('_report_body') or '').strip()
    if full_body:
        return full_body
    bf_raw = m.get('bf') or m.get('b_form') or ''
    if bf_raw:
        ...解析 [{k, v}] 拼成全文...
    return m.get('text', '') or ''
```

**ct=300 消息的 `bf` 字段会被正确解析**——前提是 daemon 返回的消息 dict 里包含 `bf` 或 `b_form` 键。

**需确认的一点**：daemon JSAPI 路径在 JS 中把 bf 存到了 `_bf_raw` 变量，但最终写到 beacon 回传的消息里键名叫什么？查看 daemon.py:1931：

```javascript
_bf_raw=bf;
```

但这个变量之后**没有作为独立字段输出到消息 dict 中**——它只用于拼接 `text` 字段。所以 JSAPI 路径返回的消息里 **`bf` 字段可能为空**，全文已经拼进了 `text`。

**对策**：在 `fetch_reports_from_inbox` 中，如果消息没有 `bf`/`b_form` 字段但 `text` 已包含 `key::value` 格式的拼接文本（JSAPI 拼接格式：`标题 [类型] || key::value || key::value`），则 `_extract_report_text` 的最后一行 `return m.get('text', '')` 会兜底返回这个拼接文本。**这已经是全文**，够 LLM 分析用。

如果走 `source=log` 降级路径（从 `_msg_log.jsonl` 扫描），monitor 写入时 `text` 也是拼接后的全文。

**结论：`_extract_report_text` 不需要改。**

---

### 4e. `--fetch-only` 模式也需要同步

`main()` 中 `args.fetch_only` 分支（约 1357-1428 行）也需要加 inbox 判断。**改法与 4c 相同**：

```python
if inbox_cid:
    messages = fetch_reports_from_inbox(target_date_for_fetch_only, inbox_cid,
                                        after_str=after_str, before_str=before_str)
else:
    # 保持原逻辑
    ...
```

**约束**：
- `--fetch-only` 与主流程共用 `fetch_reports_from_inbox`
- `--fetch-only` 模式下 inbox 路径**不调用** `fetch_full_contents`

---

### 4f. sender 姓名解析

ct=300 从 JSAPI 拉取时，`sender` 可能是 UID 而非姓名（daemon.py:1944 `creatorId`）。

**需要做**：在 `fetch_reports_from_inbox` 返回前，对每条消息检查 `sender` 是否为纯数字 UID；如果是，尝试通过 `_daemon_request('/contacts', ...)` 或本地 contacts DB 解析为姓名。

**简化方案**：复用 `digest_config.json` 的 `team_members` 列表做反向匹配（现有 `analyze_reports` 已经按姓名匹配成员）。如果 sender 解析失败，保留原始 UID，不要报错。

**约束**：不要为此新增 daemon API。可以用现有的 `GET /contacts?name=...` 或直接读 `_CONTACTS_FILE`。

---

## 5. 不改的东西（红线）

| 文件 | 说明 |
|------|------|
| `daemon.py` | 不改。所有 daemon HTTP API 已够用 |
| `lib/monitor.py` | 不改。日志记录逻辑不动 |
| `lib/utils.py` | 不改 |
| `skill_router.py` | 不改 |
| `run_daily_digest.ps1` | 不改（本次不处理 `DINGTALK_DATA_DIR` 环境变量问题） |
| `mcp_server.py` | 不改（可在后续独立会话添加 MCP 工具） |
| `digest_config.json` 的已有字段 | 不改任何已有字段。只**新增** `report_inbox_cid` |
| `message_templates.json` | 不改 |
| `fetch_reports()` 函数 | 不改。旧路径完整保留 |
| `_enrich_from_monitor_log()` | 不改 |
| `fetch_full_contents()` | 不改不删。旧路径仍可用 |
| `analyze_reports()` | 不改。它接收 messages 列表，调 `_extract_report_text` 提取文本 |
| `_extract_report_text()` | 不改。已兼容 bf 解析 |

---

## 6. 测试验证步骤

改完代码后，按以下顺序验证：

### 6a. 语法检查

```powershell
py -c "import ast; ast.parse(open(r'report_digest.py', encoding='utf-8').read()); print('OK')"
```

### 6b. 确认 inbox CID

向用户确认 `report_inbox_cid` 的值（用户可通过钉钉 → 工作台 → 日志 找到收件箱；或用 daemon `/contacts` 查找）。

### 6c. dry-run 验证（不发消息）

```powershell
$env:DINGTALK_DATA_DIR='D:\MyAgents\data\dingtalk'
py report_digest.py --date 2026-03-31 --dry-run --digest-group pipeline
```

预期输出：
- `[report-digest] inbox mode: N reports from <CID>`（N > 0）
- 随后 LLM 分析并输出摘要
- 不应出现 `[full-content]` 或 `fetch_report_content` 相关日志

### 6d. fetch-only 验证

```powershell
py report_digest.py --fetch-only --date 2026-03-31 --dry-run
```

预期：从 inbox 拉取，不走 CEF。

### 6e. 旧路径兼容验证

把 `digest_config.json` 的 `report_inbox_cid` 设为空字符串 `""`，重跑 6c，确认走旧路径（群卡片 + monitor + CEF）。

---

## 7. 风险与回退

| 风险 | 应对 |
|------|------|
| inbox CID 不对 / 用户没有权限看到所有人日报 | `report_inbox_cid` 设空即回退旧路径 |
| JSAPI 拉 ct=300 也 timed out | daemon 自动降级到 `fetch_reports_from_log`（扫日志）；日志里有 monitor 记录的 ct=300 |
| bf 字段为空（某些日报模板不带表单） | `_extract_report_text` 兜底用 `text` 字段 |
| sender 是 UID 无法解析姓名 | 保留 UID，不阻断流程；后续可优化 |

---

## 8. 后续可选（本次不做）

- `run_daily_digest.ps1` 加 `$env:DINGTALK_DATA_DIR` 环境变量
- MCP 新增 `dingtalk_fetch_report_content` 工具
- 彻底移除 CEF 全文路径（待 inbox 路径验证稳定后）
- sender UID → 姓名的批量解析优化
