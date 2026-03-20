---
name: github-ops
description: GitHub platform operations for MyAgents workspace. Covers gh CLI usage, repo management, branch protection, PR workflow, mobile Agent conventions, and GitHub-specific troubleshooting. Use when creating GitHub repos, configuring branch protection, managing PRs, working with gh CLI, or setting up mobile Cursor Agent collaboration on GitHub.
---

# GitHub 操作规范

MyAgents 使用 GitHub 作为外网开发镜像，供 Cursor 云端/移动端 Agent 协作。日常 **`git push origin` 只推 tygit**；更新 GitHub 镜像需用户明确说「推 GitHub」后对 `github` remote 执行 `git push github`（见 `dual-git-sync` Skill）。

> Remote 策略与口令见 `dual-git-sync` Skill、`shell-git.mdc`；提交规范见 `git-workflow.mdc`。

## gh CLI 速查

### 认证

```powershell
gh auth status          # 检查登录状态
gh auth login           # 交互式登录（首次）
gh auth setup-git       # 配置 Git credential helper（推荐）
```

### 仓库管理

```powershell
# 创建 Private 空仓库
gh repo create <repo-name> --private --description "描述"

# 批量查看
gh repo list --limit 20

# 查看仓库信息
gh repo view <owner>/<repo>
```

### PR 操作

```powershell
# 列出 PR
gh pr list --repo <owner>/<repo>

# 查看 PR 详情
gh pr view <number> --repo <owner>/<repo>

# 本地检出 PR 分支（用于 code review）
gh pr checkout <number>

# 合并 PR（在 GitHub 端）
gh pr merge <number> --merge --repo <owner>/<repo>

# 创建 PR
gh pr create --title "标题" --body "描述" --base main --head <branch>
```

### 分支保护

**首选 Web UI**（稳定、直观、不受 API 版本变化影响）：

Settings → Branches → Add branch ruleset → Branch name pattern: `main`
- Require a pull request before merging: 开启
- Allow force pushes: 关闭
- Allow deletions: 关闭

**CLI 备选**（API 格式可能随 GitHub 版本变化，仅供参考）：

```powershell
gh api repos/<owner>/<repo>/branches/main/protection -X PUT `
  -f "required_pull_request_reviews[required_approving_review_count]=0" `
  -F "allow_force_pushes=false" -F "allow_deletions=false" `
  -f "enforce_admins=null" -f "restrictions=null" -f "required_status_checks=null"
```

## 分支命名规范

| 来源 | 前缀 | 示例 |
|------|------|------|
| 移动端 Agent | `mobile/` | `mobile/fix-login-bug` |
| 内网功能分支 | `feat/` | `feat/ops-export` |
| 内网修复分支 | `fix/` | `fix/data-sync` |

移动端 Agent **只允许**推送 `mobile/` 前缀分支，不得直接推 main。

## PR 工作流（移动端 Agent）

### Agent 端（在 GitHub 上）

1. 从 main 创建 `mobile/<任务描述>` 分支
2. 提交代码变更
3. 创建 PR 到 main，PR 描述包含：
   - 改动摘要（做了什么、为什么）
   - 影响范围（涉及哪些模块/文件）
   - 测试情况（自测了什么）
4. 等待 Review

### 用户端（Review + Merge）

**方式一：GitHub Web UI（推荐简单场景）**

1. 在 GitHub 上 Review PR diff
2. 确认无误 → 点击 Merge PR
3. 回到内网本地：

```powershell
git pull github main        # 拉取合并后的代码
git push origin main         # 同步回 GitLab
```

**方式二：本地 Review + 合并（推荐复杂场景）**

```powershell
gh pr checkout <number>      # 检出 PR 分支到本地
# ... 本地测试、review ...
gh pr merge <number> --merge # 确认后合并
git pull github main
git push origin main
```

### 子模块 PR

Agent 改了子模块代码时，PR 在子模块的 GitHub 仓库上创建。合并后：

```powershell
cd <子模块目录>
git pull github main
git push origin main
cd ..
git add <子模块目录>
git commit -m "chore: sync <子模块> from GitHub PR #<number>"
git push origin main
```

## GitHub 仓库配置标准

每个仓库创建后需完成：

| 配置项 | 设置 |
|--------|------|
| Visibility | Private |
| Default branch | main |
| Branch protection (main) | Require PR, 禁止 force push, 禁止删除 |
| Wiki | 关闭（不使用） |
| Issues | 可选开启（用于移动端记录 TODO） |
| Actions | 暂不启用 |

## 安全规范

### Token 管理

- 使用 Fine-grained PAT（细粒度令牌），仅授权需要的仓库
- Token 权限：Metadata (Read-only, 自动包含) + Contents (Read and write) + Pull requests (Read and write)
- 不要把 Token 写入任何代码文件或 commit 历史
- 定期轮换（建议 90 天）

### 敏感文件

以下文件禁止出现在 GitHub 上（确保 `.gitignore` 覆盖）：

- `.env`（环境变量/密钥）
- `*.db` / `*.sqlite3`（本地数据库）
- `backend/data/*.json`（运行时数据）
- `__pycache__/`（编译缓存）

## 排障

| 问题 | 解决 |
|------|------|
| `git push` 到 GitHub 认证失败 | 运行 `gh auth setup-git` 刷新 credential |
| PR 无法 Merge（branch protection） | 确认 PR base 是 main，且从功能分支发起 |
| 子模块 clone 为空目录 | 确认 `.gitmodules` 用相对路径且子模块仓库已推送 |
| 仅推 tygit 后需要补镜像 | 网络或策略需要时，单独 `git push github main`（在对应仓库目录） |
| Cursor 云端 Agent 启动后端报错 | 确认 dev_mode 默认值或 `.env` 配置；参见 `dual-git-sync` Skill |
