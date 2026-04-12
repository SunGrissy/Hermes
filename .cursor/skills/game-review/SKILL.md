---
name: game-review
description: |
  基于制作人方法论的策划方案设计、优化、审核工具。
  采用双层协作模式：AI做逻辑完整性检查（6大引擎），人做直觉判断（Gate/Flag/Sense决策问题）。
  品类无关，可审核任何游戏的策划方案。

  **自动加载场景**：
  - 执行 /game.review、/game.optimize、/game.craft 命令时
  - 用户要求审核、评审、优化策划方案时
  - 用户提交设计文档要求检查时

  **关键词触发**：审核、评审、review、检查设计、优化方案、方案评估、
  策划审查、设计评分、红线检查、节奏分析、价值冲突
---

# 策划方案审核工具（Game Review）

## 概述

本 skill 基于制作人深度访谈提炼的方法论，提供策划方案的**设计、优化、审核**能力。

核心原则：**AI做逻辑完整性检查（快+全），人做直觉判断（不可替代）。**

## 三层协作架构

```
┌─────────────────────────────────┐
│         人（直觉层）             │
│  目标感判断 / 有趣判断 / sense  │
└──────────┬──────────────────────┘
           ↕ 决策问题 + 回答
┌──────────┴──────────────────────┐
│         AI（逻辑层）             │
│  6大检查引擎（串行执行）         │
│  聚合 + 决策问题生成            │
├─────────────────────────────────┤
│     虚拟用户（行为模拟层）       │  ← 可选增强
│  数据炼化的典型玩家角色扮演      │
│  行为预测 + Segment 交叉验证    │
└─────────────────────────────────┘
```

虚拟用户层为可选增强——有 `virtual-players/` 档案时自动启用，无则降级为纯逻辑审查。

## 三种使用模式

| 命令 | 用途 | 说明 |
|------|------|------|
| `/game.review` | 审核已有方案 | 6引擎检查 → 决策问题 → 审核报告 |
| `/game.optimize` | 优化已有方案 | 审核 → 优化方案生成 → 方案diff |
| `/game.craft` | 从零设计方案 | 收集信息 → MVP草稿 → 内置审核 → 迭代 |

## 六大检查引擎

| 引擎 | 代号 | 核心问题 | Reference |
|------|------|---------|-----------|
| 设计目的检查 | Purpose | 目的是否清晰、一致、服务目标人群 | [engine-purpose.md](references/engine-purpose.md) |
| 情绪节奏分析 | Rhythm | 情绪曲线是否有波峰波谷 | [engine-rhythm.md](references/engine-rhythm.md) |
| 红线与误区扫描 | RedLine | 是否触碰红线、命中误区 | [engine-redline.md](references/engine-redline.md) |
| 价值冲突检测 | Value | 价值排序是否被违反 | [engine-value.md](references/engine-value.md) |
| 玩家分层评估 | Segment | 各分层影响、中坚层是否被保护 | [engine-segment.md](references/engine-segment.md) |
| 经济系统健康度 | Economy | 通胀风险、重置策略、追赶机制 | [engine-economy.md](references/engine-economy.md) |

### 引擎裁剪规则

不是所有方案都需要6个引擎全上，虚拟用户测试也按方案类型裁剪：

| 方案类型 | 必要引擎 | 可选引擎 | 虚拟用户 |
|----------|---------|---------|---------|
| 完整策划案 | 全部6个 | — | ✅ 必要 |
| 单系统设计 | Purpose, Rhythm, RedLine | Value, Segment, Economy | ✅ 推荐 |
| 数值方案 | Purpose, RedLine, Economy | Rhythm, Value, Segment | ⚠️ 涉及付费/公平时 |
| 活动/运营方案 | Purpose, RedLine, Value | Rhythm, Segment, Economy | ✅ 推荐 |
| UI/交互方案 | Purpose, Rhythm, RedLine | — | ❌ 不需要 |

## 执行架构 & 模型建议

```
Agent 读取方案 + 确定范围 + 选择引擎
    ↓
逐一加载各引擎 reference 文件，串行执行检查
    Purpose → Rhythm → RedLine → Value → Segment → Economy
    ↓
虚拟用户行为测试（如启用，在 Segment 之后）
    ↓
汇总引擎输出 + 虚拟用户行为报告
    ↓
生成直觉层决策问题 → 交给人
```

### 模型建议（在开始前告知用户）

本审核任务对推理深度要求较高，Agent 应在启动时提醒用户：

> 「策划方案审核涉及多引擎交叉判断，建议在**更强的模型**（如 claude-sonnet 或更高版本）下执行，以获得更可靠的分析质量。当前使用的模型是否满足要求？如需切换，请在 Cursor 右上角选择后重新发起。」

**各引擎对模型能力的依赖程度**：
- Purpose / RedLine / Value：需要较强的语义理解，对模型质量敏感
- Rhythm / Segment：逻辑推演为主，普通模型也可完成
- Economy：数值逻辑检查，对模型质量敏感度中等

每个引擎加载时需读取对应 reference 文件，并包含：
1. 角色定义（引用引擎 reference）
2. 方法论来源（引用 producer-methodology.md 对应章节）
3. 审核对象（文档路径）
4. 检查要求（具体检查项）
5. 输出格式（统一格式）

## 直觉层决策问题

详见 [decision-protocol.md](references/decision-protocol.md)。

三种决策问题类型：
- **Gate**（门控）：必须等人回答才能继续
- **Flag**（标记）：人可以推翻AI结论
- **Sense**（直觉）：人的回答直接记录为裁决

规则：每轮≤3个，先Gate后Flag后Sense，尽可能提供选项。

## 制作人方法论

所有引擎的检查规则都从制作人方法论中派生：[producer-methodology.md](references/producer-methodology.md)

核心要点速览：
- **设计底线**：目标清晰且具备一定程度公平性
- **价值排序**：公平感 > 社交生态 > 爽感 > 留存 > 付费
- **三条红线**：核心循环不为KPI让步、不强迫玩家、不做冗余系统
- **五大误区**：堆系统当内容、数值解决体验问题、过度参考竞品、前期过度披露、设计给自己玩
- **判断标准**：UE是否直觉式清晰易懂

## 虚拟用户行为模拟

当 `virtual-players/` 目录下存在数据炼化的虚拟用户档案时，审查流程自动启用行为模拟层。

详见 [virtual-player-integration.md](references/virtual-player-integration.md)。

核心要点：
- **与 Segment 引擎互补**：Segment 做静态分层影响分析，虚拟用户做动态行为模拟
- **每次随机抽 3-4 个用户**，必须覆盖中坚层
- **注入随机情境变量**，避免输出模板化
- **Segment 与虚拟用户结论矛盾时**，自动触发 Flag 决策问题交给制作人
- **降级策略**：无档案时跳过，不影响 6 大引擎正常执行

## 报告模板

详见 [report-templates.md](references/report-templates.md)。

## 与 game-design skill 的关系

| 维度 | game-design | game-review |
|------|------------|-------------|
| 方法论 | 6角色团队模拟 | 制作人方法论 + 6引擎 |
| 品类 | SLG/混合休闲 | 品类无关 |
| 核心能力 | 生成方案 | 审核/优化/设计方案 |
| 直觉处理 | AI模拟 | 明确交给人 |

两套 skill 独立运行，可配合使用：`/game.design` 生成方案后用 `/game.review` 交叉审核。
