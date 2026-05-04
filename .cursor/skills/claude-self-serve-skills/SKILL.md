---
name: claude-self-serve-skills
description: Claude / Cursor Agent 在本机把 MyAgents 仓库内的 .cursor/skills 同步到用户技能目录，实现自助装载。触发词：自己装技能、同步技能、复制 skill、装 Cursor 技能、技能目录同步、claude self serve skills。
---

# Claude 自助装载技能（本仓 → 用户目录）

## 适用于

- 本机已克隆 `MyAgents`，且 Agent 会话的工作区在该仓库内（或能 `git rev-parse` 到同一棵目录树）。
- 需要把**仓库正本** `.cursor/skills/{name}/` 复制到 **`%USERPROFILE%\.cursor\skills\`**，使 Cursor / 部分工具能加载与仓库一致的 Skill。

## 不适用于

- 未克隆仓库、只有零散 SKILL 文件时，本流程无法推断源路径。
- 禁止用本机用户目录**覆盖写回**仓库 `.cursor/skills`（与 `digital-twin-voice` 约定相反）。

## 局限性

- 本 Skill **不**代替各 Skill 正文里的业务知识；只解决「发现性 / 版本一致」。
- 若团队另有 Hermes / Claude Code 专用技能路径，需在会话里**显式**追加目标目录，本 Skill 默认只写 `%USERPROFILE%\.cursor\skills`。

---

## 操作步骤

### 1. 解析仓库根路径

在 PowerShell 中（工作区应在仓库内）：

```powershell
cd "D:\MyAgents"   # 若已在会话工作区根，可省略；否则改为实际路径
$repo = git rev-parse --show-toplevel
if (-not (Test-Path (Join-Path $repo ".cursor\skills"))) { throw "Not MyAgents repo: missing .cursor/skills" }
```

### 2. 选择要同步的 Skill 目录名

**最小可用（日常开发）：**

`preflight-checks`, `digital-twin-voice`, `structured-communication`, `coding-execution-discipline`

**合并 main / 审查向（在最小集上追加）：**

`git-ops`, `preflight-checks`（已列）, `multi-service-orchestration`

**合 main 政策正文（文档，非目录）：** 同步完技能后，在会话中 `Read`：

`docs/review-merge-main-policy.md`（相对 `$repo`）

### 3. 复制到用户 `.cursor\skills`

```powershell
$srcRoot = Join-Path $repo ".cursor\skills"
$dstRoot = Join-Path $env:USERPROFILE ".cursor\skills"
New-Item -ItemType Directory -Force -Path $dstRoot | Out-Null

$names = @(
  "preflight-checks",
  "digital-twin-voice",
  "structured-communication",
  "coding-execution-discipline",
  "git-ops",
  "multi-service-orchestration",
  "claude-self-serve-skills"
)

foreach ($n in $names) {
  $s = Join-Path $srcRoot $n
  if (-not (Test-Path $s)) { Write-Host "SKIP missing: $n"; continue }
  $d = Join-Path $dstRoot $n
  if (Test-Path $d) { Remove-Item -Recurse -Force $d }
  Copy-Item -Path $s -Destination $d -Recurse -Force
  Write-Host "OK $n -> $d"
}
```

可按任务删减 `$names` 数组；**务必保留**本次会话若依赖的 Skill 名。

### 4.（可选）Claude Code 用户级目录

若本机使用 Claude Code 且约定技能在 `%USERPROFILE%\.claude\skills`：

- 将上式中 `$dstRoot` 改为 `Join-Path $env:USERPROFILE ".claude\skills"` **再执行一遍**，或只对个别 Skill 复制。
- 若项目内另有 `.claude/skills`，以项目文档为准，本 Skill 不强行统一。

---

## 预期输出（Agent 自检汇报）

合并为简短列表即可：

| 检查项 | 结果 |
|--------|------|
| `$repo` | 已解析为 … |
| 已复制目录 | `a`, `b`, … |
| 目标根路径 | `%USERPROFILE%\.cursor\skills` |
| 缺失跳过 | 无 / 列出 `n` |
| 政策文档 | 已提醒 Read `docs/review-merge-main-policy.md` 是 / 否 |

---

## 与现有文档的关系

- 总索引：`.cursor/skills/README.md`
- 双目录原则：`digital-twin-voice` Skill 末节（**仓库为正本，用户目录为副本**）
