# Master 活动开发 Skill（master-activity-dev）

本目录为 Cursor Agent Skill：**统一的限时活动（Master）开发指南**，覆盖新活动/新玩法、入口、强弹、红点、积分，以及基于钉钉文档的需求审阅与字段映射核对。

## 前置条件

使用前需提供**项目根路径**（包含 `Content/` 和 `Tables/` 的目录，如 `D:\FishUE4L3\FishUE4`）。Agent 首次加载时会主动询问。所有文档中的相对路径（lua 代码、配表）均基于此路径解析。

## 何时使用

在对话中出现以下任一情况时，Agent 应加载并遵循 **`SKILL.md`** 全文：

- 开发或修改 Master 活动：`MasterModule`、`MasterData`、`MasterPlay`、`*_play_module` 等
- 新建活动页、入口、强弹助手、玩法模块
- 审阅/对照策划文档：玩法选型、UI 与配表字段映射、Act / ActGroup 结构

## 文档怎么读

| 文件 | 用途 |
|------|------|
| **[SKILL.md](./SKILL.md)** | 主规范：开发流程、目录与命名、禁止事项、需求分析输出模板、文档过期检查规则 |
| **[reference/master-system.md](./reference/master-system.md)** | 框架接口、事件、红点、积分、生命周期（与代码冲突时以代码为准） |
| **[reference/play-index.md](./reference/play-index.md)** | 一级索引：全玩法速查、需求→玩法反向索引、相似玩法对比 |
| **[reference/play-*.md](./reference/)** | 二级详情：单玩法协议、红点、完成条件、配表字段说明 |

**推荐顺序**：需求来了 → `play-index.md` 筛玩法 → 锁定后读对应 `play-xxx.md` → 需要框架细节时读 `master-system.md`。

## 配套能力

- **配表结构核对**：用项目内的 `table-schema-preview` skill 对照当前 `.xls`，勿仅凭文档填表。
- **钉钉需求文档**：若需求来自钉钉，可按 `SKILL.md` 中流程拉取并输出 `_master_doc_review.md`（Part 1 文档分析 + Part 2 技术/配表方案；新开发经讨论后补 Part 3）。
- **reference 过期检查**：每次依赖 reference 做重要决策前，按 `SKILL.md`「文档过期检查」用 skill 自带的 `scripts/svn_file_changes.py` 对参考代码与日期做校验，过期则更新文档元数据与正文。

## 目录结构（简要）

```
master-activity-dev/
├── README.md          # 本文件：入口与导航
├── SKILL.md           # Agent 主技能说明（必读）
├── scripts/           # 自带工具脚本（无外部依赖）
│   └── svn_file_changes.py   # SVN 文件变更查询（过期检查用）
└── reference/         # 系统说明 + 玩法索引与分玩法详解
```

---

维护说明：业务规则与流程以 **`SKILL.md`** 为准；本 README 仅作人类与 Agent 的快速索引，不与 `SKILL.md` 重复长篇细节。
