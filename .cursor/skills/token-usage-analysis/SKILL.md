---
name: token-usage-analysis
description: Analyze Cursor IDE token usage from exported CSV data. Covers per-model cost breakdown, daily/hourly patterns, session analysis, cache efficiency, request size distribution, and actionable optimization recommendations. Use when the user provides a Cursor usage CSV file, asks to analyze token consumption, wants to optimize AI usage habits, or mentions token limits/quotas.
---

# Cursor Token 用量分析

基于 Cursor Team Usage 导出的 CSV 数据，完成用量结构分析 + 模式识别 + 优化建议。

## 触发条件

用户提供 `team-usage-events-*.csv` 文件，或提到"分析 token"、"用量优化"、"额度快用完了"等。

## 执行流程

```
1. 数据加载 → 2. 运行分析脚本 → 3. 解读结果 → 4. 输出优化建议
```

## 1. 数据加载

CSV 来自 Cursor Settings > Usage > Export，字段定义：

| 字段 | 含义 |
|---|---|
| Date | UTC 时间戳 |
| User | 用户邮箱 |
| Kind | `On-Demand`(付费) / `Included`(套餐内) / `Errored, No Charge`(失败不计费) |
| Model | 模型名称 |
| Max Mode | `Yes`/`No`，是否使用 Max 模式（不限速但更贵） |
| Input (w/ Cache Write) | 输入 tokens（含首次缓存写入） |
| Input (w/o Cache Write) | 输入 tokens（不含缓存写入） |
| Cache Read | 缓存命中读取的 tokens |
| Output Tokens | 模型生成的 tokens |
| Total Tokens | 以上四项之和 |
| Requests | 聚合的请求数（可能是小数或 `Free`/`-`） |

**过滤规则**：`Kind == "Errored, No Charge"` 的行不计入分析。

## 2. 运行分析脚本

```bash
py scripts/analyze_usage.py "<CSV路径>"
```

脚本位于本 skill 目录下：`scripts/analyze_usage.py`

脚本输出 10 个维度的分析（见下方解读指引），直接在终端打印。

## 3. 结果解读指引

### 3.1 模型分布

重点关注：
- Opus 占比 > 70% → 最大优化空间，日常任务应降级到 Sonnet
- Codex/Auto 用量 → 合理使用程度

### 3.2 Token 去向（Cache Efficiency）

四大类及其含义：

| 类别 | 合理占比 | 高了说明什么 |
|---|---|---|
| Cache Read | 70-90% | 上下文在重复喂入，会话太长 |
| Input (w/ cache write) | 5-15% | 新上下文在写入缓存 |
| Input (w/o cache write) | 2-10% | 未缓存的输入 |
| Output | 0.5-3% | 模型实际产出，越高说明对话越"有效" |

**核心洞察**：Output 占比极低 (<1%) 意味着绝大多数 token 花在"告诉模型你之前说了什么"，而不是"让模型为你干活"。缩短会话是最直接的改善手段。

### 3.3 请求体量分布

| 区间 | 含义 |
|---|---|
| >= 3M | 超长上下文，会话严重膨胀 |
| 1-3M | 长会话中后段的典型体量 |
| 100K-500K | 正常工作范围 |
| < 100K | 短交互，效率最高 |

**经验法则**：>= 1M 的请求占总 token > 50% → 会话管理是第一优化点。

### 3.4 会话分析

以 30 分钟无活动为分割点，聚合成会话。关注：
- 平均每会话 token → 衡量会话长度习惯
- Top 10 重度会话 → 定位哪些场景最吃 token
- 会话时长 vs token 相关性 → 超过 2 小时的会话通常进入"收益递减"区

### 3.5 时间模式

UTC+8 小时分布，用于识别：
- 高峰时段（通常是晚间长会话）
- 深夜使用（疲劳导致效率下降、反复重试）

### 3.6 Max Mode

Max Mode = Yes 的请求不受速率限制但 token 成本更高。占比 > 30% 时建议评估是否必要。

### 3.7 Kind 分布

On-Demand vs Included 的比例，反映套餐用量是否已耗尽。

## 4. 优化建议框架

按影响力排序输出，每条建议包含：
- **预估节省百分比**（基于数据推算）
- **具体操作**（不是"减少使用"这种废话）
- **优先级**（P0/P1/P2）

### 标准建议库

| 优先级 | 建议 | 触发条件 | 预估节省 |
|---|---|---|---|
| P0 | 降级模型：默认用 Sonnet，复杂任务才切 Opus | Opus > 70% | 40-60% |
| P0 | 缩短会话：任务完成即开新 Chat | >= 1M 请求占 > 50% | 30-40% |
| P1 | 精确 @ 引用：指定文件而非让 Agent 搜索 | Input 占比高 | 15-25% |
| P1 | 关闭无关标签页 | — | 5-10% |
| P2 | 减少深夜 marathon session | 00-06 占比 > 10% | 10-15% |
| P2 | 评估 Max Mode 必要性 | Max Mode > 30% | 视情况 |

### 输出格式

```markdown
## Token 用量分析报告

### 核心数据
| 指标 | 数值 |
|---|---|
| 统计周期 | ... |
| 总消耗 | ... |
| 日均消耗 | ... |
| 会话数 / 平均每会话 | ... |

### 关键发现
1. [最大发现，带数据支撑]
2. [第二大发现]
3. [第三大发现]

### 优化建议（按影响排序）
| 优先级 | 建议 | 预估节省 | 具体操作 |
|---|---|---|---|
| P0 | ... | ...% | ... |
| P1 | ... | ...% | ... |

### 预估效果
同时执行 P0 建议，日均消耗可从 X 降到 Y，节省约 Z%。
```

## 注意事项

- 时区：CSV 中 Date 是 UTC，展示时统一转 UTC+8
- Requests 字段可能是小数、`Free`、`-`，解析时做容错
- 多用户团队 CSV 先按用户拆分，聚焦用户自己的数据
- 分析脚本无第三方依赖，仅使用 Python 标准库
