from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_MAP_FILE = Path(__file__).with_name("multica_project_map.json")


@dataclass
class MulticaResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    data: dict[str, Any] | None = None


def build_issue_create_args(
    *,
    title: str,
    description: str,
    priority: str,
    status: str,
    project_id: str,
) -> list[str]:
    args = [
        "issue",
        "create",
        "--title",
        title,
        "--description",
        description,
        "--priority",
        priority,
        "--status",
        status,
        "--output",
        "json",
    ]
    if project_id.strip():
        args.extend(["--project", project_id.strip()])
    return args


def _load_project_map(env: dict[str, str]) -> dict[str, Any]:
    raw = env.get("MULTICA_PROJECT_MAP_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    map_file = Path(env.get("MULTICA_PROJECT_MAP_FILE", "") or _PROJECT_MAP_FILE)
    if not map_file.is_file():
        return {}
    try:
        data = json.loads(map_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def infer_project_id(
    *,
    title: str,
    description: str,
    env: dict[str, str] | None = None,
) -> str:
    active_env = dict(env or os.environ)
    explicit = active_env.get("MULTICA_PROJECT_ID", "").strip()
    if explicit:
        return explicit
    data = _load_project_map(active_env)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return ""
    haystack = f"{title}\n{description}".lower()
    for name, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        project_id = str(entry.get("id") or "").strip()
        if not project_id:
            continue
        aliases = [str(name), str(entry.get("path") or "")]
        raw_aliases = entry.get("aliases")
        if isinstance(raw_aliases, list):
            aliases.extend(str(alias) for alias in raw_aliases)
        for alias in aliases:
            needle = alias.strip().lower()
            if needle and needle in haystack:
                return project_id
    return ""


class MulticaClient:
    def __init__(self, multica_bin: str | None = None, env: dict[str, str] | None = None):
        self._explicit_bin = multica_bin
        self._env = dict(env or os.environ)

    def resolve_binary(self) -> str | None:
        explicit = (
            self._explicit_bin
            or self._env.get("MULTICA_BIN")
            or self._env.get("MULTICA_EXECUTABLE")
            or ""
        ).strip()
        if explicit and Path(explicit).is_file():
            return str(Path(explicit).resolve())
        path_value = self._env.get("PATH")
        found = shutil.which("multica", path=path_value) or shutil.which(
            "multica.exe", path=path_value
        )
        if found:
            return found
        if sys.platform == "win32":
            local = self._env.get("LOCALAPPDATA", "")
            if local:
                guess = Path(local) / "Programs" / "multica" / "multica.exe"
                if guess.is_file():
                    return str(guess.resolve())
        return None

    async def run_json(
        self,
        args: list[str],
        limit_stderr: int = 1200,
        timeout_seconds: float = 60.0,
    ) -> MulticaResult:
        bin_path = self.resolve_binary()
        if not bin_path:
            return MulticaResult(
                ok=False,
                returncode=127,
                stdout="",
                stderr="multica binary not found",
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                bin_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
        except OSError as exc:
            return MulticaResult(
                ok=False,
                returncode=126,
                stdout="",
                stderr=f"failed to start multica: {exc}",
            )
        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return MulticaResult(
                ok=False,
                returncode=124,
                stdout="",
                stderr="multica command timed out",
            )
        stdout = (out_b or b"").decode("utf-8", errors="replace")
        stderr = (err_b or b"").decode("utf-8", errors="replace")[:limit_stderr]
        if proc.returncode != 0:
            return MulticaResult(False, int(proc.returncode or 0), stdout, stderr)
        try:
            data = json.loads(stdout.strip()) if stdout.strip() else {}
        except json.JSONDecodeError:
            return MulticaResult(False, 0, stdout, "failed to parse multica JSON output")
        if not isinstance(data, dict):
            return MulticaResult(False, 0, stdout, "multica JSON output was not an object")
        return MulticaResult(True, 0, stdout, stderr, data)

    async def create_issue(
        self,
        *,
        title: str,
        description: str,
        priority: str = "medium",
        status: str = "todo",
        project_id: str | None = None,
    ) -> MulticaResult:
        resolved_project_id = (project_id or "").strip() or infer_project_id(
            title=title,
            description=description,
            env=self._env,
        )
        return await self.run_json(
            build_issue_create_args(
                title=title,
                description=description,
                priority=priority,
                status=status,
                project_id=resolved_project_id,
            )
        )

    async def list_issues(self, *, limit: int = 500, status: str | None = None) -> MulticaResult:
        lim = max(1, min(int(limit), 500))
        args = ["issue", "list", "--output", "json", "--limit", str(lim)]
        project_id = self._env.get("MULTICA_PROJECT_ID", "").strip()
        if project_id:
            args.extend(["--project", project_id])
        if status:
            args.extend(["--status", status])
        return await self.run_json(args)

    async def cancel_issue(self, issue_ref: str) -> MulticaResult:
        args = ["issue", "status", issue_ref, "cancelled", "--output", "json"]
        project_id = self._env.get("MULTICA_PROJECT_ID", "").strip()
        if project_id:
            args.extend(["--project", project_id])
        return await self.run_json(args)
