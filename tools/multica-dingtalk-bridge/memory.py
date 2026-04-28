from __future__ import annotations

import sqlite3
import time
import re
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
from typing import Any, Iterator


_SENSITIVE_KIND_TERMS = (
    "secret",
    "token",
    "api_key",
    "apikey",
    "client_secret",
    "clientsecret",
    "password",
    "private_key",
    "privatekey",
    "private key",
    "access_key",
    "accesskey",
    "refresh_key",
    "refreshkey",
    "auth_key",
    "authkey",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "bearer ",
    "密码",
    "密钥",
    "令牌",
)

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{6,}\b"),
    re.compile(
        r"(?i)\b(?:private[_-]?key|private\s+key|access[_-]?key|refresh[_-]?key|auth[_-]?key|"
        r"access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|password|secret|token)\b"
    ),
    re.compile(r"(?:密码|密钥|令牌)"),
)


def _contains_sensitive_marker(text: str) -> bool:
    value = str(text or "")
    lowered = value.lower()
    compact = lowered.replace("_", "").replace("-", "").replace(" ", "")
    if any(
        term in lowered or term.replace("_", "").replace("-", "").replace(" ", "") in compact
        for term in _SENSITIVE_KIND_TERMS
    ):
        return True
    return any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS)


def classify_memory_candidate(candidate: dict[str, Any]) -> str:
    kind = str(candidate.get("kind") or "").lower().replace("-", "_")
    value = str(candidate.get("value") or "")
    if _contains_sensitive_marker(kind) or _contains_sensitive_marker(value):
        return "reject"
    if kind in {"path", "port", "command", "project_boundary", "tooling"}:
        return "knowledge"
    if kind in {"preference", "rule", "acceptance", "permission", "classification"}:
        return "pending"
    return "pending"


class MemoryStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

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

    def set_session_suggestion(self, chat_id: str, value: str) -> None:
        key = "pending_dispatch_suggestion"
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_memory WHERE chat_id = ? AND key = ?",
                (chat_id, key),
            )
            conn.execute(
                "INSERT INTO session_memory(chat_id, key, value, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, key, value, int(time.time())),
            )

    def get_session_suggestion(self, chat_id: str) -> str | None:
        key = "pending_dispatch_suggestion"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value FROM session_memory
                WHERE chat_id = ? AND key = ?
                ORDER BY id DESC LIMIT 1
                """,
                (chat_id, key),
            ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def clear_session_suggestion(self, chat_id: str) -> None:
        key = "pending_dispatch_suggestion"
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_memory WHERE chat_id = ? AND key = ?",
                (chat_id, key),
            )

    def set_session_clarification(self, chat_id: str, value: str) -> None:
        key = "pending_dispatch_clarification"
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_memory WHERE chat_id = ? AND key = ?",
                (chat_id, key),
            )
            conn.execute(
                "INSERT INTO session_memory(chat_id, key, value, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, key, value, int(time.time())),
            )

    def get_session_clarification(self, chat_id: str) -> str | None:
        key = "pending_dispatch_clarification"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT value FROM session_memory
                WHERE chat_id = ? AND key = ?
                ORDER BY id DESC LIMIT 1
                """,
                (chat_id, key),
            ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def clear_session_clarification(self, chat_id: str) -> None:
        key = "pending_dispatch_clarification"
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_memory WHERE chat_id = ? AND key = ?",
                (chat_id, key),
            )

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

    def upsert_knowledge_memory(self, kind: str, key: str, value: str) -> None:
        """Insert or replace a knowledge entry (idempotent by kind+key)."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM knowledge_memory WHERE kind = ? AND key = ?",
                (kind, key),
            )
            conn.execute(
                "INSERT INTO knowledge_memory(kind, key, value, created_at) VALUES (?, ?, ?, ?)",
                (kind, key, value, int(time.time())),
            )

    def get_knowledge_by_key(self, kind: str, key: str) -> str | None:
        """Retrieve a single knowledge entry by kind+key, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM knowledge_memory WHERE kind = ? AND key = ? ORDER BY id DESC LIMIT 1",
                (kind, key),
            ).fetchone()
        return str(row["value"]) if row else None

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

    def process_memory_candidates(self, candidates: list[dict[str, Any]], source: str) -> dict[str, int]:
        counts = {"knowledge": 0, "pending": 0, "reject": 0}
        if not isinstance(candidates, (list, tuple)):
            return counts
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            kind = str(candidate.get("kind") or "").lower()
            value = str(candidate.get("value") or "")
            if not value:
                continue
            classification = classify_memory_candidate(candidate)
            if classification not in counts:
                continue
            counts[classification] += 1
            if classification == "knowledge":
                self.add_knowledge_memory(kind, value[:80], value)
            elif classification == "pending":
                try:
                    confidence = float(candidate.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                if not isfinite(confidence):
                    confidence = 0.0
                self.add_pending_memory(
                    kind=kind,
                    value=value,
                    source=source,
                    confidence=confidence,
                )
        return counts

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
