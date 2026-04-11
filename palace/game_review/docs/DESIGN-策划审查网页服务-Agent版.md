# 策划方案审查 · 网页交互服务（Agent 实现说明）

**文档版本**：0.4（与人类版 v0.5 对齐）  
**更新日期**：2026-04-11  
**读者**：在本仓库内实现/修改该功能的 AI Agent 与工程师  

**产品权威**：范围、分期、验收、数据留存与审计、**仓库与实施对接约定**以 [`DESIGN-策划审查网页服务-人类版.md`](DESIGN-策划审查网页服务-人类版.md) **v0.5** 为准（尤其 **文档目的 · 文档与仓库约定**、**§2.6、§3.1、§4.3、§5.7**）。本文档为实现侧约束与接口草案；**冲突时以人类版为准并回写修订**。

---

## 1. 目标

在**不臆造业务规则**的前提下，实现「**玄石登录** → 网页上传与云文档链接 → 本地 Ollama 多轮审查 → 终稿 Markdown 下载与**独立 Git 仓永久归档**」的服务端与前端编排，并与现有 `game_review_ollama.py` 的 Skill 与调用方式**对齐**（首轮 **C 档单轮 v2**），避免双份判据。

**与人类版分期对齐（摘要）**

| 人类版阶段 | Agent 侧重点 |
|------------|----------------|
| **A · MVP** | 玄石身份、主路径、**埋点（必选）+ 用户反馈（必选）**、上传 **30 天**落盘、**会话与对话长期存储**、终稿 **Git 归档 + 业务互链**、**异常用户提示 + 维护侧实时通知** |
| **B · V1** | 业务 Webhook（首轮/终稿等）、会话恢复、数据看板、反馈增强（单条有用/没用）；可与 MVP 告警通道**合并实现** |
| **C · V1+** | 队列与并发、长文档策略、黄金样例回归、可选 A/B、终稿更强模型 |

---

## 2. 约束（必读）

- **中文**：对用户可见文案、本仓库新增注释以简体中文为主（与 workspace 规则一致）。
- **Skill 权威路径**：审核判据以 `/workspace/.cursor/skills/game-review/` 下文件为准；读取路径可配置，默认指向仓库内 skills。
- **首轮 Prompt**：与 `game_review_ollama.py` **默认单轮（C 档 v2）**一致，即 `_build_system_prompt` + 正文；**不要**默认使用 `--multi-pass`（D 档）作为首轮，除非产品另行指定。
- **Ollama 调用**：OpenAI 兼容 Chat Completions；环境变量：`GAME_REVIEW_LLM_API_BASE`、`GAME_REVIEW_LLM_MODEL`（默认 `http://127.0.0.1:11434/v1`、`gemma4:latest`）。
- **身份**：MVP **必须**接入**玄石登录**；`user_id` 来自玄石，写入会话、埋点与审计相关记录。
- **Git**：**禁止**将用户上传文件、会话正文、终稿提交到**研发业务代码仓**。终稿仅推送到人类版约定的**独立归档仓**；提交信息须含 `session_id` 等可对账字段（见 §8）。
- **禁止**：在代码中硬编码密钥；不擅自 `git push --force` / `reset --hard` 于业务仓。
- **提交**：未经用户明确说「请提交/验收通过」，不执行 `git commit`。

---

## 3. 仓库与现有代码

| 路径 | 作用 |
|------|------|
| `palace/game_review/game_review_ollama.py` | 正文提取、`_build_system_prompt`（C 档）、`_run_multi_pass`（D 档，非 MVP 默认）、`_call_openai_compatible` |
| `palace/game_review/docs/DESIGN-策划审查网页服务-人类版.md` | 产品权威 **v0.4** |
| `.cursor/skills/game-review/` | Skill 正本 |

**重构边界**：将「读文件 → 文本」「构建 system/user（C 档首轮 / 追问 / 终稿变体）」「单次 chat 调用」抽成模块；网页服务增加 **玄石鉴权、会话状态、埋点、反馈、上传生命周期、Git 归档任务**。禁止复制大段 prompt 到多处不引用。

---

## 4. 架构组件（实现清单）

1. **HTTP 服务**：建议 FastAPI；**全局依赖玄石会话**（除健康检查等白名单）。
2. **会话存储**：须持久化（SQLite/PostgreSQL 等）；**长期保存**会话与完整 `messages`（人类版 §5.7）。字段至少含：`session_id`、`user_id`（玄石）、`messages`、`source_meta`（文件名、`truncated`）、`scheme_type`、`cloud_doc_url`、`round_count`、`status`、终稿元数据（含 `git_commit` / 归档路径，若已归档）。
3. **云文档链接**：创建或上传阶段 **强制校验非空**；写入终稿 Markdown **固定章节**；与会话一并存库。
4. **上传文件**：落盘至 `DATA_DIR` 下受控路径；**保留 30 天**（删除策略与计时起点在实现说明中写死，与人类版一致）。
5. **文本提取**：复用 `game_review_ollama.py` 中 `_load_text_from_file`、`_truncate`。
6. **首轮**：C 档，与 `_build_system_prompt(scheme_type)` + 用户正文一致。
7. **追问轮**：用户输入作为 `user` 追加；可省 token 的 system 补充由工程决定。
8. **终稿**：单独一轮 `system`/`user`，输出**唯一** Markdown；**正文必须包含云文档链接**；供下载并触发 **Git 归档**（见 §8）。
9. **埋点**：事件写入库表或等价可查询存储；字段含 §6.4 与版本元数据。
10. **用户反馈**：`POST .../feedback` **MVP 必选**（与人类版 §3.1）。
11. **异常**：用户可见结构化错误码 + 文案；维护侧 **实时通知**（Webhook/钉钉等，配置化），payload 含 `session_id`、错误类型、时间。

---

## 5. 会话状态机（建议）

```
CREATED → FIRST_RUNNING → FIRST_DONE → CHAT_LOOP → FINAL_RUNNING → ARCHIVING → CLOSED
```

- `FIRST_RUNNING`：禁止同会话并发第二次首轮。
- `CHAT_LOOP`：直到用户触发「生成终稿」或 `max_rounds`。
- `FINAL_RUNNING`：生成终稿 Markdown，持久化，准备下载。
- `ARCHIVING`（建议显式状态）：推独立 Git 归档仓；成功后业务表写入 `git_commit` / 路径，再 `CLOSED`。失败则 `FAILED` 或 `CLOSED`+告警，规则由工程定，**须通知维护**。
- 错误：`FAILED` + `error_code`；并触发 §4 第 11 项通知。

---

## 6. API 契约（草案，实现时可微调）

### 6.1 认证

- 除 `/api/health` 等白名单外，**均需玄石登录态**（Cookie / Header / 网关注入，与玄石方案一致）。
- `user_id` 从鉴权上下文注入，**禁止**由客户端随意伪造。

### 6.2 核心会话与报告

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions` | 创建会话；body 含 `scheme_type`、**`cloud_doc_url`（必填，URL 校验）** |
| POST | `/api/sessions/{id}/upload` | multipart 文件；返回 `truncated`、任务 id |
| POST | `/api/sessions/{id}/review/start` | 触发首轮（可与 upload 合并） |
| GET | `/api/sessions/{id}/status` | `state`, `last_error` |
| POST | `/api/sessions/{id}/chat` | `content` 或 `choice`（A/B/C） |
| POST | `/api/sessions/{id}/finalize` | 生成终稿；触发 Git 归档 |
| GET | `/api/sessions/{id}/report` | 下载 `text/markdown` |

**异步**：首轮与 finalize 若耗时较长，后台任务 + 轮询 `status` 或 SSE/WebSocket（实现写清）。

### 6.3 反馈（MVP：必选，人类版 FR-07）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions/{id}/feedback` | `rating`（1～5）、`reason_tags`（可选多选）、`comment`（可选） |

**V1+**：单条问题「有用/没用」等见人类版阶段 B。

### 6.4 埋点（MVP：必选）

关键节点须可统计；事件带 **版本元数据**。`user_id` 使用 **玄石** 用户 id。

| 事件 | 触发时机 | 建议附加字段 |
|------|----------|----------------|
| `session_created` | 创建会话 | `session_id`, `user_id`, `cloud_doc_url`（可哈希脱敏） |
| `upload_ok` / `upload_fail` | 上传结束 | `truncated`, `mime`, `size` |
| `first_review_done` / `first_review_fail` | 首轮完成或失败 | `duration_ms`, `error_code` |
| `chat_round` | 每轮追问完成 | `round_index` |
| `finalize_done` / `finalize_fail` | 终稿生成 | `duration_ms` |
| `report_downloaded` | 用户下载终稿 | `user_id` |
| `feedback_submitted` | 用户提交反馈 | `rating` |
| `archive_done` / `archive_fail` | Git 归档成功或失败 | `git_commit` 或错误 |

**版本元数据（尽量每条携带）**：`skill_version` 或 Skill hash、`prompt_version`、`model_id`。

### 6.5 分期与实现优先级

- **MVP**：§6.2 + §6.3 + §6.4 + **Git 归档（§8）** + **维护侧通知（§9）**。
- **V1**：业务 Webhook、会话恢复、看板、反馈增强（人类版 §3.2）。
- **V1+**：队列、黄金样例回归、可选 A/B 等（人类版 §3.3）。

---

## 7. Ollama 调用参数

- `temperature=0.3`（可配置）。
- `timeout`：默认 600s 或可配置。
- **多轮**：每次携带完整 `messages`。

---

## 8. 终稿 Git 归档（独立仓）

- **仓库**：与人类版 §5.7 一致，**与研发业务仓分离**；克隆地址与凭据由运维配置（如环境变量）。
- **时机**：`finalize` 成功、终稿内容已定后异步执行；失败须 `archive_fail` 事件 + **维护通知**。
- **内容**：至少包含终稿 `.md`；路径建议含日期或 `session_id`，避免冲突。
- **互链**：业务表保存 `git_commit`、仓库 URL、文件路径，便于与人类版「对账」验收。
- **禁止**：向研发业务仓推送终稿或上传文件。

---

## 9. 维护侧实时通知（MVP 必选）

- **触发**：模型失败、超时、归档失败、关键路径异常等（具体列表在实现中枚举）。
- **通道**：Webhook / 钉钉 / 企业内告警等，**配置化**。
- **Payload**：至少 `session_id`、`error_code` 或类型、`timestamp`、`user_id`（可选脱敏）；可附简短 `message`。
- **与用户提示分离**：用户侧文案友好、可操作；维护侧信息偏诊断。

---

## 10. 业务 Webhook（V1，可选与 MVP 告警合并）

- 人类版阶段 B：首轮完成、终稿就绪等**业务向**推送；实现可与 §9（维护通知）基础设施合并，**事件类型**区分即可。

---

## 11. 安全与合规

- 上传：白名单扩展名、max size、安全文件名、隔离目录；**30 天**清理任务。
- **玄石**：MVP 主鉴权；额外口令等见人类版 FR-O3（V1+ 增强）。
- 日志与埋点：注意脱敏；**独立 Git 仓**访问权限与策划案内容分级由项目约定。

---

## 12. 测试清单（Agent 自测）

- [ ] 未登录不可访问受保护 API；玄石身份可贯通 `session_id`。
- [ ] 无 `cloud_doc_url` 或非法 URL 创建会话失败。
- [ ] 健康检查与 Ollama 不可达时用户提示与维护通知。
- [ ] md/pdf/docx 小样上传 → 首轮非空（C 档）。
- [ ] 两轮追问后 finalize → 终稿含用户关键词与**云文档链接**章节。
- [ ] 并发两会话，`messages` 与 `user_id` 不串。
- [ ] 大文件 `truncated=true` 可见。
- [ ] 埋点可查询，含版本元数据与 `user_id`。
- [ ] 反馈提交可关联 `session_id`。
- [ ] 终稿推送**独立归档仓**成功，业务表 `git_commit` 可写；**研发仓**无策划上传物。
- [ ] 上传文件 30 天策略（单测或集成测模拟时间/配置）。
- [ ] 关键失败路径触发维护通知。

---

## 13. 与人类版文档的对应（v0.4）

| 人类版 FR | Agent 实现要点 |
|-----------|----------------|
| FR-01 | 上传 + `_load_text_from_file` + 上限 + **30 天**落盘生命周期 |
| FR-02 | 首轮 C 档 `_build_system_prompt` + 正文 |
| FR-03 | `messages` 长期持久化 + 多轮 chat |
| FR-04 | finalize + 下载 + **终稿 Git 归档** + 互链 |
| FR-05 | 会话隔离（含 `user_id` 维度） |
| FR-06 | **玄石**登录与身份注入 |
| FR-07 | §6.4 埋点 + §6.3 反馈 API，**均为必选** |
| FR-08 | **cloud_doc_url** 必填、写入终稿、会话存链接；§8 Git 归档 |
| FR-09 | 用户友好错误 + §9 维护侧实时通知 |
| V1 起 | 业务 Webhook、会话恢复、看板、反馈增强（人类版 §3.2） |
| V1+ | 队列、黄金样例、A/B、更强模型等（人类版 §3.3） |

---

## 14. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1 | 2026-04-11 | 初稿 |
| 0.2 | 2026-04-11 | 与人类版 v0.2：分期、FR-06、埋点、反馈草案 |
| 0.3 | 2026-04-11 | 与人类版 **v0.4** 对齐：玄石、FR-06～09、云链接、30 天上传、长期会话、终稿独立 Git 仓、审计互链、维护通知、API/测试/约束全文同步 |
| 0.4 | 2026-04-11 | 与人类版 **v0.5** 对齐：产品权威含「文档与仓库约定（实施对接）」 |
