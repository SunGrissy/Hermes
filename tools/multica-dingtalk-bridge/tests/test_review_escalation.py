import json
import os
import unittest
from unittest.mock import MagicMock, patch

import sys
from pathlib import Path

_BRIDGE = Path(__file__).parent.parent
if str(_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_BRIDGE))


class ReviewEscalationTests(unittest.TestCase):
    def test_load_escalation_prefers_env(self):
        from review_escalation import load_escalation_webhook_url

        with patch.dict(os.environ, {"MULTICA_REVIEW_ESCALATION_WEBHOOK_URL": "https://env.example/hook"}, clear=False):
            self.assertEqual(load_escalation_webhook_url(), "https://env.example/hook")

    def test_send_escalation_posts_markdown(self):
        from review_escalation import send_review_escalation

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"errcode":0}'

        captured = {}

        def fake_urlopen(req, timeout=30):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResp()

        issue = {"identifier": "UUM-7", "title": "测试"}
        with (
            patch.dict(os.environ, {"MULTICA_REVIEW_ESCALATION_WEBHOOK_URL": "https://oapi.example/x"}, clear=False),
            patch("review_escalation.urllib.request.urlopen", fake_urlopen),
        ):
            self.assertTrue(send_review_escalation(issue, reason="unit test", backend="hermes"))

        self.assertEqual(captured["body"]["msgtype"], "markdown")
        self.assertIn("UUM-7", captured["body"]["markdown"]["text"])
        self.assertIn("unit test", captured["body"]["markdown"]["text"])


class StatusWatcherEscalationDispatchTests(unittest.TestCase):
    def test_cli_dispatch_escalation_calls_send_on_failure(self):
        import status_watcher as sw

        mock_d = MagicMock()
        mock_d.config.enabled = True
        mock_d.dispatch.return_value = False
        issue = {"identifier": "UUM-99", "title": "t"}

        with (
            patch.dict(os.environ, {"MULTICA_REVIEW_ESCALATION_WEBHOOK_URL": "https://example.invalid/h"}, clear=False),
            patch("code_review_dispatcher.CodeReviewDispatcher", return_value=mock_d),
            patch("review_escalation.send_review_escalation") as send_e,
        ):
            sw._cli_dispatch_with_escalation(issue, "a", "b")

        mock_d.dispatch.assert_called_once()
        send_e.assert_called_once()
        self.assertEqual(send_e.call_args.kwargs["backend"], "cli")


if __name__ == "__main__":
    unittest.main()
