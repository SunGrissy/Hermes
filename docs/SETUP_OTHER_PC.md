# 另一台电脑：环境同步指南

> 适用场景：另一台电脑已有 MyAgent 目录（含子仓库），需要同步为 management-hub submodule 架构。
>
> 前提：子仓库不比本机更新，根目录有其他文件需要保留。

---

## Step 1：备份根目录的其他文件

```bash
cd /到/MyAgent所在的父目录/
mkdir MyAgent_backup
cp MyAgent/*.* MyAgent_backup/
```

> 如果根目录下有子文件夹也要保留，按需手动拷贝到 backup。

## Step 2：确认子仓库没有未推送的 commit

```bash
cd MyAgent
for dir in performeval pm-system cci_system task_reminder teamscore; do
  echo "=== $dir ==="
  (cd "$dir" && git status --short && git log --oneline -1)
done
```

> 如果某个子仓库有未 push 的变更，先处理：
> ```bash
> cd 那个子目录
> git add . && git commit -m "sync local changes" && git push
> cd ..
> ```

## Step 3：删除旧目录，重新 clone

```bash
cd ..
rm -rf MyAgent
git clone --recurse-submodules http://tygit.tuyoo.com/ue4_pm_group/management-hub.git MyAgent
```

## Step 4：拷回备份的其他文件

```bash
cp MyAgent_backup/* MyAgent/
```

## Step 5：验证

```bash
cd MyAgent
git submodule status              # 5个子仓库都应显示 commit hash
ls PLAYBOOK.md                    # 增长效能总纲
ls .cursor/rules/                 # session-focus.mdc + git-submodule.md
ls AGENT_TODO_*.md                # 两份 Agent 任务书
```

## Step 6：清理备份

确认一切正常后：

```bash
rm -rf MyAgent_backup
```

---

## 日常同步命令速查

```bash
# 拉取所有子仓库最新
git submodule update --remote

# 查看所有子仓库状态
git submodule foreach 'git status --short && git log --oneline -1'

# 拉取根仓库最新（PLAYBOOK、任务书等）
git pull origin main
```
