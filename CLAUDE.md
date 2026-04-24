# MyAgents 工作空间（Claude Code 登机简报）

本文供 **Claude Code** 或其它终端侧工具在进入本仓库时快速对齐上下文。**完整流程与细节**以 Cursor 规则与 Skill 为准，避免在此文件双写长文以免漂移。

---

## 1. 定位

本仓库是「游戏研发自动办公军团」**总司令部**：多个**相互独立**的工具与文档子项目并列，**默认不做跨项目 API 调用**。改动前先确认目标目录属于哪个子项目。

---

## 2. 子项目目录速查

| 目录 | 说明 | 常见入口 |
|------|------|----------|
| `pm-system/` | 游戏项目管理（PmSystem）；PM 主数据、版本规划 | `index.html`、`backend/main.py` |
| `performeval/` | 乘法绩效评价 | `index.html`、`backend/main.py`（常用端口 8112） |
| `cci_system/` | 素材竞争力 CCI | `app.py`（Streamlit） |
| `task_reminder/` | 任务提醒 + 钉钉推送 | `server.py`、`TaskReminder.html`（常用端口 8000） |
| `FileCleanerTool/` | 文件清理桌面工具 | `gui.py` |
| `teamscore/` | 团队评分脚本（M12 等） | 各子目录 `.py` |
| `dingtalk-desktop/` | 钉钉桌面消息通道（基础设施） | `daemon.py`（常用端口 19200） |
| `palace/` | 内部引擎/脚本与相关物料 | 按任务进入子目录 |
| `tools/` | 桥接脚本、第三方工具克隆等 | 如 `tools/multica-dingtalk-bridge/` |
| `workspace-docs/` | 管理规范文档 | `README.md` |
| `面试/interviews/` | 面试清单与评价材料 | 按候选人子目录存放 |
| `docs/` | 跨项目文档 | 按需 |

**独立 Git 仓库（父仓 `.gitignore` 常忽略或子模块管理，勿当普通子文件夹乱提交）：**

- `novel/`：小说正文与设定（远端以团队约定为准）。
- `roi-forecast/`：ROI Streamlit（独立维护）。

---

## 3. 关键约定（与业务相关）

- **对外消息通道**：各系统需要发钉钉时，通过 HTTP 调用 **dingtalk-desktop** 的 daemon API；不要假设其它子项目内置钉钉发送链路。
- **工作日志**：根目录 `WORK_LOG.md` 记录跨项目级工作日志；子项目内也可能有各自的 WORK_LOG。
- **启动**：根目录 `start_army.bat` 用于批量启服务（以本机环境为准）。
- **Cursor Agent 深度手册**：`pm-system/AgentReadMe.md`、`performeval/AgentReadMe.md`（若任务涉及对应项目）。
- **Skill 单一真源**：`.cursor/skills/README.md`；详细步骤以各 `SKILL.md` 为准。

---

## 4. Windows / PowerShell 执行习惯

- 命令串联使用 **`;`**，不要使用 **`&&`**（当前环境为 PowerShell）。
- Python 启动优先使用 **`py`**。
- 控制台输出**避免 emoji**，以免在 GBK 等编码下触发编码错误。

---

## 5. Git 与提交（红线摘要）

- **禁止**在未获用户明确指令时执行 `git commit` / `git push` / 分支切换 / `merge` / `rebase`。**多工具或多会话共享同一工作区时**，不要擅自 `checkout` 改分支；若用户要求切分支，需先确认脏工作区已处理。
- **禁止** `push --force`、`reset --hard`、`clean -fd`，除非用户逐字要求对应危险操作。
- 存在 **子模块** 时：推送顺序与指针同步见 `.cursor/rules/shell-git.mdc` 与 `acceptance-checklist.mdc`；避免只推父仓不推子模块。
- 提交前若本次任务涉及代码交付：按 `.cursor/rules/agent-core.mdc` 检查 **WORK_LOG.md** 等门禁；验收口令与完整清单见 `.cursor/rules/acceptance-checklist.mdc`。

---

## 6. 「工作日」口径

凡文档或脚本中出现「工作日、是否上班、上一工作日」等，**默认与 PmSystem 假日/调休数据一致**，不可简单等价于「周一到周五」。实现或排查时优先对齐 PM 日历接口与主数据（见 `.cursor/rules/pm-work-calendar.mdc`）。

---

## 7. 沟通与语言

- 对用户/团队输出：**简体中文**。
- 立场与措辞：内部材料用 **「我们」** 等主人翁表述，避免把己方团队说成「你们」；细则见 `.cursor/rules/digital-twin-voice.mdc`。

---

## 8. 需要细节时读哪里

| 主题 | 路径 |
|------|------|
| 全局地图与列表口径 | `.cursor/rules/workspace-map.mdc` |
| Shell/Git/推送 | `.cursor/rules/shell-git.mdc`、`git-workflow.mdc`、`git-branch-guard.mdc` |
| 编辑后门禁、提交前检查 | `.cursor/rules/agent-core.mdc` |
| 验收全流程 | `.cursor/rules/acceptance-checklist.mdc` |

修改本文件时：**只保留「终端侧易漏」的摘要**；长 SOP 仍放在 `.cursor/rules` 与 Skills 中维护。
