# Hermes 入站命令路由器 + Multica 适配器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Hermes 网关内实现「入站命令路由器 + Multica 适配器」，使钉钉单 Stream 入口下派单/删单/查单 **不进 LLM** 而调本机 `multica`；MyAgents 侧更新运维文档与 `quick_start`，最终退役 `dispatch_bot` 常驻进程。

**Architecture:** 路由器在鉴权之后、主 Agent 之前短路；Multica 适配器端口化 `tools/multica-dingtalk-bridge/dispatch_bot.py` 的解析与子进程逻辑；环境变量总开关与 §0/§9.2 割接清单并行交付。

**Tech Stack:** Python 3.11+（与 Hermes 一致）、Hermes `gateway` 包、`asyncio.subprocess`、pytest；行为金线源：`d:/MyAgents/tools/multica-dingtalk-bridge/dispatch_bot.py`。

**Spec:** `docs/superpowers/specs/2026-04-21-hermes-inbound-command-router-design.md`

**Hermes 源码根目录（示例）:** `D:\hermes\hermes-agent`（下文记为 `HERMES_SRC`；以本机 `HERMES_HOME` 安装为准）。

---

## 文件与职责映射

| 路径（相对 `HERMES_SRC`） | 职责 |
|---------------------------|------|
| `gateway/inbound_command_router/__init__.py` | 导出 `InboundCommandRouter`、`InboundContext`、`RouterReply`、`InboundAdapter` 协议 |
| `gateway/inbound_command_router/router.py` | 按 `priority` 排序并依次调用 `try_handle` |
| `gateway/inbound_command_router/adapters/multica.py` | Multica 适配器：解析 + `multica` 子进程 + Markdown |
| `gateway/inbound_command_router/adapters/multica_parsers.py` | 从金线文件端口化的**纯函数**（便于单测，避免依赖 `dingtalk_stream`） |
| `gateway/run.py`（或 `gateway/platforms/dingtalk.py`） | **唯一挂载点**：鉴权通过后调用路由器；短路时 `adapter.send` 并 return |
| `tests/gateway/test_inbound_router_core.py` | 路由器排序与协议 |
| `tests/gateway/test_multica_parsers.py` | 解析与格式化 golden cases |

| 路径（MyAgents） | 职责 |
|------------------|------|
| `docs/hermes-dingtalk-gateway.md` | 增加「路由器开关 + 与派单桥互斥 + 割接」互链到 spec §9.2 |
| `tools/multica-dingtalk-bridge/README.md` | 顶部增加 **退役路径**：改由 Hermes 路由时本脚本不再与同一 Client ID 同启 |
| `pm-system/quick_start.bat` | 菜单与说明：生产切 Hermes 后 **[7]** 派单桥改为可选/文档提示 |

---

### Task 1: 定位 Hermes 挂载点（只读探针）

**Files:**

- Read: `HERMES_SRC/gateway/run.py`（搜索 `_handle_message`、`handle_message`）
- Read: `HERMES_SRC/gateway/platforms/dingtalk.py`（搜索 `handle_message`、`_on_message`）

- [ ] **Step 1: 用 ripgrep 定位候选钩子**

Run（在 `HERMES_SRC` 下）:

```powershell
cd D:\hermes\hermes-agent
rg -n "_handle_message|async def handle_message" gateway/run.py gateway/platforms/dingtalk.py
```

Expected: 至少一处「用户已鉴权、且已得到 `MessageEvent` / 文本」的集中入口；选定 **单一点** 挂载（优先 `run.py` 中平台无关路径，否则钉钉适配器内紧挨 `handle_message(event)` 调用前）。

- [ ] **Step 2: 在 spec 附录（本 plan 末尾「实施记录」）记下**

文件路径 + 函数名 + 插入行附近逻辑一句话（便于 Code Review）。

---

### Task 2: 路由器内核 + 单元测试

**Files:**

- Create: `HERMES_SRC/gateway/inbound_command_router/__init__.py`
- Create: `HERMES_SRC/gateway/inbound_command_router/router.py`
- Create: `HERMES_SRC/tests/gateway/test_inbound_router_core.py`

- [ ] **Step 1: 写失败测试（适配器优先级）**

Create `HERMES_SRC/tests/gateway/test_inbound_router_core.py`:

```python
import pytest
from gateway.inbound_command_router.router import InboundCommandRouter
from gateway.inbound_command_router import InboundContext, RouterReply


class HiAdapter:
    priority = 5

    async def try_handle(self, ctx: InboundContext):
        if ctx.text.strip() == "hi":
            return RouterReply(markdown="HI")
        return None


class LoAdapter:
    priority = 50

    async def try_handle(self, ctx: InboundContext):
        return RouterReply(markdown="LO")


@pytest.mark.asyncio
async def test_router_picks_lower_priority_first():
    r = InboundCommandRouter([LoAdapter(), HiAdapter()])
    out = await r.route(InboundContext(platform="dingtalk", chat_id="c", user_id="u", text="hi"))
    assert out is not None
    assert out.markdown == "HI"
```

Run:

```powershell
cd D:\hermes\hermes-agent
py -m pytest tests/gateway/test_inbound_router_core.py::test_router_picks_lower_priority_first -v
```

Expected: **FAIL**（`InboundCommandRouter` / 模块不存在）。

- [ ] **Step 2: 实现最小路由器**

Create `HERMES_SRC/gateway/inbound_command_router/__init__.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class InboundContext:
    platform: str
    chat_id: str
    user_id: str
    text: str
    raw: Any = None


@dataclass
class RouterReply:
    markdown: str


@runtime_checkable
class InboundAdapter(Protocol):
    priority: int

    async def try_handle(self, ctx: InboundContext) -> Optional[RouterReply]: ...
```

Create `HERMES_SRC/gateway/inbound_command_router/router.py`:

```python
from __future__ import annotations

from typing import Iterable, Optional

from . import InboundAdapter, InboundContext, RouterReply


class InboundCommandRouter:
    def __init__(self, adapters: Iterable[InboundAdapter]) -> None:
        self._adapters = sorted(adapters, key=lambda a: a.priority)

    async def route(self, ctx: InboundContext) -> Optional[RouterReply]:
        for adapter in self._adapters:
            reply = await adapter.try_handle(ctx)
            if reply is not None:
                return reply
        return None
```

Run Step 1 的 pytest again。Expected: **PASS**。

- [ ] **Step 3: Commit（Hermes 仓库内）**

```powershell
cd D:\hermes\hermes-agent
git add gateway/inbound_command_router tests/gateway/test_inbound_router_core.py
git commit -m "feat(gateway): add inbound command router core"
```

（若用户要求仅在 MyAgents 记录，可跳过 Hermes 内 commit，但计划默认 **小步提交**。）

---

### Task 3: 纯函数端口 — `查工单` 判定

**Files:**

- Create: `HERMES_SRC/gateway/inbound_command_router/adapters/__init__.py`（可为空或仅 docstring）
- Create: `HERMES_SRC/gateway/inbound_command_router/adapters/multica_parsers.py`
- Create: `HERMES_SRC/tests/gateway/test_multica_parsers.py`

- [ ] **Step 1: 失败测试**

`HERMES_SRC/tests/gateway/test_multica_parsers.py`:

```python
from gateway.inbound_command_router.adapters.multica_parsers import is_query_issues_command


def test_query_command_variants():
    assert is_query_issues_command("查工单") is True
    assert is_query_issues_command("#查工单") is True
    assert is_query_issues_command("  查工单  ") is True
    assert is_query_issues_command("派单 标题") is False
```

Run: `py -m pytest tests/gateway/test_multica_parsers.py -v` → Expected **FAIL**。

- [ ] **Step 2: 最小实现**

`HERMES_SRC/gateway/inbound_command_router/adapters/multica_parsers.py`:

```python
def is_query_issues_command(raw: str) -> bool:
    s = (raw or "").strip()
    return s in ("查工单", "#查工单")
```

Run pytest → Expected **PASS**。

---

### Task 4: Multica 适配器骨架 + 环境开关

**Files:**

- Create: `HERMES_SRC/gateway/inbound_command_router/adapters/__init__.py`
- Create: `HERMES_SRC/gateway/inbound_command_router/adapters/multica.py`
- Modify: `HERMES_SRC/gateway/run.py`（或 Task 1 选定的钉钉文件）

- [ ] **Step 1: 适配器恒返回 `None`（未接线）**

`HERMES_SRC/gateway/inbound_command_router/adapters/multica.py` 骨架：

```python
from __future__ import annotations

import os
from typing import Optional

from gateway.inbound_command_router import InboundContext, RouterReply


class MulticaInboundAdapter:
    priority = 10

    def __init__(self) -> None:
        self._enabled = os.getenv("HERMES_ROUTER_MULTICA_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    async def try_handle(self, ctx: InboundContext) -> Optional[RouterReply]:
        if not self._enabled:
            return None
        return None
```

- [ ] **Step 2: 在网关构造路由器单例（伪代码位置由 Task 1 定）**

在 `GatewayRunner.__init__` 或等价处增加：

```python
from gateway.inbound_command_router.router import InboundCommandRouter
from gateway.inbound_command_router.adapters.multica import MulticaInboundAdapter

self._inbound_router = InboundCommandRouter([MulticaInboundAdapter()])
```

并增加 `HERMES_INBOUND_ROUTER_ENABLED` 总开关判断（与 spec §7 一致）：仅当总开关 on 时构造或调用路由器。

- [ ] **Step 3: 运行 Hermes 现有网关测试（若有）**

```powershell
cd D:\hermes\hermes-agent
py -m pytest tests/gateway/ -q --tb=no
```

Expected: 与基线一致（无新增失败）。若仓库无相关测试，至少 `py -c "import gateway.run"` 导入成功。

---

### Task 5: 端口 `查工单` — 子进程 + 回复体

**Files:**

- Modify: `HERMES_SRC/gateway/inbound_command_router/adapters/multica_parsers.py`（增加 `_format_query_issues_reply_body` 等，**从** `d:/MyAgents/tools/multica-dingtalk-bridge/dispatch_bot.py` **逐函数复制**并删去仅桥用的 import）
- Modify: `HERMES_SRC/gateway/inbound_command_router/adapters/multica.py`
- Modify: `HERMES_SRC/tests/gateway/test_multica_parsers.py` 或新建 `test_multica_query_integration.py`

- [ ] **Step 1: 复制金线函数**

从 `dispatch_bot.py` 复制到 `multica_parsers.py`（保持行为一致）的符号清单（最小集）：

- `_dispatch_reply_separator`, `_format_issue_stats_md`, `_PRIORITY_WEIGHT`, `_PRIORITY_LABEL_ZH`, `_issue_created_sort_key`, `_sort_issues_priority_then_created`, `_format_query_issues_reply_body`, `_issue_list_project_args`
- `_fetch_workspace_issue_stats` / `_multica_issue_list_json` 若依赖 `asyncio.create_subprocess_exec`，可放在 `multica.py` 中，`parsers` 只保留纯格式化

- [ ] **Step 2: `MulticaInboundAdapter.try_handle` 实现查工单分支**

逻辑：若 `is_query_issues_command(ctx.text)`，则 `await _run_issue_list_and_format(...)` 返回 `RouterReply(markdown=...)`。

- [ ] **Step 3: 集成测试（可选 mock subprocess）**

用 `pytest` + `monkeypatch` mock `multica issue list` 的 stdout 为固定 JSON，断言 Markdown 含「按优先级前 10」。

---

### Task 6: 端口「派单」建单

**Files:**

- Modify: `HERMES_SRC/gateway/inbound_command_router/adapters/multica_parsers.py`
- Modify: `HERMES_SRC/gateway/inbound_command_router/adapters/multica.py`

- [ ] **Step 1: 从金线复制**

`_strip_dispatch_prefix`, `_EMPTY_DISPATCH_HELP`, `_parse_create_stdout`, `_format_dispatch_create_reply`, `_resolve_multica_binary`（或合并为 `multica_exec` 模块）。

- [ ] **Step 2: `try_handle` 分支**

解析标题/描述 → `multica issue create ...` → 成功则 `_format_dispatch_create_reply`。

- [ ] **Step 3: pytest 覆盖空标题 / 单行标题**

字符串 fixture 断言返回的帮助文案与现桥一致（复制 `_EMPTY_DISPATCH_HELP` 常量比对或 `in` 关键字）。

---

### Task 7: 端口「删除派单 / 取消派单」

**Files:**

- Modify: `multica_parsers.py` / `multica.py`

- [ ] **Step 1: 复制金线**

`_strip_delete_dispatch_prefix`, `_parse_delete_dispatch_tokens`, `_UUID_RE`, `_ISSUE_IDENT_RE`, `_DELETE_TOKEN_SPLIT_RE`, `_DELETE_DISPATCH_HELP`, `_resolve_issue_ref_for_status`, `_multica_issue_set_cancelled`。

- [ ] **Step 2: 多目标与帮助文案测试**

pytest 参数化：`删除派单 UUM-1, 2`、无参数仅 `删除派单` 等。

---

### Task 8: 网关短路接线 + 钉钉 `send`

**Files:**

- Modify: `HERMES_SRC/gateway/run.py` 与/或 `HERMES_SRC/gateway/platforms/dingtalk.py`

- [ ] **Step 1: 在 `MessageEvent` 进入 Agent 之前**

```python
if os.getenv("HERMES_INBOUND_ROUTER_ENABLED", "").lower() in ("1", "true", "yes", "on"):
    ctx = InboundContext(
        platform=source.platform.value,
        chat_id=source.chat_id,
        user_id=source.user_id or "",
        text=event.text or "",
        raw=event,
    )
    reply = await self._inbound_router.route(ctx)
    if reply is not None:
        adapter = self.adapters.get(source.platform)
        if adapter:
            await adapter.send(source.chat_id, reply.markdown)
        return None
```

（`adapter.send` 签名以 Hermes 钉钉适配器实际 API 为准；若第二个参数为关键字参数则调整。）

- [ ] **Step 2: 手工联调（§9.2）**

按 spec **停桥 → 启 Hermes → 钉钉测 `查工单` → `派单` → `删除派单`**；测完 **反向恢复**。

---

### Task 9: MyAgents 文档与 quick_start

**Files:**

- Modify: `d:/MyAgents/docs/hermes-dingtalk-gateway.md`
- Modify: `d:/MyAgents/tools/multica-dingtalk-bridge/README.md`
- Modify: `d:/MyAgents/pm-system/quick_start.bat`

- [ ] **Step 1: `hermes-dingtalk-gateway.md`**

增加小节：「入站命令路由器」开关名、`HERMES_ROUTER_MULTICA_ENABLED`、与 `dispatch_bot` **互斥**、链接 `specs/2026-04-21-hermes-inbound-command-router-design.md` §9.2。

- [ ] **Step 2: `multica-dingtalk-bridge/README.md`**

在「前提」上方加 **状态横幅**：若已启用 Hermes 路由，请勿用同一 Client ID 启动本桥。

- [ ] **Step 3: `quick_start.bat`**

在启动派单桥前 `echo` 警告：若 Hermes 已接同一机器人则跳过；或 **[7]** 改为「仅当未使用 Hermes 路由时」。（具体文案与菜单行为以制作人选定为准，默认 **保守：仍可调起但打印互斥警告**。）

---

### Task 10: 回归清单 + WORK_LOG（MyAgents）

**Files:**

- Modify: `d:/MyAgents/WORK_LOG.md`（若本轮交付跨仓库，记 3～5 行摘要 + spec/plan 链接）

- [ ] **Step 1: 在 WORK_LOG 增加**

日期、Hermes 路由 MVP、互链 spec/plan、现网仍为桥、割接窗口说明。

---

## Plan self-review（对照 spec）

| Spec 章节 | 覆盖 Task |
|-----------|-----------|
| §0 现网 / Stream 单活 | Task 8 Step 2 + Task 9 文档 |
| §4 主路径对齐 | Task 5–7 |
| §5 接入点 | Task 1 + Task 8 |
| §6 注册约定 | Task 2（扩展第二适配器时复用 `InboundAdapter`） |
| §7 配置 | Task 4 + Task 9 |
| §8–9 错误/切换 | Task 5 子进程超时（实施时在 `multica.py` 加 `asyncio.wait_for`）、Task 8 Step 2 |

**Placeholder 扫描:** 无 TBD。  
**类型一致:** `InboundContext` / `RouterReply` 全 plan 统一。

---

## 实施记录（Task 1 完成后由执行者填写）

- **挂载文件:** `HERMES_SRC/gateway/run.py`（本机绝对路径示例：`D:\hermes\hermes-agent\gateway\run.py`）
- **挂载函数:** `GatewayRunner._handle_message`
- **备注:** 在 `_is_user_authorized` 通过且走完 `/update` 应答、忙线（`_running_agents`）分支、网关 `/command` 分发、quick/plugin/skill 改写之后，**紧挨** `# Claim this session` 哨兵与 `await self._handle_message_with_agent(...)`（约 `run.py:3721-3733`）之前插入路由器：此处是平台无关的集中入口，且仅当本会话**未**走「忙线 interrupt」路径时才会到达，适合在文本已定型后、主 Agent 消费前短路。`MessageEvent` 上正文为 `event.text`；会话路由用 `event.source`（`gateway/session.py` 的 `SessionSource`）中的 `chat_id`、`user_id`（及 `platform` 等），钉钉适配器在 `gateway/platforms/dingtalk.py:622-640` 构造同一结构后调用 `handle_message(event)`，最终仍进入该 `_handle_message`。若需在 **Agent 已运行**时对普通文本也先过路由器（避免只走 `interrupt`），需在 `_handle_message` 内忙线分支更早位置另加一次 `try_handle` 或接受仅空闲会话由本挂载点覆盖。

- **实施落盘（2026-04-21）:** 已按上述挂载点写入 `run.py`；`multica_cli_bridge.py` 为 vendored 派单逻辑 + `multica_inbound_try_markdown`；`GatewayRunner.__init__` 条件构造 `InboundCommandRouter`；MyAgents 文档与 `WORK_LOG` 已更新。

---

**Plan 已保存:** `docs/superpowers/plans/2026-04-21-hermes-inbound-command-router.md`

**执行模式:** Subagent-Driven（已选）。按 Task 顺序派发子代理；父会话做 spec 复核。**勿自动 `git commit`**（以用户「请提交」为准）。

---

**Brainstorming 收尾:** `docs/superpowers/specs/2026-04-21-hermes-inbound-command-router-design.md` 已在前序回合落地；本 plan 与之对齐。若还需把 `bp-8/bp-9` 在会话内标记完成，执行者可在实现开始前将 TODO 勾掉。
