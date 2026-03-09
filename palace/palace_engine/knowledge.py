"""PLAYBOOK section slicer.

Extracts chapter text from PLAYBOOK.md by matching ## headers,
avoiding hardcoded line numbers that break on edits.
"""

import re
from pathlib import Path

SECTION_PATTERNS: dict[str, re.Pattern] = {
    "north_star":      re.compile(r"^## 零、"),
    "strategic":       re.compile(r"^## 一、"),
    "dual_track":      re.compile(r"^## 二、"),
    "pipeline_roles":  re.compile(r"^## 三、"),
    "authority_model": re.compile(r"^## 四、"),
    "dor_standards":   re.compile(r"^## 五、"),
    "evaluation":      re.compile(r"^## 六、"),
    "ai_evolution":    re.compile(r"^## 七、"),
    "org_diagnosis":   re.compile(r"^## 八、"),
    "data_collab":     re.compile(r"^## 九、"),
}


def load_playbook(playbook_path: Path) -> str:
    with open(playbook_path, "r", encoding="utf-8") as f:
        return f.read()


def extract_section(playbook_text: str, section_id: str) -> str:
    """Extract one section from PLAYBOOK by matching ## headers.

    Returns the text from the matched ## header up to (but not including)
    the next ## header or the end of the document.
    """
    pattern = SECTION_PATTERNS.get(section_id)
    if not pattern:
        return ""

    lines = playbook_text.split("\n")
    start = None
    end = None

    for i, line in enumerate(lines):
        if start is None:
            if pattern.match(line):
                start = i
        elif re.match(r"^## [^#]", line):
            end = i
            break

    if start is None:
        return ""
    if end is None:
        end = len(lines)

    text = "\n".join(lines[start:end]).strip()
    return text.removesuffix("---").strip()


def get_knowledge_for_role(role_config: dict, playbook_text: str) -> str:
    """Combine relevant PLAYBOOK sections for a role based on its config."""
    section_ids = role_config.get("knowledge_sections", [])
    parts = []
    for sid in section_ids:
        text = extract_section(playbook_text, sid)
        if text:
            parts.append(text)
    return "\n\n---\n\n".join(parts)
