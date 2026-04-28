import unittest
from unittest.mock import patch

import status_watcher


class StatusWatcherReviewDispatchTests(unittest.TestCase):
    def _run_poll(self, status):
        cache = {"UUM-42": "in_progress"}
        issue = {
            "identifier": "UUM-42",
            "title": "登录页白屏",
            "status": status,
            "assignee": "Agent",
        }
        output = {"issues": [issue]}

        with (
            patch("status_watcher._run_multica", return_value=(True, __import__("json").dumps(output))),
            patch("status_watcher._send_webhook", return_value=True),
            patch("status_watcher._save_cache"),
            patch("status_watcher.trigger_code_review_async") as trigger,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")
            return trigger

    def test_inreview_transition_triggers_code_review_once(self):
        trigger = self._run_poll("In Review")

        trigger.assert_called_once()
        args = trigger.call_args.args
        self.assertEqual(args[0]["identifier"], "UUM-42")
        self.assertEqual(args[1], "in_progress")
        self.assertEqual(args[2], "In Review")

    def test_done_transition_does_not_trigger_code_review(self):
        trigger = self._run_poll("done")

        trigger.assert_not_called()

    def test_cancelled_transition_does_not_trigger_code_review(self):
        trigger = self._run_poll("cancelled")

        trigger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
