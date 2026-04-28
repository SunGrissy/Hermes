import unittest
from types import SimpleNamespace
from unittest.mock import patch

from brain import BrainDecision
from dispatch_bot import (
    MulticaDispatchHandler,
    _normalize_dingtalk_at_prefixes,
    _redact_sensitive_text,
    classify_incoming_text,
    should_route_to_brain,
)
from multica_client import MulticaResult


class DispatchRouterTests(unittest.TestCase):
    def test_fixed_dispatch_command_wins(self):
        self.assertEqual(classify_incoming_text("派单 修复查工单"), "create_issue")

    def test_fixed_dispatch_command_wins_over_patrol_text(self):
        self.assertEqual(classify_incoming_text("派单 巡查功能补测试"), "create_issue")

    def test_query_command_wins(self):
        self.assertEqual(classify_incoming_text("查工单"), "query_issues")

    def test_delete_command_wins(self):
        self.assertEqual(classify_incoming_text("取消派单 UUM-1"), "cancel_issue")

    def test_patrol_command_routes_to_patrol(self):
        for text in ("巡查", "队列巡查", "巡查工单", "multica巡查"):
            with self.subTest(text=text):
                self.assertEqual(classify_incoming_text(text), "patrol")

    def test_non_command_goes_to_brain(self):
        self.assertEqual(classify_incoming_text("这个需求怎么派比较好？"), "brain")

    def test_at_dispatch_command_wins(self):
        self.assertEqual(classify_incoming_text("@机器人 派单 修复查工单"), "create_issue")

    def test_at_query_command_wins(self):
        self.assertEqual(classify_incoming_text("@机器人 查工单"), "query_issues")

    def test_at_delete_command_wins(self):
        self.assertEqual(classify_incoming_text("@机器人 取消派单 UUM-1"), "cancel_issue")

    def test_at_confirm_without_space_normalizes_to_confirm_phrase(self):
        self.assertEqual(_normalize_dingtalk_at_prefixes("@机器人就按这个派"), "就按这个派")

    def test_dispatch_intent_routes_to_brain(self):
        self.assertIs(should_route_to_brain("这个需求怎么派比较好？"), True)

    def test_dispatch_natural_language_routes_to_brain(self):
        self.assertIs(should_route_to_brain("这个事项要不要派单处理？"), True)

    def test_acceptance_followup_routes_to_brain(self):
        self.assertIs(should_route_to_brain("验收：打开登录页不白屏了"), True)

    def test_chat_does_not_route_to_brain(self):
        self.assertIs(should_route_to_brain("大家晚上吃啥"), False)


class FakeMemoryStore:
    def __init__(self, suggestion=None, process_counts=None, process_exception=None):
        self.suggestion = suggestion
        self.clarification = None
        self.cleared = []
        self.clarification_cleared = []
        self.processed = []
        self.process_counts = process_counts or {"knowledge": 0, "pending": 1, "reject": 0}
        self.process_exception = process_exception

    def get_session_suggestion(self, chat_id):
        return self.suggestion

    def clear_session_suggestion(self, chat_id):
        self.cleared.append(chat_id)
        self.suggestion = None

    def set_session_suggestion(self, chat_id, value):
        self.suggestion = value

    def get_session_clarification(self, chat_id):
        return self.clarification

    def set_session_clarification(self, chat_id, value):
        self.clarification = value

    def clear_session_clarification(self, chat_id):
        self.clarification_cleared.append(chat_id)
        self.clarification = None

    def process_memory_candidates(self, candidates, source):
        if self.process_exception is not None:
            raise self.process_exception
        self.processed.append((candidates, source))
        return self.process_counts


class FakeMulticaClient:
    def __init__(self, result=None, exception=None):
        self.result = result
        self.exception = exception
        self.calls = []

    async def create_issue(self, **kwargs):
        self.calls.append(("create_issue", kwargs))
        if self.exception is not None:
            raise self.exception
        return self.result

    async def list_issues(self, **kwargs):
        self.calls.append(("list_issues", kwargs))
        if self.exception is not None:
            raise self.exception
        return self.result

    async def cancel_issue(self, *args, **kwargs):
        self.calls.append(("cancel_issue", args, kwargs))
        raise AssertionError("patrol must not cancel issues")


class FakeIncoming:
    conversation_id = "chat-1"
    sender_staff_id = "staff-1"
    text = SimpleNamespace(content="这个需求怎么派比较好？")


class CapturingDispatchHandler(MulticaDispatchHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.replies = []

    def _reply_dispatch_message(self, incoming, card_header_title, markdown_body):
        self.replies.append((card_header_title, markdown_body))


class FakeBrain:
    def __init__(self):
        self.decision = BrainDecision(
            intent="dispatch",
            category="task",
            confidence=0.8,
            suggested_description="我先记录这条需求。",
            recommended_action="reply",
            memory_candidates=[
                {"kind": "preference", "value": "派单前先确认 DoD", "confidence": 0.8}
            ],
        )

    async def decide(self, raw, context: str = "", project_context: str = ""):
        return self.decision

    def render_reply(self, decision):
        return "我先记录这条需求。"


class CapturingBrain:
    def __init__(self):
        self.inputs = []
        self.decision = BrainDecision(
            intent="dispatch",
            category="task",
            confidence=0.8,
            suggested_title="登录页偶发白屏",
            suggested_description="登录页偶发白屏\n验收：打开登录页不白屏了",
            definition_of_done=["打开登录页不白屏了"],
            recommended_action="ask_confirm",
        )

    async def decide(self, raw, context: str = "", project_context: str = ""):
        self.inputs.append(raw)
        return self.decision

    def render_reply(self, decision):
        return "我先整理成这张派单建议卡：\n确认无误就回复：就按这个派"


class DispatchConfirmTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_without_pending_suggestion_replies_empty(self):
        handler = MulticaDispatchHandler(
            memory_store=FakeMemoryStore(),
            multica_client=FakeMulticaClient(MulticaResult(True, 0, "", "", {})),
        )

        reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())

        self.assertEqual(reply, "没有待确认的派单建议")

    async def test_confirm_pending_suggestion_creates_issue(self):
        suggestion = """{
  "recommended_action": "ask_confirm",
  "suggested_title": "修复登录白屏",
  "suggested_description": "复现：iOS 17。",
  "definition_of_done": ["登录页正常进入"],
  "priority": "high"
}"""
        multica = FakeMulticaClient(
            MulticaResult(True, 0, "", "", {"identifier": "UUM-7", "id": "issue-7"})
        )
        memory = FakeMemoryStore(suggestion)
        handler = MulticaDispatchHandler(memory_store=memory, multica_client=multica)

        reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())

        self.assertIn("UUM-7", reply)
        self.assertEqual(memory.cleared, ["chat-1"])
        self.assertEqual(
            multica.calls[0],
            (
                "create_issue",
                {
                    "title": "修复登录白屏",
                    "description": "复现：iOS 17。",
                    "priority": "high",
                    "status": "todo",
                },
            ),
        )

    async def test_successful_confirm_clears_pending_and_prevents_duplicate_create(self):
        suggestion = """{
  "recommended_action": "ask_confirm",
  "suggested_title": "修复登录白屏",
  "suggested_description": "复现：iOS 17。",
  "priority": "high"
}"""
        multica = FakeMulticaClient(
            MulticaResult(True, 0, "", "", {"identifier": "UUM-7", "id": "issue-7"})
        )
        handler = MulticaDispatchHandler(
            memory_store=FakeMemoryStore(suggestion),
            multica_client=multica,
        )

        first_reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())
        second_reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())

        self.assertIn("UUM-7", first_reply)
        self.assertEqual(second_reply, "没有待确认的派单建议")
        self.assertEqual(len(multica.calls), 1)

    async def test_confirm_create_failure_returns_sanitized_message(self):
        suggestion = """{
  "recommended_action": "ask_confirm",
  "suggested_title": "修复登录白屏",
  "suggested_description": "复现：iOS 17。",
  "priority": "high"
}"""
        multica = FakeMulticaClient(
            MulticaResult(
                False,
                1,
                "stdout SECRET_TOKEN=abc123",
                "stderr password=abc123",
                None,
            )
        )
        handler = MulticaDispatchHandler(
            memory_store=FakeMemoryStore(suggestion),
            multica_client=multica,
        )

        with self.assertLogs("multica-bridge", level="WARNING") as logs:
            reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())

        self.assertEqual(reply, "建单失败：Multica CLI 返回错误，请查看桥进程日志。")
        self.assertNotIn("SECRET_TOKEN", reply)
        self.assertNotIn("password", reply)
        joined = "\n".join(logs.output)
        self.assertNotIn("abc123", joined)
        self.assertIn("[REDACTED]", joined)

    async def test_confirm_create_exception_returns_failure_message(self):
        suggestion = """{
  "recommended_action": "ask_confirm",
  "suggested_title": "修复登录白屏",
  "suggested_description": "复现：iOS 17。",
  "priority": "high"
}"""
        handler = MulticaDispatchHandler(
            memory_store=FakeMemoryStore(suggestion),
            multica_client=FakeMulticaClient(exception=RuntimeError("boom secret=abc")),
        )

        with self.assertLogs("multica-bridge", level="WARNING") as logs:
            reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())

        self.assertEqual(reply, "建单失败：Multica CLI 调用异常，请查看桥进程日志。")
        self.assertNotIn("secret", reply)
        self.assertNotIn("abc", "\n".join(logs.output))

    async def test_malformed_pending_suggestion_does_not_create_issue(self):
        multica = FakeMulticaClient(
            MulticaResult(True, 0, "", "", {"identifier": "UUM-7", "id": "issue-7"})
        )
        handler = MulticaDispatchHandler(
            memory_store=FakeMemoryStore("not json"),
            multica_client=multica,
        )

        with self.assertLogs("multica-bridge", level="WARNING"):
            reply = await handler._confirm_pending_dispatch_suggestion(FakeIncoming())

        self.assertIn("待确认的派单建议格式有误", reply)
        self.assertEqual(multica.calls, [])

    async def test_patrol_process_lists_issues_only(self):
        multica = FakeMulticaClient(
            MulticaResult(
                True,
                0,
                "",
                "",
                {
                    "issues": [
                        {
                            "identifier": "UUM-1",
                            "title": "缺验收",
                            "status": "todo",
                            "assignee": "小橘",
                            "description": "背景说明",
                        }
                    ]
                },
            )
        )
        handler = CapturingDispatchHandler(
            memory_store=FakeMemoryStore(),
            multica_client=multica,
        )
        incoming = SimpleNamespace(
            conversation_id="chat-1",
            sender_staff_id="staff-1",
            text=SimpleNamespace(content="巡查"),
        )
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=incoming):
            await handler.process(callback)

        self.assertEqual(multica.calls, [("list_issues", {"limit": 500})])
        self.assertEqual(handler.replies[0][0], "Multica 队列巡查")
        self.assertIn("只读巡查，不会自动改状态", handler.replies[0][1])
        self.assertIn("UUM-1", handler.replies[0][1])

    async def test_patrol_process_accepts_list_data(self):
        multica = FakeMulticaClient(
            MulticaResult(
                True,
                0,
                "",
                "",
                [
                    {
                        "identifier": "UUM-2",
                        "title": "列表形态数据",
                        "status": "blocked",
                        "description": "验收：能渲染",
                    }
                ],
            )
        )
        handler = CapturingDispatchHandler(
            memory_store=FakeMemoryStore(),
            multica_client=multica,
        )
        incoming = SimpleNamespace(
            conversation_id="chat-1",
            sender_staff_id="staff-1",
            text=SimpleNamespace(content="巡查"),
        )
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=incoming):
            await handler.process(callback)

        self.assertEqual(multica.calls, [("list_issues", {"limit": 500})])
        self.assertIn("总数：1", handler.replies[0][1])
        self.assertIn("UUM-2", handler.replies[0][1])

    async def test_patrol_failure_reply_is_sanitized(self):
        multica = FakeMulticaClient(
            MulticaResult(
                False,
                1,
                "stdout token=abc123",
                "stderr password=abc123",
                None,
            )
        )
        handler = CapturingDispatchHandler(
            memory_store=FakeMemoryStore(),
            multica_client=multica,
        )
        incoming = SimpleNamespace(
            conversation_id="chat-1",
            sender_staff_id="staff-1",
            text=SimpleNamespace(content="巡查"),
        )
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=incoming):
            with self.assertLogs("multica-bridge", level="WARNING") as logs:
                await handler.process(callback)

        self.assertEqual(
            handler.replies[0][1],
            "巡查失败：Multica CLI 返回错误，请查看桥进程日志。",
        )
        self.assertNotIn("abc123", handler.replies[0][1])
        self.assertNotIn("abc123", "\n".join(logs.output))
        self.assertIn("[REDACTED]", "\n".join(logs.output))

    async def test_patrol_exception_reply_is_sanitized(self):
        handler = CapturingDispatchHandler(
            memory_store=FakeMemoryStore(),
            multica_client=FakeMulticaClient(exception=RuntimeError("boom secret=abc123")),
        )
        incoming = SimpleNamespace(
            conversation_id="chat-1",
            sender_staff_id="staff-1",
            text=SimpleNamespace(content="巡查"),
        )
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=incoming):
            with self.assertLogs("multica-bridge", level="WARNING") as logs:
                await handler.process(callback)

        self.assertEqual(
            handler.replies[0][1],
            "巡查失败：Multica CLI 返回错误，请查看桥进程日志。",
        )
        self.assertNotIn("abc123", handler.replies[0][1])
        self.assertNotIn("abc123", "\n".join(logs.output))

    def test_redact_sensitive_text_masks_patrol_log_values(self):
        redacted = _redact_sensitive_text(
            "token=aaa password=bbb api_key=ccc secret=ddd client_secret=eee "
            "private_key=fff private key=ggg access_key=hhh refresh_key=iii auth_key=jjj "
            "access_token=kkk refresh_token=lll Bearer mmm.nnn.ooo sk-pppppppp "
            "密码=mmm 密钥：nnn 令牌=ooo "
            '"token":"json-token" CLIENT_SECRET:UpperSecret'
        )

        for value in (
            "aaa",
            "bbb",
            "ccc",
            "ddd",
            "eee",
            "fff",
            "ggg",
            "hhh",
            "iii",
            "jjj",
            "kkk",
            "lll",
            "mmm.nnn.ooo",
            "sk-pppppppp",
            "密码=mmm",
            "密钥：nnn",
            "令牌=ooo",
            "json-token",
            "UpperSecret",
        ):
            with self.subTest(value=value):
                self.assertNotIn(value, redacted)
        self.assertGreaterEqual(redacted.count("[REDACTED]"), 19)

    async def test_brain_reply_appends_pending_memory_candidate_note(self):
        memory = FakeMemoryStore()
        handler = CapturingDispatchHandler(
            memory_store=memory,
            multica_client=FakeMulticaClient(),
        )
        handler._brain = FakeBrain()
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=FakeIncoming()):
            await handler.process(callback)

        self.assertEqual(
            memory.processed[0][0],
            [{"kind": "preference", "value": "派单前先确认 DoD", "confidence": 0.8}],
        )
        self.assertEqual(memory.processed[0][1], "chat-1")
        self.assertIn("我还提取到 1 条长期记忆候选", handler.replies[0][1])

    async def test_acceptance_followup_uses_pending_clarification_context(self):
        memory = FakeMemoryStore(
            process_counts={"knowledge": 0, "pending": 0, "reject": 0}
        )
        memory.clarification = """{
  "recommended_action": "ask_clarification",
  "suggested_title": "登录页偶发白屏",
  "missing_info": ["验收标准"]
}"""
        brain = CapturingBrain()
        handler = CapturingDispatchHandler(
            memory_store=memory,
            multica_client=FakeMulticaClient(),
        )
        handler._brain = brain
        incoming = SimpleNamespace(
            conversation_id="chat-1",
            sender_staff_id="staff-1",
            text=SimpleNamespace(content="验收：打开登录页不白屏了"),
        )
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=incoming):
            await handler.process(callback)

        self.assertEqual(brain.inputs, ["登录页偶发白屏\n验收：打开登录页不白屏了"])
        self.assertIsNotNone(memory.suggestion)
        self.assertEqual(memory.clarification_cleared, ["chat-1"])
        self.assertIn("派单建议卡", handler.replies[0][1])

    async def test_brain_reply_ignores_memory_processing_exception(self):
        memory = FakeMemoryStore(process_exception=RuntimeError("memory failed"))
        handler = CapturingDispatchHandler(
            memory_store=memory,
            multica_client=FakeMulticaClient(),
        )
        handler._brain = FakeBrain()
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=FakeIncoming()):
            with self.assertLogs("multica-bridge", level="WARNING"):
                await handler.process(callback)

        self.assertEqual(handler.replies[0][1], "我先记录这条需求。")

    async def test_brain_reply_does_not_append_note_when_pending_zero(self):
        memory = FakeMemoryStore(process_counts={"knowledge": 1, "pending": 0, "reject": 0})
        handler = CapturingDispatchHandler(
            memory_store=memory,
            multica_client=FakeMulticaClient(),
        )
        handler._brain = FakeBrain()
        callback = SimpleNamespace(data={})

        with patch("dispatch_bot.dingtalk_stream.ChatbotMessage.from_dict", return_value=FakeIncoming()):
            await handler.process(callback)

        self.assertEqual(handler.replies[0][1], "我先记录这条需求。")
        self.assertNotIn("长期记忆候选", handler.replies[0][1])
