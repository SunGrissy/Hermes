# Palace 多角色协商引擎

> 基于管线角色（PLD/PLE/PLT/PMO）的 AI 审查与决策系统
> 创建日期：2026-03-03
> 最后更新：2026-03-09

## 定位

Palace 是 MyAgent 下的新项目，定位为**管线决策服务层**——读取 PLAYBOOK 规则和 PmSystem 数据，通过多角色 AI 并行审查，产出结构化决策报告。

审查发生在两个层级：
- **Feature 级**：单个 Feature 的交付物质量门禁（WHAT 预审、DoR 门禁、HOW 品质门禁）
- **版本级**：版本整体 scope / 风险 / 排期的健康度评估（PMO 角色）

## 设计灵感

- **复杂任务三步法（S0→S3）**：分层防御思想——用最少资源识别真正需要资源的任务，逐层递减流量、递增精度
- **Palace 三省六部制**：人类验证过的治理结构映射为多Agent协作——角色专业化 + 制度化流程替代单点智能
- **PLAYBOOK 四层模型**：WHAT/HOW/BUILD/MAKE 职权边界天然定义了每个审查角色的视角和权力范围

## 三层概念模型

管线审查发生在清晰的概念分层之上：

```
运营节点 (Operational Node)     版本 (Version/Release)      Feature (管线单元)
─────────────────────────      ──────────────────────      ───────────────────
描述"市场侧"                    描述"交付侧"                 描述"生产侧"
SABC = 内容密度/新鲜感           = 一次部署的打包容器          = 一条独立管线的最小单位

属性：                          属性：                       属性：
  tier (S/A/B/C)                 release_date                 pipeline_weight (fast/slow)
  关联 Features 列表              scope (Feature 列表)          operational_node (运营节点)
                                 resource_budget               version (所属版本)
                                                              pipeline_stage (规划→复盘)
```

**三者正交**：
- SABC 描述运营节点的内容投放密度，不是版本属性
- 快/慢轨是 Feature 属性，一个版本可同时包含快轨和慢轨 Feature
- Feature 可跨版本迁移而管线状态不变
- Palace Feature 级审查基于 pipeline_weight 选择审查场景和审查强度
- Palace 版本级审查（PMO）聚合所有 Feature 的管线状态评估整体健康度

## 审查职责矩阵

### 交付物 × 审查人 × 权力

> Owner 是管线角色（同 PLD），不固定为某个职能。同一个 Feature 的 WHAT/HOW/BUILD 文档可能由不同人编写。
> 审查跟文档的层级走，不跟写文档的人的职能走。

| 文档层级 | 制作人 | PLD | PLE | PLT | 主美 | 主程 |
|---|---|---|---|---|---|---|
| **WHAT（体验设计）** | **审**（战略对齐） | **审**（内容方向，block 权） | **审**（可设计性 + 向上理解，concern） | **审**（可实现性 + 向上理解，concern） | — | — |
| **HOW（交互方案）** | **关注**（纠偏，不阻塞） | — | **验**（品质 Owner，block 权） | **审**（技术可行性，block 权） | **审**（视觉品质，block 权） | — |
| **BUILD（系统方案）** | — | — | — | **验**（品质 Owner） | — | **审**（架构合理性，block 权） |

**"向上理解"**：审查者不仅审本层质量，还审文档是否体现了对上游层级意图的正确理解（如系统策划的 BUILD 文档应体现对 WHAT 体验意图和 HOW 交互方案的理解）。

### WHAT 文档的定义

WHAT 文档 = **内容体验设计**（不是功能需求文档）：

```
第一层：体验意图（必须）—— 用户应该产生什么感受/行为变化？
第二层：内容结构（必须）—— 用什么内容结构承载体验意图？
第三层：决策约束（必须）—— 哪些是已决策？哪些留给 HOW/BUILD？
第四层：成功指标（必须）—— 怎么衡量体验意图是否实现？
```

**边界判断标准**：描述"用户应该有什么感受/行为" = WHAT；描述"怎么在界面上实现" = HOW。

### 层间连贯性审查模型（D72-D75）

审查跟着**文档的层级**走，不跟着**人的职能**走。"谁写的"不是审查重点，"这个层级的核心交付物到位了吗"才是。

**核心原则**：每份文档既审**本层质量**，又审**跨层连贯性**：

```
                向上对齐（理解上游意图）
                    ↑
    本层核心交付完整度 ← 审查焦点 → 跨层材料定性（参考 vs 决策）
                    ↓
                向下空间（给下游留余地）
```

**三类跨层内容的定性**（替代旧的"越界检测"）：

| 类型 | 定义 | 审查态度 | 示例 |
|------|------|---------|------|
| **跨层理解展示** | 附带相邻层材料帮助接收方理解 | 正面（鼓励，审质量） | 系统策划在 BUILD 文档中画交互流程图 |
| **跨层参考标注** | 包含其他层的参数/方案但标注为"参考值" | 中性（检查标注清晰度） | WHAT 文档附"35人一组（参考值，由系统策划确定）" |
| **跨层替代决策** | 替其他层做了最终决策且未标注 | 需改进（建议改为参考） | 运营在 WHAT 文档中写死匹配算法的具体参数 |

**审查优先级翻转**：
1. **P0 核心交付**：本层的核心交付物完整吗？质量达标吗？
2. **P1 向上对齐**：文档是否体现了对上游层级意图的理解？
3. **P1 向下空间**：给下游层级留够设计/实现空间了吗？
4. **P2 跨层定性**：附带的跨层材料是否清晰标注了"参考"而非"决策"？

**document_layer 元数据**：提交审查时必须声明文档层级：

```yaml
feature_meta:
  document_layer: "WHAT"    # WHAT / HOW / BUILD / mixed
  # mixed = 过渡期混合文档，Palace 按层拆开审
```

当 `document_layer: mixed` 时，Palace 对同一份文档分别用 WHAT/HOW/BUILD 标准审查各自的内容，并额外检查层间连贯性。

### 版本排布预审（version_layout）

版本排布预审发生在**版本规划阶段**，是所有 Feature 进入详细设计之前的门禁。
与 `what_precheck`（审单篇 Feature 文档纵向深度）正交——它审的是多个 Feature 组合在一起的横向构成质量。

```
管线时序：

PLD 产出版本规划（Feature 清单 + 各自的 WHAT 概要 + 组盘逻辑）
    ↓
version_layout 预审 ← 审的是这份规划，不是各 Feature 的完整文档
    ↓
制作人决策（direction_aligned ✅ 或 打回重组）
    ↓
各 Feature Owner 领到明确的 WHAT 要求，开始写详细文档
    ↓
what_precheck 审单篇文档
    ↓
DoR 门禁
```

| 项目 | 说明 |
|------|------|
| **场景 ID** | `version_layout` |
| **输入物** | 版本规划文本（Feature 清单 + 各 Feature WHAT 概要 + 组盘逻辑） |
| **提取角色** | `layout_analyst`（版本排布结构分析师，advisory） |
| **评估角色** | `pld`（concern）+ `pmo`（advisory） |
| **审查维度** | 快慢轨配比、用户价值覆盖、内容节奏、研发负荷、风险集中度、逐 Feature WHAT 交代 |
| **综合规则** | any_block → block, concern_threshold: 1 |
| **对应 PmSystem** | planning 节点的 `direction_aligned` 勾选前置 |

**关键设计决策**：版本规划先于 Feature 文档存在。不能等所有 Feature 文档写完再组版本，那样来不及。
版本规划里每个 Feature 应包含的不是完整设计，而是 WHAT 层的"交代"：
体验意图（一句话）、管线权重、目标用户群、在版本中的角色、粗略体量、成功标准方向。

### 快慢轨分级审查

| | 慢轨 WHAT 预审（准备中期） | 慢轨 DoR 门禁 | 快轨轻量审查 |
|---|---|---|---|
| **触发时机** | 准备阶段中期 | DoR 申请时 | DoR 申请时 |
| **Palace 角色** | PLD + PLE + PLT + Boundary | PLD + PLE + PLT（人审签字） | PLD + PLT（兼容性半锁） |
| **PLD 权力** | block | block | block |
| **PLE 权力** | concern（审可设计性） | block（人审） | 不参与 |
| **PLT 权力** | concern（审可实现性） | block（人审） | concern（框架兼容性确认） |
| **Boundary** | advisory | 不参与（已在预审覆盖） | 不参与 |
| **综合规则** | any_block → block | 三把锁全过 | PLD 过 + PLT 兼容 → 通过 |

HOW 方案审查（独立于 WHAT 审查，发生在准备阶段后期）：

| | 慢轨 HOW 审查 | 快轨 HOW 审查 |
|---|---|---|
| **审查人** | PLE（品质 Owner）+ 主美 + PLT | PLE 轻量确认 |
| **PLE 权力** | block（整体体验不达标） | concern |
| **主美 权力** | block（视觉品质不达标） | 不参与 |
| **PLT 权力** | block（技术不可行 / 性能超标） | 不参与 |
| **制作人** | 关注（纠偏，不阻塞） | 不参与 |

### 轨道分类决策树

```
Feature 需要新增系统框架（新代码模块）？
       /              \
     是                否
     ↓                 ↓
  慢轨（确定）       美术资产超出快轨预算？
                      /          \
                    是            否
                    ↓              ↓
              升级慢轨         体验追求代差？
              （主美确认）       /         \
                            是           否
                            ↓             ↓
                      升级慢轨        快轨（确定）
                      （PLE 确认）

主判据：是否需要新框架（二值，无模糊）
升级触发器：逐项检查每个 B 指标能否在快轨预算内消化
核心原则：轨道只能升级（快→慢），不能降级
```

## 项目结构

```
MyAgent/
  palace/
    palace_engine/
      __init__.py
      engine.py           # 核心引擎：议题路由 + 角色调度 + 并行执行 + 意见综合
      llm_client.py       # LLM Provider 抽象（MockProvider + OpenAI Compatible）
      config.py           # 配置加载（角色YAML + 环境变量）
      knowledge.py        # PLAYBOOK 章节切片器
      schemas.py          # 结构化输出 schema（review_result / advisory_result）
    roles/
      pld.yaml            # 管线主策：审 WHAT 内容方向（block 权）
      ple.yaml            # 管线体验：审 WHAT 可设计性 + 验 HOW 品质（block 权）
      plt.yaml            # 管线技术：审 WHAT 可实现性 + 审 HOW 技术可行性（block 权）
      boundary.yaml       # 职权边界检查（advisory）
      pmo.yaml            # 版本级 PMO：scope/风险/排期评估（advisory）
      layout_analyst.yaml # 版本排布结构分析师：审版本组盘构成（advisory）
    scenarios/
      what_precheck.yaml  # 慢轨 WHAT 预审（已实现，PLD+PLE+PLT+Boundary）
      dor_slow.yaml       # 慢轨 DoR 审查（PLD+PLE+PLT，正式门禁）
      dor_fast.yaml       # 快轨 DoR 审查（PLD+PLT 兼容性半锁）
      dor_review.yaml     # Feature DoR 审查（6角色：PLD+PLE+PLT+边界+数值+QA）
      how_review.yaml     # HOW 方案审查（PLE+PLT，独立于 WHAT 审查）
      version_scope.yaml  # 版本 scope 健康度评估（PMO）
      version_layout.yaml # 版本内容排布预审（LayoutAnalyst+PLD+PMO，已实现）
      version_health.yaml # 版本健康度检查（PMO 主导，待实现）
      version_planning.yaml # 版本规划综合审查（全阁审议，待实现）
      growth_review.yaml  # 增长复盘（御史台主导 advisory，待实现）
      org_advisory.yaml   # 组织架构咨询（吏部尚书主导，待实现）
      resume_screening.yaml # 简历筛选（吏部尚书主导，待实现）
    run.py                # CLI 入口（测试用）
    requirements.txt
    .env.example
```

## 核心架构

```
输入                              Palace Engine                              输出
─────────                         ─────────────                              ─────

Feature 级审查：
  WHAT 文档文本 ─┐                ┌──────────────┐
  HOW 方案文本 ──┤                │ PLD Agent    ├──┐
  Feature 元数据 ┘──→ 议题路由器 ─┤ PLE Agent    │  │
                                 │ PLT Agent    │  ├──→ 综合器 ──→ 结构化审查报告 JSON
  场景配置 YAML ───→              │ Boundary     │  │
                                 └──────┬───────┘  │
版本级审查（scope）：                      │          │
  版本 Feature 列表 ──→ PMO Agent ──────────────────┘
  各 Feature 管线状态

版本排布预审（layout）：
  版本规划文本 ──→ LayoutAnalyst（提取） ──→ PLD + PMO（评估） ──→ 排布预审报告
  （各 Feature 的 WHAT 概要 + 组盘逻辑）
                                 LLM Provider 接口
                                 ├── MockProvider（开发/测试）
                                 └── OpenAI Compatible（中转站）
```

### Feature 元数据（Input Metadata）

提交审查时附带的结构化信息，用于精准匹配审查场景和审查强度：

```yaml
feature_meta:
  title: "锦标赛月赛"
  owner: "崔忠仁"
  owner_role: "运营策划"           # Owner 的职能角色
  pipeline_weight: "slow"         # fast / slow
  pipeline_stage: "scoping"       # planning / scoping / dor / production
  operational_node: "五一"         # 所属运营节点
  operational_tier: "S"           # S / A / B / C
  version: "v2.1"                 # 所属版本
```

## 关键设计决策

### 1. LLM 客户端：Provider 抽象 + Mock 优先

开发阶段使用 MockProvider，最后一步接入真实 API。

```python
class LLMProvider(ABC):
    async def complete(self, system: str, user: str, schema: dict) -> dict:
        """返回结构化 JSON 响应"""

class MockProvider(LLMProvider):
    """根据角色ID和议题关键词返回预设的审查结果"""

class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容接口（智谱 GLM-4 / DeepSeek / 通义等）"""
```

MockProvider 设计要点：
- 根据角色 ID 返回符合 schema 的预设 JSON（有业务含义的模拟审查意见）
- 支持通过议题关键词触发不同结果（如包含"交互稿缺失"→ PLE 返回 block）
- 模拟真实延迟（asyncio.sleep），验证并行调度逻辑

真实 Provider 核心参数（Phase 5 实现）：
- `temperature: 0.2`（审查场景需要确定性）
- `response_format: json_schema`（强制结构化输出）
- 每次调用独立会话，角色之间不共享上下文

### 2. 角色配置 Schema

每个角色 YAML 包含五层——身份、知识、行为、输出、轨道差异：

```yaml
# roles/pld.yaml 示例
id: pld
name: "管线主策 (PLD)"
layer: WHAT

persona: |
  你是本版本的管线主策(PLD)，版本内容方向总负责人。
  你审查的是 WHAT 层的「内容体验设计」文档——关注体验意图、内容结构、
  决策约束和成功指标，而非功能需求参数或实现细节。

knowledge_sections:
  - pipeline_roles
  - authority_model
  - dor_standards
  - dual_track

# 慢轨审查维度（完整）
review_dimensions:
  - "体验意图是否清晰？能否一句话说清'用户应产生什么感受'？"
  - "内容结构是否能承载体验意图？逻辑是否自洽？"
  - "已决策项是否有依据（数据/竞品/战略判断）？"
  - "留给 HOW/BUILD 的空间是否合理？有没有锁死下游？"
  - "成功指标是否可衡量、和北极星对齐？"
  - "数值/经济模型是否已协调数值评审？"

# 快轨审查维度（精简）
review_dimensions_fast:
  - "内容设计是否在框架能力范围内？"
  - "增量改动的预期用户价值是否清晰？"
  - "资源投入是否在快轨预算内？"

authority: block
block_conditions:
  - "内容方向偏离版本目标"
  - "体验意图不清晰，下游无法落地"
  - "成功指标缺失"
```

```yaml
# roles/pmo.yaml 示例（管线运营域）
id: pmo
name: "管线总管 (PMO)"
layer: cross

persona: |
  你是版本管线的总管（PMO），负责全局进度监控和跨组协调。
  你不做内容判断（那是PLD的事），不做体验判断（那是PLE的事），
  不做技术判断（那是PLT的事）。
  你只看三件事：进度是否健康、资源是否到位、依赖是否断裂。
  你的输出铁律：每一条记录必须包含——「谁」在「什么时间」把「什么」做到「什么程度」。
  不接受"在跟进了""差不多了""有点问题"。

knowledge_sections:
  - pipeline_roles           # §三 管线角色（理解谁负责什么）
  - dor_standards            # §五 DoR 分级（门禁标准）
  - dual_track               # §二 双轨制（快轨/慢轨不同节奏）

data_sources:                # 系统数据（非 PLAYBOOK 章节）
  - pmsystem_versions        # PmSystem 版本数据
  - pmsystem_features        # PmSystem Feature 状态/进度
  - pmsystem_milestones      # PmSystem 里程碑
  - pmo_report_template      # PMO 管线汇报模板（输出格式参考）

review_dimensions:
  - "整体进度是否健康？完成比 vs 时间比差值多少？"
  - "有无阻塞/延期 Feature？原因和预计解决时间？"
  - "跨组依赖是否完整？有无等待超时？"
  - "上下游交付质量评价是否存在标准偏差？"
  - "资源是否有瓶颈？谁过载了？下个版本轮值候选人够不够？"

authority: concern_only
```

```yaml
# roles/personnel.yaml 示例（人才组织域）
id: personnel
name: "吏部尚书"
layer: cross

persona: |
  你是工作室的组织与人才管理顾问，分管三条线：
  1. 组织能力建设——管理幅度诊断、中间层策略、轮值制运转
  2. 人事考核管理——绩效公式设计、标尺校准、评价周期运营
  3. 招聘线——岗位需求分析、JD 设计、简历筛选、候选人画像
  你的核心原则：
  - 管理体系是效能的基础设施——建议必须回答"省了什么？快了多少？好了多少？"
  - 单一指标归属——一个指标不由两个人同时背
  - tenure 递增——标尺随在位时间提高，"非升即走"
  - 进化系数——无 AI 成果 = 上限 80%，不可商量
  - 轮值优于固化——降低关键人依赖成本
  你的沟通风格：不上价值，用"痛点→解法"结构；给选择而非给指令。

knowledge_sections:
  - evaluation               # §六 评价哲学（乘法公式、标尺设计）
  - ai_evolution             # §七 AI进化纲领（进化系数、职能融合）
  - org_diagnosis            # §八 组织诊断（管理幅宽、中间层策略）
  - pipeline_roles           # §三 管线角色体系（理解轮值制）
  - north_star               # §零 北极星（增长效能，建议的锚点）

data_sources:
  - producer_context         # producer-context.mdc（团队80人现状）
  - org_structure            # org-structure.html 中的组织数据
  - rubrics                  # rubric_*.json（各职能标尺定义）
  - performeval_members      # PerformEval 成员数据
  - performeval_evaluations  # PerformEval 评价记录

review_dimensions:
  - "这个方案是否降低了管理幅度，还是增加了？"
  - "考核标准是否符合'整体评判+加法层举证'的两层模型？"
  - "标尺是否满足 tenure 递增原则？卓越档是否指向下一 L 级？"
  - "招聘需求是否因组织诊断驱动，而非'感觉缺人'？"
  - "方案是否有利于超级个体培养，还是在固化层级？"

authority: concern_only
```

```yaml
# roles/numerics.yaml 示例（数值/经济系统域）
id: numerics
name: "户部尚书（数值顾问）"
layer: WHAT_BUILD        # 跨两层：WHAT 层判断生态方向，BUILD 层审查配表/公式

persona: |
  你是数值与经济系统顾问，对应 PLAYBOOK §九"命题-解题"模型中的解题方视角。
  你负责：生态方向判断、经济系统健康度、定价策略、概率设计、留存影响评估。
  你不做"做什么"的决策（那是命题方/制作人的事），
  你做"数值上行不行"的判断。
  你和 PLD 的分工：PLD 审查"内容方向对不对"，你审查"数值上合不合理"。

knowledge_sections:
  - north_star               # §零 北极星（增长效能）
  - dual_track               # §二 双轨制（快轨数值支撑 vs 慢轨策略实验）

review_dimensions:
  - "奖励/产出是否会打破现有经济平衡？"
  - "定价是否在玩家接受区间？付费深度合理吗？"
  - "概率设计是否透明、合规？预期收益是否经过模拟？"
  - "对长期留存的影响是正向还是负向？"
  - "是否需要 A/B 实验验证？实验设计是否严谨？"

authority: concern_only      # 不 block，但可标记"数值风险"
```

```yaml
# roles/qa_review.yaml 示例（质量门禁）
id: qa_review
name: "刑部尚书（QA 审查）"
layer: MAKE              # 质量门禁，站在 MAKE 层往上看

persona: |
  你是质量与风险控制官。你的职责不是测试本身，
  而是审查：这个方案的验收标准是否清晰可测？测试资源是否够用？上线风险是否可控？
  你在两个节点介入：
  1. DoR 阶段：审查可测性——spec 能不能转化为测试用例？
  2. DoD 阶段：审查发版就绪度——bug 量、覆盖率、风险等级。
  你和 PLT 的分工：PLT 管"技术上能不能实现"，你管"实现之后能不能验证"。

knowledge_sections:
  - pipeline_roles           # §三 管线角色体系
  - dor_standards            # §五 DoR 分级

review_dimensions:
  - "验收标准是否明确、可量化、可自动化？"
  - "边界条件和异常路径是否被定义？"
  - "预估测试工作量是否合理？资源是否到位？"
  - "是否有回归风险？影响已有功能的概率？"
  - "上线后的监控和回退方案是否准备好？"

authority: block             # 可 block——验收标准不清晰的 Feature 不准进生产
```

```yaml
# roles/strategist.yaml 示例（战略对齐）
id: strategist
name: "御史台（战略锚）"
layer: WHY               # 唯一一个 WHY 层角色
scope: [pipeline, growth] # 双轨：管线战略 + 增长战略

persona: |
  你是战略对齐的守门人，覆盖两条轨道：
  1. 管线轨：Feature/版本规划是否对齐北极星。
  2. 增长轨：买量节奏/投放策略是否对齐增长效能公式。
  两条轨道共享同一个核心问题：
  这件事是否推动了北极星——增长效能 = 单位成本产出的用户价值。
  三条路径：做分子（提升LTV和自然量）？做分母（压缩边际成本）？提转化？
  你同时是制作人的学习伙伴——当制作人的决策思路不够清晰时，
  你通过追问帮助他厘清思路，而非直接给出答案。
  你不做具体方案判断，你做战略方向判断和思维训练。
  你遵守制作人的思维纪律（见 producer-context.mdc）：
  穿透表面指标、看结构再看绝对值、警惕相关≠因果、追问决策本质。

knowledge_sections:
  - north_star               # §零 北极星（增长效能公式）
  - dual_track               # §二 双轨制（平战结合节奏）

review_dimensions:
  # 管线轨
  - "这个 Feature 对北极星公式的哪个变量有贡献？能量化吗？"
  - "这是平时状态该做的还是节点状态该做的？时机对吗？"
  - "快轨还是慢轨？管线重量和投入产出比匹配吗？"
  - "机会成本：如果这些资源投到别处，效果会更好吗？"
  - "这个决策背后的假设是什么？假设如果错了，后果是什么？"
  # 增长轨（growth_review 场景时激活）
  - "当前投放节奏和版本节奏是否匹配？是平时保底还是节点脉冲？"
  - "CPI 变化的归因是什么？素材质量、版位结构、还是市场竞争？"
  - "素材储备的健康度如何？头部依赖度是否过高？"
  - "这笔获客投入的回收预期，和利润率目标是否矛盾？"

authority: concern_only      # 不 block 具体方案，但标记"战略偏移"
```

**角色配置新增 `data_sources` 字段**：`knowledge_sections` 引用 PLAYBOOK 章节（静态文档），`data_sources` 引用系统 API 和文件数据（动态数据）。PMO 和吏部尚书比 PLD/PLE/PLT 更依赖动态数据。开发阶段 data_sources 用 mock 数据，Phase 5+ 接真实 API。

### 3. 场景配置

场景按审查对象（Feature/版本）× 管线阶段 × 轨道类型组合：

```yaml
# scenarios/what_precheck.yaml — 慢轨 WHAT 预审（Palace 主战场）
id: what_precheck
name: "慢轨 WHAT 预审"
mode: review
target: feature
pipeline_weight: slow
pipeline_stage: scoping
roles: [pld, ple, plt, boundary]
synthesis_rules:
  any_block_means_block: true
  concern_threshold: 2
  must_list_action_items: true

# scenarios/dor_slow.yaml — 慢轨 DoR 门禁
id: dor_slow
name: "慢轨 DoR 审查"
mode: review
target: feature
pipeline_weight: slow
pipeline_stage: dor
roles: [pld, ple, plt]          # 无 boundary（已在预审覆盖）
synthesis_rules:
  any_block_means_block: true
  must_list_action_items: true

# scenarios/dor_fast.yaml — 快轨 DoR 审查
id: dor_fast
name: "快轨 DoR 审查"
mode: review
target: feature
pipeline_weight: fast
pipeline_stage: dor
roles: [pld, plt]               # PLD block 权 + PLT 兼容性半锁
synthesis_rules:
  any_block_means_block: true
  must_list_action_items: true
# PLD 使用 review_dimensions_fast，PLT 使用 review_dimensions_fast

# scenarios/how_review.yaml — HOW 方案审查
id: how_review
name: "HOW 方案审查"
mode: review
target: feature
pipeline_stage: scoping_late    # 准备阶段后期
roles: [ple, plt]               # PLE 品质 Owner + PLT 技术可行性
synthesis_rules:
  any_block_means_block: true
  must_list_action_items: true

# scenarios/version_scope.yaml — 版本 scope 健康度
id: version_scope
name: "版本 Scope 评估"
mode: advisory                  # 只建议，不 block
target: version
roles: [pmo]
synthesis_rules:
  must_list_action_items: true
  flag_risk_concentration: true
```

### 4. 知识切片

从 PLAYBOOK.md 按 `## X、` 标题正则匹配提取章节（已实现，替代了脆弱的硬编码行号）：

```python
SECTION_PATTERNS = {
    "north_star":      r"^## 零、",
    "strategic":       r"^## 一、",
    "dual_track":      r"^## 二、",
    "pipeline_roles":  r"^## 三、",
    "authority_model": r"^## 四、",
    "dor_standards":   r"^## 五、",
    "evaluation":      r"^## 六、",
    "ai_evolution":    r"^## 七、",
    "org_diagnosis":   r"^## 八、",
    "data_collab":     r"^## 九、",
}
```

### 5. 结构化输出 Schema

单角色审查结果：

```json
{
    "role_id": "pld",
    "verdict": "concern",
    "reasoning": "活动规则完整，但奖励梯度缺数值论证",
    "dimension_checks": [
        {"question": "内容方向是否一致？", "status": "pass", "note": ""},
        {"question": "需求描述完整？", "status": "concern", "note": "缺预期指标"}
    ],
    "boundary_violations": [],
    "action_items": ["补充预期指标", "请数值出奖励梯度方案"]
}
```

综合审查结果：

```json
{
    "overall_verdict": "block",
    "summary": "PLE block：交互稿缺失。PLD concern：数值未评审。PLT pass。",
    "role_results": ["...各角色独立结果..."],
    "boundary_violations": ["运营方案包含UI布局建议 → WHAT层侵入HOW层"],
    "action_items": [
        {"priority": "P0", "owner": "PLE/UX", "action": "补交互稿"},
        {"priority": "P1", "owner": "数值", "action": "出奖励梯度方案"},
        {"priority": "P2", "owner": "运营", "action": "移除方案中的UI布局描述"}
    ],
    "dor_status": "blocked",
    "blocker_count": 1,
    "concern_count": 1
}
```

### 6. engine.py 核心流程

```python
async def run_scenario(scenario_id: str, topic_text: str) -> dict:
    scenario = load_scenario(scenario_id)
    roles = [load_role(r) for r in scenario.roles]

    tasks = [invoke_role(role, topic_text, scenario.mode) for role in roles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid, errors = partition_results(results, roles)
    synthesis = await synthesize(valid, scenario.synthesis_rules)

    return synthesis
```

### 7. MVP 验证方式

```bash
py palace/run.py --scenario dor_review --input "春节限时礼包活动：面向付费用户的限时7天礼包..."
```

## 实施步骤

### Phase 1：引擎骨架 + Mock LLM 客户端

- 创建目录结构
- 实现 `llm_client.py`（Provider 抽象接口 + MockProvider）
- 实现 `config.py`（YAML 加载 + .env 读取）
- MockProvider 能根据角色ID返回预设的结构化审查结果

### Phase 2：角色配置 + 知识注入

- 编写 4 个角色 YAML（PLD/PLE/PLT/边界检查）
- 实现 `knowledge.py`（PLAYBOOK 章节切片）
- 实现 `schemas.py`（结构化输出 JSON Schema）

### Phase 3：引擎核心 + 场景配置（Mock 驱动）

- 实现 `engine.py`（角色调度 + asyncio.gather 并行 + 综合器）
- 编写场景 YAML（已实现 what_precheck + 5 个占位；待实现 version_health / version_planning / growth_review / org_advisory / resume_screening）
- 实现综合器的硬规则（any_block_means_block 等）+ 后续支持 advisory 模式（建议+选择）
- 全部用 MockProvider 驱动，验证调度逻辑和综合逻辑正确

### Phase 4：CLI 入口 + Mock 端到端验证

- 实现 `run.py` CLI 入口
- 准备 2-3 个测试 Feature 方案（一个应通过、一个应 block、一个边界情况）
- 用 mock 端到端跑通完整流程
- 验证：并行调度正确、综合规则正确、输出格式合规、错误降级正常

### Phase 5：接入真实 LLM API

- 实现 `OpenAICompatibleProvider`（智谱 GLM-4）
- 通过环境变量 `PALACE_PROVIDER=openai_compatible` 切换 mock/真实
- 用测试 Feature 方案对比 mock 和真实输出
- 调优角色 persona 和 review_dimensions
- 验证结构化输出解析的鲁棒性

## 后续扩展路径

- 接入 PmSystem API（从 `/api/features/{id}` 拉取 Feature 数据 + 元数据）
- S0 静态预检层（纯规则，零 LLM 成本）：待定项计数、Owner 声明、成功指标、管线重量
- 框架能力清单对照：快轨 PLT 兼容性半锁的自动化基础

```
层级         角色                域               authority
─────────────────────────────────────────────────────────────
WHY          御史台（战略锚）     战略对齐          concern_only
WHAT         PLD（管线主策）      Feature 审查      block
WHAT+BUILD   户部尚书（数值）     数值/经济系统      concern_only
HOW          PLE（管线体验）      Feature 审查      block
BUILD        PLT（管线技术）      Feature 审查      block
MAKE         刑部尚书（QA）       质量门禁          block
跨层          边界检查            职权边界          block
─── 横向职能 ──────────────────────────────────────────────
运营          PMO（管线总管）      管线运营          concern_only
组织          吏部尚书            人才组织          concern_only
```

**block 权力分布**：PLD、PLE、PLT、QA、边界 共 5 个角色有 block 权。其余 4 个角色只能标记 concern。这保证了"具体执行层有否决权，战略和管理层只提建议"的权力结构。

## 御史台进化路径（长期规划）

御史台（Strategist）不只是一个审查角色——它是制作人的**思维训练伙伴**。

### 职责范围（双轨）

**管线战略对齐**（原有）：审查 Feature / 版本规划是否对齐北极星。
**增长战略对齐**（扩展）：审查买量节奏、投放策略是否对齐增长效能公式。

两条轨道共享同一个思维内核：**这件事对"单位成本产出的用户价值"的哪个变量有贡献？**

> 增长侧的即时判断需求（素材初评、A/B 解读）由 `growth-advisor.mdc` 覆盖，
> 不走 Palace 引擎。御史台只参与结构化的增长复盘场景（见 `growth_review`）。

### 阶段 1：对齐检查（当前 MVP）
- 被动模式：在 dor_review / version_planning / growth_review 中作为角色参与
- 职责：检查议题是否对齐北极星

### 阶段 2：决策追问
- 主动模式：制作人输入一个决策想法，御史台通过苏格拉底式追问帮助厘清
- 覆盖管线决策和增长决策
- 记录追问-回答链路，沉淀为决策档案

### 阶段 3：认知建模
- 基于历史决策档案，构建制作人的决策模式画像
- 识别常见思维盲区（如"总是低估时间成本""倾向于做加法而非减法""节点放量时容易被短期数据冲昏"）
- 主动提醒：当新决策触发已知盲区模式时预警

### 阶段 4：战略参谋
- 结合行业数据、竞品分析、历史项目数据、投放数据
- 从"检查对齐"升级为"建议方向"
- 制作人和御史台形成"命题-挑战"的良性循环

> 阶段 1 在本次 MVP 范围内。阶段 2-4 架构预留，不实现。

## 增长复盘场景

```yaml
# scenarios/growth_review.yaml — 增长复盘（御史台主导 advisory）
id: growth_review
name: "增长复盘"
mode: advisory
roles: [strategist]
trigger: 手动触发 / 周期性（建议每周或每版本节点后）

input_schema:
  - period: "复盘周期（如 '上周' / '2月' / 'v3.2版本期间'）"
  - spending_data: "投放消耗数据（总消耗、CPI、ROI、分版位明细）"
  - cci_summary: "CCI 系统输出摘要（头部素材表现、淘汰率、新素材成功率）"
  - product_events: "产品侧事件（版本更新、活动上线、功能变更）"
  - market_context: "市场环境（竞品动作、行业 CPI 趋势、季节性因素）"

output_includes:
  - period_summary           # 本期投放概况（平时 vs 节点拆分）
  - north_star_impact        # 对北极星公式各变量的影响评估
  - pulse_rhythm_review      # 脉冲节奏回顾：开枪时机对不对？收枪信号是否及时？
  - creative_health          # 素材健康度：储备量、头部依赖度、衰减速度
  - next_period_suggestion   # 下期策略建议：预算分配、素材生产重点、节点预判
  - lessons_learned          # 本期经验沉淀（可回写到 growth-advisor.mdc 经验区）
```

> 此场景和 PLD/PLT 等管线角色无关，只有御史台参与。
> 它的本质是帮制作人做"增长侧的结构化复盘"，逐步建立脉冲买量的量化框架。

## 后续扩展路径（不在本次范围，架构预留）

- 接入 PmSystem API（PMO 角色从 `/api/features` `/api/versions` 拉取真实数据）
- 接入 PerformEval API（吏部尚书从 `/api/members` `/api/evaluations` 拉取成员和评价数据）
- 解析 org-structure.html 中的组织架构数据供吏部尚书使用
- 户部尚书接入数值策划工具数据（配表、经济系统模拟结果）
- 刑部尚书接入 QA 系统（bug 数据库、测试覆盖率报告）
- growth_review 场景接入广告平台 API（自动拉取投放数据，减少手动输入）
- growth_review 输出的 lessons_learned 自动回写 `growth-advisor.mdc` 经验沉淀区
- 新增场景：运营活动规划（advisory 模式）、考核标准设计（eval_design）
- 集成到 PmSystem 前端（Feature 页加"审查"按钮，版本页加"健康度检查"按钮）
- 集成到 Cursor AgentX（作为 Agent Skill 被调用）
- 审查历史沉淀 → 组织诊断数据源（越界频率、block 率、返工率趋势）

## 决策记录（本轮讨论 2026-03-04）

| # | 决策 | 详情 |
|---|------|------|
| D59 | 三层概念模型 | 运营节点(SABC,用户感知) / 版本(部署容器) / Feature(管线单元) 三者正交。SABC 描述运营节点内容密度，不是版本属性。快/慢轨是 Feature 级属性 |
| D60 | WHAT 文档定义 | WHAT 文档 = 内容体验设计（体验意图 + 内容结构 + 决策约束 + 成功指标），不是功能需求文档。描述"用户应有什么感受" = WHAT，描述"界面怎么实现" = HOW |
| D61 | 审查职责矩阵 | 审查跟文档层级走不跟人的职能走。Owner 是管线角色不固定职能。制作人审 WHAT + 关注 HOW；PLD/PLE/PLT 各自按文档层级审；PLE+主美+PLT 审 HOW；主程审 BUILD |
| D62 | HOW block 权 | 慢轨：PLE(整体体验) + 主美(视觉品质) + PLT(技术可行性) 三方均有 block 权。快轨：PLE 轻量 concern，主美/PLT 不参与 |
| D63 | 快慢轨分级审查 | 慢轨全量审查（预审+DoR），快轨轻量审查（PLD+PLT 兼容性半锁）。审查强度由 pipeline_weight 决定 |
| D64 | 轨道分类机制 | Owner 自评 → PLD 审核 → PLT 兜底。主判据：是否需要新框架（二值）。只能升级不能降级 |
| D65 | 框架能力清单 | 主程 + 主美 + 制作人共建，定义快轨沙盒边界。PLT 兼容性半锁以此为判据 |
| D66 | 快轨资源预算 | 开发 ≤0.5 人天、美术 ≤1 新素材、策划 ≤1 人天。超预算触发轨道升级评审 |
| D67 | 创意差异化量化 | 用活动表现指数（活动指标/同期大盘基线）衡量相对表现，组合趋势优于单次对比 |
| D68 | PMO 角色 | 新增版本级审查角色，评估 scope/风险/依赖/排期，advisory 模式（不 block） |
| D69 | 文档分层提交 | 目标态：WHAT/HOW/BUILD 分别提交（模板即边界）。过渡期：综合文档 + 层标注 |
| D70 | Palace 发力节点 | Palace 主战场 = 节点 0（轨道分类 S0）+ 节点 2（准备阶段预审）+ 节点 6（复盘趋势）。DoR 门禁以人审为主，Palace 辅助 checklist |
| D71 | PLE 反向约束 | PLE 审 WHAT 时需检查"是否给 HOW 层留了足够设计空间"，防止 WHAT 锁死下游 |
| D72 | 层间连贯性模型 | 审查从"越界检测"转向"核心交付完整度 + 跨层连贯性"。三类跨层内容：理解展示（鼓励）、参考标注（中性）、替代决策（需改进）。审查优先级：P0 核心交付 > P1 上下游对齐 > P2 跨层定性 |
| D73 | document_layer 元数据 | 提交审查时必须声明 document_layer（WHAT/HOW/BUILD/mixed），Palace 据此匹配审查标准。mixed 文档按层拆开分别审 |
| D74 | boundary 角色重定义 | 从"越界检测器"改为"层间连贯性审查官"，审核心交付完整度、跨层材料定性、层间对齐质量。不再用"越界"一词 |
| D75 | 跨层理解审查 | 所有审查角色增加"向上理解"维度：审查文档是否体现对上游层级意图的正确理解，确保 Feature 在不同层级有连贯性 |

## 批注系统需求规格（2026-03-09 讨论确定）

### 使用场景

预审报告的定位是"给审查者的提示清单"，不是 AI 的最终判决。人类通过批注过滤误判、背书有效发现，再转交下一环节。

**场景 A — 版本规划预审：**
```
PLD 提交版本规划 → Palace 生成预审报告 → 制作人批注 → 钉钉通知 PLD → PLD 查看批注
```
制作人的批注 = 对 AI 发现的筛选和背书，PLD 看到的是"制作人认同哪些、跳过哪些"。

**场景 B — Feature 文档预审：**
```
Owner 提交 Feature 文档 → Palace 生成预审报告 → PLD 批注 → 钉钉通知制作人 → 制作人复审
```
制作人通过 PLD 的批注同时考察两件事：Feature 质量 + PLD 的判断力。

### 批注标记语义

| 标记 | 语义 | 行动含义 | 需对方回应 |
|---|---|---|---|
| 🔴 **采纳** | 认同此问题，需要处理 | 请给方案或回应 | 是 |
| 🟡 **待议** | 拿不准，需要碰 | 约面聊 | 是 |
| 🟢 **已知** | 知道这个情况，已有应对或可控 | 仅供知晓 | 否 |
| ⚪ **不适用** | AI 误判，语境下不是问题 | 忽略此条 | 否 |
| （无标记） | 尚未审阅 | 未处理 | — |

同一套标记，不同角色使用时语义自然转换（制作人视角 vs PLD 视角）。

### 交互流程

1. 批注者打开内网报告页面
2. 逐条查看 AI 发现，选择标记 + 填写自由文本（可选）
3. 过程中随时自动保存，**不触发通知**
4. 全部审阅完毕后，手动点击 **"完成批注"按钮** 提交
5. 提交时推送钉钉通知（一次性，文档级别）

**关键约束：** "完成批注"必须是手动点击按钮的显式动作，不可自动触发。即使所有条目均已批注，仍需批注者主动确认。

### 钉钉通知

"完成批注"时一次性推送，包含汇总统计：

```markdown
### 📋 版本预审批注完成
**报告**：【0422】五一版本内容预审
**批注人**：制作人
**批注结果**：🔴采纳 3 · 🟡待议 1 · 🟢已知 4 · ⚪不适用 2 · 未批 0

🔗 查看报告
```

复用 PmSystem 的钉钉 webhook 模式（`POST /api/dingtalk/send`，markdown 消息格式）。

### 部署架构

- 内网 web 服务（FastAPI），报告 + 批注持久化
- 报告渲染为 HTML（带侧栏批注 UI），所有人访问同一 URL
- 批注数据存 JSON 文件或 SQLite

### 批注人身份

- **短期**（PmSystem RBAC 未合并前）：手动选择角色（制作人 / PLD / PMO）
- **长期**：接入 PmSystem 角色管理 API（`feature/rbac-backup` 分支），自动识别身份

数据结构预留兼容字段：
```json
{
  "annotator": {
    "role": "producer",
    "name": "SY",
    "source": "manual"
  },
  "mark": "adopt",
  "comment": "..."
}
```
`source` 从 `"manual"` 切换到 `"pmsystem_rbac"` 时对前端无感。

### 报告 UI 布局

```
┌──────────────────────────────┬────────────────────────┐
│ 报告正文                      │ 批注侧栏                │
│                              │                        │
│ ### 6. 锦标赛耦合风险 ‼️ 预警  │ 🔴 制作人：             │
│ > 两个新系统深度耦合...        │ 认同，已要求同步排期     │
│ - 内容方向：...               │                        │
│ - 资源与排期：...              │                        │
│                              │                        │
│ ### 7. Owner并行负荷 🔶       │ 🟢 制作人：             │
│ > ...                        │ 已线下确认，可控         │
│                              │                        │
└──────────────────────────────┴────────────────────────┘
                       [ 完成批注 ]
```
