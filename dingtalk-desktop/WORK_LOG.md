# dingtalk-desktop WORK_LOG

## [2026-04-20] 简历初筛：多 contentType、PDF 双解析、读失败自动重试

### 状态：已提交推送

### 本次工作内容

- `skill_router.py`：`_RESUME_FILE_CONTENT_TYPES`（501/502/503/2001）；`_read_pdf_text` 缺 pdfplumber 时用 pypdf；轮询前 `clear_resume_infra_read_fail` 清除「简历文件读取失败」类跳过记录以便重试
- `skills/resume_screen.py`：PDF 优先 pdfplumber、后备 pypdf
- `db/store.py`：`clear_resume_infra_read_fail`
- `lib/monitor.py`：`_msg_log` 写入 raw 扩展至 501/502/503/2001
- `lib/utils.py`：`CT_NAMES` 补 501/502/503
- `requirements.txt`：`pdfplumber`、`pypdf`

---

## [2026-04-15] check_tracker：引用回复 TR 标注转跟进任务

### 状态：已验收，待推送

### 本次工作内容

- `skills/check_tracker.py`（新增）：TR 跟进任务主逻辑；解析引用回复格式、提取任务标题与 DDL、写入 TaskReminder、发 Webhook 确认
- `db/store.py`：新增 `check_items` 表及 CRUD（`get_next_check_seq`、`is_check_processed`、`save_check_item`）
- `skill_router.py`：在 push/poll 两条路径接入 check_tracker；P2P 私聊（CID 含 `:`）跳过 is_self 检查（JSAPI 路径该字段不可靠）；send 路径 msg_id=0 时补打 log 便于 debug；内容去重防双路径重复创建
- `digest_config.json`：`memo_tracker.check_tracker` 配置节（`allowed_cids`、`cid_names`）；`colleague_skill_cids` 新增车君怡私聊 CID

---

## [2026-04-14] 简历初筛：docx、监测 72h、运营策划招聘群文件名（保留 block）

### 状态：已提交推送

### 本次工作内容

- `skills/resume_screen.py` + `requirements.txt`：docx 解析；PDF 仍 pdfplumber
- `skill_router.py`：`_RESUME_FETCH_COUNT=50`；`resume_monitor_max_age_hours`；`_resume_bypass_filename_gate_cids`（73137527367 仅 `blocks_only`）；时间窗与 msg_ts；静默超窗
- `digest_config.json`：上述配置项与 `_note`
- `daemon.py`：`_BeaconServer` 内 `H.send_error` 忽略连接中止

---

## [2026-04-09] PMO晚报 / 管线晚报（pmo-evening、pm-evening）与傍晚 18:00 计划任务

### 状态：已推送

### 本次工作内容

- `version_digest.py`：`--mode pmo-evening`、`--mode pm-evening`；`message_templates.json` 中 `pmo_evening` / `pm_evening` 全文布局与配色；`digest_config.json` 晚间 webhook 键
- `run_evening_digest_both.ps1`（先 PMO 后管线）、`run_evening_pmo.ps1`、`run_evening_pm.ps1`
- `register_evening_digest_task.ps1`：计划任务 `MyAgents_EveningDigest_1800` 每日 18:00

---

## [2026-04-08] 日志助手定时汇总（work_report_assistant_run + 计划任务）

### 状态：已提交推送

### 本次工作内容

- `work_report_assistant_run.py`：四场景提示词、`/api/v1/chat`、回复分片、`send_result_webhook.py` 推送；周报素材/体验提炼/AI 周报格式与钉钉可读性迭代
- `work_report_assistant_roster.json`：汇总名单与技组口径
- `run_work_report_assistant.ps1`、`register_work_report_assistant_tasks.ps1`（Windows 计划任务四档）
- `docs/work-report-assistant.md`；`.cursor/skills/work-report-assistant/SKILL.md`
- `webhook_config.json.example`：补充 `hr` / `work_report_assistant` 键说明；本机 `webhook_config.json` 含 `hr` 不入库

---

## [2026-04-03] VersionDigest 定时 09:40 + 提权注册入口（elevated.cmd）

### 状态：脚本/文档已更新

### 本次工作内容

- `run_version_digest.ps1`、`register_version_digest_task.ps1`：**每日 09:40**（与产品「早间」一致）
- 新增 **`register_version_digest_task_elevated.cmd`**：双击经 UAC 提权后执行注册（非管理员终端下 `Register-ScheduledTask` 会拒绝访问）
- `docs/version-digest-morning.md`、`README.md`：补充定时任务与提权说明

---

## [2026-04-03] VersionDigest：注册脚本时间与 run_version_digest 对齐 + 文档说明「本机须管理员注册」

### 状态：已由当日后续条目覆盖（曾短暂改为 15:00，已回退 09:40）

### 本次工作内容

- （历史）`register_version_digest_task.ps1` 与 `run_version_digest` 对齐说明

---

## [2026-04-02] 早间 VersionDigest 行为文档化（version-digest-morning.md）

### 状态：文档已落库（代码变更见同周期会话）

### 本次工作内容

- 新增 **`docs/version-digest-morning.md`**：受众与版本过滤、PLD 单条 / 版本快报多条、footer 与「请 PM」相对顺序、详情链接、`--audience-sweep` 注意点、配置项与变更摘要
- **`README.md`**、**`版本与管线推送说明.md`**：增加该文档入口链接

---

## [2026-03-30] 待发变更入库：模板与简历技能、260330 可分发包、daemon_spawn、Webhook 说明

### 状态：已提交（待推送）

### 本次工作内容

- `message_templates.json`、`skills/resume_screen.py`：待发修改一并入库
- `dingtalk-desktop260330/`：独立可分发 skill 源码（不含 zip 构建产物）
- `lib/daemon_spawn.py`：守护进程拉起辅助
- `WEBHOOK_关键词说明.md`：机器人关键词说明

---

## [2026-03-26] 定时管线 + 专项 suffix：规划窗口 / 任务名 1945 / 管线待办本机覆盖接口

### 状态：待验收

### 本次工作内容

- `_push_versions_webhook_at_dm.py`：`--auto-scheduled` 排除 `phase=released`、管线发版已完成、`demand_pool`；规划 DDL **仅** `pipelineDdls.planning`（去掉 startDate-7 推算）
- **专项 / 定时推送**：拉到 `version-checklist-blocks` 后仍用本机 `render_pipeline_node_checklists_markdown` **覆盖**「管线节点待办」段，阻塞/关注与**本机 pm-system** 一致（不再被服务端旧逻辑带偏）
- `register_pipeline_notify_task.ps1` / `register_pipeline_notify_schtasks.ps1`：晚间任务名 **`MyAgents_PipelineNotify_1945`**，并清理旧名 **`_1615`**
- `版本与管线推送说明.md`：与上同步

---

## [2026-03-26] VersionDigest / 专项 Webhook：与 pm-system 管线待办语义对齐；子模块 a79ca66；根仓提交推送 tygit

### 状态：验收通过（已推送 tygit）

### 本次工作内容

- `_push_versions_webhook_at_dm.py`：合并冲突已解决；`pm-system` 子模块已推送并与需求池五维健康、`render_demand_pool_version_block_markdown` 行为一致
- 文档：`README.md`、`版本与管线推送说明.md`；`WORK_LOG` 条目收口

---

## [2026-03-25] 查岗/上班啦/修复：列表摘要、口令始终回执、大门自检与查岗对齐

### 状态：验收通过（已推送 tygit）

### 本次工作内容

- **status_check**：查岗/上班啦 **始终 webhook**（全绿也推）；异常项 **列表+emoji**；**修复** 先推「已收到」、`run_repair_flow` 分离子进程 `daemon_health_notify`；**上班啦** 展示 **本次拉起已恢复** / **需关注**
- **skill_router**：「修复」「查岗」「上班啦」路由与日志与上述一致
- **daemon_health_notify**：`analyze_health` 纳入 `monitor_running`/`dingtalk_running` 与查岗一致；未通过时提示看控制台/stdout/stderr
- **message_templates**：`repair_ack`、`intro_inspection_all_ok`、`title_inspection_all_ok`、`title_morning_all_ok`、`intro_morning_all_ok*` 等

---

## [2026-03-25] 定时筛选：规划 DDL <=28 天或已到期；digest 全局 APM

### 状态：验收通过（已推送 tygit）

### 本次工作内容

- `_push_versions_webhook_at_dm.py`：`--auto-scheduled` 筛选改为规划 DDL **距今 <=28 天或已过期**、且未发版（去掉 -14 天下限）；`@` 顺序 **PM+APM**+PLD+PLE+PLT+PLQA
- `digest_config.json`：`default_pipeline_apm_user_id` = `u079`（屈丽茹），PM 仍为 `u021`（张梦君）

---

## [2026-03-25] 定时管线提醒：--auto-scheduled、默认 Webhook、注册计划任务脚本

### 状态：验收通过（已推送 tygit）

### 本次工作内容

- `_push_versions_webhook_at_dm.py`：`--auto-scheduled`（规划 DDL 距今 -14～28 天且未发版）；Webhook 空则用 `webhook_config.json` → `default`；`@` PM+PLD+PLE+PLT+PLQA
- `run_pipeline_notify_scheduled.ps1`：日志写入 `logs/pipeline_scheduled_YYYYMMDD.log`
- `register_pipeline_notify_schtasks.ps1`：周一至周六 9:15 / 19:45 注册示例（管理员执行一次）

---

## [2026-03-25] skill_router：助理群白名单、手机消息轮询、/fetch 超时与 daemon HTTP

### 状态：验收通过（已推送 tygit）

### 本次工作内容

- **skill_router**：助理主群 `assistant_group_skill_uids` + `assistant_group_skill_aliases` 与显示名/通讯录归一；`_message_sender_identity`（uid / is_self / sender / `?`→本人）；Frida 有 `memo_queue` 时仍周期 `_poll_memo_once`（手机消息）；今日/明日/本周关注 `_RECENT_FOCUS_CMD_MS`；`/fetch` POST 带 `timeout`、默认备忘拉取约 95s；可选 `SKILL_ROUTER_MEMO_POLL_TRACE`、`SKILL_ROUTER_POLL_HEARTBEAT_MS`
- **daemon**：`POST /fetch` 解析 `timeout` 传入 `fetch_history`；`DaemonHandler.send_error` 捕获对端已断开，避免 WinError 10053 刷屏
- **digest_config**：`assistant_group_skill_uids`、`assistant_group_skill_aliases` 与说明
- **同期已纳入本提交**：`db/store.py`、`lib/utils.py`、`skills/doc_review.py`、`skills/memo_tracker.py`、`version_digest.py`（当期本地修改）

---

## [2026-03-24] 专项推送：默认数据源 digest（192 PM）+ 0401 并入 _push

### 状态：验收通过

### 本次工作内容

- `digest_config.json`：`pm_system_url` 指向内网 192 PM（`http://192.168.20.160:8112`），作为 version_digest / 专项推送默认信息源
- `_push_versions_webhook_at_dm.py`：PM 基址顺序 `--pm-url` > `digest_config.pm_system_url` > `PM_SYSTEM_URL` > 172 兜底；默认任务含五一版、五月中、0401；`--only` / `--report`
- `_send_0401_remote_version_webhook.py`：调用 `_push_versions_webhook_at_dm.py --only <版本名>`，保留互斥锁与冷却
- `run_daily_version.ps1`：A2 跑 `_push_versions_webhook_at_dm.py`（定时任务由本机计划任务另行配置）

---

## [2026-03-24] version_digest：拉 users + Webhook @ 手机号；run_daily_version.ps1

### 状态：待验收

### 本次工作内容

- `version_digest.py`：`GET /api/data` 取 `users`，按版本 `_pld/_ple/_plt` 汇总 `dingtalk_mobile`；正文追加 `@手机号`；`send_via_webhook` 增加 `at`/`atMobiles`
- `run_daily_version.ps1`：串联 `version_digest.py` 与 `_send_0401_remote_version_webhook.py`（可按需改版本名）

---

## [2026-03-20] 备忘提醒任务脚本、status_check、monitor/utils/skill_router 调整

### 状态：已提交推送（父仓）

### 本次工作内容

- `lib/monitor.py`、`lib/utils.py`：通道/监控相关调整
- `skill_router.py`：路由逻辑调整
- `memo_reminder.py`、`register_memo_reminder_task.ps1`、`run_memo_reminder.ps1`：备忘提醒定时任务
- `skills/status_check.py`：状态检查 skill

---

## [2026-03-21] 日报拉取、定时任务、通道自检、简历 fetch 超时

### 状态：验收通过

### 本次工作内容

- **report_digest**：`time` 导入；CEF 全文 `_report_body` 优先；`--fetch-only` + `--window overnight-morning` / `--after` `--before`；与 `--full-content` 组合发 default 全文（单条上限 12k 字）；`--notify-default` 仅保留阶段节点通知
- **run_daily_digest.ps1**：`Start-Process`+`Wait-Process` 超时、钉钉进度/失败 Markdown
- **restart_daemon.ps1**、**daemon_health_notify.py**、**run_daemon_health_notify.ps1**：daemon 健康检查、重启、default webhook 结论
- **skill_router**：`_poll_once` 调 `/fetch` 超时改为 75s（对齐 hydrate）
- **message_templates.json**、**digest_config.json**：日报 LLM `text_limit` 等

---

## [2026-03-20] 快捷指令：人员筛选、选题独立号、桌面运维、双发去重

### 状态：验收通过

### 本次工作内容

- **人员关键词**：`person_lookup_aliases`；群内「洋哥」「找崔哥」等列出备忘+愿望；路由 15s 关键词节流 + `_MEMO_THROTTLE_LOCK`
- **选题**：`topic_items` + TR `topic:#N`，与 `memo_seq` 独立；`topic_pick_confirm` / `topic_duplicate`；TR 同步闭环 topic
- **备忘**：改描述/版本/指派全文去重（`_EDIT_CMD_DEDUP_LOCK`、与路由一致的零宽/繁体归一）；指派正则「指派给」、who 去冗余「给」
- **桌面运维**（`desk_ops`）：检查大门（`daemon_health_notify --no-webhook`）、重启大门（`desk_ops_restart` 分离进程）、拉日报（`--full-content --notify-default`）；`desk_ops_enabled`
- **脚本**：`daemon_health_notify.py` 增加 `--no-webhook`；`report_digest` / `version_digest` / `run_daily_digest.ps1` 与进度通知、定时说明同期维护

---

## [2026-03-19] 预审技能 + 推送缓存 + 强制重跑 + 助理群入队

### 状态：验收通过

### 本次工作内容

- `skills/doc_review.py`：文档预审（钉钉文档抓取 + Palace），同一文档短时去重；支持「再预审」等跳过去重
- `skill_router.py`：预审口令扩展；助理群最近文档 URL 推送缓存，预审优先不走 fetch；与备忘同队列消费
- `daemon.py`：助理群消息一律可入 `memo_event_queue`（避免 MY_UID 不一致导致备忘/预审无推送）
- `message_templates.json`：预审文案与「强制重跑」提示

---

## [2026-03-19] 备忘推送立刻响应 + 删除/今日关注 + cursor-to-dingtalk 编码

### 状态：验收通过

### 本次工作内容

#### 1. 备忘/完成/删除 走推送立刻响应
- daemon：`memo_event_queue`，monitor 写日志时 `on_record` 推队列；`start_router(queue)` 传入 skill_router
- lib/monitor：`_display_and_log` / `_process_push` 支持 `on_record` 回调
- skill_router：`_memo_push_loop` 消费队列，`_dispatch_one_message` 单条处理；备忘群不再轮询，仅简历/文档预审轮询

#### 2. 删除 memo N
- 指令：`删除memo N` / `删除备忘 N`；store 新增 `delete_memo_item`（status=deleted）；TR 从列表移除对应任务
- 已删状态回复「已是删除状态」；成功删除注明「TR 已同步删除」或「TR 中未找到对应任务或已删除」

#### 3. 今日关注语义
- 发「今天我要关注啥」/「今天关注啥」→ 列出到期日≤今天的备忘（超期+今日到期），编号可读排版；模板 today_focus_title/empty/item

#### 4. TR 一条只对应一条备忘
- `_create_task_in_reminder` 的 note 只保留 `memo:#{seq} source:dingtalk`，不写入上文 context

#### 5. cursor-to-dingtalk 中文问号修复
- send_result_webhook.py：stdin 用 `stdin.buffer.read().decode('utf-8')`；`json.dumps(ensure_ascii=False)`；请求头 `charset=utf-8`
- SKILL.md：管道前设 `$OutputEncoding = [System.Text.Encoding]::UTF8`

---

## [2026-03-18] 应届生初筛分支

### 状态：验收通过

### 本次工作内容

#### 1. 应届生识别
- `_is_fresh_graduate(file_name, text)` — 启发式判断：匹配「应届/在读/预计毕业」关键词 + 近2年/未来1年毕业年份
- 主流程传入 `is_fresh`，影响 checklist 加载、prompt 生成、消息格式

#### 2. 应届专用 checklist
- 新建 `performeval/面试/简历初筛/简历初筛清单_应届生.md`：思维/潜力/热情导向
- 红线宽松化，待定标准宽松化；岗位清单作为非硬性补充附后

#### 3. 应届专用 LLM prompt
- 专用 system prompt：不卡经验年限，关注思维逻辑/游戏热情/学习速度
- 输出格式新增「潜力信号」字段，替换社招的「亮点」

#### 4. 消息模板扩展
- `version_digest_template.json` 新增 `title_fresh`、`fresh_lines`、`footer` 字段
- 应届消息标题含"应届"标识，内容行展示「潜力信号」而非「亮点」
- `_load_footer()` 优先读 `resume_screen.footer`，隔离全局 footer

---

## [2026-03-18] 简历初筛推送优化

### 状态：验收通过

### 本次工作内容

#### 1. 推送通道改为机器人 webhook
- `digest_config.json` 新增 `resume_notify_webhook` 字段，存放机器人 webhook URL
- `resume_screen.py` 新增 `_send_via_webhook(title, text)` 函数，发送 markdown 类型消息
- 不再依赖 JSAPI `sendTextMsg`，消息更稳定

#### 2. 消息格式升级（markdown）
- 消息类型从 `text` 改为 `markdown`，支持加粗、分割线、标题级别
- "通过/待定/不通过"统一走 `_format_reply`，返回 `(title, text)` 元组
- 待定标记从 ❌ 改为 ❓，"小秘书提醒"作为 `<font>` 角标置于底部

#### 3. 消息模板提取到 version_digest_template.json
- `version_digest_template.json` 新增 `resume_screen` 段，含 `title`（三种结论）和 `lines`（字段顺序/显隐/文案）
- `_format_reply` 实时读取模板文件，热更新无需重启 daemon
- LLM prompt 新增"核心判定"字段（≤20字一句话），替代原来过长的"原因"字段

---

## [2026-03-17] 日报摘要管线全面打通

### 状态：已验收

### 本次工作内容

#### 1. 日报采集与分析管线（report_digest.py）

- **时间窗口**：从"当天 00:00-23:59"改为"当天 18:30 → 次日 12:00"，覆盖晚间提交和隔夜补交，实际采集条数从 10 条提升至 21 条
- **完整内容抓取**（`--full-content`）：新增 `fetch_report_content` 调用，LLM 分析改为基于完整日报正文而非消息摘要
- **提交人数计算修正**：`submitted_count` 改为只统计 `team_members` 中的提交者，解决"7+17≠22"问题
- **LLM prompt 补充规则**：同一人在多个群提交日报属正常行为，不标记为重复提交
- **消息格式优化**：替换不渲染的 emoji，改用【总览】【关注】等文字标记
- **Webhook 支持**：新增 `send_via_webhook`，优先于 daemon 一人群发送；发送时自动添加安全关键词"小秘书提醒"
- **摘要标题加时间窗口**：显示"3/17 18:30 - 3/18 12:00"，收件人清楚覆盖范围

#### 2. daemon.py 稳定性修复

- **browser 隔离（关键修复）**：`fetch_report_content` 始终用 browser 1，用前读取当前 URL，用完恢复到 `about:blank`（不恢复到 advancedSearch.html，否则触发搜索栏 UI 弹出）
- **移除破坏性探测**：删除了对 browser 2~8 调用 `load_url(about:blank)` 进行测试的逻辑，防止破坏文档面板等可见 UI
- **`/debug/scan_browsers` 修复**：改为只列出 browser ID + browser 1 当前 URL，不再对所有 browser 做导航测试
- **report card 正则扩展**：`_normalize_report_card` 支持提取"周报""月报"发送人姓名
- **`send_digest` 支持 CID 直传**：`notify_target` 为纯数字时直接用 `cid` 参数，避免 emoji 群名解析失败

#### 3. 配置更新（digest_config.json）

- `team_members` 更新为 23 人（新增杨玉涛）
- `report_cids` 新增：崔哥日报直通车、鹏锐汇报直通车、君怡日报直通车、杨琳汇报直通车、涛哥日报直通车
- `notify_target` 改为直接 CID（73216314617）
- 新增 `webhook_url` 字段

#### 4. 定时任务（run_daily_digest.ps1）

- 每天 09:00 执行，自动检测 daemon 状态并在必要时重启
- 跑完后通过 webhook 发送到"🐱助理通知"群

### 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `report_digest.py` | 时间窗口、webhook、计算修正、格式优化 |
| `daemon.py` | browser 隔离、UI 保护、正则扩展 |
| `digest_config.json` | 成员列表、群 CID、webhook URL |
| `run_daily_digest.ps1` | 新增定时任务脚本 |
| `WORK_LOG.md` | 本文件 |

---

## [2026-03-18] 简历 AI 初筛 + DB 持久化

**状态**：验收通过

### 新增功能

1. **DB 持久化层**（`db/store.py`）：SQLite 封装，三张表（reports / digest_runs / resume_screen_log）
2. **简历 AI 初筛技能**（`skills/resume_screen.py`）：监听招聘群 ct=502 PDF 消息，pdfplumber 读文本，调 LLM（relay.tuyoo.com / claude-opus-4.6），仅「通过」时发群消息并入库
3. **技能路由器**（`skill_router.py`）：后台轮询线程（60s），内存去重防重复调 LLM
4. **daemon.py 扩展**：新增 `/exec_js` 自定义 JS 执行端点，启动时启动 SkillRouter
5. **digest_config.json**：新增 `recruit_cids` 字段（当前为测试群，待替换为正式招聘群 CID）

### 关键技术结论

| 结论 | 说明 |
|---|---|
| ct=502 文件已在本地磁盘 | DingTalk 收文件时自动缓存到 `D:/DownLoads/`，无需单独下载 |
| quoteMessage 需群窗口打开 | 后台 browser 调用报 -50，降级为普通 sendTextMsg |
| 待定/不通过不写 DB | 用内存 set 去重，防止重启后反复调 LLM |

### 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `db/__init__.py` | 新增 |
| `db/store.py` | 新增 |
| `skills/__init__.py` | 新增 |
| `skills/resume_screen.py` | 新增 |
| `skill_router.py` | 新增 |
| `daemon.py` | 新增 `/exec_js` 端点 + 启动 SkillRouter |
| `digest_config.json` | 新增 `recruit_cids` 字段 |

---

## [2026-03-18] 消息模板统一 + P2P监控扩展（验收通过）

### 变更说明
- 另一个 Agent 将 `version_digest_template.json` 合并入统一模板 `message_templates.json`
- `resume_screen.py` 改为优先读 `message_templates.json`，兼容旧文件名
- `digest_config.json` 新增笛笛（杨柳笛）私信 CID（`46459012:300405507`）
- 追加：李军私信 CID（`46459012:153460168`）已加入 recruit_cids
- 追加：李晓明、Jojo吴娇娇、朱慧敏、王姣莉私信 CID 全部加入 recruit_cids（验收通过）
- 新增 source_name 功能：推送消息包含简历来源，已实测

### 文件变更清单
| 文件 | 变更类型 |
|---|---|
| `message_templates.json` | 新增（统一模板入口）|
| `version_digest_template.json` | 删除（内容已迁移）|
| `skills/resume_screen.py` | 修改（模板文件优先级）|
| `digest_config.json` | 修改（添加笛笛 P2P CID）|
