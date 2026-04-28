"""单元测试：task_context.py / dev_agent_runner.py / feedback_handler.py
以及 dispatch_bot.py 中的 #派给Agent 路由。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 把 multica-dingtalk-bridge 目录加到 sys.path
_BRIDGE = Path(__file__).parent.parent
if str(_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_BRIDGE))


# ─────────────────────────────────────────────────────────
# task_context
# ─────────────────────────────────────────────────────────

class TaskContextTests(unittest.TestCase):
    def _make_task(self, **kwargs):
        base = {
            "id": "UUM-1",
            "title": "登录页白屏",
            "description": "复现：iOS 17",
            "definition_of_done": ["打开登录页不白屏"],
            "category": "bug",
            "project_hint": "pm-system",
        }
        base.update(kwargs)
        return base

    def test_build_context_returns_string(self):
        from task_context import build_context
        ctx = build_context(self._make_task())
        self.assertIsInstance(ctx, str)
        self.assertIn("登录页白屏", ctx)
        self.assertIn("打开登录页不白屏", ctx)

    def test_build_context_contains_fixed_layer_filenames(self):
        from task_context import build_context, _FIXED_LAYER
        ctx = build_context(self._make_task())
        for path in _FIXED_LAYER:
            if path.exists():
                self.assertIn(path.name, ctx)

    def test_build_context_respects_max_bytes(self):
        from task_context import _MAX_CONTEXT_BYTES, build_context
        ctx = build_context(self._make_task())
        self.assertLessEqual(len(ctx.encode("utf-8")), _MAX_CONTEXT_BYTES + 100)

    def test_build_context_unknown_category_falls_back(self):
        from task_context import build_context
        ctx = build_context(self._make_task(category="xyz_unknown"))
        self.assertIn("UUM-1", ctx)

    def test_estimate_context_size_returns_dict(self):
        from task_context import estimate_context_size
        sizes = estimate_context_size(self._make_task())
        self.assertIsInstance(sizes, dict)
        self.assertTrue(all(isinstance(v, int) for v in sizes.values()))


# ─────────────────────────────────────────────────────────
# dev_agent_runner helpers
# ─────────────────────────────────────────────────────────

class DevAgentRunnerParseTests(unittest.TestCase):
    def test_parse_result_line_success(self):
        from dev_agent_runner import _parse_claude_result
        line = json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "[完成]\n修改文件：login.js\n摘要：添加了空值保护",
        })
        ok, summary = _parse_claude_result(line)
        self.assertTrue(ok)
        self.assertIn("空值保护", summary)

    def test_parse_result_line_error(self):
        from dev_agent_runner import _parse_claude_result
        line = json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "Not logged in",
        })
        ok, summary = _parse_claude_result(line)
        self.assertFalse(ok)

    def test_parse_result_empty(self):
        from dev_agent_runner import _parse_claude_result
        ok, summary = _parse_claude_result("")
        self.assertFalse(ok)
        self.assertEqual(summary, "(no output)")

    def test_parse_result_fallback_to_last_500(self):
        from dev_agent_runner import _parse_claude_result
        ok, summary = _parse_claude_result("some raw text output without json")
        self.assertTrue(ok)
        self.assertIn("raw text", summary)


class DevAgentEnqueueTests(unittest.TestCase):
    def test_enqueue_creates_file(self):
        from dev_agent_runner import enqueue_task
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp)
            task = {"id": "UUM-99", "title": "test task"}
            path = enqueue_task(task, queue_dir)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["id"], "UUM-99")
            self.assertEqual(data["status"], "pending")

    def test_enqueue_idempotent_overwrite(self):
        from dev_agent_runner import enqueue_task
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp)
            task = {"id": "UUM-1", "title": "first"}
            enqueue_task(task, queue_dir)
            task2 = {"id": "UUM-1", "title": "second"}
            path = enqueue_task(task2, queue_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["title"], "second")

    def test_load_pending_returns_only_pending(self):
        from dev_agent_runner import enqueue_task, load_pending_tasks
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp)
            enqueue_task({"id": "UUM-1", "title": "a"}, queue_dir)
            done_task = {"id": "UUM-2", "title": "b", "status": "done"}
            path2 = queue_dir / "UUM-2.json"
            path2.write_text(json.dumps(done_task), encoding="utf-8")

            pending = load_pending_tasks(queue_dir)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0][0]["id"], "UUM-1")


class DevAgentRunnerMockTests(unittest.TestCase):
    """使用 mock subprocess 验证 run_dev_agent 的主流程。"""

    def _make_task(self):
        return {
            "id": "UUM-7",
            "title": "测试任务",
            "description": "测试描述",
            "definition_of_done": ["验收：测试通过"],
            "category": "bug",
            "project_hint": "",
        }

    def _mock_proc(self, returncode=0, stdout="", stderr=""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def _claude_success_output(self):
        return json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "[完成]\n修改文件：foo.py\n摘要：修好了",
        })

    def test_worktree_path_is_per_task(self):
        from dev_agent_runner import _worktree_path

        self.assertEqual(_worktree_path("UUM-7").name, "UUM-7")
        self.assertIn(".worktrees", str(_worktree_path("UUM-7")))

    def test_ensure_worktree_uses_git_worktree_add(self):
        from dev_agent_runner import _ensure_worktree

        calls = []

        def fake_git(args, **kwargs):
            calls.append((args, kwargs))
            if args[:3] == ["worktree", "list", "--porcelain"]:
                return self._mock_proc(returncode=0, stdout="")
            return self._mock_proc(returncode=0, stdout="")

        with patch("dev_agent_runner._git", side_effect=fake_git):
            path = _ensure_worktree("UUM-7", "agent/UUM-7")

        self.assertEqual(path.name, "UUM-7")
        self.assertIn((["worktree", "add", "-b", "agent/UUM-7", str(path), "main"], {"timeout": 60}), calls)

    def test_ensure_worktree_refuses_existing_path_for_other_branch(self):
        from dev_agent_runner import _ensure_worktree

        def fake_git(args, **kwargs):
            if args[:3] == ["worktree", "list", "--porcelain"]:
                return self._mock_proc(
                    returncode=0,
                    stdout="worktree D:/MyAgents/.worktrees/UUM-7\nbranch refs/heads/agent/OTHER\n",
                )
            return self._mock_proc(returncode=0, stdout="")

        with patch("dev_agent_runner._git", side_effect=fake_git):
            with self.assertRaises(RuntimeError):
                _ensure_worktree("UUM-7", "agent/UUM-7")

    def test_run_dev_agent_success(self):
        from dev_agent_runner import run_dev_agent

        good_git = self._mock_proc(returncode=0, stdout="")
        worktree = Path(r"D:\MyAgents\.worktrees\UUM-7")

        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "UUM-7.json"
            import json as _json
            task_path.write_text(_json.dumps(self._make_task()), encoding="utf-8")

            with patch("dev_agent_runner._ensure_worktree", return_value=worktree):
                with patch("dev_agent_runner._call_claude", side_effect=[
                    (True, self._claude_success_output()),
                    (True, "[完成]\n修改文件：foo.py\n摘要：修好了"),
                ]) as call_claude:
                    with patch("dev_agent_runner._git", return_value=good_git):
                        with patch("task_context.build_eval_context", return_value="eval prompt"):
                            with patch("task_context.build_sub_task_context", return_value="sub prompt"):
                                with patch("feedback_handler.notify_agent_done"):
                                    with patch("feedback_handler.notify_eval_split"):
                                        with patch("feedback_handler.notify_agent_started"):
                                            with patch("feedback_handler.notify_sub_task_done"):
                                                result = run_dev_agent(self._make_task(), task_path)

        self.assertTrue(result.success)
        self.assertIn("修好了", result.summary)
        self.assertEqual(result.task_id, "UUM-7")
        self.assertEqual(result.worktree_path, str(worktree))
        self.assertEqual(call_claude.call_args_list[-1].kwargs["cwd"], worktree)

    def test_run_dev_agent_git_branch_fail(self):
        from dev_agent_runner import run_dev_agent

        with patch("dev_agent_runner._call_claude", return_value=(True, self._claude_success_output())):
            with patch("dev_agent_runner._ensure_worktree", side_effect=RuntimeError("branch already exists")):
                with patch("task_context.build_eval_context", return_value="eval prompt"):
                    result = run_dev_agent(self._make_task())

        self.assertFalse(result.success)
        self.assertIn("worktree prepare failed", result.error)

    def test_run_dev_agent_timeout(self):
        from dev_agent_runner import run_dev_agent

        with patch("dev_agent_runner._call_claude", side_effect=[
            (True, self._claude_success_output()),
            (False, "(timeout after 600s)"),
        ]):
            with patch("dev_agent_runner._ensure_worktree", return_value=Path(r"D:\MyAgents\.worktrees\UUM-7")):
                with patch("dev_agent_runner._git", return_value=self._mock_proc(returncode=0, stdout="")):
                    with patch("task_context.build_eval_context", return_value="eval prompt"):
                        with patch("task_context.build_sub_task_context", return_value="sub prompt"):
                            result = run_dev_agent(self._make_task())

        self.assertFalse(result.success)
        self.assertIn("timeout", result.summary)


# ─────────────────────────────────────────────────────────
# feedback_handler
# ─────────────────────────────────────────────────────────

class FeedbackHandlerFormatTests(unittest.TestCase):
    def _make_result(self, success=True):
        from dev_agent_runner import AgentRunResult
        return AgentRunResult(
            task_id="UUM-42",
            branch="agent/UUM-42",
            success=success,
            summary="[完成]\n修改文件：login.js\n摘要：添加了空值保护",
            files_changed=["pm-system/ui/login.js"],
            worktree_path=r"D:\MyAgents\.worktrees\UUM-42",
            duration_seconds=45.2,
        )

    def _make_task(self):
        return {
            "id": "UUM-42",
            "title": "登录页白屏",
            "definition_of_done": ["打开登录页不白屏"],
        }

    def test_format_notification_success(self):
        from feedback_handler import _format_notification
        title, body = _format_notification(self._make_result(success=True), self._make_task())
        self.assertIn("完成", title)
        self.assertIn("UUM-42", title)
        self.assertIn("agent/UUM-42", body)
        self.assertIn(r"D:\MyAgents\.worktrees\UUM-42", body)
        self.assertIn("login.js", body)

    def test_format_notification_failure(self):
        from feedback_handler import _format_notification
        r = self._make_result(success=False)
        r.error = "git checkout failed"
        title, body = _format_notification(r, self._make_task())
        self.assertIn("未完成", title)

    def test_notify_no_webhook_returns_false(self):
        from feedback_handler import notify_agent_done
        with patch("feedback_handler._load_webhook_url", return_value=""):
            result = self._make_result()
            ok = notify_agent_done(result, self._make_task(), webhook_url="")
            self.assertFalse(ok)

    def test_notify_sends_webhook(self):
        from feedback_handler import notify_agent_done
        with patch("feedback_handler._send_webhook", return_value=True) as mock_send:
            result = self._make_result()
            ok = notify_agent_done(result, self._make_task(), webhook_url="https://fake.webhook/")
            self.assertTrue(ok)
            mock_send.assert_called_once()


# ─────────────────────────────────────────────────────────
# dispatch_bot routing (#派给Agent)
# ─────────────────────────────────────────────────────────

class DispatchAgentRouteTests(unittest.TestCase):
    def test_strip_dispatch_to_agent_prefix_hash(self):
        from dispatch_bot import _strip_dispatch_to_agent_prefix
        self.assertEqual(_strip_dispatch_to_agent_prefix("#派给Agent UUM-42"), "UUM-42")

    def test_strip_dispatch_to_agent_prefix_no_hash(self):
        from dispatch_bot import _strip_dispatch_to_agent_prefix
        self.assertEqual(_strip_dispatch_to_agent_prefix("派给Agent UUM-10"), "UUM-10")

    def test_strip_dispatch_to_agent_prefix_none_for_other(self):
        from dispatch_bot import _strip_dispatch_to_agent_prefix
        self.assertIsNone(_strip_dispatch_to_agent_prefix("派单 登录页白屏"))
        self.assertIsNone(_strip_dispatch_to_agent_prefix("查工单"))

    def test_classify_dispatch_agent(self):
        from dispatch_bot import classify_incoming_text
        self.assertEqual(classify_incoming_text("#派给Agent UUM-99"), "dispatch_agent")
        self.assertEqual(classify_incoming_text("派给Agent UUM-5"), "dispatch_agent")

    def test_classify_dispatch_agent_does_not_beat_delete(self):
        """删除命令仍优先于 dispatch_agent。"""
        from dispatch_bot import classify_incoming_text
        self.assertEqual(classify_incoming_text("删除派单 UUM-1"), "cancel_issue")

    def test_at_prefix_normalize_for_dispatch_agent(self):
        from dispatch_bot import _normalize_dingtalk_at_prefixes
        r = _normalize_dingtalk_at_prefixes("@机器人 #派给Agent UUM-3")
        self.assertEqual(r, "#派给Agent UUM-3")


# ─────────────────────────────────────────────────────────
# patrol_scheduler helpers
# ─────────────────────────────────────────────────────────

class PatrolSchedulerTests(unittest.TestCase):
    def _make_issue(self, status="todo", labels=None, has_dod=True):
        issue = {
            "identifier": "UUM-1",
            "title": "test",
            "status": status,
            "stateType": "unstarted",
            "labels": labels or [],
            "description": "验收：测试通过" if has_dod else "no dod here",
        }
        return issue

    def test_is_agent_ready_with_label(self):
        from patrol_scheduler import _is_agent_ready
        self.assertTrue(_is_agent_ready(self._make_issue(labels=["agent-ready"])))
        self.assertFalse(_is_agent_ready(self._make_issue(labels=[])))

    def test_has_dod_from_description(self):
        from patrol_scheduler import _has_dod
        self.assertTrue(_has_dod(self._make_issue(has_dod=True)))
        self.assertFalse(_has_dod(self._make_issue(has_dod=False)))

    def test_is_already_queued_not_exists(self):
        from patrol_scheduler import _is_already_queued
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_is_already_queued("UUM-99", Path(tmp)))

    def test_is_already_queued_pending(self):
        from patrol_scheduler import _is_already_queued
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp)
            (queue_dir / "UUM-99.json").write_text(
                json.dumps({"status": "pending"}), encoding="utf-8"
            )
            self.assertTrue(_is_already_queued("UUM-99", queue_dir))

    def test_is_already_queued_done_allows_re_dispatch(self):
        from patrol_scheduler import _is_already_queued
        with tempfile.TemporaryDirectory() as tmp:
            queue_dir = Path(tmp)
            (queue_dir / "UUM-99.json").write_text(
                json.dumps({"status": "done"}), encoding="utf-8"
            )
            self.assertFalse(_is_already_queued("UUM-99", queue_dir))

    def test_build_task_extracts_dod_from_description(self):
        from patrol_scheduler import _build_task
        issue = {
            "identifier": "UUM-5",
            "title": "fix bug",
            "description": "something\n验收：测试通过\n验收：无报错",
        }
        task = _build_task(issue)
        self.assertEqual(task["id"], "UUM-5")
        self.assertIn("测试通过", task["definition_of_done"])


if __name__ == "__main__":
    unittest.main()
