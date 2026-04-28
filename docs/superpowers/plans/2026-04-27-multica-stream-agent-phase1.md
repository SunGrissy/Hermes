# Multica Stream Agent Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing Multica DingTalk Stream bridge into a first-stage Multica queue steward Agent with natural dialogue, dispatch suggestions, memory candidates, skill summaries, and read-only patrol summaries.

**Architecture:** Keep the existing `dispatch_bot.py` Stream entry point and preserve fixed command behavior. Add three focused modules: `multica_client.py` for CLI access, `memory.py` for local memory, and `brain.py` for LLM-backed dialogue and structured decisions. Use standard-library `unittest` for regression tests and a mock LLM provider for deterministic behavior.

**Tech Stack:** Python 3, `dingtalk-stream`, `python-dotenv`, standard-library `asyncio`, `json`, `sqlite3`, `unittest`, local `multica` CLI.

---

## File Structure

- Modify: `tools/multica-dingtalk-bridge/dispatch_bot.py`
  - Keep DingTalk Stream setup.
  - Keep fixed command matching first.
  - Delegate Multica subprocess work to `MulticaClient`.
  - Delegate non-command messages to `Brain`.
- Create: `tools/multica-dingtalk-bridge/multica_client.py`
  - Resolve `multica` binary.
  - Run `issue create/list/status`.
  - Return structured results without DingTalk formatting.
- Create: `tools/multica-dingtalk-bridge/memory.py`
  - Store session memory, issue memory, low-risk knowledge memory, pending memory.
  - Use SQLite to keep writes atomic and inspectable.
- Create: `tools/multica-dingtalk-bridge/brain.py`
  - Load minimal skill summaries.
  - Build LLM prompts.
  - Parse structured JSON decisions.
  - Render natural-language replies and dispatch suggestion cards.
  - Generate memory candidates.
- Create: `tools/multica-dingtalk-bridge/tests/test_multica_client.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_memory.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_brain.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_dispatch_router.py`
- Modify: `tools/multica-dingtalk-bridge/README.md`
  - Document new natural dialogue, memory, skill summary, and patrol commands.
- Modify: `tools/multica-dingtalk-bridge/.env.example`
  - Add LLM and memory-related environment examples.

No commit should be made during implementation unless the user explicitly asks for commit or accepts the work through the repository's验收 flow.

---

## Task 1: Multica CLI Client

**Files:**
- Create: `tools/multica-dingtalk-bridge/multica_client.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_multica_client.py`

- [ ] **Step 1: Write tests for binary resolution and command construction**

Create `tools/multica-dingtalk-bridge/tests/test_multica_client.py`:

```python
import os
import unittest
from unittest.mock import patch

from multica_client import MulticaClient, build_issue_create_args


class MulticaClientTests(unittest.TestCase):
    def test_build_issue_create_args_without_project(self):
        args = build_issue_create_args(
            title="修复筛选",
            description="验收：筛选结果正确",
            priority="medium",
            status="todo",
            project_id="",
        )
        self.assertEqual(
            args,
            [
                "issue",
                "create",
                "--title",
                "修复筛选",
                "--description",
                "验收：筛选结果正确",
                "--priority",
                "medium",
                "--status",
                "todo",
                "--output",
                "json",
            ],
        )

    def test_build_issue_create_args_with_project(self):
        args = build_issue_create_args(
            title="修复筛选",
            description="验收：筛选结果正确",
            priority="high",
            status="todo",
            project_id="project-123",
        )
        self.assertEqual(args[-2:], ["--project", "project-123"])

    @patch.dict(os.environ, {"MULTICA_BIN": r"C:\\Tools\\multica.exe"})
    @patch("pathlib.Path.is_file", return_value=True)
    def test_resolve_binary_prefers_env(self, _is_file):
        client = MulticaClient()
        self.assertTrue(client.resolve_binary().endswith("multica.exe"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: FAIL because `multica_client.py` does not exist.

- [ ] **Step 3: Implement `multica_client.py`**

Create `tools/multica-dingtalk-bridge/multica_client.py`:

```python
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MulticaResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    data: dict[str, Any] | None = None


def build_issue_create_args(
    *,
    title: str,
    description: str,
    priority: str,
    status: str,
    project_id: str,
) -> list[str]:
    args = [
        "issue",
        "create",
        "--title",
        title,
        "--description",
        description,
        "--priority",
        priority,
        "--status",
        status,
        "--output",
        "json",
    ]
    if project_id.strip():
        args.extend(["--project", project_id.strip()])
    return args


class MulticaClient:
    def __init__(self, multica_bin: str | None = None, env: dict[str, str] | None = None):
        self._explicit_bin = multica_bin
        self._env = dict(env or os.environ)

    def resolve_binary(self) -> str | None:
        explicit = (
            self._explicit_bin
            or self._env.get("MULTICA_BIN")
            or self._env.get("MULTICA_EXECUTABLE")
            or ""
        ).strip()
        if explicit and Path(explicit).is_file():
            return str(Path(explicit).resolve())
        found = shutil.which("multica") or shutil.which("multica.exe")
        if found:
            return found
        if sys.platform == "win32":
            local = self._env.get("LOCALAPPDATA", "")
            if local:
                guess = Path(local) / "Programs" / "multica" / "multica.exe"
                if guess.is_file():
                    return str(guess.resolve())
        return None

    async def run_json(self, args: list[str], limit_stderr: int = 1200) -> MulticaResult:
        bin_path = self.resolve_binary()
        if not bin_path:
            return MulticaResult(
                ok=False,
                returncode=127,
                stdout="",
                stderr="multica binary not found",
            )
        proc = await asyncio.create_subprocess_exec(
            bin_path,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        out_b, err_b = await proc.communicate()
        stdout = (out_b or b"").decode("utf-8", errors="replace")
        stderr = (err_b or b"").decode("utf-8", errors="replace")[:limit_stderr]
        if proc.returncode != 0:
            return MulticaResult(False, int(proc.returncode or 0), stdout, stderr)
        try:
            data = json.loads(stdout.strip()) if stdout.strip() else {}
        except json.JSONDecodeError:
            return MulticaResult(False, 0, stdout, "failed to parse multica JSON output")
        if not isinstance(data, dict):
            return MulticaResult(False, 0, stdout, "multica JSON output was not an object")
        return MulticaResult(True, 0, stdout, stderr, data)

    async def create_issue(
        self,
        *,
        title: str,
        description: str,
        priority: str = "medium",
        status: str = "todo",
    ) -> MulticaResult:
        project_id = self._env.get("MULTICA_PROJECT_ID", "")
        return await self.run_json(
            build_issue_create_args(
                title=title,
                description=description,
                priority=priority,
                status=status,
                project_id=project_id,
            )
        )

    async def list_issues(self, *, limit: int = 500, status: str | None = None) -> MulticaResult:
        lim = max(1, min(int(limit), 500))
        args = ["issue", "list", "--output", "json", "--limit", str(lim)]
        project_id = self._env.get("MULTICA_PROJECT_ID", "").strip()
        if project_id:
            args.extend(["--project", project_id])
        if status:
            args.extend(["--status", status])
        return await self.run_json(args)

    async def cancel_issue(self, issue_ref: str) -> MulticaResult:
        args = ["issue", "status", issue_ref, "cancelled", "--output", "json"]
        project_id = self._env.get("MULTICA_PROJECT_ID", "").strip()
        if project_id:
            args.extend(["--project", project_id])
        return await self.run_json(args)
```

- [ ] **Step 4: Run tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: `test_multica_client` tests PASS.

---

## Task 2: Memory Store

**Files:**
- Create: `tools/multica-dingtalk-bridge/memory.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_memory.py`

- [ ] **Step 1: Write memory tests**

Create `tools/multica-dingtalk-bridge/tests/test_memory.py`:

```python
import tempfile
import unittest
from pathlib import Path

from memory import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_session_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.add_session_memory("chat-1", "scope", "只做 pm-system")
            rows = store.get_session_memory("chat-1")
            self.assertEqual(rows[0]["key"], "scope")
            self.assertEqual(rows[0]["value"], "只做 pm-system")

    def test_pending_memory_requires_review(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.add_pending_memory(
                kind="preference",
                value="派单建议要带 DoD",
                source="chat-1",
                confidence=0.91,
            )
            rows = store.list_pending_memory()
            self.assertEqual(rows[0]["kind"], "preference")
            self.assertEqual(rows[0]["status"], "pending")

    def test_low_risk_knowledge_auto_writes(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.add_knowledge_memory("path", "multica bridge path", "tools/multica-dingtalk-bridge")
            rows = store.list_knowledge_memory()
            self.assertEqual(rows[0]["key"], "multica bridge path")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: FAIL because `memory.py` does not exist.

- [ ] **Step 3: Implement `memory.py`**

Create `tools/multica-dingtalk-bridge/memory.py`:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS issue_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_ref TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )

    def add_session_memory(self, chat_id: str, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session_memory(chat_id, key, value, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, key, value, int(time.time())),
            )

    def get_session_memory(self, chat_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value, created_at FROM session_memory WHERE chat_id = ? ORDER BY id ASC",
                (chat_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_issue_memory(self, issue_ref: str, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO issue_memory(issue_ref, key, value, created_at) VALUES (?, ?, ?, ?)",
                (issue_ref, key, value, int(time.time())),
            )

    def get_issue_memory(self, issue_ref: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value, created_at FROM issue_memory WHERE issue_ref = ? ORDER BY id ASC",
                (issue_ref,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_knowledge_memory(self, kind: str, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO knowledge_memory(kind, key, value, created_at) VALUES (?, ?, ?, ?)",
                (kind, key, value, int(time.time())),
            )

    def list_knowledge_memory(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, key, value, created_at FROM knowledge_memory ORDER BY id ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_pending_memory(self, *, kind: str, value: str, source: str, confidence: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_memory(kind, value, source, confidence, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (kind, value, source, float(confidence), int(time.time())),
            )

    def list_pending_memory(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, value, source, confidence, status, created_at
                FROM pending_memory
                WHERE status = 'pending'
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: `test_memory` and `test_multica_client` tests PASS.

---

## Task 3: Brain and Structured Dialogue

**Files:**
- Create: `tools/multica-dingtalk-bridge/brain.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_brain.py`

- [ ] **Step 1: Write tests for mock Brain behavior**

Create `tools/multica-dingtalk-bridge/tests/test_brain.py`:

```python
import json
import unittest

from brain import Brain, BrainDecision, MockLLMProvider, parse_brain_decision


class BrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_brain_asks_clarification_when_dod_missing(self):
        provider = MockLLMProvider(
            {
                "intent": "dispatch_suggestion",
                "category": "feat",
                "confidence": 0.62,
                "missing_info": ["验收标准"],
                "suggested_title": "",
                "suggested_description": "",
                "definition_of_done": [],
                "priority": "medium",
                "split_suggestion": "信息不足，暂不判断",
                "recommended_action": "ask_clarification",
                "memory_candidates": [],
            }
        )
        brain = Brain(provider)
        decision = await brain.decide("帮我优化 PM 系统")
        self.assertEqual(decision.recommended_action, "ask_clarification")
        self.assertIn("验收", brain.render_reply(decision))

    def test_parse_brain_decision_accepts_json_block(self):
        text = "```json\n{\"intent\":\"patrol_summary\",\"category\":\"ops\",\"confidence\":0.9,\"missing_info\":[],\"suggested_title\":\"\",\"suggested_description\":\"\",\"definition_of_done\":[],\"priority\":\"medium\",\"split_suggestion\":\"无需拆单\",\"recommended_action\":\"reply\",\"memory_candidates\":[]}\n```"
        decision = parse_brain_decision(text)
        self.assertIsInstance(decision, BrainDecision)
        self.assertEqual(decision.intent, "patrol_summary")

    async def test_brain_renders_dispatch_card(self):
        provider = MockLLMProvider(
            {
                "intent": "dispatch_suggestion",
                "category": "fix",
                "confidence": 0.88,
                "missing_info": [],
                "suggested_title": "修复查工单排序",
                "suggested_description": "查工单按优先级与创建时间排序。",
                "definition_of_done": ["查工单前 10 顺序正确"],
                "priority": "medium",
                "split_suggestion": "无需拆单",
                "recommended_action": "ask_confirm",
                "memory_candidates": [],
            }
        )
        brain = Brain(provider)
        decision = await brain.decide("查工单排序不对，帮我派一下")
        reply = brain.render_reply(decision)
        self.assertIn("修复查工单排序", reply)
        self.assertIn("就按这个派", reply)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: FAIL because `brain.py` does not exist.

- [ ] **Step 3: Implement `brain.py` with mock provider and parser**

Create `tools/multica-dingtalk-bridge/brain.py`:

```python
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class BrainDecision:
    intent: str
    category: str
    confidence: float
    missing_info: list[str] = field(default_factory=list)
    suggested_title: str = ""
    suggested_description: str = ""
    definition_of_done: list[str] = field(default_factory=list)
    priority: str = "medium"
    split_suggestion: str = ""
    recommended_action: str = "reply"
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)


class LLMProvider(Protocol):
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


class MockLLMProvider:
    def __init__(self, response: dict[str, Any] | None = None):
        self.response = response or {
            "intent": "dispatch_suggestion",
            "category": "chore",
            "confidence": 0.72,
            "missing_info": ["验收标准"],
            "suggested_title": "",
            "suggested_description": "",
            "definition_of_done": [],
            "priority": "medium",
            "split_suggestion": "信息不足，暂不判断",
            "recommended_action": "ask_clarification",
            "memory_candidates": [],
        }

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(self.response, ensure_ascii=False)


class OpenAICompatibleProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return await asyncio.to_thread(self._complete_sync, system_prompt, user_prompt)

    def _complete_sync(self, system_prompt: str, user_prompt: str) -> str:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(
                {
                    "model": self.model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]


def parse_brain_decision(text: str) -> BrainDecision:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Brain decision must be a JSON object")
    return BrainDecision(
        intent=str(data.get("intent") or "reply"),
        category=str(data.get("category") or "chore"),
        confidence=float(data.get("confidence") or 0),
        missing_info=[str(x) for x in data.get("missing_info") or []],
        suggested_title=str(data.get("suggested_title") or ""),
        suggested_description=str(data.get("suggested_description") or ""),
        definition_of_done=[str(x) for x in data.get("definition_of_done") or []],
        priority=str(data.get("priority") or "medium"),
        split_suggestion=str(data.get("split_suggestion") or ""),
        recommended_action=str(data.get("recommended_action") or "reply"),
        memory_candidates=[
            x for x in data.get("memory_candidates") or [] if isinstance(x, dict)
        ],
    )


def load_minimal_skill_summary() -> str:
    return "\n".join(
        [
            "身份：机器人是制作人的数字分身入口，称呼制作人为老大。",
            "派单：需求要有标题、范围、DoD；信息不足时只追问一个关键问题。",
            "Git：不自动提交、不自动推送；验收与提交仍由明确口令触发。",
            "记忆：低风险事实可自动沉淀；偏好、规则、权限进入待审核候选。",
            "安全：不把密钥、token、未脱敏敏感信息写入 Multica。",
        ]
    )


class Brain:
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or build_provider_from_env()

    async def decide(self, user_text: str, context: str = "") -> BrainDecision:
        system_prompt = (
            "你是 Multica 队列管家 Agent。"
            "对外自然对话，对内只输出 JSON。"
            "当需求不清时 recommended_action=ask_clarification。"
            "当可派单但需要确认时 recommended_action=ask_confirm。"
            "不要自动执行代码，不要自动提交 Git。"
            "\n\n"
            + load_minimal_skill_summary()
        )
        user_prompt = f"上下文：{context}\n\n用户消息：{user_text}"
        raw = await self.provider.complete(system_prompt, user_prompt)
        return parse_brain_decision(raw)

    def render_reply(self, decision: BrainDecision) -> str:
        if decision.recommended_action == "ask_clarification":
            target = decision.missing_info[0] if decision.missing_info else "验收标准"
            return f"这条需求还差一个关键信息：{target}。老大先补这一点，我再整理派单建议。"
        if decision.recommended_action == "ask_confirm":
            dod = "\n".join(f"- {x}" for x in decision.definition_of_done) or "- 验收标准待补充"
            return (
                "我建议这样派：\n\n"
                f"**标题**：{decision.suggested_title}\n\n"
                f"**分类**：{decision.category} / {decision.priority}\n\n"
                f"**说明**：{decision.suggested_description}\n\n"
                f"**DoD**：\n{dod}\n\n"
                f"**拆单建议**：{decision.split_suggestion or '无需拆单'}\n\n"
                "老大确认的话，回复“就按这个派”。"
            )
        return "我先记录这个信息；如果要落 Multica，请补一句派单目标或验收标准。"


def build_provider_from_env() -> LLMProvider:
    provider = (os.environ.get("MULTICA_BOT_LLM_PROVIDER") or "mock").strip().lower()
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MULTICA_BOT_OPENAI_API_KEY")
        base = os.environ.get("OPENAI_API_BASE") or os.environ.get("MULTICA_BOT_OPENAI_BASE_URL") or "https://api.openai.com/v1"
        model = os.environ.get("OPENAI_MODEL") or os.environ.get("MULTICA_BOT_MODEL") or "gpt-4o-mini"
        if key:
            return OpenAICompatibleProvider(key, base, model)
    return MockLLMProvider()
```

- [ ] **Step 4: Run tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: `test_brain`, `test_memory`, and `test_multica_client` PASS.

---

## Task 4: Integrate Brain Into Fixed Command Router

**Files:**
- Modify: `tools/multica-dingtalk-bridge/dispatch_bot.py`
- Create: `tools/multica-dingtalk-bridge/tests/test_dispatch_router.py`

- [ ] **Step 1: Add tests for routing priority**

Create `tools/multica-dingtalk-bridge/tests/test_dispatch_router.py`:

```python
import unittest

from dispatch_bot import classify_incoming_text


class DispatchRouterTests(unittest.TestCase):
    def test_fixed_dispatch_command_wins(self):
        self.assertEqual(classify_incoming_text("派单 修复查工单"), "create_issue")

    def test_query_command_wins(self):
        self.assertEqual(classify_incoming_text("查工单"), "query_issues")

    def test_delete_command_wins(self):
        self.assertEqual(classify_incoming_text("取消派单 UUM-1"), "cancel_issue")

    def test_non_command_goes_to_brain(self):
        self.assertEqual(classify_incoming_text("这个需求怎么派比较好？"), "brain")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: FAIL because `classify_incoming_text` is not defined.

- [ ] **Step 3: Add router classification function to `dispatch_bot.py`**

Add this function near the existing prefix helpers in `dispatch_bot.py`:

```python
def classify_incoming_text(raw: str) -> str:
    """固定命令优先；非固定命令进入 Brain。"""
    text = _normalize_dingtalk_at_prefixes((raw or "").strip())
    if _strip_delete_dispatch_prefix(text) is not None:
        return "cancel_issue"
    if _is_query_issues_command(text):
        return "query_issues"
    if _strip_dispatch_prefix(text) is not None:
        return "create_issue"
    return "brain"
```

- [ ] **Step 4: Wire non-command messages to Brain**

In `MulticaDispatchHandler.__init__`, instantiate Brain:

```python
from brain import Brain


class MulticaDispatchHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__()
        self._log = logger or LOG
        self._brain = Brain()
        self._interactive_card_broken: bool = False
```

At the top of `process`, after `raw` is normalized, compute route:

```python
route = classify_incoming_text(raw)
```

Replace the current non-command return path:

```python
if body is None:
    return AckMessage.STATUS_OK, "OK"
```

with:

```python
if route == "brain":
    try:
        decision = await self._brain.decide(raw)
        reply = self._brain.render_reply(decision)
    except Exception as exc:
        self._log.warning("brain route failed: %s", exc)
        reply = "我暂时没能把这条需求整理清楚。老大可以换成固定格式：`派单 标题`，第二行写验收说明。"
    self._reply_dispatch_message(incoming, "Multica 队列管家", reply)
    return AckMessage.STATUS_OK, "OK"
```

Keep fixed command branches unchanged except for using `route` where it improves readability.

- [ ] **Step 5: Run tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: all tests PASS.

---

## Task 5: Confirmed Suggestion to Multica Issue

**Files:**
- Modify: `tools/multica-dingtalk-bridge/brain.py`
- Modify: `tools/multica-dingtalk-bridge/memory.py`
- Modify: `tools/multica-dingtalk-bridge/dispatch_bot.py`
- Create or modify: `tools/multica-dingtalk-bridge/tests/test_brain.py`

- [ ] **Step 1: Add tests for confirm phrase and pending suggestion**

Append to `tools/multica-dingtalk-bridge/tests/test_brain.py`:

```python
from brain import is_confirm_dispatch_phrase


class ConfirmPhraseTests(unittest.TestCase):
    def test_confirm_dispatch_phrase(self):
        self.assertTrue(is_confirm_dispatch_phrase("就按这个派"))
        self.assertTrue(is_confirm_dispatch_phrase("确认派单"))
        self.assertFalse(is_confirm_dispatch_phrase("先别派"))
```

- [ ] **Step 2: Implement confirm phrase helper**

Add to `brain.py`:

```python
def is_confirm_dispatch_phrase(text: str) -> bool:
    normalized = (text or "").strip()
    return normalized in {"就按这个派", "确认派单", "按这个派", "可以派"}
```

- [ ] **Step 3: Add session pending suggestion storage**

Add to `memory.py`:

```python
    def set_session_suggestion(self, chat_id: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_memory WHERE chat_id = ? AND key = 'pending_dispatch_suggestion'",
                (chat_id,),
            )
            conn.execute(
                "INSERT INTO session_memory(chat_id, key, value, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, "pending_dispatch_suggestion", value, int(time.time())),
            )

    def get_session_suggestion(self, chat_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value FROM session_memory
                WHERE chat_id = ? AND key = 'pending_dispatch_suggestion'
                ORDER BY id DESC LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
        return str(row["value"]) if row else None
```

- [ ] **Step 4: Store ask-confirm decisions and create on confirmation**

In `dispatch_bot.py`, instantiate memory and client:

```python
from pathlib import Path
from brain import Brain, is_confirm_dispatch_phrase, parse_brain_decision
from memory import MemoryStore
from multica_client import MulticaClient


def _default_memory_path() -> Path:
    return Path(os.environ.get("MULTICA_BOT_MEMORY_DB") or Path(__file__).resolve().parent / "data" / "memory.db")
```

In `MulticaDispatchHandler.__init__`:

```python
self._memory = MemoryStore(_default_memory_path())
self._multica = MulticaClient()
```

In the `route == "brain"` branch:

```python
chat_id = str(getattr(incoming, "conversation_id", "") or getattr(incoming, "sender_staff_id", "") or "default")
if is_confirm_dispatch_phrase(raw):
    suggestion_raw = self._memory.get_session_suggestion(chat_id)
    if not suggestion_raw:
        self._reply_dispatch_message(incoming, "Multica 队列管家", "我这里没有待确认的派单建议。老大先描述需求，我整理后再派。")
        return AckMessage.STATUS_OK, "OK"
    decision = parse_brain_decision(suggestion_raw)
    result = await self._multica.create_issue(
        title=decision.suggested_title,
        description=decision.suggested_description,
        priority=decision.priority,
        status="todo",
    )
    if not result.ok or not result.data:
        self._reply_dispatch_message(incoming, "Multica 派单", f"建单失败：{result.stderr or '未返回有效 JSON'}")
        return AckMessage.STATUS_OK, "OK"
    identifier = result.data.get("identifier") or result.data.get("id") or "?"
    self._reply_dispatch_message(incoming, "Multica 派单", f"已按建议创建工单：`{identifier}`")
    return AckMessage.STATUS_OK, "OK"
```

After rendering an ask-confirm decision:

```python
if decision.recommended_action == "ask_confirm":
    self._memory.set_session_suggestion(chat_id, json.dumps(decision.__dict__, ensure_ascii=False))
```

- [ ] **Step 5: Run tests and syntax parse**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; py -c "import ast; ast.parse(open(r'dispatch_bot.py', encoding='utf-8').read()); print('OK')"; Pop-Location
```

Expected: tests PASS and syntax parse prints `OK`.

---

## Task 6: Memory Candidate Processing

**Files:**
- Modify: `tools/multica-dingtalk-bridge/brain.py`
- Modify: `tools/multica-dingtalk-bridge/memory.py`
- Modify: `tools/multica-dingtalk-bridge/dispatch_bot.py`
- Modify: `tools/multica-dingtalk-bridge/tests/test_memory.py`

- [ ] **Step 1: Add tests for candidate classification**

Append to `tools/multica-dingtalk-bridge/tests/test_memory.py`:

```python
from memory import classify_memory_candidate


class MemoryCandidateTests(unittest.TestCase):
    def test_low_risk_path_is_auto(self):
        candidate = {"kind": "path", "value": "bridge lives at tools/multica-dingtalk-bridge", "confidence": 0.95}
        self.assertEqual(classify_memory_candidate(candidate), "knowledge")

    def test_preference_requires_review(self):
        candidate = {"kind": "preference", "value": "派单必须带验收口径", "confidence": 0.95}
        self.assertEqual(classify_memory_candidate(candidate), "pending")

    def test_secret_is_rejected(self):
        candidate = {"kind": "knowledge", "value": "OPENAI_API_KEY=abc", "confidence": 0.9}
        self.assertEqual(classify_memory_candidate(candidate), "reject")
```

- [ ] **Step 2: Implement candidate classifier**

Add to `memory.py`:

```python
def classify_memory_candidate(candidate: dict[str, Any]) -> str:
    kind = str(candidate.get("kind") or "").lower()
    value = str(candidate.get("value") or "")
    lowered = value.lower()
    if any(x in lowered for x in ("secret", "token", "api_key", "client_secret", "password")):
        return "reject"
    if kind in {"path", "port", "command", "project_boundary", "tooling"}:
        return "knowledge"
    if kind in {"preference", "rule", "acceptance", "permission", "classification"}:
        return "pending"
    return "pending"
```

- [ ] **Step 3: Add candidate persistence helper**

Add to `memory.py`:

```python
    def process_memory_candidates(self, candidates: list[dict[str, Any]], source: str) -> dict[str, int]:
        counts = {"knowledge": 0, "pending": 0, "reject": 0}
        for candidate in candidates:
            bucket = classify_memory_candidate(candidate)
            counts[bucket] += 1
            value = str(candidate.get("value") or "").strip()
            if not value:
                continue
            if bucket == "knowledge":
                self.add_knowledge_memory(str(candidate.get("kind") or "knowledge"), value[:80], value)
            elif bucket == "pending":
                self.add_pending_memory(
                    kind=str(candidate.get("kind") or "memory"),
                    value=value,
                    source=source,
                    confidence=float(candidate.get("confidence") or 0),
                )
        return counts
```

- [ ] **Step 4: Call candidate persistence after Brain decision**

In `dispatch_bot.py`, after `decision = await self._brain.decide(raw)`:

```python
memory_counts = self._memory.process_memory_candidates(decision.memory_candidates, source=chat_id)
```

Append a short note to reply only when pending memory exists:

```python
if memory_counts.get("pending", 0) > 0:
    reply += f"\n\n我还提取到 {memory_counts['pending']} 条长期记忆候选，后续可汇总给老大确认。"
```

- [ ] **Step 5: Run tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: all tests PASS.

---

## Task 7: Read-only Patrol Summary

**Files:**
- Modify: `tools/multica-dingtalk-bridge/brain.py`
- Modify: `tools/multica-dingtalk-bridge/dispatch_bot.py`
- Modify: `tools/multica-dingtalk-bridge/tests/test_brain.py`

- [ ] **Step 1: Add patrol summary rendering test**

Append to `tools/multica-dingtalk-bridge/tests/test_brain.py`:

```python
from brain import render_patrol_summary


class PatrolSummaryTests(unittest.TestCase):
    def test_render_patrol_summary_flags_missing_dod(self):
        issues = [
            {"identifier": "UUM-1", "title": "优化一下系统", "status": "todo", "priority": "medium"},
            {"identifier": "UUM-2", "title": "修复登录白屏", "status": "in_review", "priority": "high"},
        ]
        text = render_patrol_summary(issues)
        self.assertIn("只读巡查摘要", text)
        self.assertIn("UUM-1", text)
        self.assertIn("建议补 DoD", text)
```

- [ ] **Step 2: Implement patrol renderer**

Add to `brain.py`:

```python
def render_patrol_summary(issues: list[dict[str, Any]]) -> str:
    status_counts: dict[str, int] = {}
    missing_dod: list[dict[str, Any]] = []
    in_review: list[dict[str, Any]] = []
    for issue in issues:
        status = str(issue.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        title = str(issue.get("title") or "")
        if len(title) < 12 or "优化一下" in title or "处理一下" in title:
            missing_dod.append(issue)
        if status == "in_review":
            in_review.append(issue)
    lines = ["## Multica 只读巡查摘要", ""]
    lines.append("### 状态概况")
    for status, count in sorted(status_counts.items()):
        lines.append(f"- `{status}`：{count}")
    if in_review:
        lines.extend(["", "### 待验收"])
        for issue in in_review[:10]:
            lines.append(f"- `{issue.get('identifier') or issue.get('id')}` · {issue.get('title')}")
    if missing_dod:
        lines.extend(["", "### 建议补 DoD"])
        for issue in missing_dod[:10]:
            lines.append(f"- `{issue.get('identifier') or issue.get('id')}` · {issue.get('title')}")
    if not issues:
        lines.append("当前没有拉到工单。")
    lines.append("")
    lines.append("本摘要只读，不会自动认领、改状态或触发执行。")
    return "\n".join(lines)
```

- [ ] **Step 3: Add patrol command route**

In `dispatch_bot.py`, extend `classify_incoming_text`:

```python
if text in ("巡查工单", "#巡查工单", "工单巡查", "#工单巡查"):
    return "patrol_summary"
```

In `process`, before fixed create path:

```python
if route == "patrol_summary":
    result = await self._multica.list_issues(limit=500)
    if not result.ok or not result.data:
        self._reply_dispatch_message(incoming, "Multica 巡查", f"无法拉取工单：{result.stderr or '无有效返回'}")
        return AckMessage.STATUS_OK, "OK"
    issues = result.data.get("issues") if isinstance(result.data, dict) else []
    if not isinstance(issues, list):
        issues = []
    reply = render_patrol_summary([x for x in issues if isinstance(x, dict)])
    self._reply_dispatch_message(incoming, "Multica 巡查", reply)
    return AckMessage.STATUS_OK, "OK"
```

Also import:

```python
from brain import render_patrol_summary
```

- [ ] **Step 4: Run tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; Pop-Location
```

Expected: all tests PASS.

---

## Task 8: Documentation and Configuration

**Files:**
- Modify: `tools/multica-dingtalk-bridge/README.md`
- Modify: `tools/multica-dingtalk-bridge/.env.example`
- Modify: `tools/multica-dingtalk-bridge/requirements.txt`

- [ ] **Step 1: Update `.env.example`**

Append:

```dotenv
# 可选：启用自然语言队列管家。默认 mock，仅用于本地验证；openai 使用 OpenAI-compatible Chat Completions。
# MULTICA_BOT_LLM_PROVIDER=mock
# MULTICA_BOT_LLM_PROVIDER=openai
# MULTICA_BOT_OPENAI_API_KEY=
# MULTICA_BOT_OPENAI_BASE_URL=https://api.openai.com/v1
# MULTICA_BOT_MODEL=gpt-4o-mini

# 可选：机器人本地记忆库。默认写到本目录 data/memory.db。
# MULTICA_BOT_MEMORY_DB=tools/multica-dingtalk-bridge/data/memory.db
```

- [ ] **Step 2: Update README command section**

Add a section after existing command examples:

```markdown
## 自然语言队列管家（第一阶段）

固定命令仍优先处理；其它消息会进入队列管家 Brain。

支持：

- 需求澄清：需求缺少验收标准时，机器人只追问一个关键问题。
- 派单建议：机器人给出标题、分类、说明、DoD、拆单建议。
- 确认建单：机器人提示后，回复 `就按这个派` / `确认派单` / `按这个派` / `可以派` 创建 Multica Issue。
- 只读巡查：发送 `巡查工单` 或 `#巡查工单`，机器人汇总待办、待验收、疑似缺 DoD 工单。
- 记忆候选：低风险事实自动写入本地记忆库；派单偏好、分类规则、验收口径进入待审核候选。

第一阶段不会自动认领、自动改状态、自动执行代码、自动提交或推送 Git。
```

- [ ] **Step 3: Keep requirements unchanged**

Do not add `openai` or `httpx` for phase 1. The OpenAI-compatible call uses standard-library `urllib.request`; tests use `MockLLMProvider`.

- [ ] **Step 4: Run syntax and tests**

Run:

```powershell
Push-Location "tools\multica-dingtalk-bridge"; py -m unittest discover -s tests -v; py -c "import ast; ast.parse(open(r'brain.py', encoding='utf-8').read()); ast.parse(open(r'memory.py', encoding='utf-8').read()); ast.parse(open(r'multica_client.py', encoding='utf-8').read()); ast.parse(open(r'dispatch_bot.py', encoding='utf-8').read()); print('OK')"; Pop-Location
```

Expected: tests PASS and syntax parse prints `OK`.

---

## Task 9: Manual DingTalk Regression

**Files:**
- No file changes.

- [ ] **Step 1: Start bridge**

Run:

```powershell
cd "d:\MyAgents\tools\multica-dingtalk-bridge"
.\run_bridge.ps1
```

Expected: console logs `DingTalk stream started`.

- [ ] **Step 2: Verify fixed commands still work**

In DingTalk, send:

```text
查工单
```

Expected: reply contains status distribution and priority top 10.

Send:

```text
派单 Multica 队列管家回归测试
验收：机器人能创建一条测试工单，随后可取消。
```

Expected: reply contains a Multica Issue identifier.

Send:

```text
取消派单 <上一步编号>
```

Expected: reply says the issue was requested cancelled.

- [ ] **Step 3: Verify natural dialogue**

In DingTalk, send:

```text
我想把 multica 机器人做成会澄清需求的队列管家，这个需求怎么派？
```

Expected: reply is a natural clarification or dispatch suggestion. It should not create an issue yet.

- [ ] **Step 4: Verify confirmation create path**

If the previous reply is a dispatch card, send:

```text
就按这个派
```

Expected: robot creates a Multica Issue and replies with the new identifier.

- [ ] **Step 5: Verify read-only patrol**

In DingTalk, send:

```text
巡查工单
```

Expected: reply starts with `Multica 只读巡查摘要` and states it will not auto-assign or change status.

---

## Self-Review

### Spec coverage

- Fixed command priority: Task 4 and Task 9.
- Natural dialogue: Task 3, Task 4, Task 9.
- Confirmed issue creation: Task 5 and Task 9.
- Memory candidates and promotion buckets: Task 2 and Task 6.
- Skill summary loading: Task 3.
- Read-only patrol summary: Task 7 and Task 9.
- Error handling and LLM failure fallback: Task 3 and Task 4.
- Sensitive memory rejection: Task 6.
- No Hermes/OpenClaw dependency: Task 3 uses provider abstraction and mock default.

### Type consistency

- `BrainDecision` is the single structured decision type.
- `MulticaResult` is the single CLI result type.
- `MemoryStore` owns all local memory writes.
- `classify_incoming_text` returns route strings used by `dispatch_bot.py`.

### Test strategy

- Unit tests use `unittest` and mock providers.
- No network, DingTalk, or real Multica dependency is needed for unit tests.
- Manual regression verifies Stream, real CLI, and DingTalk reply behavior.

### Scope guard

The implementation plan does not include automatic patrol, automatic assignment, code execution, Git commit, Git push, or Hermes/OpenClaw integration. Those remain phase 2 or phase 3.
