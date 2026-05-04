# Agent 体系增强：三仓库吸收分析

> 来源：hermes-agent / Archon / nuwa-skill 三个开源项目的架构分析与吸收落地。

## 一、三仓库核心洞察

### Hermes Agent（NousResearch）
| 维度 | 核心设计 |
|------|----------|
| **自进化 Skills** | Agent 从经验中自主创建技能，使用中自主 patch 改进 |
| **三层记忆** | 系统提示(静态) → 持久记忆(MEMORY.md/USER.md) → 会话上下文(FTS5) |
| **上下文压缩** | 便宜操作先行(prune tool output) → 贵操作后行(LLM 结构化摘要) |
| **工具注册表** | import-time 自注册单例，三文件即可添加新工具 |
| **子 Agent 隔离** | 上下文隔离 + 工具集继承∩限制 + 深度限制(MAX_DEPTH=2) |
| **提示注入防护** | 正则扫描外部上下文文件，检测注入模式 |

### Archon（coleam00）
| 维度 | 核心设计 |
|------|----------|
| **YAML DAG 工作流** | 声明式定义开发流程：节点(command/prompt/bash/mcp) + 依赖 + 条件路由 |
| **Markdown Command** | 提示词模板 = 分阶段 + CHECKPOINT 清单 + GATE 门禁 |
| **Hooks 系统** | PreToolUse / PostToolUse 运行时行为注入，工具级粒度 |
| **Artifact 通信** | 节点间通过 `$ARTIFACTS_DIR/` 文件通信，规避上下文膨胀 |
| **多模型精细路由** | 分类用 haiku、实现用 opus、review 用 sonnet |
| **并行 Review Agent** | 5 个独立 review agent 并行(代码/错误/测试/注释/文档) |

### nuwa-skill（alchaincyf）
| 维度 | 核心设计 |
|------|----------|
| **认知蒸馏方法论** | 提取 HOW they think 而非 WHAT they said |
| **6-Agent Swarm** | 并行调研(著作/对话/表达/他者/决策/时间线) |
| **三重验证** | 跨域复现 + 生成力 + 排他性，筛选心智模型 |
| **Agentic Protocol** | 先分类→按需研究→再输出，从心智模型反推搜索维度 |
| **诚实边界** | 强制声明做不到什么，反幻觉设计 |
| **质量自检脚本** | `quality_check.py` 把 Skill 质量标准代码化 |

## 二、吸收落地计划

| # | 增强项 | 主要来源 | 落地为 | 影响 |
|---|--------|----------|--------|------|
| 1 | Skill 自进化规范 | Hermes | `skill-evolution.mdc` (新规则) | 让 Skills 从静态文档变为可迭代的知识资产 |
| 2 | Skill 质量验证 | nuwa-skill | `skill-quality-gate.mdc` (新规则) + 自检脚本 | 确保新 Skill 不是"随便写的" |
| 3 | 结构化会话交接 | Hermes + Archon | `session-handoff.mdc` (新规则) | 长会话切换时保留关键上下文 |
| 4 | 分阶段检查点 | Archon | 增强 `agentx.mdc` | 复杂任务中增加中间校验 |
| 5 | Skill 编写模板 | nuwa-skill | `skill-authoring-guide.md` (新 Skill) | 标准化 Skill 的结构与质量 |

## 三、不吸收的部分（及原因）

| 特性 | 来源 | 不吸收原因 |
|------|------|-----------|
| YAML DAG 引擎 | Archon | 需要额外运行时；我们的 Rules 体系已够用 |
| 多平台网关 | Hermes | 钉钉通道已满足需求 |
| PreToolUse/PostToolUse Hooks | Archon | Cursor IDE 不支持此级别的运行时拦截 |
| FTS5 全文检索 | Hermes | Cursor 本身管理会话历史 |
| 认知蒸馏流水线 | nuwa-skill | 是生产 Skill 的 Skill，与我们的业务导向 Skill 定位不同 |
