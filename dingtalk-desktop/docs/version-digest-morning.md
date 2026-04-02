# 早间版本汇总（VersionDigest）— 行为说明与近期变更

> 供新会话快速对齐上下文：**受众差异、版本过滤、文末形态、脚本入口**。实现分散在 `dingtalk-desktop` 与 `pm-system` 两处，以本节为单一说明入口。

---

## 1. 涉及代码（按职责）

| 位置 | 作用 |
|------|------|
| `dingtalk-desktop/version_digest.py` | 早间/傍晚入口、Webhook 多群发送、`digest_config` 读取、状态文件、助理群 `--assistant-batch` / `--audience-sweep`、**按受众合并 `/api/data` 后的版本筛选**（`_morning_names_from_merged`） |
| `dingtalk-desktop/_push_versions_webhook_at_dm.py` | `render_multi_version_digest_markdown`：多版本合并、**文末小尾巴链接**（`_digest_footer_links_markdown`）、与 PM 专项同源 checklist；group 仍用 `_filter_names_exclude_release_done` 与 data 对齐 |
| `pm-system/backend/app/services/version_progress_notify.py` | `render_version_status_markdown`、`_render_version_block`：**各受众标题**（PMO早报 / 管线快报 / PLD快报 / 版本快报）、**文末 `---` + 可选链接块 + `###### ※ 小秘书提醒`**（`footer_links_md`） |

---

## 2. 受众与「选哪些版本」

活跃版本来自 `GET /api/dashboard` 的 **activeVersions**，**不再**用 `version_digest_limit` 截断条数。在合并 `GET /api/data` 全量版本（含 `pipelineStatus`、`pipelineDdls`）后，按受众取 **并集**（同一版本可因多条规则入选，去重）：

| 受众 | 纳入规则（均为「或」关系） |
|------|---------------------------|
| **PMO早报（producer）**、**full** | ① 管线 **发版节点未完成**；或 ② **发版已完成且复盘节点未完成**（`release` 且非 `retro`）；或 ③ **规划节点 DDL** 满足「距今」窗口：`delta = (planning_ddl − 今天).days ≤ N`，PMO 默认 **N=28**（配置键 `version_digest_pmo_planning_days`，缺省回退 `version_digest_producer_planning_days`） |
| **管线快报（pm）** | 先 **排除**：若存在**规划节点 DDL** 且 **(DDL−今天).days ≥ M**，整版不纳入（默认 **M=7**，`version_digest_pm_planning_exclude_days_ahead`）；再与 PMO 并集相同规则，③ 中默认 **N=7**（`version_digest_pm_planning_days`） |
| **PLD（pld）** | 先 **排除**：若存在规划节点 DDL 且 **(DDL−今天).days ≥ M**，整版不纳入（默认 **M=3**，`version_digest_pld_planning_exclude_days_ahead`）；再 ① **发版节点未完成**；或 ② 规划 DDL **N=14**（`version_digest_pld_planning_days`）。**多版本时按版本拆成多条消息**（每条标题带版本名） |
| **版本快报（group）** | ① **发版节点未完成**；且 ② 若填写了**规划节点 DDL**，则 **不纳入**「距规划 DDL 还有 **≥N** 天」的版本（默认 **N=3**，`version_digest_group_planning_exclude_days_ahead`）；无规划 DDL 的版本仍可进版本快报。**推送目标 URL 仅从 PM 数据源各版本的 `progressNotifyWebhooks` 读取**，**不**使用 `dingtalk-desktop/webhook_config.json` 里为 `group` 映射的条目（该条目在早间任务中会被跳过）。多版本早间：按纳入版本逐个渲染并 POST 到各版本自己的 webhook；单版本若存在 `__progress__` 行则仍走该条（与专项同源，避免重复）。 |

`render_multi_version_digest_markdown` 对 **pld/group** 仍会对传入名单再执行 `_filter_names_exclude_release_done`（与 `/api/data` 对齐）；上游已按规则算好时结果一致。

### 2.1 `full` 受众指什么？

- **不是**某个固定业务群昵称，而是渲染侧的一种 **audience 标识**：管线块信息密度按「全量」参数走（与 `producer` 在 checklist 密度上对齐），**选版规则与 PMO（producer）相同**。
- 早间任务里 `need_raw` 会包含 `full`，用于生成 `digest_cache['full']` 写入状态；**仅当**某条 webhook 在 `version_digest_audience_by_key` 里映射为 `full` 时，才会向对应群发这条正文。

---

## 3. 正文与文末形态

- **统一 footer 骨架**：`---` + **可选 Markdown 链接块** + `###### ※ 小秘书提醒`（`version_progress_notify._digest_footer_for_audience(..., footer_links_md=...)`）。
- **小尾巴链接**（`_digest_footer_links_markdown`，仅影响「链接块」，**不替代** footer）：
  - **PMO早报、管线快报**：`[PM 系统]({pm}/index.html)`。
  - **PLD 快报**：每个纳入版本一行：`- 版本名：[查看版本]({pm}/index.html#version=id)`。
  - **版本快报（group）**：**无跳转链接块**，但正文**仍然**以 `###### ※ 小秘书提醒` 结尾（与钉钉关键词习惯一致）。
- **无版本可推**：若 **仅** PLD 或 **仅** 版本快报在过滤后无正文，则 **该路不发送**（不发占位文案）；多群任务中其它受众照常发送。
- **多群全部无可发**（过滤后没有任何一条可推送）：向 `webhook_config.json` 的 **`version_digest_assistant`** 推一条简短说明（标题含「小秘书提醒」）；若未配置该键则仅打日志。
- **符合时间进度**：不输出「当前应处于 / 系统实际处于」两行（与 PM 侧 `_render_version_block` 约定一致）。
- **Webhook 正文尾 @**：早间汇总侧仍为 **不拼正文尾 @**；@ 以 payload 与 `version_digest_webhook_at` 为准。

---

## 4. 详情链接（历史说明）

- 版本快报 **不再**在文末追加「查看版本详情」；需要时用户从 PMO/管线/PLD 小尾巴进入 PM。

---

## 5. 助理群四条连发（调试）

- `py version_digest.py --audience-sweep`：同一助理 webhook 连发 **producer → pm → pld → group**，版本筛选与生产早间一致（全量活跃 + `_morning_names_from_merged`）。pld/group 若无可推版本则 **跳过该条**（不计为失败）。

---

## 6. 常用命令

```text
py version_digest.py                    # 早间快照：按 digest_config 多 webhook 发送
py version_digest.py --dry-run          # 只打印
py version_digest.py --audience-sweep   # 助理群四受众连发（调试）
py version_digest.py --assistant-batch  # 助理群按 slot 连发（另一套规则，见 version_digest_assistant_batch）
```

---

## 7. 配置备忘（`digest_config.json`）

- `pm_system_url` / `pm_system_api_key`：PM 数据源。
- `version_digest_pmo_planning_days`：PMO 规划窗口 **N**（默认 28）；未设时回退 **`version_digest_producer_planning_days`**。
- `version_digest_pm_planning_days`：管线快报规划窗口 **N**（默认 7）。
- `version_digest_pm_planning_exclude_days_ahead`：管线快报 **排除**「规划 DDL 距今 ≥N 天」的版本（默认 **7**）。
- `version_digest_pld_planning_days`：PLD 规划窗口 **N**（默认 14）。
- `version_digest_pld_planning_exclude_days_ahead`：PLD **排除**「规划 DDL 距今 ≥N 天」的版本（默认 **3**）。
- `version_digest_group_planning_exclude_days_ahead`：版本快报排除「距规划 DDL 还有 ≥N 天」的版本（默认 **3**）。
- `version_digest_limit`：**早间已不再用于截断活跃条数**；其它脚本若仍读取以各自代码为准。
- `version_digest_webhook_keys` + `version_digest_audience_by_key` + `version_digest_webhook_at`：多群路由与 @ 策略。

---

## 8. 变更记录（摘要）

| 日期 | 内容 |
|------|------|
| 2026-04-02 | 早间：**活跃版本不再 limit 截断**；PMO/管线/PLD/版本 **选版规则**与 **文末链接**按产品约定重做；PLD **多版本拆条**；pld/group **无内容则不推**；管线/PLD **规划 DDL 远于阈值整版排除**；日志 **pld/group 纳入列表**；**group 需单独配置 webhook**。 |

（更老的管线/定时说明仍见 **[版本与管线推送说明.md](../版本与管线推送说明.md)**、**[pipeline-push.md](./pipeline-push.md)**。）
