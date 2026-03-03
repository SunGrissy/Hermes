# 双 Git 工作流迁移计划

> 创建日期：2026-03-03
> 状态：实施中（P-2, R-2, R-3 已完成，等待 P-1 密钥改造后首推）

## 1. 背景与目标

当前 MyAgents 仓库（含 5 个子模块）托管在内网 GitLab。为支持 **Cursor 云端 Agent（移动端）** 进行远程开发，需要在 GitHub 上建立 Private 镜像，实现双向开发协作。

**目标**：
- 内网 GitLab 保持日常开发主力地位
- GitHub 作为外网开发镜像，供 Cursor 云端 Agent 使用
- 一次 `git push origin` 同时推送两端
- 移动端 Agent 通过 GitHub 分支 + PR 参与开发

## 2. 架构设计

```
GitLab (内网, 主仓)  ←── 你的电脑 ──→  GitHub (外网, 开发镜像)
       ↑                                       ↑
    内网开发 push                         移动端 Agent push
       ↑                                       ↑
       └─── git push origin → 自动推两边 ──────┘
       └─── git pull github ← 拉取 Agent 成果 ─┘
```

**关键决策**：
- ~~GitLab Push Mirror~~（已否决：单向只读，不支持 GitHub 端开发）
- **采用双 Remote + 双 Push URL**：灵活、双向、支持 GitHub 端 Merge PR

## 3. 仓库清单

| 序号 | 项目 | GitLab URL | GitHub URL | 状态 |
|:---:|------|-----------|-----------|:----:|
| 1 | MyAgents (父) | `management-hub.git` | `https://github.com/SunGrissy/MyAgents.git` | 已配置 |
| 2 | pm-system | `pm-system.git` | `https://github.com/SunGrissy/pm-system.git` | 已配置 |
| 3 | performeval | `performeval.git` | `https://github.com/SunGrissy/performeval.git` | 已配置 |
| 4 | cci_system | `cci_system.git` | `https://github.com/SunGrissy/cci_system.git` | 已配置 |
| 5 | task_reminder | `task_reminder.git` | `https://github.com/SunGrissy/task_reminder.git` | 已配置 |
| 6 | teamscore | `teamscore.git` | `https://github.com/SunGrissy/teamscore.git` | 已配置 |

全部为 **Private** 仓库，不初始化 README。

**已排除：** `workspace-docs` — 该目录有独立 `.git` 但不是子模块（未注册在 `.gitmodules`，父仓库 untracked）。属于本地管理规范文档库，无需镜像到 GitHub。

## 4. 实施阶段

### 阶段一：前置准备（可并行）

| 编号 | 任务 | 负责人 | 依赖 | 状态 |
|:---:|------|:------:|:---:|:----:|
| P-1 | 密钥外置化改造（pm-system config.py） | 后端工程师 | 无 | 已发需求，等待 |
| P-2 | 完善根目录 `.gitignore` | Agent | 无 | **已完成** |
| P-3 | GitHub 创建 6 个 Private 仓库 | 用户/Agent | 无 | **已完成** |
| P-4 | 安装配置 `gh` CLI + GitHub 认证 | 用户 | 无 | **已完成** |

**P-1 密钥外置化改造需求（发给后端工程师）：**

文件：`pm-system/backend/app/config.py`

| 字段 | 当前 | 改为 | 理由 |
|------|------|------|------|
| `secret_key` | 硬编码占位符 | 默认值 `"dev-only-unsafe-key"` | dev 可启动，生产必须通过 .env 覆盖 |
| `oidc_app_key` | 硬编码真实值 | 默认值 `""` | 代码已有空值守卫（L150） |
| `oidc_app_secret` | 硬编码真实值 | 默认值 `""` | 代码已有空值守卫（L186） |

配套：
- 新增 `.env.example` 模板（提交到 git）
- 在 `main.py` 中添加启动校验（非 dev_mode 时检查 secret_key 不是默认值）
- 上线后轮换 OIDC 密钥（让旧密钥失效）

**P-2 `.gitignore` 需补充项：**

```gitignore
__pycache__/
*.py[cod]
*.db
*.sqlite3
.env
venv/
.venv/
node_modules/
*.log
backend/data/
*.json.bak
```

### 阶段二：Remote 配置与首推

| 编号 | 任务 | 依赖 | 状态 |
|:---:|------|:---:|:----:|
| R-1 | 整理未提交文件并提交 | P-1, P-2 | 等待 P-1 |
| R-2 | 6 个仓库配置双 push URL + github remote | P-3 | **已完成** |
| R-3 | 修改 `.gitmodules` 为相对路径 + submodule sync | R-2 | **已完成** |
| R-4 | 首次推送（**子模块先→父仓库后**，见下方说明） | R-1, R-3 | 等待 R-1 |

**R-2 配置命令模板（每个仓库执行）：**

```powershell
git remote add github https://github.com/<user>/<repo>.git
git remote set-url --add --push origin <gitlab-url>
git remote set-url --add --push origin <github-url>
git remote -v  # 验证
```

**R-3 `.gitmodules` 目标格式：**

```ini
[submodule "pm-system"]
    path = pm-system
    url = ../pm-system.git
[submodule "performeval"]
    path = performeval
    url = ../performeval.git
[submodule "cci_system"]
    path = cci_system
    url = ../cci_system.git
[submodule "task_reminder"]
    path = task_reminder
    url = ../task_reminder.git
[submodule "teamscore"]
    path = teamscore
    url = ../teamscore.git
```

**R-4 首次推送顺序（关键）：**

父仓库的 gitlink 引用子模块的 commit hash。如果父仓库先推，GitHub 上子模块仓库还是空的，gitlink 指向不存在的 commit，`git clone --recursive` 会失败。

```powershell
# 第一步：5 个子模块逐个推送
cd pm-system   ; git push origin main ; cd ..
cd performeval ; git push origin main ; cd ..
cd cci_system  ; git push origin main ; cd ..
cd task_reminder ; git push origin main ; cd ..
cd teamscore   ; git push origin main ; cd ..

# 第二步：确认 5 个子模块都推送成功后，再推父仓库
git push origin main
```

### 阶段三：GitHub 端配置

| 编号 | 任务 | 依赖 | 状态 |
|:---:|------|:---:|:----:|
| G-1 | 6 个仓库配置 main 分支保护规则（Web UI） | R-4, P-4 | 待开始 |
| G-2 | 验证：Cursor 云端 clone + 子模块初始化 | R-4 | 待开始 |
| G-3 | 验证：dev_mode 启动后端应用 | G-2, P-1 | 待开始 |

**G-1 分支保护规则（首选 Web UI 配置）：**

GitHub Web UI: Settings → Branches → Add branch ruleset → `main`
- Require a pull request before merging: 开启
- Allow force pushes: 关闭
- Allow deletions: 关闭

### 阶段四：工作流验证

| 编号 | 验证场景 | 预期结果 |
|:---:|---------|---------|
| V-1 | 内网 commit + push origin | GitLab 和 GitHub 同时更新 |
| V-2 | GitHub 上创建 mobile/ 分支 + PR + Merge | PR 合入 GitHub main |
| V-3 | 本地 git pull github main | 拉取到 Agent 的改动 |
| V-4 | git push origin main | Agent 改动同步回 GitLab |
| V-5 | Cursor 云端 Agent clone + 子模块 | 所有代码可见 |

## 5. 日常操作速查

| 场景 | 命令 |
|------|------|
| 内网开发推送（自动双推） | `git push origin main` |
| 拉取 Agent 成果 | `git pull github main` → `git push origin main` |
| 拉取子模块 Agent 改动 | `cd 子模块` → `git pull github main` → `git push origin main` → `cd ..` → `git add 子模块` → commit → push |
| 查看双 push 配置 | `git remote -v` |

## 6. 安全保障

| 风险 | 对策 |
|------|------|
| GitHub 仓库泄露 | 全部 Private；token 仅授权必要仓库 |
| Agent 改坏主线 | GitHub main 分支保护，只能 PR 合入 |
| 密钥泄露 | config.py 外置化 + `.env` 在 .gitignore 中 + 上线后轮换密钥 |
| 两端改同一文件冲突 | 内网主力开发，Agent 做小修；合入前先 pull 对方 |
| 子模块同步遗漏 | 每个子模块独立配双 push URL |

## 7. 相关文档

| 文档 | 位置 | 用途 |
|------|------|------|
| 双 Git 同步 Skill | `~/.cursor/skills/dual-git-sync/SKILL.md` | Agent 同步操作指南 |
| GitHub 操作规范 Skill | `~/.cursor/skills/github-ops/SKILL.md` | GitHub 端操作标准（gh CLI、PR 工作流、分支保护） |
| Git 工作流规范 | `.cursor/rules/git-workflow.mdc` | 提交、验收流程 |
| 分支安全协议 | `.cursor/rules/git-branch-guard.mdc` | 多会话分支保护 |
