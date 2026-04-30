# 四栈入口脚本索引（P0）

本文登记 **`MyAgents`、`D:\hermes`、`D:\OpenClaw`、`D:\OpenClaw2`** 中与日常运维相关的入口级脚本：根目录、`scripts/`、`tools/`（MyAgents）、以及明确的 Gateway 启动器。

**不在范围：** `node_modules`、`__pycache__`、依赖目录内 `.cmd/.ps1`；业务代码树中的海量 `.py`（仅列 `MyAgents/scripts` 与 `OpenClaw/scripts` 下的辅助脚本）。

**维护约定：** 新增或废弃入口脚本时，顺手改一行；密钥与机器路径以各仓本地 `.env` / `gateway.cmd` 为准，勿把密钥写入本文档。

**横向参考：** 端口与依赖见 `.cursor/skills/multi-service-orchestration/SKILL.md`；硅基编排背景见 `docs/silicon-legion-orchestration.md`。

**文档枢纽（需求 / 面试 / 会议等非运行时）：** `docs/DOC_HUB.md`、`docs/narrative/README.md`。

---

## 1. MyAgents（`D:\MyAgents`）

### 1.1 仓库根与子项目 `.bat`

| 路径 | 用途（简述） |
|------|----------------|
| `start_army.bat` | 启动 LLM Plotter（Streamlit）、AlignFlow 前后端、打开 `central-console\index.html`（与 PM 子项目无直接耦合，见脚本正文）。 |
| `pm-system\quick_start.bat` | PmSystem：拉起后端与前端（含 MD Reader / Palace 路径探测），常用日常入口。 |
| `pm-system\build_and_run.bat` | PM 构建并运行流程（发布/一体化脚本，按需使用）。 |
| `pm-system\package_minimal.bat` | PM 最小打包相关。 |
| `pm-system\backend\setup_env.bat` | PM 后端环境初始化。 |
| `performeval\run.bat` | 乘法绩效后端/站点启动入口（常见）。 |
| `performeval\watchdog.bat` | PerformEval 看门狗/守护相关。 |
| `cci_system\启动.bat` | CCI Streamlit 应用启动。 |
| `FileCleanerTool\run.bat` | 文件清理工具 GUI 入口。 |
| `silicon-legion\director\start.bat` | 硅基军团 Director 入口。 |
| `silicon-legion\scripts\start.bat` | 硅基军团脚本层总启（与 advisor 配合）。 |
| `silicon-legion\scripts\start_advisors.bat` | 拉起硅基顾问侧实例。 |
| `silicon-legion\advisors\acha\start.bat` | 顾问「阿茶」入口。 |
| `silicon-legion\advisors\miaomiao\start.bat` | 顾问「妙妙」入口。 |
| `silicon-legion\advisors\xiaomei\start.bat` | 顾问「小美」入口。 |
| `silicon-legion\advisors\xiaomei\start_clean.bat` | 「小美」清理后启动变体。 |

### 1.2 `tools\`（跨工具）

| 路径 | 用途（简述） |
|------|----------------|
| `tools\kimi-myagents.cmd` | 固定以 MyAgents 根为工作区调用 `kimi -w`。 |
| `tools\openclaw-start.ps1` | OpenClaw（`D:\OpenClaw`）网关前台启动：读 `.env` 中继密钥、`openclaw gateway --port 18789`。 |
| `tools\openclaw-apply-custom-llm.ps1` | 向 OpenClaw 写入自定义 LLM/兼容网关配置（配合自建后端）。 |
| `tools\check-claude-code-running.ps1` | 检测本机是否有 `claude.exe` 或 `node` 加载 `claude-code` 包。 |
| `tools\multica-dingtalk-bridge\run_bridge.ps1` | Multica 钉钉桥：启动桥接服务（常与计划任务/守护配合）。 |
| `tools\multica-dingtalk-bridge\run_multica_daemon_isolated.ps1` | 桥接进程隔离启动变体。 |
| `tools\multica-dingtalk-bridge\register_patrol_task.ps1` | 注册 Multica 巡逻相关计划任务。 |

### 1.3 `scripts\`（仓库根下辅助 `.py`）

| 路径 | 用途（简述） |
|------|----------------|
| `scripts\gen_interview_checklist.py` | 由简历/材料生成面试清单。 |
| `scripts\gen_ops_l3_interview_checklist.py` | L3 运营向面试清单生成。 |
| `scripts\game_review_ollama.py` | 游戏评审相关 Ollama 调用脚本。 |
| `scripts\notify_tao_daemon.py` | 通过 daemon/通道通知「涛哥」类工作流。 |
| `scripts\run_resume_preview_ollama.py` | 简历预览 + Ollama。 |

### 1.4 `dingtalk-desktop\`（钉钉通道与定时周边）

**守护与运维**

| 路径 | 用途（简述） |
|------|----------------|
| `dingtalk-desktop\restart_daemon.ps1` | `POST /shutdown` 后重启 `daemon.py`，并探测 `/health`。 |
| `dingtalk-desktop\run_daemon_health_notify.ps1` | Daemon 健康检查与通知逻辑。 |

**计划任务注册（`register_*.ps1` / `.cmd`）**

| 路径 | 用途（简述） |
|------|----------------|
| `register_version_digest_task.ps1` / `register_version_digest_task_elevated.cmd` | 版本摘要类任务计划注册（ elevated 变体需管理员）。 |
| `register_pipeline_notify_task.ps1` / `register_pipeline_notify_schtasks.ps1` | 管线/流水线通知任务注册。 |
| `register_evening_digest_task.ps1` | 晚间摘要任务注册。 |
| `register_memo_reminder_task.ps1` | 备忘录提醒任务注册。 |
| `register_work_report_assistant_tasks.ps1` | 日志助手（早报/周报素材等）相关任务注册。 |

**计划任务实际执行体（`run_*.ps1`）**

| 路径 | 用途（简述） |
|------|----------------|
| `run_daily_version.ps1` / `run_version_digest.ps1` | 按日版本/版本摘要执行。 |
| `run_daily_digest.ps1` / `run_evening_digest_both.ps1` | 日终/晚间摘要执行。 |
| `run_evening_pm.ps1` / `run_evening_pmo.ps1` | 晚间 PM / PMO Digest。 |
| `run_pipeline_notify_scheduled.ps1` | 定时管线通知跑批。 |
| `run_memo_reminder.ps1` | 备忘录提醒跑批。 |
| `run_work_report_assistant.ps1` | 日志助手跑批入口。 |

---

## 2. Hermes（`D:\hermes`）

### 2.1 根目录 `.bat`（硅基 / 顾问 Gateway）

| 路径 | 用途（简述） |
|------|----------------|
| `start_all.bat` | **批量启动**多个 Hermes Gateway（清理残留 PID、按实例拉起满满/阿茶/小美/妙妙等，脚本内注释为准）。 |
| `start_advisors.bat` | 启动 **PM / HR / Design** 三条 advisor：`hermes_cli\main.py gateway run`。 |
| `start_miaomiao.bat` | `HERMES_HOME=D:\hermes\miaomiao`，妙妙实例 `hermes gateway run --accept-hooks`。 |
| `restart_*_only.bat`（`manman` / `acha` / `xiaomei` / `miaomiao` / `dangdang`） | **仅重启**对应昵称实例（通常含杀旧进程、清 `gateway.pid`、再拉起）。 |
| `restart_acha.bat` | **注意：** 当前脚本内容为拉起 **PM advisor**（`D:\hermes\pm` + `hermes_cli gateway run`），与文件名「acha」不一致；若依赖语义命名请以实际脚本为准或择机改名。 |

### 2.2 根目录 `.py`（入口）

| 路径 | 用途（简述） |
|------|----------------|
| `start_manman.py` | 满满主 Gateway：读 `D:\hermes\.env` 中继密钥，`venv\Scripts\hermes.exe gateway run --accept-hooks`，新开控制台。 |
| `start_all_gateways.py` | 为 **pm / hr / design** 目录分别拉起 gateway，日志写入各目录 `gateway.log`。 |
| `start_acha.py` / `start_acha_debug.py` | 阿茶实例启动 / 调试启动。 |
| `kill_hermes.py` | 按路径清理 Hermes 相关残留进程（被多个 `restart_*` 调用）。 |

### 2.3 `scripts\`

| 路径 | 用途（简述） |
|------|----------------|
| `scripts\multica-patrol-collect.py` | Multica 巡逻采集相关脚本。 |

### 2.4 `hermes-agent\scripts\`（安装类，非日常启停）

| 路径 | 用途（简述） |
|------|----------------|
| `hermes-agent\scripts\install.cmd` / `install.ps1` | Hermes Agent 安装/依赖初始化（装机一次）。 |

### 2.5 Skill 包内副本（易与根目录重复）

| 路径 | 用途（简述） |
|------|----------------|
| `skills\silicon-legion\silicon-legion-boot\scripts\start_all.bat` | Skill 携带的硅基批量启动脚本；**日常以根目录 `start_all.bat` 为准**，避免双维护。 |

---

## 3. OpenClaw（`D:\OpenClaw`）

### 3.1 根目录

| 路径 | 用途（简述） |
|------|----------------|
| `gateway.cmd` | **官方网关包装**：设置 `OPENCLAW_*` 状态目录与端口 **18789**，调用全局 `openclaw ... gateway`（密钥与路径以本机文件为准，勿入版本库）。 |

### 3.2 `scripts\` — 启动 Hermes / 满满链路的 `.bat`

| 路径 | 用途（简述） |
|------|----------------|
| `scripts\start_hermes.bat` | 从 OpenClaw 侧拉起 Hermes 相关进程（路径指向 `D:\hermes`）。 |
| `scripts\start_xiaoma.bat` | 小玛 / 相关实例启动入口。 |
| `scripts\start_miaomiao.bat` | 妙妙实例启动。 |
| `scripts\start_manman.bat` | 满满：`hermes gateway run --replace`。 |
| `scripts\start_manman_verbose.bat` | 满满启动（verbose 变体）。 |
| `scripts\start_manman_hermes.bat` | 满满 + Hermes 组合场景。 |
| `scripts\start_manman_myagents.bat` | 满满与 MyAgents 工作区联合场景。 |
| `scripts\hermes_terminal.bat` | 打开 Hermes 调试终端上下文。 |

### 3.3 `scripts\` — 健康检查 / 计划任务 / Git

| 路径 | 用途（简述） |
|------|----------------|
| `scripts\hermes-healthcheck.ps1` | 检查满满/阿茶/小美/妙妙 `gateway_state.json` 等并汇总告警。 |
| `scripts\openclaw-watchdog.ps1` | 探活 `http://127.0.0.1:18789/health`，失败则尝试重启网关；配计划任务（脚本头注释）。 |
| `scripts\register-openclaw-watchdog.cmd` | 注册上述 watchdog 计划任务。 |
| `scripts\is-workday.ps1` | 是否工作日判定（供其它任务调度使用）。 |
| `scripts\git-status-check.ps1` / `git-status-check.cmd` | Git 工作区状态检查。 |
| `scripts\register-git-status-check.cmd` | 注册 Git 状态检查计划任务。 |

### 3.4 `scripts\` — 排障 / 辅助 `.py`

| 路径 | 用途（简述） |
|------|----------------|
| `scripts\search_bridge.py` | 在妙妙 `agent.log` 中搜 bridge / inbound 相关行。 |
| `scripts\check_missed.py` | 按时间戳在 `agent.log` 中截取 inbound 上下文（漏单排查）。 |
| `scripts\check_miaomiao.py` | 妙妙实例检查脚本。 |
| `scripts\check_client_ids.py` | 客户端 ID 配置检查。 |
| `scripts\diff_env.py` | 环境变量/配置 diff。 |
| `scripts\recent_myagents.py` | 列举 MyAgents 近期修改文件（12h 内，排除常见大目录）。 |
| `scripts\recent_files.py` | 通用近期文件列举（实现类似 `recent_myagents`）。 |
| `scripts\test_kimi_key.py` | Kimi Key 探测/校验脚本。 |

---

## 4. OpenClaw2（`D:\OpenClaw2`）

| 路径 | 用途（简述） |
|------|----------------|
| `gateway.cmd` | 第二套 OpenClaw 网关：状态目录 **`D:\OpenClaw2`**，端口 **18790**，与 `D:\OpenClaw`（18789）并存；调用全局 `openclaw gateway`。 |

**说明：** 当前目录下**无**与 `OpenClaw\scripts` 对等的 `scripts` 子目录；辅助脚本以 `D:\OpenClaw\scripts` 或 Hermes/MyAgents 侧为准，或后续再抽到此仓。

---

## 5. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-30 | 初版：四栈 P0 入口索引（按目录枚举 + 抽样读脚本）。 |
