# dingtalk-desktop WORK_LOG

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
