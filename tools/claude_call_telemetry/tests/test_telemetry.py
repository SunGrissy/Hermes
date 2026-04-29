# -*- coding: utf-8 -*-
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_TOOLS = Path(__file__).resolve().parent.parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from claude_call_telemetry.telemetry import (  # noqa: E402
    call_claude_with_telemetry,
    next_call_index,
    parse_token_usage_from_claude_stdout,
    scan_dangerous_keywords,
)


class TelemetryTests(unittest.TestCase):
    def test_scan_dangerous_keywords_git_reset(self):
        hits = scan_dangerous_keywords("Please run git reset --hard on main")
        self.assertIn("git reset --hard", hits)

    def test_parse_token_usage(self):
        stdout = (
            '{"type":"message","usage":{"input_tokens":10,"output_tokens":20}}\n'
        )
        pin, pout = parse_token_usage_from_claude_stdout(stdout)
        self.assertEqual(pin, 10)
        self.assertEqual(pout, 20)

    def test_next_call_index_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "calls-2099-01-01.jsonl"
            p.write_text(
                json.dumps({"task_id": "t1", "call_index": 1}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(next_call_index(p, "t1"), 2)
            self.assertEqual(next_call_index(p, "t2"), 1)

    def test_call_claude_with_telemetry_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            completed = subprocess.CompletedProcess(
                args=["claude"],
                returncode=0,
                stdout='{"usage":{"input_tokens":5,"output_tokens":7}}\n',
                stderr="",
            )
            with patch("claude_call_telemetry.telemetry.subprocess.run", return_value=completed):
                r = call_claude_with_telemetry(
                    cmd=["claude", "--print", "hello"],
                    cwd=Path(tmp),
                    env={},
                    timeout=30,
                    task_id="task-ut-1",
                    caller="test.unit",
                    task_title="unit title",
                    log_dir=log_dir,
                    call_index=1,
                )
            self.assertEqual(r.returncode, 0)
            files = list(log_dir.glob("calls-*.jsonl"))
            self.assertEqual(len(files), 1)
            line = files[0].read_text(encoding="utf-8").strip()
            rec = json.loads(line)
            self.assertEqual(rec["task_id"], "task-ut-1")
            self.assertEqual(rec["call_index"], 1)
            self.assertEqual(rec["caller"], "test.unit")
            self.assertEqual(rec["task_title"], "unit title")
            self.assertEqual(rec["status"], "ok")
            self.assertEqual(rec["prompt_tokens"], 5)
            self.assertEqual(rec["output_tokens"], 7)

    def test_timeout_writes_then_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)

            def boom(*_a, **_k):
                raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

            with patch("claude_call_telemetry.telemetry.subprocess.run", side_effect=boom):
                with self.assertRaises(subprocess.TimeoutExpired):
                    call_claude_with_telemetry(
                        cmd=["claude", "x"],
                        cwd=Path(tmp),
                        env={},
                        timeout=1,
                        task_id="task-timeout",
                        caller="test.unit",
                        log_dir=log_dir,
                        call_index=1,
                    )
            files = list(log_dir.glob("calls-*.jsonl"))
            self.assertEqual(len(files), 1)
            rec = json.loads(files[0].read_text(encoding="utf-8").strip())
            self.assertEqual(rec["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
