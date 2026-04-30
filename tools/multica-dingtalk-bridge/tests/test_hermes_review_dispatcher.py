import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_review_dispatcher import (
    HermesReviewConfig,
    HermesReviewDispatcher,
    _is_review_passed,
    build_review_prompt,
    extract_final_response,
    trigger_hermes_review_async,
)


class HermesReviewDispatcherTests(unittest.TestCase):
    def test_disabled_trigger_does_not_start_thread(self):
        with (
            patch.dict("os.environ", {"HERMES_REVIEW_ENABLED": "0"}, clear=False),
            patch("hermes_review_dispatcher.threading.Thread") as thread_cls,
        ):
            trigger_hermes_review_async({"identifier": "UUM-42"}, "in_progress", "In Review")

        thread_cls.assert_not_called()

    def test_build_review_prompt_contains_issue_contract(self):
        prompt = build_review_prompt(
            {"identifier": "UUM-42", "title": "登录页白屏"},
            "in_progress",
            "In Review",
        )

        self.assertIn("multica-code-review", prompt)
        self.assertIn("UUM-42", prompt)
        self.assertIn("只做代码审查", prompt)
        self.assertIn("agent/UUM-42", prompt)

    def test_extract_final_response_prefers_agent_marker(self):
        stdout = "prefix\n🎯 FINAL RESPONSE:\n---\n报告正文\n\n👋 Agent execution completed!\n"

        self.assertEqual(extract_final_response(stdout), "报告正文")

    def test_dispatch_skips_when_agent_entry_missing(self):
        cfg = HermesReviewConfig(
            enabled=True,
            hermes_home=Path(r"D:\missing-hermes"),
            agent_root=Path(r"D:\missing-hermes\hermes-agent"),
            python_bin="py",
            max_turns=1,
            timeout_s=1,
            send_timeout_s=1,
            target="",
            daemon_cid="",
            daemon_url="http://127.0.0.1:19200",
        )

        self.assertFalse(HermesReviewDispatcher(cfg).dispatch({"identifier": "UUM-42"}, "a", "b"))

    def test_daemon_delivery_accepts_compact_json_success(self):
        cfg = HermesReviewConfig(
            enabled=True,
            hermes_home=Path(r"D:\hermes"),
            agent_root=Path(r"D:\hermes\hermes-agent"),
            python_bin="py",
            max_turns=1,
            timeout_s=1,
            send_timeout_s=1,
            target="",
            daemon_cid="cid-1",
            daemon_url="http://127.0.0.1:19200",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"success":true}'

        with patch("hermes_review_dispatcher.urllib.request.urlopen", return_value=FakeResponse()):
            self.assertTrue(HermesReviewDispatcher(cfg)._send_via_dingtalk_daemon("UUM-42", "报告"))

    def test_review_passed_heuristic(self):
        self.assertTrue(_is_review_passed("未发现阻塞项，风险很低"))
        self.assertTrue(_is_review_passed("审查通过，可以合并"))
        self.assertFalse(_is_review_passed("高风险，必须修复后再合并"))
        self.assertFalse(_is_review_passed(""))


if __name__ == "__main__":
    unittest.main()
