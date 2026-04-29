#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Multica 待审查工单交给 Hermes profile 执行代码审查。"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

LOG = logging.getLogger("hermes-review-dispatcher")


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _default_hermes_home() -> Path:
    return Path(os.environ.get("HERMES_REVIEW_HOME") or os.environ.get("HERMES_HOME") or r"D:\hermes")


def _default_agent_root(hermes_home: Path) -> Path:
    configured = os.environ.get("HERMES_REVIEW_AGENT_ROOT", "").strip()
    if configured:
        return Path(configured)
    return hermes_home / "hermes-agent"


@dataclass(frozen=True)
class HermesReviewConfig:
    enabled: bool
    hermes_home: Path
    agent_root: Path
    python_bin: str
    max_turns: int
    timeout_s: int
    send_timeout_s: int
    target: str
    daemon_cid: str
    daemon_url: str

    @classmethod
    def from_env(cls) -> "HermesReviewConfig":
        hermes_home = _default_hermes_home()
        return cls(
            enabled=_is_truthy(os.environ.get("HERMES_REVIEW_ENABLED", "")),
            hermes_home=hermes_home,
            agent_root=_default_agent_root(hermes_home),
            python_bin=os.environ.get("HERMES_REVIEW_PYTHON", "py").strip() or "py",
            max_turns=int(os.environ.get("HERMES_REVIEW_MAX_TURNS", "40")),
            timeout_s=int(os.environ.get("HERMES_REVIEW_TIMEOUT", "1800")),
            send_timeout_s=int(os.environ.get("HERMES_REVIEW_SEND_TIMEOUT", "90")),
            target=os.environ.get("HERMES_REVIEW_DINGTALK_TARGET", "").strip(),
            daemon_cid=os.environ.get("HERMES_REVIEW_DAEMON_CID", "").strip(),
            daemon_url=os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200").rstrip("/"),
        )

    @property
    def agent_entry(self) -> Path:
        return self.agent_root / "run_agent.py"


def _issue_id(issue: dict) -> str:
    return str(issue.get("identifier") or issue.get("id") or "").strip()


def build_review_prompt(issue: dict, prev_status: str, curr_status: str) -> str:
    issue_id = _issue_id(issue) or "UNKNOWN"
    title = str(issue.get("title") or issue.get("name") or issue_id)
    payload = json.dumps(issue, ensure_ascii=False, indent=2)
    return f"""请使用 multica-code-review skill 审查 Multica 工单 {issue_id}。

上下文：
- 工单状态刚从 {prev_status} 进入 {curr_status}
- 工单标题：{title}
- 本地仓库：D:/MyAgents
- 优先检查分支：agent/{issue_id}

审查边界：
- 只做代码审查，不修改文件，不提交，不推送，不改变 Multica 状态。
- 如无法定位分支或变更，报告阻塞原因和下一步需要的信息。
- 输出中文审查报告，先列问题，按严重程度排序；若无问题，明确说未发现阻塞项，并列出测试缺口。

工单原始 JSON：
```json
{payload}
```
"""


def extract_final_response(stdout: str) -> str:
    marker = "🎯 FINAL RESPONSE:"
    if marker not in stdout:
        return stdout.strip()
    tail = stdout.split(marker, 1)[1]
    for end_marker in ("\n💾 Sample", "\n👋 Agent execution completed!"):
        if end_marker in tail:
            tail = tail.split(end_marker, 1)[0]
    return tail.strip(" \n-")


def _post_review_comment(issue_id: str, report: str) -> bool:
    """将审查结果写回 Multica 工单评论。"""
    multica = shutil.which("multica") or "multica"
    try:
        result = subprocess.run(
            [multica, "issue", "comment", "add", issue_id,
             "--content", report, "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("post review comment failed for %s: %s", issue_id, exc)
        return False
    if result.returncode != 0:
        LOG.warning("post review comment failed for %s: %s", issue_id, result.stderr[-300:])
        return False
    LOG.info("review comment posted for %s", issue_id)
    return True



def _notify_review_done_safe(
    issue_id: str, report: str, backend: str, *, issue_title: str | None = None
) -> None:
    try:
        from status_watcher import notify_review_done

        notify_review_done(issue_id, report, backend, issue_title=issue_title)
    except Exception:
        pass

class HermesReviewDispatcher:
    def __init__(self, config: HermesReviewConfig | None = None):
        self.config = config or HermesReviewConfig.from_env()

    def dispatch(self, issue: dict, prev_status: str, curr_status: str) -> bool:
        if not self.config.enabled:
            LOG.debug("Hermes review disabled")
            return False
        if not self.config.agent_entry.exists():
            LOG.warning("Hermes run_agent.py not found: %s", self.config.agent_entry)
            return False

        issue_id = _issue_id(issue) or "UNKNOWN"
        issue_title = str(issue.get("title") or issue.get("name") or issue_id)
        prompt = build_review_prompt(issue, prev_status, curr_status)
        env = os.environ.copy()
        env["HERMES_HOME"] = str(self.config.hermes_home)
        env.setdefault("PYTHONIOENCODING", "utf-8")

        cmd = [
            self.config.python_bin,
            str(self.config.agent_entry),
            "--query",
            prompt,
            "--max_turns",
            str(self.config.max_turns),
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.config.agent_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.timeout_s,
            )
        except subprocess.TimeoutExpired:
            LOG.warning("Hermes review timed out: %s", issue_id)
            return False
        except OSError as exc:
            LOG.warning("Hermes review failed to start: %s", exc)
            return False

        if result.returncode != 0:
            LOG.warning("Hermes review failed: %s", (result.stderr or result.stdout)[-500:])
            return False

        report = extract_final_response(result.stdout)
        if not report:
            LOG.warning("Hermes review produced empty report: %s", issue_id)
            return False

        # ── 写回 Multica 评论 ───────────────────────────────────────────
        _post_review_comment(issue_id, report)
        # ── 审查完毕 webhook 通知 ──────────────────────────────────────
        _notify_review_done_safe(issue_id, report, "hermes", issue_title=issue_title)

        if self.config.daemon_cid:
            return self._send_via_dingtalk_daemon(issue_id, report)

        if self.config.target:
            return self._send_report(issue_id, report, env)

        LOG.info("Hermes review finished without delivery target: %s", issue_id)
        return True

    def _send_via_dingtalk_daemon(self, issue_id: str, report: str) -> bool:
        message = f"【Multica 代码审查】{issue_id}\n\n{report} 🤖"
        payload = json.dumps(
            {"cid": self.config.daemon_cid, "message": message},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.daemon_url}/send",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.send_timeout_s) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except OSError as exc:
            LOG.warning("DingTalk daemon delivery failed: %s", exc)
            return False
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        if not data.get("success"):
            LOG.warning("DingTalk daemon delivery returned error: %s", body[-500:])
            return False
        LOG.info("Hermes review delivered via DingTalk daemon: %s", issue_id)
        return True

    def _send_report(self, issue_id: str, report: str, env: dict[str, str]) -> bool:
        message = f"【Multica 代码审查】{issue_id}\n\n{report}"
        with NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
            tmp.write(message)
            report_path = tmp.name
        script = (
            "import sys; "
            "from pathlib import Path; "
            "from tools.send_message_tool import send_message_tool; "
            "msg = Path(sys.argv[2]).read_text(encoding='utf-8'); "
            "print(send_message_tool({'action':'send','target':sys.argv[1],'message':msg}))"
        )
        try:
            result = subprocess.run(
                [self.config.python_bin, "-c", script, self.config.target, report_path],
                cwd=str(self.config.agent_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.send_timeout_s,
            )
        finally:
            try:
                Path(report_path).unlink(missing_ok=True)
            except OSError:
                pass

        if result.returncode != 0:
            LOG.warning("Hermes review delivery failed: %s", (result.stderr or result.stdout)[-500:])
            return False
        if '"error"' in (result.stdout or "").lower():
            LOG.warning("Hermes review delivery returned error: %s", result.stdout[-500:])
            return False
        LOG.info("Hermes review delivered: %s", issue_id)
        return True


def trigger_hermes_review_async(issue: dict, prev_status: str, curr_status: str) -> None:
    dispatcher = HermesReviewDispatcher()
    if not dispatcher.config.enabled:
        LOG.debug("Hermes review disabled, skip async trigger")
        return
    issue_id = _issue_id(issue) or "UNKNOWN"
    thread = threading.Thread(
        target=dispatcher.dispatch,
        args=(issue, prev_status, curr_status),
        daemon=True,
        name=f"hermes-review-{issue_id}",
    )
    thread.start()
