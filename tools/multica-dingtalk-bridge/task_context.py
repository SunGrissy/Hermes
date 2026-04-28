#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文包构建器：为 Claude Code headless 调用组装精选的 rules + skills + 任务描述。

token 效率优先：固定层 (~3KB) + 任务层按 category 选 1-3 个文件 (~2-5KB)。
总上下文控制在 8KB 以内；项目 AgentReadMe 按 project_hint 按需附加。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent.parent  # multica-dingtalk-bridge -> tools -> MyAgents
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

    return f"""你是一个任务规划 Agent。请对下面的开发工单进行**评估**，并拆分为具体子任务。

注意：这是规划阶段。你可以 Read/Glob/Grep 相关代码文件了解现状，但**不要修改任何文件**。

=== workspace-map（子项目地图）===
{workspace_map[:3000]}

=== 工单信息 ===
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

    full = rules_block + "\n\n" + _section("当前子任务", task_block)
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
