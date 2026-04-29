# -*- coding: utf-8 -*-
"""把完整审查报告压成钉钉 Markdown 易读短摘要（去表格、少说人话）。"""
from __future__ import annotations

import re

_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}[\s:|+-]*\|?\s*$")


def _line_is_markdown_table_row(line: str) -> bool:
    s = line.strip()
    if s.count("|") < 2:
        return False
    if _TABLE_SEP.match(s):
        return True
    if s.startswith("|"):
        return True
    parts = [p for p in s.split("|") if p.strip() != ""]
    return len(parts) >= 2 and s.count("|") >= 2


def strip_markdown_tables(text: str) -> str:
    lines = [ln for ln in text.splitlines() if not _line_is_markdown_table_row(ln)]
    return "\n".join(lines)


def _strip_heading_hashes(s: str) -> str:
    return re.sub(r"^#+\s*", "", s.strip())


def _pick_focus_section(text: str) -> str | None:
    """优先取「问题 / 风险 / 结论」相关小节，避免把变更表格后的碎行贴进摘要。"""
    markers = (
        "问题清单",
        "问题",
        "风险",
        "阻塞",
        "结论",
        "总结",
        "建议",
        "issue list",
        "findings",
    )
    parts = re.split(r"\n(?=#+\s)", text)
    for part in parts:
        if not part.strip():
            continue
        first, _, rest = part.partition("\n")
        head = _strip_heading_hashes(first)
        hl = head.lower()
        if any(m.lower() in hl for m in markers):
            cleaned = strip_markdown_tables(rest).strip()
            if cleaned:
                return cleaned
    return None


def humanize_review_for_webhook(report: str, max_len: int = 900) -> str:
    """从完整审查报告生成短摘要：去掉 Markdown 表格，口语化、非表格。"""
    raw = (report or "").strip()
    if not raw:
        return "审查已跑完，详细说明在 Multica 工单评论里。"

    no_tables = strip_markdown_tables(raw)
    focus = _pick_focus_section(no_tables)
    chunk = focus or no_tables

    lines_out: list[str] = []
    for line in chunk.splitlines():
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        if _line_is_markdown_table_row(s):
            continue
        s = _strip_heading_hashes(s)
        if not s:
            continue
        if re.fullmatch(r"[-*]{3,}", s):
            continue
        lines_out.append(s)
        if sum(len(x) for x in lines_out) > max_len:
            break

    body = "\n".join(lines_out).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)

    if not body:
        body = no_tables.strip()[:max_len]

    intro = "审查刚跑完，结论要点如下（完整报告在 Multica 评论）："
    out = f"{intro}\n\n{body}"
    if len(out) > max_len:
        out = out[: max_len - 1].rstrip() + "…"
    return out
