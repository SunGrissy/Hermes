import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from multica_client import MulticaClient, build_issue_create_args, infer_project_id


class FakeProc:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        communicate_error: BaseException | None = None,
    ):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.communicate_error = communicate_error
        self.killed = False
        self.waited = False

    async def communicate(self):
        if self.communicate_error:
            raise self.communicate_error
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        return self.returncode


class MulticaClientTests(unittest.TestCase):
    def test_build_issue_create_args_without_project(self):
        args = build_issue_create_args(
            title="修复筛选",
            description="验收：筛选结果正确",
            priority="medium",
            status="todo",
            project_id="",
        )
        self.assertEqual(
            args,
            [
                "issue",
                "create",
                "--title",
                "修复筛选",
                "--description",
                "验收：筛选结果正确",
                "--priority",
                "medium",
                "--status",
                "todo",
                "--output",
                "json",
            ],
        )

    def test_build_issue_create_args_with_project(self):
        args = build_issue_create_args(
            title="修复筛选",
            description="验收：筛选结果正确",
            priority="high",
            status="todo",
            project_id="project-123",
        )
        self.assertEqual(args[-2:], ["--project", "project-123"])

    def test_infer_project_id_prefers_explicit_env(self):
        project_id = infer_project_id(
            title="PmSystem 任务",
            description="",
            env={
                "MULTICA_PROJECT_ID": "explicit-project",
                "MULTICA_PROJECT_MAP_JSON": '{"projects":{"pm-system":{"id":"pm-project","aliases":["pmsystem"]}}}',
            },
        )

        self.assertEqual(project_id, "explicit-project")

    def test_infer_project_id_uses_project_map_aliases(self):
        project_id = infer_project_id(
            title="Feature 批量维护 API",
            description="范围：PmSystem 后端",
            env={
                "MULTICA_PROJECT_MAP_JSON": '{"projects":{"pm-system":{"id":"pm-project","aliases":["pmsystem","feature"]}}}',
            },
        )

        self.assertEqual(project_id, "pm-project")

    @patch.dict(os.environ, {"MULTICA_BIN": r"C:\\Tools\\multica.exe"})
    @patch("pathlib.Path.is_file", return_value=True)
    def test_resolve_binary_prefers_env(self, _is_file):
        client = MulticaClient()
        self.assertTrue(client.resolve_binary().endswith("multica.exe"))

    @patch.dict(os.environ, {"MULTICA_EXECUTABLE": r"C:\\Tools\\multica-exec.exe"})
    @patch("pathlib.Path.is_file", return_value=True)
    def test_resolve_binary_prefers_executable_env(self, _is_file):
        client = MulticaClient()
        self.assertTrue(client.resolve_binary().endswith("multica-exec.exe"))

    @patch("shutil.which")
    def test_resolve_binary_uses_injected_path(self, which):
        path_value = r"C:\\Injected\\Bin"
        which.side_effect = [None, r"C:\\Injected\\Bin\\multica.exe"]

        client = MulticaClient(env={"PATH": path_value})

        self.assertEqual(client.resolve_binary(), r"C:\\Injected\\Bin\\multica.exe")
        which.assert_any_call("multica", path=path_value)
        which.assert_any_call("multica.exe", path=path_value)


class MulticaClientRunJsonTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_json_success_json_dict(self):
        proc = FakeProc(stdout=b'{"id": "issue-1"}')
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value="multica"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            create_proc.return_value = proc
            result = await client.run_json(["issue", "list"])

        self.assertTrue(result.ok)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.data, {"id": "issue-1"})

    async def test_run_json_nonzero_exit_code(self):
        proc = FakeProc(returncode=2, stdout=b"", stderr=b"bad args")
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value="multica"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            create_proc.return_value = proc
            result = await client.run_json(["issue", "list"])

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "bad args")

    async def test_run_json_invalid_json(self):
        proc = FakeProc(stdout=b"not-json")
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value="multica"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            create_proc.return_value = proc
            result = await client.run_json(["issue", "list"])

        self.assertFalse(result.ok)
        self.assertEqual(result.stderr, "failed to parse multica JSON output")

    async def test_run_json_json_not_object(self):
        proc = FakeProc(stdout=b'["issue-1"]')
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value="multica"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            create_proc.return_value = proc
            result = await client.run_json(["issue", "list"])

        self.assertFalse(result.ok)
        self.assertEqual(result.stderr, "multica JSON output was not an object")

    async def test_run_json_binary_not_found(self):
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value=None),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            result = await client.run_json(["issue", "list"])

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stderr, "multica binary not found")
        create_proc.assert_not_called()

    async def test_run_json_start_failure(self):
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value="multica"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            create_proc.side_effect = OSError("permission denied")
            result = await client.run_json(["issue", "list"])

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 126)
        self.assertIn("failed to start multica: permission denied", result.stderr)

    async def test_run_json_timeout_kills_process(self):
        proc = FakeProc(communicate_error=asyncio.TimeoutError())
        client = MulticaClient(env={})

        with (
            patch.object(client, "resolve_binary", return_value="multica"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as create_proc,
        ):
            create_proc.return_value = proc
            result = await client.run_json(["issue", "list"], timeout_seconds=0.01)

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stderr, "multica command timed out")
        self.assertTrue(proc.killed)
        self.assertTrue(proc.waited)


if __name__ == "__main__":
    unittest.main()
