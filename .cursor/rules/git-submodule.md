---
description: Git submodule 操作规范
globs: ["**/*"]
---

# Git Submodule 操作规范

本项目使用 git submodule 管理多个子仓库。

## 仓库结构

```
MyAgent/                        ← 根仓库 (management-hub)
├── .gitmodules                 ← submodule 配置
├── PLAYBOOK.md                 ← 增长效能总纲
├── AGENT_TODO_*.md             ← Agent 任务书
├── performeval/                ← submodule: 绩效系统
├── pm-system/                  ← submodule: 管线系统
├── cci_system/                 ← submodule: 素材评分(发行用)
├── task_reminder/              ← submodule: 任务提醒
└── teamscore/                  ← submodule: 评估引擎
```

## 常用命令

```bash
# 查看所有子仓库状态
git submodule foreach 'git status --short && git log --oneline -1'

# 拉取所有子仓库最新代码
git submodule update --remote

# 提交根仓库（PLAYBOOK等根级文件变更后）
git add . && git commit -m "message"

# 提交子仓库（在子目录中操作）
cd performeval && git add . && git commit -m "message" && cd ..

# 提交子仓库引用更新到根仓库
git add performeval && git commit -m "update performeval ref"
```

## 注意事项

- 修改子仓库文件后，**先在子仓库内 commit**，再到根仓库 commit submodule 引用
- `PLAYBOOK.md` 和 `AGENT_TODO_*.md` 属于根仓库
- 不要在根仓库直接修改子仓库内的文件引用路径
- 推送时，先推子仓库，再推根仓库
