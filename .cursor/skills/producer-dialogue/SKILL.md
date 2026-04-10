---
name: producer-dialogue
description: 与制作人对话时默认说人话、少技术黑话、用产品思维组织回答；改 Skills 须以仓库 .cursor/skills 为正本，再复制到 %USERPROFILE%\.cursor\skills（禁止以本机覆盖仓库）。在讨论需求、方案、结论、验收时优先激活。
---

# 制作人对话 · 产品表述

## 对话风格（默认）

- **说人话**：先给结论和「对你意味着什么」，再按需补细节；避免一上来就文件路径、类名、命令行堆砌。
- **少技术语言**：非排查场景不写栈、不炫术语；必须提技术名词时，用括号或半句白话点明含义。
- **产品思维**：优先讲用户/业务结果、取舍、风险、需要你拍板的点；实现步骤放在「若要落地」时再展开。
- **例外**：你明确在查 bug、对接口、写提交说明或说「要技术细节」时，再切换到技术粒度。

## Skills 与工作区、Cursor 目录同步

- **唯一权威（正本）**：本仓库 `MyAgents/.cursor/skills/`（随 Git 提交；**Git 即备份**，本机挂了只要仓库在即可恢复）。
- **Cursor 用户目录**：`%USERPROFILE%\.cursor\skills\` 仅为本机加载用**副本**；内容须与仓库同名 skill **一致**，且**单向**：先改仓库 → 再复制到用户目录；**不要用本机旧文件覆盖仓库**，避免丢失备份。
- **Agent 在本仓库新增或改版 `SKILL.md` 后**：交付时**简短提醒**把该 skill 目录同步到用户目录（或执行下方命令）。

PowerShell 示例（将单个 skill 同步到用户目录；`$repo` 换成本机 `MyAgents` 根路径）：

```powershell
$repo = "d:\MyAgents"
$skill = "producer-dialogue"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.cursor\skills" | Out-Null
Copy-Item -Recurse -Force "$repo\.cursor\skills\$skill" "$env:USERPROFILE\.cursor\skills\"
```

批量同步整个仓库 skills 时，可将源改为 `"$repo\.cursor\skills\*"` 并保持目标为 `"$env:USERPROFILE\.cursor\skills\"`（注意覆盖同名目录）。

## 与现有规则的关系

- 与 `digital-twin-voice`（主人翁、「我们」）、`producer-context.mdc` 并存：本 skill 侧重**表达粒度与产品视角**，不替代身份与协作立场。
