# Memory Index

Quick-lookup table for retrieval. Use Ctrl+F on keywords.

## By Tool
| Keyword | File | Section | Priority |
|---------|------|---------|----------|
| terminal, drain, stdout, empty output | MEMORY.md | environment | P1 |
| skill_view, GBK, encoding, UTF-8 | MEMORY.md | environment | P1 |
| taskkill, Git Bash, path, slash | MEMORY.md | environment | P1 |
| daemon.py, dingtalk-desktop, persistent, timeout | MEMORY.md | systems | P1 |
| gateway, hermes.exe, restart, PID | MEMORY.md | systems | P1 |
| multica, stream, 派单, hijack, Client ID | MEMORY.md | systems | P1 |

## By Protocol
| Keyword | File | Section | Priority |
|---------|------|---------|----------|
| fault, error, SOUL, silent fail, retry | skill:fault-response | (external) | P0 |
| progress, 30s, 60s, phased, discipline | skill:execution-discipline | (external) | P0 |
| decision-repair, anti-pattern, failure loop | MEMORY.md | decision-repair | P1 |

## By User Profile
| Keyword | File | Section | Priority |
|---------|------|---------|----------|
| 猫姐, 老大, 助理小橘, sign-off | USER.md | identity | P0 |
| conclusion-first, concise, technical, retro | USER.md | workflow-style | P0 |
| 30s, 60s, progress, visibility, timeout | USER.md | workflow-style | P0 |
| 连续翻车, failure, ack, confirmation | USER.md | workflow-style | P0 |
| mono, theme, skin | USER.md | preferences | P2 |
| OpenClaw, DingTalk, integration | USER.md | preferences | P2 |

## Retrieval Tiers (MemOS-style)
- Tier 1 (Skill): fault-response, execution-discipline -> always load on task start.
- Tier 2 (World Model): environment, systems, decision-repair -> load when relevant tool/system is invoked.
- Tier 3 (User Profile): identity, workflow-style, preferences -> load on conversation start.
