# 四栈文档目录扫描与归类规划（仅方案，未移动任何文件）

**日期：** 2026-04-30  
**范围：** `D:\MyAgents`、`D:\hermes`、`D:\OpenClaw`、`D:\OpenClaw2` 中与「人读文档」相关的目录；**不**把 `node_modules` 等依赖树当作自有文档资产。  
**落地进度：** MyAgents 侧已将工单附件、面试目录及部分「叙事类」根文档迁入 **`docs/narrative/`**，总索引见 **`docs/DOC_HUB.md`**。Hermes / OpenClaw 仍以链接引用为主。

---

## 1. 扫描摘要（按目录，排除 node_modules）

| 位置 | 规模（约） | 结构/性质摘要 |
|------|------------|----------------|
| `MyAgents\docs\`（根级） | 减少中 | `superpowers/`、`silicon-legion*`、`script-entry-index`、`DOC_HUB`、taxonomy 等；原散落的需求/JD/赛季文已迁至 `docs/narrative/`。 |
| `MyAgents\workspace-docs\` | 10 篇 | 工作区治理：架构简报、Git 流、报告助手展示、与根仓 `WORK_LOG` 有功能重叠需后续对齐。 |
| `MyAgents\docs\narrative\multica-tasks\` | 5 篇 | 工单/需求长文附件，**宜保持「按任务聚类」**，不混进 `docs/superpowers`。 |
| `MyAgents\shared-memory\` | 25 篇 | 跨 Agent 事实流（charter、hub 日、 knowledge、任务 JSON）；**语义是「运行期记忆」**，与「设计规格」分离。 |
| `MyAgents\docs\narrative\面试\` | 37 篇 | 由根目录 `面试/` 迁入；候选人 `interviews/`、已面试索引；初筛仍在 `performeval/面试/`。 |
| `MyAgents\.cursor\skills\` | 136 篇 | **Cursor 侧 Agent Skills 正本**（与规则中「唯一真源」一致）。 |
| `MyAgents\skills\` | 314 篇 | 历史/通用 Skills 树，与 `.cursor/skills` **存在双轨**；整理重点应是 **保留策略**（只读归档 vs 迁正本 vs 删重复），而非简单搬家。 |
| `MyAgents\pm-system\docs\` | 22 篇 | 子产品技术/验收/重构说明，**应随 pm-system 子模块** 走，不强制收到根 `docs/`。 |
| `MyAgents\palace\` | 93 篇（含子树） | 报告/评审/引擎说明混放；**宜在 palace 内再分子类**（与 MyAgents 根 `docs` 用链接互指即可）。 |
| `MyAgents\dingtalk-desktop\docs\` | 4 篇 | 通道与摘要类技术说明，**跟子产品** 即可。 |
| `D:\hermes\skills\` | 387 篇 | **Hermes 侧 Skills 主库**；与 MyAgents `.cursor/skills` 是「同步/衍生」关系，整理时以 **单点发布 + 拉取** 为原则，避免三份手改。 |
| `D:\hermes\cron\output\` | 35 篇（层级尚有各 advisor 子目录） | **定时任务产出**，属生成物；规划重点是 **保留周期 + 归档目录约定**，不是并入「规格文档」。 |
| `D:\hermes\acha\data\` | 14 篇 | PM/Ops 巡检、规划器诊断等**数据化报告**；可视为「业务输出」子类。 |
| `D:\hermes\memories\` 与各实例下 `memories\`、根 `SOUL.md` 等 | 少量 + 分散 | **身份/长期记忆**；与 OpenClaw `workspace` 下 MEMORY 同源异构，**不做物理合并**，只做「索引里互相引用」。 |
| `D:\hermes\hermes-agent\` | 大量 `.md`（含 `website/`、`RELEASE_*`、上游文档） | **上游/产品级仓库内文档**；我们整理范围限定为：**README、AGENTS、与网关运维相关的几篇**，**勿整体搬迁**。 |
| `D:\OpenClaw\workspace\` | 60 篇（排除依赖后） | OpenClaw **运行时工作区**：AGENTS/SOUL/IDENTITY、按日 `memory\`、`TOOLS`、`dingtalk-workspace-cli` 整包（偏第三方/嵌入式）。 |
| `D:\OpenClaw2\workspace\` | 15 篇 | 第二实例：同类结构 + `PORT_MAP`、`STARTUP`、`OPS_*`、简短教程；体量小，**先做命名与索引一致即可**。 |

**说明：** 全仓模糊统计 `MyAgents` 下可达 **600+** `.md`，主因是 `.cursor/skills`、`skills`、子项目与 palace 嵌套；治理时应 **按「职能分类」过滤**，而不是以「全量 Markdown」为搬运单位。

---

## 2. 归类维度（建议作为后续挪文件的「坐标系」）

建议用 **五条轴** 标记每份文档，避免只按「在哪个硬盘目录」来归堆：

| 轴 | 含义 | 典型落点示例 |
|----|------|----------------|
| **A. 规格与设计（Spec）** | 跨系统协议、方案、评审结论，需版本感与可追溯 | `MyAgents/docs/superpowers/specs|plans`、部分 `docs/narrative/multica-tasks/*.md`（链接进索引） |
| **B. 产品与业务叙述（Narrative）** | 玩法/赛季/运营/招聘 JD 等 | `MyAgents/docs/` 根级或按主题子文件夹、`docs/narrative/面试/` |
| **C. Agent 操作说明（Skill）** | 给模型/Agent 的规程，要求单一真源 | `MyAgents/.cursor/skills`、`D:\hermes\skills`（及 Hermes/OpenClaw workspace 内 `skills/`） |
| **D. 运行时状态（Runtime）** | 日记、心跳、共享记忆、定时产出 | `shared-memory/`、`OpenClaw(2)/workspace/memory/`、`hermes/**/cron/output/`、`acha/data/` |
| **E. 运维与索引（Ops）** | 启动入口、端口、脚本册、Runbook | `docs/script-entry-index.md`、OpenClaw2 `PORT_MAP`/`STARTUP`、`workspace-docs` 里 Git/架构简报 |

**规则：** 同一文件只能有一个 **主类**；其余关系用「索引链接」表达，不复制正文。

---

## 3. 分栈策略（不搬家前提下的「应然结构」）

### 3.1 MyAgents

- **`docs/`**：向「A + B + E」收敛；保持 `superpowers/` 现分法；根下散文件逐步收进 **主题子目录**（如 `ops/`、`liveops/`）或标 `archive/`。  
- **`workspace-docs/`**：与根 `WORK_LOG.md`、规范类 **二选一主入口**（另一处只保留短链或「已迁」说明），减少「到底看哪份」摩擦。  
- **`docs/narrative/multica-tasks/`**：维持 **按日期/工单** 命名，索引里按链接收录。  
- **`shared-memory/`**：不迁入 `docs/`；在总索引中单列「运行时记忆」。  
- **`.cursor/skills` vs `skills/`**：单独做一次 **重复扫描与保留策略**（本方案不展开执行）。

### 3.2 Hermes

- **`D:\hermes\skills\`**：Hermes 侧 Skill 主库；与 MyAgents 的同步方式写在索引（谁 master、谁 consumer）。  
- **`cron/output/` 与各实例 cron**：统一视为 **D 类生成物**；规划默认保留窗口（如 30/90 天）与「可删」标记，避免与规格混目录。  
- **`acha/data/`**：视为 **业务输出**；若体积增长，可增设 `archive/` 或按月份子目录。  
- **`hermes-agent`**：仅维护 **对外运维可读** 的几条入口，**不**把 `website`/`RELEASE` 纳入我们「四栈文档整理」范围。

### 3.3 OpenClaw

- **`workspace/`**：以 **运行时配置 + 轻量规程** 为主；`dingtalk-workspace-cli` 视为 **嵌入式第三方文档树**，整理时 ** subtree 内少动**，仅在 `workspace` 根增加 **一页总目录（INDEX）** 指向 AGENTS/MEMORY/TOOLS/cli README。  
- 与 **MyAgents `docs`** 的关系：**链接**，不合并仓库。

### 3.4 OpenClaw2

- 与 OpenClaw 同逻辑；**`PORT_MAP`、`STARTUP`、`OPS_*`** 明确归为 **E 类**，与 MyAgents `script-entry-index` 在总索引中并列引用。

---

## 4. 总入口（已建）

- **`docs/DOC_HUB.md`**：叙事类 / Superpowers / 脚本索引 / workspace-docs / WORK_LOG 的跳转枢纽（持续补链接即可）。

本文档仍为 **分类规划真源**；更细的搬迁 checklist 可按 `docs/narrative/README.md` 子目录维护。

---

## 5. 分阶段执行建议（供老大拍板）

| 阶段 | 内容 | 风险 |
|------|------|------|
| **P0** | 新增 `DOC_HUB` + 在 `CLAUDE.md` 或 `workspace-docs/README` 加一行入口 | 低 |
| **P1** | 仅 `MyAgents/docs` 根下散文件 → 主题子目录 | 中（需更新站内链接） |
| **P2** | `workspace-docs` 与 `WORK_LOG` 职责拆分说明 + 旧文标注 | 低 |
| **P3** | `skills` vs `.cursor/skills` 去重策略（文档层面） | 高（牵涉同步机制） |
| **P4** | Hermes `cron/output` 保留策略（文档 + 可选脚本清理） | 中 |

---

## 6. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-30 | 初版：目录扫描量级 + 五轴分类 + 分栈策略 + 分阶段建议。 |
| 2026-04-30 | MyAgents：`MulticaTasks`、`面试`、部分根级叙事文档迁入 `docs/narrative/`；新增 `DOC_HUB.md`；索引更新于 workspace-map、CLAUDE、script-entry-index、Skills。 |
