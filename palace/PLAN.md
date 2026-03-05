# Palace 多角色协商引擎

> 基于管线角色和管理体系的 AI 审查、运营监控与组织决策系统
> 创建日期：2026-03-03

## 定位

Palace 是 MyAgent 下的新项目，定位为**管理决策服务层**——读取 PLAYBOOK 规则、PmSystem 和 PerformEval 数据，通过多角色 AI 并行审查，产出结构化决策报告。

引擎服务三个域：

| 域 | 核心问题 | 角色 | 时间尺度 |
|---|---|---|---|
| **Feature 审查** | "这个 Feature 行不行？" | PLD + PLE + PLT + 边界检查 | 单 Feature 生命周期 |
| **管线运营** | "版本能不能按时交？" | PMO（管线总管） | 单版本周期 |
| **人才组织** | "组织能不能持续运转？" | 吏部尚书（人才组织） | 跨版本 / 半年度 |

第一个验证场景：Feature DoR 审查（PLD + PLE + PLT + 职权边界检查，4 角色并行）。

## 设计灵感

- **复杂任务三步法（S0→S3）**：分层防御思想——用最少资源识别真正需要资源的任务，逐层递减流量、递增精度
- **Palace 三省六部制**：人类验证过的治理结构映射为多Agent协作——角色专业化 + 制度化流程替代单点智能
- **PLAYBOOK 四层模型**：WHAT/HOW/BUILD/MAKE 职权边界天然定义了每个审查角色的视角和权力范围

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
      pld.yaml            # 管线主策（WHAT 层）
      ple.yaml            # 管线体验（HOW 层）
      plt.yaml            # 管线技术（BUILD 层）
      boundary.yaml       # 职权边界检查（跨层）
      pmo.yaml            # 管线总管（管线运营域）
      personnel.yaml      # 吏部尚书（人才组织域）
      numerics.yaml       # 户部尚书（数值/经济系统）
      qa_review.yaml      # 刑部尚书（质量门禁）
      strategist.yaml     # 御史台（战略锚）
    scenarios/
      dor_review.yaml     # Feature DoR 审查（6角色：PLD+PLE+PLT+边界+数值+QA）
      version_health.yaml # 版本健康度检查（PMO 主导）
      version_planning.yaml # 版本规划综合审查（全阁审议：御史台+PLD+PLT+PMO+吏部+户部）
      growth_review.yaml  # 增长复盘（御史台主导 advisory）
      org_advisory.yaml   # 组织架构咨询（吏部尚书主导）
      resume_screening.yaml # 简历筛选（吏部尚书主导）
    run.py                # CLI 入口（测试用）
    requirements.txt
    .env.example
```

## 核心架构

```
                         Palace Engine
                         ─────────────
议题 + 场景配置 ──→ 议题路由器 ──→ 按场景召唤角色 ──→ 并行执行 ──→ 综合器 ──→ 结构化报告

                    ┌─────────── 角色池 ───────────┐
                    │                              │
                    │  Feature 审查域               │
                    │  ├── PLD (WHAT)              │
                    │  ├── PLE (HOW)               │
                    │  ├── PLT (BUILD)             │
                    │  └── Boundary (跨层)          │
                    │                              │
                    │  管线运营域                    │
                    │  └── PMO (跨层)               │
                    │                              │
                    │  人才组织域                    │
                    │  └── Personnel/吏部尚书 (跨层)  │
                    │                              │
                    └──────────────────────────────┘
                                 │
                          LLM Provider 接口
                          ├── MockProvider（开发/测试）
                          └── OpenAI Compatible（智谱 GLM-4）
```

### 三域关系与信号流

```
Feature 审查域 ────────── 管线运营域 ────────── 人才组织域
(PLD/PLE/PLT)             (PMO)              (吏部尚书)
"方案行不行"              "版本跑不跑得动"       "组织撑不撑得住"
     │                      │                     │
     │ DoR 通过率下降        │ 资源缺口信号          │
     └──────────→ PMO 监控 ──┘──────────→ 吏部接手  │
                  进度/资源/依赖            架构/培养/招聘
```

三个域的角色可以**按场景灵活组合**——版本规划审查时同时召唤 PLD + PLT + PMO + 吏部尚书，各自从自己的视角给意见。

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

每个角色 YAML 包含五层——身份、知识、数据源、行为、输出：

```yaml
# roles/pld.yaml 示例（Feature 审查域）
id: pld
name: "管线主策 (PLD)"
layer: WHAT

persona: |
  你是本版本的管线主策(PLD)，版本内容方向总负责人。
  你将战略目标转化为内容方案，主导优先级，闭环内容验收。
  你只管 WHAT 层（做什么），不侵入 HOW 层（怎么呈现）。
  你有权 block 内容不达标的 feature。

knowledge_sections:
  - pipeline_roles           # §三 管线角色体系
  - authority_model          # §四 职权边界模型
  - dor_standards            # §五 DoR 分级

review_dimensions:
  - "内容方向是否与版本战略目标一致？"
  - "优先级排序是否有数据或逻辑支撑？"
  - "需求描述是否完整（目标用户、核心玩法、预期指标）？"
  - "奖励/数值设计是否已经过数值评审？"

authority: block
block_conditions:
  - "内容方向偏离版本目标"
  - "需求描述严重不完整，无法进入生产"
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
  - producer_context         # producer-context.mdc（团队93人现状）
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

引擎支持两种模式：`review`（审查，有 pass/block 结论）和 `advisory`（咨询，给建议和选择）。

```yaml
# scenarios/dor_review.yaml — Feature DoR 审查（6 角色）
id: dor_review
name: "Feature DoR 审查"
mode: review
roles: [pld, ple, plt, boundary, numerics, qa_review]
#       WHAT  HOW  BUILD 跨层     WHAT+BUILD  MAKE
#       内容  体验  技术  职权边界   数值审查    可测性

synthesis_rules:
  any_block_means_block: true      # PLD/PLE/PLT/QA 任一 block → 整体 block
  concern_threshold: 2             # >=2 concern → 整体至少 concern
  must_list_action_items: true
  no_hedging: true

output_includes:
  - overall_verdict
  - per_role_verdicts
  - boundary_violations
  - numerics_risk                  # 数值风险标记
  - action_items
  - dor_checklist_status           # DoR 四把锁状态（需求+体验+技术+可测性）
```

```yaml
# scenarios/version_health.yaml — 管线运营域
id: version_health
name: "版本健康度检查"
mode: advisory
roles: [pmo]

output_includes:
  - progress_health          # 进度健康度（完成比 vs 时间比）
  - blockers                 # 阻塞/延期 Feature 清单
  - dependency_status        # 跨组依赖状态
  - resource_risks           # 资源瓶颈和过载预警
  - action_items
```

```yaml
# scenarios/org_advisory.yaml — 人才组织域
id: org_advisory
name: "组织架构咨询"
mode: advisory
roles: [personnel]

output_includes:
  - diagnosis                # 当前状态诊断
  - recommendations          # 建议方案（给选择而非指令）
  - risk_assessment          # 风险评估
  - action_items
```

```yaml
# scenarios/resume_screening.yaml — 人才组织域
id: resume_screening
name: "简历筛选"
mode: advisory
roles: [personnel]

input_format:
  job_description: "岗位 JD"
  resumes: "候选人简历（批量）"

output_includes:
  - match_score              # 匹配度评分
  - strengths                # 匹配项
  - concerns                 # 不匹配项/风险点
  - interview_focus          # 面试建议重点考察什么
  - ranking                  # 候选人排序
```

```yaml
# scenarios/version_planning.yaml — 全阁审议（跨域联合）
id: version_planning
name: "版本规划综合审查"
mode: review
roles: [strategist, pld, plt, numerics, pmo, personnel]
#       WHY      WHAT BUILD WHAT+BUILD 运营  组织
#       战略对齐  内容  技术   数值      资源  人才

synthesis_rules:
  any_block_means_block: true
  must_list_action_items: true
  no_hedging: true

output_includes:
  - overall_verdict
  - strategic_alignment      # 御史台: 是否对齐北极星
  - per_role_verdicts
  - numerics_feasibility     # 户部: 经济系统影响
  - resource_feasibility     # PMO: 资源够不够
  - org_readiness            # 吏部: 人才准备度
  - action_items
```

### 4. 知识切片

从 PLAYBOOK.md 按行号范围提取章节，按角色按需注入：

```python
PLAYBOOK_SECTIONS = {
    "north_star":      (10, 46),     # §零 北极星（增长效能）
    "dual_track":      (76, 110),    # §二 双轨制
    "pipeline_roles":  (112, 156),   # §三 管线角色体系
    "authority_model": (159, 234),   # §四 职权边界模型
    "dor_standards":   (236, 255),   # §五 DoR 分级
    "evaluation":      (258, 302),   # §六 评价哲学
    "ai_evolution":    (305, 351),   # §七 AI进化纲领（进化系数、职能融合）
    "org_diagnosis":   (354, 388),   # §八 组织诊断
}
```

各角色的知识切片映射：

| 角色 | 注入章节 | 典型 token 量 |
|------|---------|-------------|
| PLD | §三§四§五 | ~140 行 |
| PLE | §三§四§五 | ~140 行 |
| PLT | §三§四§五§二 | ~175 行 |
| Boundary | §四 | ~75 行 |
| Numerics（户部） | §零§二 | ~70 行 |
| QA Review（刑部） | §三§五 | ~85 行 |
| Strategist（御史台） | §零§二 | ~70 行 |
| PMO | §三§五§二 | ~115 行 |
| Personnel（吏部） | §零§三§六§七§八PerformEval 数据 + rubric | ~200 行 + 动态数据 |

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

- 编写 9 个角色 YAML：
  - Feature 审查域：PLD / PLE / PLT / 边界检查
  - 数值 & 质量域：户部尚书（numerics）/ 刑部尚书（qa_review）
  - 管线运营域：PMO
  - 人才组织域：吏部尚书（personnel）
  - 战略对齐域：御史台（strategist）
- 实现 `knowledge.py`（PLAYBOOK 章节切片 + data_sources 抽象，动态数据先用 mock）
- 实现 `schemas.py`（结构化输出 JSON Schema，review_result + advisory_result 两种）

### Phase 3：引擎核心 + 场景配置（Mock 驱动）

- 实现 `engine.py`（角色调度 + asyncio.gather 并行 + 综合器）
- 编写 6 个场景 YAML（dor_review / version_health / version_planning / growth_review / org_advisory / resume_screening）
- 实现综合器同时支持 review 模式（pass/block）和 advisory 模式（建议+选择）
- 全部用 MockProvider 驱动，验证调度逻辑和综合逻辑正确

### Phase 4：CLI 入口 + Mock 端到端验证

- 实现 `run.py` CLI 入口
- 准备四域测试用例：
  - Feature 审查（含数值 + 可测性）：一个应通过、一个应 block、一个数值风险 concern
  - 管线运营：一个版本健康度检查（PMO 视角）
  - 人才组织：一个组织诊断咨询（如"体验组无组长，怎么办"）
  - 全阁审议：一个版本规划（御史台 + PLD + PLT + 户部 + PMO + 吏部联合审议）
- 用 mock 端到端跑通完整流程
- 验证：并行调度正确、review/advisory 两种模式正确、输出格式合规、错误降级正常

### Phase 5：接入真实 LLM API

- 实现 `OpenAICompatibleProvider`（智谱 GLM-4）
- 通过环境变量 `PALACE_PROVIDER=openai_compatible` 切换 mock/真实
- 用测试 Feature 方案对比 mock 和真实输出
- 调优角色 persona 和 review_dimensions
- 验证结构化输出解析的鲁棒性

## 完整角色图谱

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
- 简历筛选批量处理（接入邮件/文件夹自动读取候选人简历）
- 御史台阶段 2-4 进化（决策追问 → 认知建模 → 战略参谋）
