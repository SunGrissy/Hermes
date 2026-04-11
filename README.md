# MyAgents 工作空间

本目录为**制作人自用**的游戏研发效能与工具集合仓库。**规格、Skill、规则与 palace 内文档均以本 Git 库为准**；实施方不要依赖口传或外部散落链接，以克隆后的仓库内容作为唯一事实源。

## 对接说明（给接收实施的同学）

- **需求与范围**：与仓库维护者（制作人）**直接对接**，确认当前要做的是哪一子项目、哪份设计文档、验收口径。
- **依赖位置**：Cursor Rules、Agent Skills、palace 内方案等**全部在本仓库内**，路径如下；若与口头不一致，**以本库为准**。
- **双远程**：内网主仓与 GitHub 镜像的配合见 `.cursor/skills/dual-git-sync/SKILL.md`（克隆来源不同会影响子模块 URL，请先读该文档）。

## 本库内关键路径（索引）

| 内容 | 路径 |
|------|------|
| 工作空间地图（各子项目入口） | `.cursor/rules/workspace-map.mdc` |
| Agent Skills 总说明 | `.cursor/skills/README.md` |
| 策划方案 **审核**（game-review） | `.cursor/skills/game-review/` |
| **策划审查网页服务**（规划/设计文档，含人类版与 Agent 版） | `palace/game_review/docs/` |
| 本地 Ollama 审核脚本 | `palace/game_review/game_review_ollama.py` |

更细的子项目说明见各子目录内 `README.md`（若有）。

## 说明

本仓库默认读者为**协作者与实施方**；对外分发以单独摘录或文档包为准。新增重要约定时，请同步更新本 README 或 `palace/` 下对应说明，避免「只有本机知道」。
