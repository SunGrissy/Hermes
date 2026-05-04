# My Army Git Workflow Guide

## 1. 架构概览

本项目采用 **Root Repository + Submodules** 的架构来管理"My Army"的所有模块。

- **Root Repo (`d:\MyAgents`)**: 总司令部。不直接包含代码，只追踪各子模块的版本（Commit Hash）。代表系统的"Total Score"（总进度）。
- **Submodules**: 各个独立的作战单元（如 `gamedev-pm-system`, `align-flow`）。它们是独立的 Git 仓库，拥有完整的 commit 历史。

## 2. 日常开发流程

### 2.1 准备工作 (Sync)

在开始工作前，确保你的环境是最新的：

```bash
# 1. 更新总司令部
cd d:\MyAgents
git pull origin main

# 2. 更新所有子模块到总司令部指定的版本
git submodule update --init --recursive
```

### 2.2 开发 (Develop)

进入具体的模块进行开发，就像操作普通 Git 仓库一样：

```bash
cd d:\MyAgents\gamedev-pm-system

# 1. 检出分支 (确保不在 'detached HEAD' 状态)
git checkout main
# 或者创建新分支
git checkout -b feature/new-module

# 2. 开发、修改代码...
# (持续迭代，暂不提交)
```

### 2.3 提交 (Commit) - 用户主动触发

**触发条件**: 用户明确说"请提交"时

```bash
cd d:\MyAgents\gamedev-pm-system

# 1. 维护工作日志 (WORK_LOG.md)
# Agent 自动添加本次工作的记录到日志文件

# 2. 提交所有变更（包括代码和工作日志）
git add .
git commit -m "feat: 完成新功能模块"
```

### 2.4 验收与集成 (Acceptance & Integrate) - 用户主动触发

**触发条件**: 用户明确说"验收通过"时

```bash
cd d:\MyAgents\gamedev-pm-system

# 1. 维护工作日志
# Agent 添加验收通过的记录

# 2. 提交当前分支（如果有未提交的修改）
git add .
git commit -m "feat: [功能描述] - 验收通过"

# 3. 切换到主分支并合并
git checkout master
git merge feature/new-module -m "chore: merge feature/new-module - 验收通过"

# 4. 回到总司令部更新子模块版本
cd d:\MyAgents
git add gamedev-pm-system
git commit -m "chore(gamedev-pm): 更新至验收节点"

# 5. (可选) 推送到远程
# git push origin main
```

## 3. 工作日志维护 (Work Log)

每个模块应维护 `WORK_LOG.md` 文件，记录开发进度和关键节点。

### 日志格式

```markdown
# Work Log - [模块名称]

## [日期] - [功能/任务名称]

**状态**: 开发中 / 提交 / 验收通过

**内容**:
- 完成的功能点1
- 完成的功能点2

**备注**: 
- 遇到的问题或技术决策
```

### Agent 自动维护时机

1. **用户说"请提交"时**: 添加提交记录
2. **用户说"验收通过"时**: 添加验收通过记录

## 4. 常用命令速查

| 目标 | 命令 |
|------|------|
| **查看总状态** | `git status` (在根目录) |
| **查看子模块状态** | `git submodule status` |
| **一键更新所有** | `git submodule update --remote` (拉取子模块的最新远程分支) |
| **重置子模块** | `git submodule update --init --force` (放弃子模块的修改，回到总仓库指定的版本) |

## 5. 注意事项

- **Detached HEAD**: 当你运行 `git submodule update` 后，子模块会处于 "Detached HEAD" 状态。**在开发前，务必先 `git checkout main` 或你的工作分支**。
- **原子性提交**: 尽量保持总仓库的提交干净，通常只包含 submodule 的版本更新。
- **用户触发**: 所有 Git 提交操作都需要用户明确发起（"请提交" 或 "验收通过"），Agent 不应自动提交。
- **日志先行**: 提交前必须先更新 WORK_LOG.md，记录本次工作内容。

## 6. 最佳实践

1. **小步迭代**: 频繁测试，但不急于提交
2. **明确触发**: 只在用户要求时提交代码
3. **日志完整**: 每次提交都要有工作日志记录
4. **验收规范**: "验收通过" = 日志更新 + 提交 + 合并到 master
5. **总仓库同步**: 验收通过后记得更新总仓库的子模块指针

---
**维护者**: AI Agent  
**最后更新**: 2025-12-04
