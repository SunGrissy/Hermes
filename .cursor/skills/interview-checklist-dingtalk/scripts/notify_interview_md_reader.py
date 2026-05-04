# -*- coding: utf-8 -*-
"""
面试清单生成后：拼 md-reader 局域网直链（含 ?path=），经 Webhook 发到助理通知群。
依赖：send_result_webhook.py（DINGTALK_WEBHOOK_KEY=interview_checklist，空则回退 default）。
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path


def _workspace_root() -> Path:
    here = Path(__file__).resolve().parent
    return (here / ".." / ".." / ".." / "..").resolve()


def _guess_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        s.connect(("203.0.113.1", 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


def _rel_under_workspace(abs_md: Path, workspace: Path) -> str:
    try:
        rel = abs_md.resolve().relative_to(workspace.resolve())
    except ValueError as e:
        raise SystemExit(
            f"error: file not under workspace root:\n  {abs_md}\n  root: {workspace}"
        ) from e
    return rel.as_posix()


def _infer_role_from_readme(md_path: Path) -> str:
    """同目录 README.md 中「- 目标岗位：xxx」"""
    readme = md_path.parent / "README.md"
    if not readme.is_file():
        return ""
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for raw in text.splitlines():
        s = raw.strip()
        for sep in ("- 目标岗位：", "- 目标岗位:"):
            if s.startswith(sep):
                return s[len(sep) :].strip()
    return ""


def _build_body(
    rel_path: str,
    reader_url: str,
    agent: str,
    role: str,
) -> str:
    lines = [
        "## 面试清单已生成",
        "",
    ]
    if role.strip():
        lines.append(f"**面试岗位**：{role.strip()}")
        lines.append("")
    lines.extend(
        [
            f"- **文件**：`{rel_path}`",
            f"- **md-reader**：[{reader_url}]({reader_url})",
            "",
        ]
    )
    if agent.strip():
        lines.append(f"本会话代号：**{agent.strip()}**")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send interview checklist md-reader link to DingTalk")
    parser.add_argument(
        "md_file",
        help="面试清单 .md 的绝对路径或相对工作区根的路径",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MD_READER_PUBLIC_HOST", "").strip(),
        help="md-reader 访问用 IP（默认自动探测局域网 IP，可用环境变量 MD_READER_PUBLIC_HOST）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MD_READER_PORT", "8899")),
        help="md-reader 端口（默认 8899）",
    )
    parser.add_argument(
        "--agent",
        default=os.environ.get("AGENT_SESSION_CODE", "").strip(),
        help="本会话 Agent 代号，写入正文（也可用环境变量 AGENT_SESSION_CODE）",
    )
    parser.add_argument(
        "--role",
        default=os.environ.get("INTERVIEW_ROLE", "").strip(),
        help="候选人面试岗位；不写则尝试从同目录 README.md「目标岗位」推断",
    )
    args = parser.parse_args()

    workspace = _workspace_root()
    md_arg = Path(args.md_file)
    abs_md = md_arg if md_arg.is_absolute() else (workspace / md_arg)
    if not abs_md.is_file():
        print(f"error: not a file: {abs_md}", file=sys.stderr)
        return 1

    rel_path = _rel_under_workspace(abs_md, workspace)
    host = args.host.strip() or _guess_lan_ip()
    q = urllib.parse.urlencode({"path": rel_path})
    reader_url = f"http://{host}:{args.port}/?{q}"

    role = args.role.strip() or _infer_role_from_readme(abs_md)
    body = _build_body(rel_path, reader_url, args.agent, role)

    webhook_script = workspace / ".cursor" / "skills" / "dingtalk-actions" / "scripts" / "send_result_webhook.py"
    if not webhook_script.is_file():
        print(f"error: missing {webhook_script}", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".md",
        delete=False,
    ) as tmp:
        tmp.write(body)
        tmp_path = tmp.name

    env = os.environ.copy()
    env["DINGTALK_WEBHOOK_KEY"] = "interview_checklist"
    env["DINGTALK_TITLE"] = "面试清单-md-reader"

    try:
        r = subprocess.run(
            [sys.executable, str(webhook_script), tmp_path],
            env=env,
            cwd=str(workspace),
        )
        return r.returncode
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
