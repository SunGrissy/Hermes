#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文包构建器：为 Claude Code headless 调用组装精选的 rules + skills + 任务描述。

token 效率优先：固定层 (~3KB) + 任务层按 category 选 1-3 个文件 (~2-5KB)。
支持工单正文中的 @doc: 相对路径或 D:/MyAgents/.../*.md，将仓库内 Markdown 全文注入（过长截断）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent  # multica-dingtalk-bridge -> tools -> MyAgents
_REPO_ROOT_RESOLVED = _REPO_ROOT.resolve()
_RULES_DIR = _REPO_ROOT / ".cursor" / "rules"
_SKILLS_DIR = _REPO_ROOT / ".cursor" / "skills"

# 固定层：每次必带（无论 category 如何，这些规范始终生效）
_FIXED_LAYER: list[Path] = [
    _REPO_ROOT / "CLAUDE.md",          # Claude Code 登机简报
    _RULES_DIR / "workspace-map.mdc",  # 子项目地图
    _RULES_DIR / "agent-core.mdc",     # 门禁检查（post-edit / pre-commit）
    _RULES_DIR / "shell-git.mdc",      # PowerShell + push 流程
    _RULES_DIR / "git-workflow.mdc",   # commit 格式 + 何时提交（所有任务必需）
]

# 任务层：按 category 映射到额外 rules/skills
_TASK_LAYER: dict[str, list[Path]] = {
    "bug": [
        _RULES_DIR / "regression-testing.mdc",
        _RULES_DIR / "git-workflow.mdc",
    ],
    "fix": [
        _RULES_DIR / "regression-testing.mdc",
        _RULES_DIR / "git-workflow.mdc",
    ],
    "feature": [
        _RULES_DIR / "agentx.mdc",
        _RULES_DIR / "version-management.mdc",
    ],
    "frontend": [
        _RULES_DIR / "frontend-conventions.mdc",
        _SKILLS_DIR / "vanilla-js-ui-patterns" / "SKILL.md",
    ],
    "backend": [
        _SKILLS_DIR / "fastapi-router" / "SKILL.md",
    ],
    "refactor": [
        _RULES_DIR / "version-management.mdc",
        _SKILLS_DIR / "coding-execution-discipline" / "SKILL.md",
    ],
    "task": [
        _RULES_DIR / "agentx.mdc",
    ],
}

# 有 AgentReadMe 的项目目录（可按需扩展）
_PROJECT_AGENT_READMES: dict[str, Path] = {
    "pm-system": _REPO_ROOT / "pm-system" / "AgentReadMe.md",
    "performeval": _REPO_ROOT / "performeval" / "AgentReadMe.md",
}

_MAX_CONTEXT_BYTES = 100_000  # 约 100KB；实际使用约 8-20KB
# 单个附件文档最大字节（超出截断），可通过环境变量覆盖
_MAX_DOC_ATTACHMENT_BYTES = int(os.environ.get("TASK_CONTEXT_DOC_MAX_BYTES", "60000"))

# @doc:相对或绝对路径（每行一条，也可插在描述任意行）
_DOC_LINE_RE = re.compile(r"^\s*@doc:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
# 形如 D:/MyAgents/MulticaTasks/foo.md 的本地需求文档路径（须在仓库根目录之下）
_WIN_REPO_MD_RE = re.compile(r"(?:[Dd]:)[\\/][^\s<>\"]+\.md\b")


def _read_file_safe(path: Path) -> str:
    """读取文件内容；找不到或读取失败返回空串。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, IOError):
        return ""


def _section(title: str, content: str) -> str:
    if not content.strip():
        return ""
    return f"=== {title} ===\n{content.strip()}\n"


def _is_under_repo(path: Path) -> bool:
    """仅允许读取仓库根目录内的文件，防止任意路径泄露。"""
    try:
        path.resolve().relative_to(_REPO_ROOT_RESOLVED)
        return True
    except ValueError:
        return False


def _resolve_doc_path(raw: str) -> Path | None:
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (_REPO_ROOT / raw).resolve()
    else:
        candidate = candidate.resolve()
    if not _is_under_repo(candidate):
        return None
    return candidate


def _gather_scan_text(task: dict[str, Any]) -> str:
    """合并标题、描述、DoD 供附件路径扫描。"""
    parts: list[str] = [
        str(task.get("title") or ""),
        str(task.get("description") or ""),
    ]
    dod = task.get("definition_of_done") or []
    if isinstance(dod, list):
        parts.extend(str(x) for x in dod)
    return "\n".join(parts)


def collect_attachment_paths(scan_text: str) -> list[Path]:
    """从文本中收集 @doc: 行与 D:/.../*.md 路径，去重后返回存在的文件路径。"""
    ordered: list[Path] = []
    seen: set[str] = set()

    for m in _DOC_LINE_RE.finditer(scan_text or ""):
        p = _resolve_doc_path(m.group(1))
        if p is None or not p.is_file():
            continue
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            ordered.append(p)

    for m in _WIN_REPO_MD_RE.finditer(scan_text or ""):
        p = _resolve_doc_path(m.group(0).strip())
        if p is None or not p.is_file():
            continue
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            ordered.append(p)

    return ordered


def format_doc_attachment_sections(paths: list[Path]) -> str:
    """读取附件文档并格式化为 prompt 片段；单文件超长则截断。"""
    if not paths:
        return ""

    blocks: list[str] = []
    for path in paths:
        try:
            rel = path.resolve().relative_to(_REPO_ROOT_RESOLVED)
            title = f"附件文档 {rel.as_posix()}"
        except ValueError:
            title = f"附件文档 {path}"

        raw = _read_file_safe(path)
        if not raw.strip():
            blocks.append(
                _section(
                    title + "（读取失败或为空）",
                    f"路径存在但内容为空或不可读: {path}",
                )
            )
            continue

        body_bytes = raw.encode("utf-8")
        if len(body_bytes) > _MAX_DOC_ATTACHMENT_BYTES:
            truncated = body_bytes[:_MAX_DOC_ATTACHMENT_BYTES].decode("utf-8", errors="replace")
            raw = truncated + "\n...[附件过长已截断，完整版见仓库内源文件]"

        blocks.append(_section(title, raw))

    return "\n\n".join(blocks)


def build_doc_layers(task: dict[str, Any]) -> str:
    """供 build_context / eval / sub_task 复用：根据工单文本注入本地文档全文。"""
    scan = _gather_scan_text(task)
    paths = collect_attachment_paths(scan)
    return format_doc_attachment_sections(paths)


def _task_description(task: dict[str, Any]) -> str:
    task_id = task.get("id", "")
    title = task.get("title", "（无标题）")
    description = (task.get("description") or "").strip()
    dod: list[str] = task.get("definition_of_done") or []
    category = task.get("category", "task")
    priority = task.get("priority", "medium")

    dod_text = (
        "\n".join(f"- {d}" for d in dod)
        if dod
        else "- 无明确验收标准，请根据标题和描述自行判断完成条件"
    )

    return f"""# 开发 Agent 任务说明

你是 MyAgents 工作空间的**独立开发 Agent**（非 Cursor IDE 对话模式）。
当前 git 分支已创建为 `agent/{task_id}`，你在此分支上工作。

## 你的角色与 Cursor 会话 Agent 的区别

- 你不是在和用户对话——你需要**独立完成整个任务后自行 commit**
- commit 时机：所有修改完成、自测通过后，**主动执行 git add + git commit**，不等用户说「提交」
- commit message 格式：`<type>(<scope>): <中文描述>`（type: feat/fix/refactor/chore 等）
- commit 完成后**不要 push**（由人工审核后合并）
- Windows PowerShell 环境：用 `;` 连接命令，不用 `&&`；用 `py` 启动 Python

## 工单信息

- **ID**: {task_id}
- **标题**: {title}
- **分类**: {category}
- **优先级**: {priority}
- **描述**: {description or '（无额外描述）'}

## 验收标准（DoD）

{dod_text}

## 工作流程

1. 先 **Read** 相关代码，理解现状（不要盲目改）
2. 按 DoD 精准修改，不引入无关变更
3. 修改后检查 lint（`ReadLints`）和引用一致性
4. **git add 相关文件 → git commit**（必须执行）
5. 最后输出执行摘要，格式：

```
[完成] 或 [部分完成] 或 [未完成]
修改文件：file1.py, file2.js
摘要：<做了什么，100字以内>
DoD对照：
- [x] 验收条目1
- [ ] 验收条目2（原因）
```

请开始工作。"""


def build_context(task: dict[str, Any]) -> str:
    """为指定 task 构建 Claude Code 的完整 prompt。"""
    parts: list[str] = []

    # 固定层
    for path in _FIXED_LAYER:
        content = _read_file_safe(path)
        if content:
            parts.append(_section(path.name, content))

    # 任务层（按 category）
    category = (task.get("category") or "task").lower()
    task_files = _TASK_LAYER.get(category, _TASK_LAYER.get("task", []))
    for path in task_files:
        content = _read_file_safe(path)
        if content:
            parts.append(_section(path.name, content))

    # 项目 AgentReadMe（按 project_hint）
    project_hint = (task.get("project_hint") or "").lower()
    if project_hint:
        for key, readme_path in _PROJECT_AGENT_READMES.items():
            if key in project_hint or project_hint in key:
                content = _read_file_safe(readme_path)
                if content:
                    parts.append(_section(f"{key}/AgentReadMe.md", content))
                break

    # 工单引用的本地文档（@doc: 或 D:/MyAgents/.../*.md）
    doc_layers = build_doc_layers(task)
    if doc_layers:
        parts.append(doc_layers)

    # 任务描述（最后注入）
    parts.append(_section("当前任务", _task_description(task)))

    full = "\n\n".join(p for p in parts if p)

    # 粗略截断保护（避免超 token）
    if len(full.encode("utf-8")) > _MAX_CONTEXT_BYTES:
        full = full.encode("utf-8")[: _MAX_CONTEXT_BYTES].decode("utf-8", errors="replace")

    return full


def build_eval_context(task: dict[str, Any]) -> str:
    """Phase-1 评估+拆分阶段的 prompt。

    Claude 只读代码（Read/Glob/Grep），最终输出 JSON 规划，不修改任何文件。
    """
    task_id = task.get("id", "")
    title = task.get("title", "（无标题）")
    description = (task.get("description") or "").strip()
    dod: list[str] = task.get("definition_of_done") or []
    category = task.get("category", "task")
    priority = task.get("priority", "medium")

    dod_text = (
        "\n".join(f"- {d}" for d in dod)
        if dod
        else "- 无明确验收标准，请根据标题和描述判断"
    )

    workspace_map = _read_file_safe(_RULES_DIR / "workspace-map.mdc")

    doc_layers = ""
    eval_task = {
        "id": task_id,
        "title": title,
        "description": description,
        "definition_of_done": dod,
        "category": category,
        "priority": priority,
    }
    built = build_doc_layers(eval_task)
    if built:
        doc_layers = built + "\n\n"

    return f"""你是一个任务规划 Agent。请对下面的开发工单进行**评估**，并拆分为具体子任务。

注意：这是规划阶段。你可以 Read/Glob/Grep 相关代码文件了解现状，但**不要修改任何文件**。
若有「附件文档」段落，请先以其为需求真源进行规划。

=== workspace-map（子项目地图）===
{workspace_map[:3000]}

{doc_layers}=== 工单信息 ===
- ID: {task_id}
- 标题: {title}
- 分类: {category}
- 优先级: {priority}
- 描述: {description or "（无额外描述）"}

=== 验收标准（DoD）===
{dod_text}

=== 你的任务 ===
1. 先 Read 相关代码文件，了解当前实现状态
2. 评估整体复杂度（low/medium/high）
3. 识别潜在风险或依赖
4. 将任务拆分为 1-5 个**独立可执行**的子任务（简单任务拆 1 个即可）

**最后，输出下面格式的 JSON（放在 ```json ... ``` 代码块内）：**

```json
{{
  "complexity": "low",
  "risks": ["风险说明1"],
  "sub_tasks": [
    {{
      "index": 1,
      "title": "子任务简标题",
      "description": "具体要做什么，包含关键步骤",
      "files_hint": ["预计要修改的文件路径"]
    }}
  ],
  "notes": "其他注意事项（可留空）"
}}
```

只输出规划 JSON，不要开始实现任何代码。"""


def build_sub_task_context(
    sub_task: dict[str, Any],
    parent_task: dict[str, Any],
    completed_sub_tasks: list[dict[str, Any]],
) -> str:
    """Phase-3 子任务执行阶段的 prompt。

    sub_task 结构: {index, title, description, files_hint}
    completed_sub_tasks: [{"index": 1, "title": ..., "success": bool, "summary": ...}, ...]
    """
    task_id = parent_task.get("id", "")
    parent_title = parent_task.get("title", "")
    total = parent_task.get("_total_sub_tasks", 1)
    category = (parent_task.get("category") or "task").lower()
    idx = sub_task.get("index", 1)

    completed_text = ""
    if completed_sub_tasks:
        lines = [
            f"- 子任务{c['index']}: {c['title']} → {'完成' if c.get('success') else '未完成'}，{c.get('summary', '')[:80]}"
            for c in completed_sub_tasks
        ]
        completed_text = "## 已完成子任务（勿重复）\n" + "\n".join(lines)

    files_hint = sub_task.get("files_hint") or []
    files_hint_text = (
        "预计涉及文件：" + ", ".join(files_hint)
        if files_hint
        else "（请自行探索相关文件）"
    )

    # 固定层 rules
    fixed_parts: list[str] = []
    for path in _FIXED_LAYER:
        content = _read_file_safe(path)
        if content:
            fixed_parts.append(_section(path.name, content))

    # 任务层 rules
    task_files = _TASK_LAYER.get(category, _TASK_LAYER.get("task", []))
    for path in task_files:
        content = _read_file_safe(path)
        if content:
            fixed_parts.append(_section(path.name, content))

    rules_block = "\n\n".join(fixed_parts)

    sub_scan = "\n".join(
        [
            _gather_scan_text(parent_task),
            str(sub_task.get("title") or ""),
            str(sub_task.get("description") or ""),
        ]
    )
    doc_extra = format_doc_attachment_sections(collect_attachment_paths(sub_scan))

    task_block = f"""# 开发 Agent — 子任务执行

你是 MyAgents 工作空间的**独立开发 Agent**（headless 模式，非对话模式）。
当前 git 分支：`agent/{task_id}`

## 父工单
- **ID**: {task_id}
- **标题**: {parent_title}

## 当前子任务（{idx}/{total}）
- **标题**: {sub_task.get("title", "")}
- **描述**: {sub_task.get("description", "（无额外描述）")}
- **{files_hint_text}**

{completed_text}

## 执行要求
- **只完成当前子任务**，不要超前实现其他子任务
- 修改完成并自测通过后，**立即执行 git add + git commit**（不等待外部指令）
- commit message 格式：`<type>({task_id}-{idx}): <中文描述>`
- Windows PowerShell：用 `;` 连接命令，不用 `&&`；用 `py` 运行 Python
- commit 完成后**不要 push**（人工审核后合并）

## 最后输出执行摘要（必须包含）

```
[完成] 或 [部分完成] 或 [未完成]
修改文件：file1.py, file2.js
摘要：<做了什么，80字以内>
```

请开始工作。"""

    mid = ""
    if doc_extra:
        mid = doc_extra + "\n\n"

    full = rules_block + "\n\n" + mid + _section("当前子任务", task_block)
    if len(full.encode("utf-8")) > _MAX_CONTEXT_BYTES:
        full = full.encode("utf-8")[: _MAX_CONTEXT_BYTES].decode("utf-8", errors="replace")
    return full


def estimate_context_size(task: dict[str, Any]) -> dict[str, int]:
    """返回各层的字节估算，用于调试/日志。"""
    result: dict[str, int] = {}
    for path in _FIXED_LAYER:
        result[path.name] = len(_read_file_safe(path).encode("utf-8"))
    category = (task.get("category") or "task").lower()
    task_files = _TASK_LAYER.get(category, _TASK_LAYER.get("task", []))
    for path in task_files:
        result[path.name] = len(_read_file_safe(path).encode("utf-8"))
    result["task_description"] = len(_task_description(task).encode("utf-8"))
    return result
