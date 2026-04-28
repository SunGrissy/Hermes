import unittest
from unittest.mock import patch

from brain import (
    Brain,
    BrainDecision,
    MockLLMProvider,
    OpenAICompatibleProvider,
    build_provider_from_env,
    is_confirm_dispatch_phrase,
    parse_brain_decision,
    render_patrol_summary,
)


class BrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_brain_asks_clarification_when_dod_missing(self):
        brain = Brain(provider=MockLLMProvider())

        decision = await brain.decide("派单 修复登录白屏")
        reply = brain.render_reply(decision)

        self.assertEqual(decision.recommended_action, "ask_clarification")
        self.assertEqual(decision.missing_info, ["验收标准"])
        self.assertIn("验收", reply)

    def test_parse_brain_decision_accepts_json_block(self):
        decision = parse_brain_decision(
            """我会这样处理：

```json
{
  "intent": "dispatch",
  "category": "bug",
  "recommended_action": "ask_confirm",
  "suggested_title": "修复登录白屏",
  "suggested_description": "复现：iOS 17。",
  "definition_of_done": ["登录页能正常进入"],
  "priority": "high",
  "confidence": 0.87
}
```
"""
        )

        self.assertIsInstance(decision, BrainDecision)
        self.assertEqual(decision.recommended_action, "ask_confirm")
        self.assertEqual(decision.suggested_title, "修复登录白屏")
        self.assertEqual(decision.priority, "high")

    def test_confirm_dispatch_phrase_matches_only_confirmations(self):
        for phrase in (
            "就按这个派",
            "就按这个派单",
            "确认",
            "确认派单",
            "按这个派",
            "按这个派单",
            "可以派",
            "派吧",
        ):
            with self.subTest(phrase=phrase):
                self.assertIs(is_confirm_dispatch_phrase(phrase), True)

        self.assertIs(is_confirm_dispatch_phrase("先别派"), False)
        self.assertIs(is_confirm_dispatch_phrase(""), False)

    async def test_brain_renders_dispatch_card(self):
        brain = Brain(
            provider=MockLLMProvider(
                BrainDecision(
                    intent="dispatch",
                    category="feature",
                    recommended_action="ask_confirm",
                    suggested_title="补齐派单验收口径",
                    suggested_description="补齐 Brain 派单确认文案。",
                    definition_of_done=["回复包含确认按钮文案"],
                    priority="medium",
                    split_suggestion="不用拆分",
                )
            )
        )

        decision = await brain.decide("派单 补齐派单验收口径\n验收：回复包含确认按钮文案。")
        reply = brain.render_reply(decision)

        self.assertIn("补齐派单验收口径", reply)
        self.assertIn("我理解这单要解决的是", reply)
        self.assertIn("feature", reply)
        self.assertIn("medium", reply)
        self.assertIn("补齐 Brain 派单确认文案", reply)
        self.assertIn("回复包含确认按钮文案", reply)
        self.assertIn("不用拆分", reply)
        self.assertIn("就按这个派", reply)

    async def test_brain_does_not_use_acceptance_line_as_title(self):
        brain = Brain(provider=MockLLMProvider())

        decision = await brain.decide("验收：打开登录页不白屏了")
        reply = brain.render_reply(decision)

        self.assertEqual(decision.recommended_action, "ask_clarification")
        self.assertEqual(decision.missing_info, ["需求标题"])
        self.assertNotEqual(decision.suggested_title, "验收：打开登录页不白屏了")
        self.assertIn("标题", reply)

    async def test_brain_strips_dispatch_intent_prefix_from_title(self):
        brain = Brain(provider=MockLLMProvider())

        decision = await brain.decide("这个需求怎么派比较好？登录页偶发白屏\n验收：打开登录页不白屏了")
        reply = brain.render_reply(decision)

        self.assertEqual(decision.recommended_action, "ask_confirm")
        self.assertEqual(decision.suggested_title, "登录页偶发白屏")
        self.assertIn("登录页偶发白屏", reply)
        self.assertIn("打开登录页不白屏了", reply)

    async def test_dict_response_plan_fields_round_trip(self):
        payload = {
            "intent": "dispatch",
            "category": "feature",
            "confidence": 0.91,
            "missing_info": [],
            "suggested_title": "接入结构化派单大脑",
            "suggested_description": "让钉钉自然语言先进入 Brain 决策。",
            "definition_of_done": ["能输出确认卡片", "不自动执行代码"],
            "priority": "high",
            "split_suggestion": "先 Brain，再接入 handler。",
            "recommended_action": "ask_confirm",
            "memory_candidates": [{"kind": "preference", "value": "派单前先确认"}],
        }
        brain = Brain(provider=MockLLMProvider(payload))

        decision = await brain.decide("派单 接入结构化派单大脑\n验收：能输出确认卡片")

        self.assertEqual(decision.intent, payload["intent"])
        self.assertEqual(decision.category, payload["category"])
        self.assertEqual(decision.confidence, payload["confidence"])
        self.assertEqual(decision.missing_info, payload["missing_info"])
        self.assertEqual(decision.suggested_title, payload["suggested_title"])
        self.assertEqual(decision.suggested_description, payload["suggested_description"])
        self.assertEqual(decision.definition_of_done, payload["definition_of_done"])
        self.assertEqual(decision.priority, payload["priority"])
        self.assertEqual(decision.split_suggestion, payload["split_suggestion"])
        self.assertEqual(decision.recommended_action, payload["recommended_action"])
        self.assertEqual(decision.memory_candidates, payload["memory_candidates"])

    def test_malformed_fenced_json_raises(self):
        with self.assertRaises(ValueError):
            parse_brain_decision(
                """```json
{"recommended_action": "reply",
```
{"recommended_action": "reply"}"""
            )

    def test_unknown_recommended_action_raises(self):
        with self.assertRaises(ValueError):
            parse_brain_decision('{"recommended_action": "execute_now"}')

    def test_ask_confirm_requires_suggested_title(self):
        with self.assertRaises(ValueError):
            parse_brain_decision(
                '{"recommended_action": "ask_confirm", "suggested_description": "缺标题"}'
            )

    def test_memory_candidates_are_preserved(self):
        decision = parse_brain_decision(
            """{
  "recommended_action": "reply",
  "memory_candidates": [
    {"kind": "project", "value": "multica bridge"},
    {"kind": "preference", "value": "先确认再派单"}
  ]
}"""
        )

        self.assertEqual(
            decision.memory_candidates,
            [
                {"kind": "project", "value": "multica bridge"},
                {"kind": "preference", "value": "先确认再派单"},
            ],
        )

    def test_render_patrol_summary_counts_status_and_marks_read_only(self):
        summary = render_patrol_summary(
            [
                {
                    "identifier": "UUM-1",
                    "title": "补齐验收说明",
                    "status": "todo",
                    "assignee": "小橘",
                    "description": "缺少背景",
                },
                {
                    "identifier": "UUM-2",
                    "title": "修复阻塞项",
                    "status": "blocked",
                    "assignee": {"name": "大虾"},
                    "description": "验收：恢复正常",
                },
                {
                    "identifier": "UUM-3",
                    "title": "已完成任务",
                    "status": "done",
                    "description": "DoD: done",
                },
            ]
        )

        self.assertIn("只读巡查，不会自动改状态", summary)
        self.assertIn("总数：3", summary)
        self.assertIn("- blocked：1", summary)
        self.assertIn("- done：1", summary)
        self.assertIn("- todo：1", summary)
        self.assertIn("UUM-1", summary)
        self.assertIn("missing DoD", summary)
        self.assertIn("UUM-2", summary)
        self.assertIn("blocked", summary)

    def test_render_patrol_summary_does_not_flag_terminal_missing_dod(self):
        summary = render_patrol_summary(
            [
                {
                    "identifier": "UUM-10",
                    "title": "已完成但旧描述无验收",
                    "status": "done",
                    "description": "历史工单",
                },
                {
                    "identifier": "UUM-11",
                    "title": "已关闭但旧描述无验收",
                    "status": "closed",
                    "description": "历史工单",
                },
            ]
        )

        self.assertIn("暂无明显需要关注项", summary)
        self.assertNotIn("UUM-10", summary)
        self.assertNotIn("UUM-11", summary)
        self.assertNotIn("missing DoD", summary)

    def test_openai_provider_requires_explicit_multica_api_key(self):
        with patch.dict(
            "os.environ",
            {
                "MULTICA_BOT_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "global-key-must-not-be-used",
                "OPENAI_BASE_URL": "https://global.example/v1",
                "OPENAI_MODEL": "global-model",
                "MULTICA_BOT_OPENAI_API_KEY": "legacy-key-must-not-be-used",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "MULTICA_BOT_LLM_API_KEY is required when MULTICA_BOT_LLM_PROVIDER=openai",
            ):
                build_provider_from_env()

    def test_openai_provider_uses_only_multica_scoped_env(self):
        with patch.dict(
            "os.environ",
            {
                "MULTICA_BOT_LLM_PROVIDER": "openai",
                "MULTICA_BOT_LLM_API_KEY": "multica-key",
                "MULTICA_BOT_LLM_BASE_URL": "https://llm.example/v1",
                "MULTICA_BOT_LLM_MODEL": "multica-model",
                "OPENAI_API_KEY": "global-key-must-not-be-used",
                "OPENAI_BASE_URL": "https://global.example/v1",
                "OPENAI_MODEL": "global-model",
            },
            clear=True,
        ):
            provider = build_provider_from_env()

        self.assertIsInstance(provider, OpenAICompatibleProvider)
        self.assertEqual(provider.api_key, "multica-key")
        self.assertEqual(provider.base_url, "https://llm.example/v1")
        self.assertEqual(provider.model, "multica-model")


if __name__ == "__main__":
    unittest.main()
