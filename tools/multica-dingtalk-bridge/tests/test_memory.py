import tempfile
import unittest
from math import inf
from pathlib import Path

from memory import MemoryStore, classify_memory_candidate


class MemoryStoreTests(unittest.TestCase):
    def test_session_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.add_session_memory("chat-1", "scope", "只做 pm-system")
            rows = store.get_session_memory("chat-1")
            self.assertEqual(rows[0]["key"], "scope")
            self.assertEqual(rows[0]["value"], "只做 pm-system")

    def test_session_suggestion_keeps_latest_value_per_chat(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.set_session_suggestion("chat-1", '{"suggested_title": "旧建议"}')
            store.set_session_suggestion("chat-1", '{"suggested_title": "新建议"}')
            store.set_session_suggestion("chat-2", '{"suggested_title": "别的会话"}')

            self.assertEqual(store.get_session_suggestion("chat-1"), '{"suggested_title": "新建议"}')
            self.assertEqual(store.get_session_suggestion("chat-2"), '{"suggested_title": "别的会话"}')
            self.assertIsNone(store.get_session_suggestion("chat-missing"))

    def test_clear_session_suggestion_removes_only_target_chat(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.set_session_suggestion("chat-1", '{"suggested_title": "新建议"}')
            store.set_session_suggestion("chat-2", '{"suggested_title": "别的会话"}')

            store.clear_session_suggestion("chat-1")

            self.assertIsNone(store.get_session_suggestion("chat-1"))
            self.assertEqual(store.get_session_suggestion("chat-2"), '{"suggested_title": "别的会话"}')

    def test_session_clarification_keeps_latest_value_per_chat(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.set_session_clarification("chat-1", '{"suggested_title": "旧草稿"}')
            store.set_session_clarification("chat-1", '{"suggested_title": "新草稿"}')
            store.set_session_clarification("chat-2", '{"suggested_title": "别的会话"}')

            self.assertEqual(store.get_session_clarification("chat-1"), '{"suggested_title": "新草稿"}')
            self.assertEqual(store.get_session_clarification("chat-2"), '{"suggested_title": "别的会话"}')
            self.assertIsNone(store.get_session_clarification("chat-missing"))

            store.clear_session_clarification("chat-1")

            self.assertIsNone(store.get_session_clarification("chat-1"))
            self.assertEqual(store.get_session_clarification("chat-2"), '{"suggested_title": "别的会话"}')

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

    def test_classify_low_risk_path_as_knowledge(self):
        self.assertEqual(
            classify_memory_candidate(
                {"kind": "path", "value": "tools/multica-dingtalk-bridge"}
            ),
            "knowledge",
        )

    def test_classify_preference_as_pending(self):
        self.assertEqual(
            classify_memory_candidate(
                {"kind": "preference", "value": "派单建议要先确认 DoD"}
            ),
            "pending",
        )

    def test_classify_sk_false_positives_as_knowledge(self):
        self.assertEqual(
            classify_memory_candidate({"kind": "path", "value": "task docs"}),
            "knowledge",
        )
        self.assertEqual(
            classify_memory_candidate({"kind": "command", "value": "ask owner to confirm"}),
            "knowledge",
        )

    def test_classify_real_sk_key_as_reject(self):
        self.assertEqual(
            classify_memory_candidate(
                {"kind": "path", "value": "sk-abcdefghijklmnopqrstuvwxyz"}
            ),
            "reject",
        )

    def test_classify_secret_like_values_as_reject(self):
        for value in (
            "secret should not be stored",
            "token=abc123",
            "api_key=abc123",
            "apikey=abc123",
            "client_secret=abc123",
            "clientsecret=abc123",
            "password=abc123",
            "密码=abc123",
            "密钥：abc123",
            "令牌=abc123",
            "Authorization: Bearer abc.def.ghi",
            "sk-abcdefghijklmnopqrstuvwxyz",
            "private_key=abc123",
            "private key=abc123",
            "access_key=abc123",
            "refresh_key=abc123",
            "auth_key=abc123",
            "access_token=abc123",
            "refresh_token=abc123",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    classify_memory_candidate({"kind": "path", "value": value}),
                    "reject",
                )

    def test_classify_sensitive_kinds_as_reject(self):
        for kind in (
            "secret",
            "token",
            "api_key",
            "apikey",
            "client_secret",
            "clientsecret",
            "password",
            "access_token",
            "refresh-token",
            "clientSecret",
            "private_key",
            "privatekey",
            "private key",
            "access_key",
            "accesskey",
            "refresh_key",
            "refreshkey",
            "auth_key",
            "authkey",
            "accessToken",
            "refresh_token",
            "refreshToken",
            "bearer ",
            "密码",
            "密钥",
            "令牌",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    classify_memory_candidate({"kind": kind, "value": "ordinary value"}),
                    "reject",
                )

    def test_process_memory_candidates_writes_knowledge_and_pending_only(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")

            counts = store.process_memory_candidates(
                [
                    {"kind": "path", "value": "tools/multica-dingtalk-bridge"},
                    {
                        "kind": "preference",
                        "value": "派单建议要先确认 DoD",
                        "confidence": 0.72,
                    },
                    {"kind": "command", "value": "token=abc123"},
                    {"kind": "tooling", "value": ""},
                ],
                source="chat-1",
            )

            self.assertEqual(counts, {"knowledge": 1, "pending": 1, "reject": 1})

            knowledge = store.list_knowledge_memory()
            self.assertEqual(len(knowledge), 1)
            self.assertEqual(knowledge[0]["kind"], "path")
            self.assertEqual(knowledge[0]["value"], "tools/multica-dingtalk-bridge")

            pending = store.list_pending_memory()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["kind"], "preference")
            self.assertEqual(pending[0]["value"], "派单建议要先确认 DoD")
            self.assertEqual(pending[0]["source"], "chat-1")
            self.assertAlmostEqual(pending[0]["confidence"], 0.72)

    def test_process_memory_candidates_does_not_store_sensitive_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")

            counts = store.process_memory_candidates(
                [
                    {"kind": "path", "value": "Bearer abc.def.ghi"},
                    {"kind": "preference", "value": "密码=abc123", "confidence": 0.9},
                    {"kind": "access_token", "value": "ordinary value", "confidence": 0.9},
                    {"kind": "path", "value": "client_secret=abc123"},
                ],
                source="chat-1",
            )

            self.assertEqual(counts, {"knowledge": 0, "pending": 0, "reject": 4})
            self.assertEqual(store.list_knowledge_memory(), [])
            self.assertEqual(store.list_pending_memory(), [])

    def test_process_memory_candidates_ignores_non_sequence_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")

            counts = store.process_memory_candidates(None, source="chat-1")

            self.assertEqual(counts, {"knowledge": 0, "pending": 0, "reject": 0})
            self.assertEqual(store.list_knowledge_memory(), [])
            self.assertEqual(store.list_pending_memory(), [])

    def test_process_memory_candidates_normalizes_non_finite_confidence(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")

            counts = store.process_memory_candidates(
                [
                    {"kind": "preference", "value": "偏好 A", "confidence": "nan"},
                    {"kind": "rule", "value": "规则 B", "confidence": inf},
                ],
                source="chat-1",
            )

            self.assertEqual(counts, {"knowledge": 0, "pending": 2, "reject": 0})
            pending = store.list_pending_memory()
            self.assertEqual([row["confidence"] for row in pending], [0.0, 0.0])
