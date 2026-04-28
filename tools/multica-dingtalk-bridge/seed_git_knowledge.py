#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""种子脚本：扫描 MyAgents Git 仓库结构，将项目地图写入 Multica 机器人知识库。

运行方式（在 multica-dingtalk-bridge 目录下）：
    py seed_git_knowledge.py

可反复运行，每次均幂等覆盖旧条目（upsert by kind+key）。
结果写入 MULTICA_BOT_MEMORY_DB 或默认的 multica_bridge_memory.db。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parent.parent  # tools/multica-dingtalk-bridge -> tools -> MyAgents

# 已知项目描述，来源：.cursor/rules/workspace-map.mdc
_PROJECT_NOTES: dict[str, str] = {
    "pm-system": "游戏项目管理系统（FastAPI + 原生JS；backend/main.py + index.html）",
    "performeval": "乘法绩效评价系统（FastAPI + SQLite；端口 8112）",
    "cci_system": "素材竞争力评分 CCI（Streamlit；入口 app.py）",
    "task_reminder": "任务提醒 + 钉钉推送（FastAPI；端口 8000；入口 server.py）",
    "FileCleanerTool": "文件扫描清理桌面工具（Python + customtkinter；入口 gui.py）",
    "teamscore": "团队评分数据处理（Python 脚本集，M12、雷达图等）",
    "dingtalk-desktop": "钉钉桌面消息通道（基础设施；入口 daemon.py；端口 19200）",
    "palace": "内部引擎/脚本与相关物料（入口 run.py；含 palace_engine/）",
    "tools": "工具集（含 multica-dingtalk-bridge 本系统）",
    "silicon-legion": "AI 顾问军团（core/config.py；advisors/ 下各顾问）",
    "docs": "跨项目文档库（superpowers/specs/、superpowers/plans/ 等）",
    "shared-memory": "Agent 共享记忆（knowledge/、scripts/；对所有 Agent 可见）",
    "skills": "Agent Skill 体系（.cursor/skills/ 各子目录一个 Skill；唯一来源）",
    "interviews": "面试材料（候选人子目录；含面试清单、评价报告）",
    "workspace-docs": "管理规范文档库（README.md）",
    "memories": "本地记忆快照",
    "recruitment-toolkit": "招聘工具包",
    "md-reader": "Markdown 本地阅读器服务",
    "cron": "定时任务脚本目录",
    "scripts": "通用脚本目录",
}

# multica-dingtalk-bridge 内部模块说明
_BRIDGE_MODULE_NOTES: dict[str, str] = {
    "dispatch_bot.py": "DingTalk Stream 桥接主文件，消息路由入口",
    "multica_client.py": "Multica CLI 封装，返回结构化 Python 对象",
    "brain.py": "LLM 结构化大脑（BrainDecision、对话渲染）",
    "memory.py": "本地记忆存储（SQLite；knowledge/session/issue/pending）",
    "seed_git_knowledge.py": "仓库结构知识种子（本脚本，幂等）",
    "tests": "单元测试目录",
    ".env": "本地环境变量（LLM key、Multica token 等）",
    ".env.example": "环境变量模板",
    "README.md": "使用说明文档",
    "requirements.txt": "Python 依赖",
    "run_bridge.ps1": "启动脚本（PowerShell）",
}


def _git_ls_tree_names(repo: Path, path: str = "") -> list[str]:
    """运行 git ls-tree --name-only HEAD [path]，返回直接子条目名列表。"""
    cmd = ["git", "ls-tree", "--name-only", "HEAD"]
    if path:
        cmd.append(path)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(repo),
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _entry_basename(entry: str) -> str:
    return entry.rstrip("/").split("/")[-1]


def build_project_map(repo_root: Path) -> str:
    """生成仓库项目地图文本。"""
    lines: list[str] = [
        f"MyAgents 仓库结构（扫描时间：{time.strftime('%Y-%m-%d')}）",
        f"仓库路径：{repo_root}",
        "",
        "【主要项目目录（含描述）】",
    ]

    top_entries = _git_ls_tree_names(repo_root)
    for entry in sorted(top_entries):
        base = _entry_basename(entry)
        if base.startswith("."):
            continue
        note = _PROJECT_NOTES.get(base, "")
        if note:
            lines.append(f"  {base:<32} {note}")
        elif "." not in base:
            # 未知目录，直接列出
            lines.append(f"  {base}")

    # multica-dingtalk-bridge 内部结构（git + 文件系统双重扫描）
    lines.extend(["", "【tools/multica-dingtalk-bridge 内部模块】"])
    bridge_dir = repo_root / "tools" / "multica-dingtalk-bridge"
    bridge_bases: set[str] = set()

    # 先用 git ls-tree（已追踪文件）
    for entry in _git_ls_tree_names(repo_root, "tools/multica-dingtalk-bridge/"):
        bridge_bases.add(_entry_basename(entry))

    # 再用文件系统补全未追踪的新文件
    if bridge_dir.exists():
        for item in bridge_dir.iterdir():
            bridge_bases.add(item.name)

    for base in sorted(bridge_bases):
        if base.startswith(".") and base not in {".env", ".env.example"}:
            continue
        if base.startswith("__"):
            continue
        note = _BRIDGE_MODULE_NOTES.get(base, "")
        if note:
            lines.append(f"  {base:<32} {note}")
        elif not any(base.endswith(ext) for ext in (".pyc", ".db", ".zip")):
            lines.append(f"  {base}")

    # pm-system 子结构
    lines.extend(["", "【pm-system 子目录】"])
    pm_entries = _git_ls_tree_names(repo_root, "pm-system/")
    for entry in pm_entries:
        base = _entry_basename(entry)
        if not base.startswith("."):
            lines.append(f"  {base}")

    return "\n".join(lines)


def main() -> None:
    sys.path.insert(0, str(_HERE))
    from memory import MemoryStore

    db_path = os.environ.get("MULTICA_BOT_MEMORY_DB") or str(
        _HERE / "multica_bridge_memory.db"
    )
    store = MemoryStore(db_path)

    project_map = build_project_map(_REPO_ROOT)
    store.upsert_knowledge_memory("project_map", "myagents_root", project_map)

    print(f"[seed] project_map 已写入: {db_path}")
    print()
    print(project_map)


if __name__ == "__main__":
    main()
