import json
import os
import unittest
from unittest.mock import patch

import status_watcher

# 本文件多数用例假定「状态机全量 webhook」；默认环境为精简模式时需显式还原。
_SCOPE_ALL = {"MULTICA_WEBHOOK_NOTIFY_SCOPE": "all"}


@patch.dict(os.environ, _SCOPE_ALL, clear=False)
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
            patch("status_watcher.escalation_enabled", return_value=False),
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

    def test_inreview_hermes_backend_calls_hermes_not_cli(self):
        cache = {"UUM-42": "in_progress"}
        issue = {
            "identifier": "UUM-42",
            "title": "登录页白屏",
            "status": "In Review",
            "assignee": "Agent",
        }
        output = {"issues": [issue]}
        with (
            patch("status_watcher.escalation_enabled", return_value=False),
            patch.dict(os.environ, {"IN_REVIEW_REVIEW_BACKEND": "hermes"}, clear=False),
            patch("status_watcher._run_multica", return_value=(True, json.dumps(output))),
            patch("status_watcher._send_webhook", return_value=True),
            patch("status_watcher._save_cache"),
            patch("status_watcher.trigger_code_review_async") as cli_t,
            patch("status_watcher.trigger_hermes_review_async") as hermes_t,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")

        cli_t.assert_not_called()
        hermes_t.assert_called_once()
        args = hermes_t.call_args.args
        self.assertEqual(args[0]["identifier"], "UUM-42")

    def test_done_transition_does_not_trigger_code_review(self):
        trigger = self._run_poll("done")

        trigger.assert_not_called()

    def test_cancelled_transition_does_not_trigger_code_review(self):
        trigger = self._run_poll("cancelled")

        trigger.assert_not_called()

    def test_approved_transition_calls_merge(self):
        cache = {"UUM-42": "in_review"}
        issue = {
            "identifier": "UUM-42",
            "title": "x",
            "status": "approved",
            "assignee": "Agent",
        }
        output = {"issues": [issue]}
        with (
            patch("status_watcher.escalation_enabled", return_value=False),
            patch("status_watcher._run_multica", return_value=(True, json.dumps(output))),
            patch("status_watcher._send_webhook", return_value=True),
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher._load_run_transition_cache", return_value={}),
            patch("status_watcher._load_run_fail_cache", return_value={}),
            patch("status_watcher.trigger_code_review_async"),
            patch("status_watcher._merge_agent_branch") as merge,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")
        merge.assert_called_once()

    def test_done_transition_does_not_call_merge_by_default(self):
        cache = {"UUM-42": "in_review"}
        issue = {
            "identifier": "UUM-42",
            "title": "x",
            "status": "done",
            "assignee": "Agent",
        }
        output = {"issues": [issue]}
        with (
            patch("status_watcher.escalation_enabled", return_value=False),
            patch("status_watcher._run_multica", return_value=(True, json.dumps(output))),
            patch("status_watcher._send_webhook", return_value=True),
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher._load_run_transition_cache", return_value={}),
            patch("status_watcher._load_run_fail_cache", return_value={}),
            patch("status_watcher.trigger_code_review_async"),
            patch("status_watcher._merge_agent_branch") as merge,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")
        merge.assert_not_called()

    def test_done_transition_calls_merge_when_env_done_trigger(self):
        cache = {"UUM-42": "in_review"}
        issue = {
            "identifier": "UUM-42",
            "title": "x",
            "status": "done",
            "assignee": "Agent",
        }
        output = {"issues": [issue]}
        with (
            patch.dict(os.environ, {"MULTICA_AUTO_MERGE_TRIGGER_STATUS": "done"}, clear=False),
            patch("status_watcher.escalation_enabled", return_value=False),
            patch("status_watcher._run_multica", return_value=(True, json.dumps(output))),
            patch("status_watcher._send_webhook", return_value=True),
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher._load_run_transition_cache", return_value={}),
            patch("status_watcher._load_run_fail_cache", return_value={}),
            patch("status_watcher.trigger_code_review_async"),
            patch("status_watcher._merge_agent_branch") as merge,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")
        merge.assert_called_once()

    # ─── failed 转换 ─────────────────────────────────────────────────────

    def test_failed_transition_sends_webhook_no_review(self):
        """status: failed → 应该发 webhook，但不触发 code review。"""
        cache = {"UUM-42": "in_progress"}
        issue = {
            "identifier": "UUM-42",
            "title": "测试失败工单",
            "status": "failed",
            "assignee": "Agent",
        }
        output = {"issues": [issue]}
        with (
            patch("status_watcher.escalation_enabled", return_value=False),
            patch("status_watcher._run_multica", return_value=(True, json.dumps(output))),
            patch("status_watcher._send_webhook", return_value=True) as webhook,
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher.trigger_code_review_async") as trigger,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")

        trigger.assert_not_called()
        # 至少调用了一次 webhook（failed 通知）
        webhook.assert_called()

    # ─── Run 级失败检测 ───────────────────────────────────────────────────

    def test_run_failure_detected_when_status_stuck(self):
        """工单 status 卡在 in_progress，但最新 run 显示 failed → 发通知。"""
        cache = {"UUM-42": "in_progress"}
        issues_output = {"issues": [{
            "identifier": "UUM-42",
            "title": "测试工单",
            "status": "in_progress",
            "assignee": "Agent",
        }]}
        failed_run_output = json.dumps([{
            "id": "run-abc-123",
            "status": "failed",
            "failure_reason": "agent_error",
            "error": "claude execution failed",
            "attempt": 1,
            "max_attempts": 2,
        }])
        # 第一次 _run_multica(issue,list,...) → issues
        # 第二次 _run_multica(issue,runs,UUM-42,...) → failed runs list
        call_count = [0]

        def mock_multica(*args, **_kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return True, json.dumps(issues_output)
            return True, failed_run_output

        with (
            patch("status_watcher._load_run_transition_cache", return_value={"UUM-42": "run-abc-456"}),
            patch("status_watcher._load_run_fail_cache", return_value={}),
            patch("status_watcher._run_multica", side_effect=mock_multica),
            patch("status_watcher._send_webhook", return_value=True) as webhook,
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher.trigger_code_review_async"),
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")

        webhook.assert_called_once()

    def test_run_failure_already_notified_skipped(self):
        """同一 run id 已通知过 → 跳过重复通知。"""
        cache = {"UUM-42": "in_progress"}
        issues_output = {"issues": [{
            "identifier": "UUM-42",
            "title": "测试工单",
            "status": "in_progress",
            "assignee": "Agent",
        }]}
        failed_run_output = json.dumps([{
            "id": "run-abc-123",
            "status": "failed",
            "failure_reason": "agent_error",
            "error": "claude execution failed",
            "attempt": 1,
            "max_attempts": 2,
        }])
        call_count = [0]

        def mock_multica(*args, **_kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return True, json.dumps(issues_output)
            return True, failed_run_output

        with (
            patch("status_watcher._load_run_fail_cache",
                  return_value={"UUM-42": "run-abc-123"}),
            patch("status_watcher._run_multica", side_effect=mock_multica),
            patch("status_watcher._send_webhook", return_value=True) as webhook,
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher.trigger_code_review_async"),
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")

        # 已通知过，不应再发 webhook
        webhook.assert_not_called()

    def test_run_not_failed_does_not_notify(self):
        """最新 run 正常完成 → 不触发失败通知。"""
        cache = {"UUM-42": "in_progress"}
        issues_output = {"issues": [{
            "identifier": "UUM-42",
            "title": "测试工单",
            "status": "in_progress",
            "assignee": "Agent",
        }]}
        completed_run_output = json.dumps([{
            "id": "run-abc-456",
            "status": "completed",
            "result": "任务完成",
        }])
        call_count = [0]

        def mock_multica(*args, **_kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return True, json.dumps(issues_output)
            return True, completed_run_output

        with (
            patch("status_watcher._load_run_transition_cache", return_value={"UUM-42": "run-abc-456"}),
            patch("status_watcher._load_run_fail_cache", return_value={}),
            patch("status_watcher._run_multica", side_effect=mock_multica),
            patch("status_watcher._send_webhook", return_value=True) as webhook,
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher.trigger_code_review_async"),
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")

        webhook.assert_not_called()


class StatusWatcherMinimalWebhookTests(unittest.TestCase):
    """MULTICA_WEBHOOK_NOTIFY_SCOPE=review_and_failures 时：少发状态噪音，审查链仍跑。"""

    def test_inreview_skips_transition_webhook_still_triggers_review(self):
        cache = {"UUM-42": "in_progress"}
        issue = {
            "identifier": "UUM-42",
            "title": "登录页白屏",
            "status": "In Review",
            "assignee": "Agent",
        }
        output = {"issues": [issue]}
        with (
            patch.dict(os.environ, {"MULTICA_WEBHOOK_NOTIFY_SCOPE": "review_and_failures"}, clear=False),
            patch("status_watcher.escalation_enabled", return_value=False),
            patch("status_watcher._run_multica", return_value=(True, json.dumps(output))),
            patch("status_watcher._send_webhook", return_value=True) as webhook,
            patch("status_watcher._save_cache"),
            patch("status_watcher._save_run_fail_cache"),
            patch("status_watcher._load_run_transition_cache", return_value={}),
            patch("status_watcher._load_run_fail_cache", return_value={}),
            patch("status_watcher.trigger_code_review_async") as trigger,
        ):
            status_watcher.poll_once(cache, "https://example.invalid/webhook")

        webhook.assert_not_called()
        trigger.assert_called_once()


if __name__ == "__main__":
    unittest.main()
