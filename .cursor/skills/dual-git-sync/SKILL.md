---
name: dual-git-sync
description: TyGit（内网主仓）与 GitHub（可选镜像）双 remote：默认只推 origin(tygit)；仅在用户明确要求时推 GitHub。含 remote 配置、子模块、移动端 Agent、novel 独立仓说明。
---

# 双 Git Remote 工作流（TyGit 主仓 + GitHub 可选）

本 Skill 覆盖 MyAgents 工作空间的 **GitLab(tygit) 主仓** 与 **GitHub 外网镜像** 的配合方式。

> 提交时机、message 格式见 `git-workflow.mdc`；多会话分支安全见 `git-branch-guard.mdc`。本 Skill 不重复这些内容。

## 架构

```
GitLab tygit (主仓)  ←── 默认 git push origin ──┐
       ↑                                        │
  内网日常开发                                    │ 你的电脑
       ↑                                        │
GitHub (镜像)  ←── 仅当用户明确要求时 git push github ──┘
       ↑
  移动端 Agent：mobile/* + PR
```

**核心设计**：

- `origin`：**fetch 与 push 均仅指向 tygit**（单 push URL）。日常 `git push` / `git push origin` **只更新内网主仓**。
- `github` remote：用于 `fetch` / `pull`（拉 Agent 成果），以及 **显式** `git push github` 更新镜像。
- **禁止**再给 `origin` 配置第二个 push URL（避免误双推）。

## Remote 配置

### 父仓库 + 各子模块（已与 GitHub 建镜像的仓）

```powershell
# 内网主仓（fetch + 唯一 push）
git remote add origin http://tygit.tuyoo.com/ue4_pm_group/<repo>.git
# 若 origin 已存在，确保 push 只有 tygit：
git remote set-url --push --delete origin https://github.com/SunGrissy/<repo>.git
# 若上一步报「无此 URL」，用下面确认仅剩一条 push：
git remote get-url --push --all origin

# GitHub：单独 remote，仅用于 pull / 显式 push
git remote add github https://github.com/SunGrissy/<repo>.git
```

### 验证

```powershell
git remote -v
# 期望：
# origin   <tygit>   (fetch)
# origin   <tygit>   (push)    ← 仅一条 push
# github   <github>  (fetch)
# github   <github>  (push)

git push origin main --dry-run
# 应只看到 tygit 目标，不应再出现 GitHub
```

### 仓库清单

| 项目 | GitLab URL | GitHub URL |
|------|-----------|-----------|
| MyAgents (父) | `http://tygit.tuyoo.com/ue4_pm_group/management-hub.git` | `https://github.com/SunGrissy/MyAgents.git` |
| pm-system | `http://tygit.tuyoo.com/ue4_pm_group/pm-system.git` | `https://github.com/SunGrissy/pm-system.git` |
| performeval | `http://tygit.tuyoo.com/ue4_pm_group/performeval.git` | `https://github.com/SunGrissy/performeval.git` |
| cci_system | `http://tygit.tuyoo.com/ue4_pm_group/cci_system.git` | `https://github.com/SunGrissy/cci_system.git` |
| task_reminder | `http://tygit.tuyoo.com/ue4_pm_group/task_reminder.git` | `https://github.com/SunGrissy/task_reminder.git` |
| teamscore | `http://tygit.tuyoo.com/ue4_pm_group/teamscore.git` | `https://github.com/SunGrissy/teamscore.git` |
| **novel**（独立仓，见下） | — | `https://github.com/SunGrissy/novel.git` |

### `.gitmodules` 使用相对路径

```ini
[submodule "pm-system"]
    path = pm-system
    url = ../pm-system.git
```

相对路径让 Git 根据父仓库 clone 来源自动拼接子模块 URL：内网 clone 走内网，GitHub clone 走 GitHub。

## novel/（仅 GitHub 维护）

- 父仓库 **不跟踪** `novel/`（根目录 `.gitignore` 已忽略）。
- `novel/` 为 **独立 Git 仓库**，远端仅 GitHub：`https://github.com/SunGrissy/novel.git`。
- 克隆 MyAgents（tygit）后若需要小说目录：`cd novel` → 按仓库根目录 `novel/README.md` 初始化或 `git pull origin main`。

## 日常工作流

### A. 内网开发完（默认）

```powershell
git push origin main
# 仅 tygit
```

**子模块先于父仓库推送**的规则不变（见 `acceptance-checklist.mdc` 第 7 步）。

### B. 需要更新 GitHub 镜像时（显式）

用户口令：**「推 GitHub」** / `push github`（见 `shell-git.mdc`）。

```powershell
# 父仓或子模块内
git push github main
```

有多级子模块时：先在各子模块 `git push github main`，再父仓库 `git push github main`。

### C. 移动端 Agent 在 GitHub 开发

Agent 创建分支 `mobile/<任务名>` → 提交 → 创建 PR → Review 后 Merge 到 GitHub main。

GitHub `main` 分支保护：`Require pull request` 开启，`Allow force pushes` 关闭。

### D. 回到内网，拉取 Agent 成果

```powershell
git pull github main
git push origin main    # 同步回 tygit（默认不必再推 GitHub）
```

若希望镜像与内网一致，再执行：`git push github main`。

### E. Agent 改了子模块代码

```powershell
cd pm-system
git pull github main
git push origin main
cd ..
git add pm-system
git commit -m "chore: sync pm-system submodule"
git push origin main
# 需要 GitHub 镜像时再：git push github main（在子模块与父仓分别执行）
```

## 推送失败补推

仅 tygit 失败：排查内网后重试 `git push origin`。

仅需要补 GitHub：`git push github main`（在对应仓库目录内）。

## 冲突预防

- 内网做主力开发，移动端 Agent 做小修/紧急修复
- Agent 始终走 `mobile/` 分支 + PR
- 合入前先 pull 对方最新代码
- 避免两端同时改同一文件

## GitHub 认证

- **PAT**：`https://<token>@github.com/<user>/<repo>.git`
- **SSH**：`git@github.com:<user>/<repo>.git`
- `gh auth setup-git` 可配置 credential helper

## 环境自动识别

| origin URL 包含 | 环境 | 工作模式 |
|---|---|---|
| `tygit.tuyoo.com` | 内网（本地开发） | `git push origin` → 仅 tygit；GitHub 仅显式 `git push github` |
| `github.com` | 外网（云端 Agent） | `mobile/` 分支 + PR，不直接推 main |

## Cursor 云端 Agent 环境

云端 Agent 从 GitHub clone，无 `.env`：

- 后端需 `DEV_MODE=true` 或 dev-safe 默认配置
- `dev_mode=True` 时可无 `.env` 启动
- OIDC 等在 dev_mode 下跳过

## 检查清单（新建机器 / 复查）

- [ ] `origin` push **仅** tygit（`git remote get-url --push --all origin` 只有一条）
- [ ] 存在 `github` remote
- [ ] `.gitignore` 含 `novel/`；小说在独立仓 `SunGrissy/novel` 推送
- [ ] `.gitmodules` 相对路径（子模块）
- [ ] GitHub `main` 分支保护已配置（若使用移动端 Agent）
