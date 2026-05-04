---
name: git-ops
description: |
  Git 运维统一指南——双 remote 工作流（TyGit 主仓 + GitHub 镜像）、gh CLI、
  仓库管理、分支保护、PR 工作流、移动端 Agent 协作。
  默认只推 origin(tygit)；仅在用户明确要求时推 GitHub。

  触发词：Use when 推 GitHub、配置 remote、PR 操作、GitHub 仓库管理、分支保护、
  移动端 Agent 协作、双 remote 配置。
---

# Git 运维（双 Remote + GitHub 操作）

## 架构

```
GitLab tygit (主仓)  <-- 默认 git push origin --+
                                                 | 你的电脑
GitHub (镜像)  <-- 仅显式 git push github -------+
       ^
  移动端 Agent: mobile/* + PR
```

- `origin`：fetch 与 push 均仅指向 tygit
- `github` remote：用于 fetch/pull 拉 Agent 成果，显式 `git push github` 更新镜像
- **禁止**给 origin 配第二个 push URL

## Remote 配置

```powershell
git remote add origin http://tygit.tuyoo.com/ue4_pm_group/<repo>.git
git remote add github https://github.com/SunGrissy/<repo>.git
```

验证：`git remote -v` → origin 只有一条 push（tygit），github 单独 remote。

### 仓库清单

| 项目 | GitLab | GitHub |
|------|--------|--------|
| MyAgents (父) | `ue4_pm_group/management-hub.git` | `SunGrissy/MyAgents.git` |
| pm-system | `ue4_pm_group/pm-system.git` | `SunGrissy/pm-system.git` |
| performeval | `ue4_pm_group/performeval.git` | `SunGrissy/performeval.git` |
| cci_system | `ue4_pm_group/cci_system.git` | `SunGrissy/cci_system.git` |
| task_reminder | `ue4_pm_group/task_reminder.git` | `SunGrissy/task_reminder.git` |
| teamscore | `ue4_pm_group/teamscore.git` | `SunGrissy/teamscore.git` |
| **novel** | — | `SunGrissy/novel.git`（独立仓） |

## 日常工作流

| 场景 | 命令 |
|------|------|
| 内网开发完（默认） | `git push origin main` |
| 更新 GitHub 镜像 | `git push github main`（用户说「推 GitHub」时） |
| 拉取移动端 Agent 成果 | `git pull github main` → `git push origin main` |

子模块先于父仓库推送。

## gh CLI 速查

```powershell
gh auth status                     # 检查登录
gh repo create <name> --private    # 创建私有仓库
gh pr list --repo <owner>/<repo>   # 列出 PR
gh pr checkout <number>            # 本地检出 PR
gh pr merge <number> --merge       # 合并 PR
```

## PR 工作流（移动端 Agent）

1. Agent 创建 `mobile/<任务>` 分支 → 提交 → 创建 PR
2. 用户 Review（Web UI 或本地 `gh pr checkout`）→ Merge
3. 本地 `git pull github main` → `git push origin main`

## 分支命名

| 来源 | 前缀 |
|------|------|
| 移动端 Agent | `mobile/` |
| 内网功能 | `feat/` |
| 内网修复 | `fix/` |

## GitHub 仓库标准配置

- Visibility: Private
- Branch protection (main): Require PR、禁 force push、禁删除
- `.gitmodules` 使用相对路径

## 安全

- Fine-grained PAT，仅授权需要的仓库
- `.env`、`*.db`、`backend/data/*.json` 禁止出现在 GitHub
- Token 定期轮换（建议 90 天）

## novel/（仅 GitHub）

独立 Git 仓，父仓 `.gitignore` 忽略。

## 变更记录

| 日期 | 版本 | 变更 | 来源 |
|------|------|------|------|
| 2026-03-15 | v1.0 | dual-git-sync + github-ops 分别创建 | 多会话 |
| 2026-04-14 | v2.0 | 合并为 git-ops | AgentSkil |
