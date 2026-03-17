---
name: dual-git-sync
description: Dual-remote Git workflow for syncing between internal GitLab and GitHub. Covers remote configuration, dual push URL setup, bidirectional sync, submodule mirroring, and mobile Cursor Agent collaboration. Use when setting up GitHub mirrors, syncing repos between GitLab and GitHub, configuring dual push URLs, or coordinating mobile Agent development on GitHub.
---

# 双 Git Remote 同步工作流

本 Skill 覆盖 MyAgents 工作空间的 GitLab（内网主仓）+ GitHub（外网开发镜像）双 remote 协作流程。

> 提交时机、message 格式见 `git-workflow.mdc`；多会话分支安全见 `git-branch-guard.mdc`。本 Skill 不重复这些内容。

## 架构

```
GitLab (内网, 主仓)  ←─ 你的电脑 ─→  GitHub (外网, 开发镜像)
       ↑                                      ↑
    内网开发 push                        移动端 Agent push
       ↑                                      ↑
       └─── git push origin → 自动推两边 ─────┘
       └─── git pull github ← 拉取 Agent 成果 ┘
```

**核心设计**：`origin` 的 fetch 指向内网 GitLab，push 同时推 GitLab + GitHub。`github` remote 仅用于 pull Agent 改动。

## Remote 配置

### 父仓库 + 每个子模块都执行：

```powershell
# 添加 github remote
git remote add github https://github.com/<user>/<repo>.git

# 给 origin 配双 push URL
git remote set-url --add --push origin <gitlab-url>
git remote set-url --add --push origin <github-url>
```

### 验证（两步）

**第一步：检查 remote 列表**

```powershell
git remote -v
# 期望：
# origin  <gitlab>  (fetch)
# origin  <gitlab>  (push)
# origin  <github>  (push)     ← 双 push
# github  <github>  (fetch)
# github  <github>  (push)
```

**第二步：dry-run 确认双推送生效**

```powershell
git push origin main --dry-run
# 应看到两段输出，分别指向 GitLab 和 GitHub
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

### `.gitmodules` 使用相对路径

```ini
[submodule "pm-system"]
    path = pm-system
    url = ../pm-system.git
```

相对路径让 Git 根据父仓库 clone 来源自动拼接子模块 URL：内网 clone 走内网，GitHub clone 走 GitHub。

## 日常工作流

### A. 内网开发完，同步到 GitHub

```powershell
git push origin main
# origin 双 push URL → GitLab + GitHub 同时更新
```

**首次推送顺序**：子模块必须先于父仓库推送，否则 GitHub 上 gitlink 指向不存在的 commit，clone --recursive 会失败。日常增量 push 无此限制（commit 已存在）。

### B. 移动端 Agent 在 GitHub 开发

Agent 创建分支 `mobile/<任务名>` → 提交 → 创建 PR → Review 后 Merge 到 GitHub main。

GitHub main 分支配置保护规则：
- Require pull request before merging: **开启**
- Allow force pushes: **关闭**

### C. 回到内网，拉取 Agent 成果

```powershell
git pull github main
git push origin main    # 同步回 GitLab
```

### D. Agent 改了子模块代码

```powershell
cd pm-system
git pull github main
git push origin main
cd ..
git add pm-system
git commit -m "chore: sync pm-system submodule"
git push origin main
```

## 双 push 部分失败处理

内网推 GitLab 成功但外网推 GitHub 失败（网络问题）是最常见的异常场景。`git push origin` 其中一端失败时，另一端仍会成功。

```powershell
# 待网络恢复后，单独补推 GitHub
git push github main

# 如果是子模块，也需要进入子模块目录单独补推
cd pm-system ; git push github main ; cd ..
```

## 冲突预防

- 内网做主力开发，移动端 Agent 做小修/紧急修复
- Agent 始终走 `mobile/` 分支 + PR
- 合入前先 pull 对方最新代码
- 避免两端同时改同一文件

## GitHub 认证

GitHub 不支持密码推送，需要以下任一方式：
- **Personal Access Token (PAT)**：`https://<token>@github.com/<user>/<repo>.git`
- **SSH Key**：`git@github.com:<user>/<repo>.git`

PAT 方式可用 `gh auth setup-git` 自动配置 credential helper。

## 环境自动识别

Agent 通过 `git remote get-url origin` 判断当前 clone 来源，决定工作模式：

| origin URL 包含 | 环境 | 工作模式 |
|---|---|---|
| `tygit.tuyoo.com` | 内网（本地开发） | `git push origin` 双推，正常开发流程 |
| `github.com` | 外网（云端 Agent） | 走 `mobile/` 分支 + PR，不直接推 main |

## Cursor 云端 Agent 环境

云端 Agent 从 GitHub clone，无 `.env` 文件：
- 后端应用需 `DEV_MODE=true` 或 config 有 dev-safe 默认值
- 确保 `dev_mode=True` 时应用可无 `.env` 启动
- OIDC 等认证功能在 dev_mode 下自动跳过

## 首次推送检查清单

- [ ] `.gitignore` 完善（Python/Node 通用忽略项）
- [ ] 无硬编码密钥（config.py 密钥外置化完成）
- [ ] GitHub 6 个 Private 仓库已创建
- [ ] 父仓库 + 5 个子模块 remote 配置完成
- [ ] `.gitmodules` 改为相对路径
- [ ] 首次 `git push origin main`（触发双推送）
- [ ] GitHub main 分支保护规则已配置
- [ ] 验证：Cursor 云端 clone + dev_mode 启动正常
