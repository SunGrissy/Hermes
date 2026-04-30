import json
import subprocess
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from code_review_dispatcher import (
    CodeReviewConfig,
    CodeReviewDispatcher,
    _is_review_passed,
    build_review_prompt,
    extract_review_output,
    resolve_platform_review_workdir,
    resolve_platform_run_workdir,
    resolve_review_workdir,
    trigger_code_review_async,
)


class CodeReviewDispatcherTests(unittest.TestCase):
    def test_disabled_trigger_does_not_start_thread(self):
        with (
            patch.dict("os.environ", {"CODE_REVIEW_ENABLED": "0"}, clear=False),
            patch("code_review_dispatcher.threading.Thread") as thread_cls,
        ):
            trigger_code_review_async({"identifier": "UUM-42"}, "in_progress", "In Review")

        thread_cls.assert_not_called()

    def test_build_review_prompt_targets_claude_reviewer(self):
        prompt = build_review_prompt(
            {"identifier": "UUM-42", "title": "登录页白屏"},
            "in_progress",
            "In Review",
        )

        self.assertIn("UUM-42", prompt)
        self.assertIn("code-reviewer", prompt)
        self.assertIn("只读代码审查", prompt)
        self.assertIn("agent/UUM-42", prompt)
        self.assertIn(".worktrees/UUM-42", prompt)
        self.assertIn("Multica 平台 run work_dir", prompt)

    def test_extract_review_output_prefers_claude_result_json(self):
        stdout = 'noise\n{"type":"result","result":"审查报告正文"}\n'

        self.assertEqual(extract_review_output(stdout), "审查报告正文")

    def test_dispatch_runs_configured_claude_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            worktree = repo_root / ".worktrees" / "UUM-42"
            worktree.mkdir(parents=True)
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=repo_root,
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=("--print", "--output-format", "json"),
            )

            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"type":"result","result":"OK"}',
                stderr="",
            )
            with (
                patch("code_review_dispatcher._post_review_comment", return_value=True),
                patch("code_review_dispatcher._mark_issue_done", return_value=True) as mark_done,
                patch("code_review_dispatcher._notify_review_done_safe"),
                patch("code_review_dispatcher.resolve_platform_run_workdir", return_value=None),
                patch("code_review_dispatcher.call_claude_with_telemetry", return_value=completed) as run,
            ):
                self.assertTrue(CodeReviewDispatcher(cfg).dispatch({"identifier": "UUM-42"}, "a", "b"))
                mark_done.assert_not_called()

        cmd = run.call_args.kwargs["cmd"]
        self.assertEqual(cmd[:4], ["claude", "--print", "--output-format", "json"])
        self.assertEqual(Path(run.call_args.kwargs["cwd"]), worktree)

    def test_dispatch_marks_done_when_review_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            worktree = repo_root / ".worktrees" / "UUM-42"
            worktree.mkdir(parents=True)
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=repo_root,
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=("--print", "--output-format", "json"),
            )
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"type":"result","result":"审查通过：仅低风险建议，可合并"}',
                stderr="",
            )
            with (
                patch("code_review_dispatcher._post_review_comment", return_value=True),
                patch("code_review_dispatcher._mark_issue_done", return_value=True) as mark_done,
                patch("code_review_dispatcher._notify_review_done_safe"),
                patch("code_review_dispatcher.resolve_platform_run_workdir", return_value=None),
                patch("code_review_dispatcher.call_claude_with_telemetry", return_value=completed),
            ):
                self.assertTrue(CodeReviewDispatcher(cfg).dispatch({"identifier": "UUM-42"}, "a", "b"))
                mark_done.assert_called_once_with(cfg, "UUM-42")

    def test_review_passed_heuristic(self):
        self.assertTrue(_is_review_passed("未发现阻塞项，低风险建议"))
        self.assertTrue(_is_review_passed("审查通过，可以合并"))
        self.assertFalse(_is_review_passed("存在阻塞项，必须修复后再合并"))
        self.assertFalse(_is_review_passed(""))

    def test_resolve_review_workdir_falls_back_to_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=repo_root,
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=(),
            )
            with patch("code_review_dispatcher.resolve_platform_run_workdir", return_value=None):
                self.assertEqual(resolve_review_workdir(cfg, "UUM-404"), repo_root)

    def test_resolve_review_workdir_uses_platform_run_workdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            platform_workdir = Path(tmp) / "platform" / "workdir"
            platform_repo = platform_workdir / "pm-system"
            repo_root.mkdir()
            (platform_repo / ".git").mkdir(parents=True)
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=repo_root,
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=(),
            )
            with patch(
                "code_review_dispatcher.resolve_platform_run_workdir",
                return_value=platform_workdir,
            ):
                self.assertEqual(resolve_review_workdir(cfg, "UUM-42"), platform_repo)

    def test_resolve_review_workdir_prefers_platform_repo_over_local_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            local_worktree = repo_root / ".worktrees" / "UUM-42"
            platform_workdir = Path(tmp) / "platform" / "workdir"
            platform_repo = platform_workdir / "pm-system"
            local_worktree.mkdir(parents=True)
            (platform_repo / ".git").mkdir(parents=True)
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=repo_root,
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=(),
            )
            with patch(
                "code_review_dispatcher.resolve_platform_run_workdir",
                return_value=platform_workdir,
            ):
                self.assertEqual(resolve_review_workdir(cfg, "UUM-42"), platform_repo)

    def test_resolve_platform_review_workdir_ignores_plain_platform_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            platform_workdir = Path(tmp) / "platform" / "workdir"
            platform_workdir.mkdir(parents=True)
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=Path(tmp),
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=(),
            )
            with patch(
                "code_review_dispatcher.resolve_platform_run_workdir",
                return_value=platform_workdir,
            ):
                self.assertIsNone(resolve_platform_review_workdir(cfg, "UUM-42"))

    def test_resolve_platform_run_workdir_reads_latest_run_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            platform_workdir = Path(tmp) / "workdir"
            platform_workdir.mkdir()
            cfg = CodeReviewConfig(
                enabled=True,
                command="claude",
                repo_root=Path(tmp),
                multica_bin="multica",
                timeout_s=1,
                send_timeout_s=1,
                daemon_cid="",
                daemon_url="http://127.0.0.1:19200",
                extra_args=(),
            )
            stdout = json.dumps([{"result": {"work_dir": str(platform_workdir)}}])
            completed = unittest.mock.Mock(
                returncode=0,
                stdout=stdout,
                stderr="",
            )
            with patch("code_review_dispatcher.subprocess.run", return_value=completed):
                self.assertEqual(resolve_platform_run_workdir(cfg, "UUM-42"), platform_workdir)

    def test_daemon_delivery_accepts_success_json(self):
        cfg = CodeReviewConfig(
            enabled=True,
            command="claude",
            repo_root=Path(r"D:\MyAgents"),
            multica_bin="multica",
            timeout_s=1,
            send_timeout_s=1,
            daemon_cid="cid-1",
            daemon_url="http://127.0.0.1:19200",
            extra_args=(),
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"success":true}'

        with patch("code_review_dispatcher.urllib.request.urlopen", return_value=FakeResponse()):
            self.assertTrue(CodeReviewDispatcher(cfg)._send_via_dingtalk_daemon("UUM-42", "报告"))


if __name__ == "__main__":
    unittest.main()
