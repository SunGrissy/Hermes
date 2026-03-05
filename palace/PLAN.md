# Palace 多角色协商引擎

> 基于管线角色（PLD/PLE/PLT/PMO）的 AI 审查与决策系统
> 创建日期：2026-03-03
> 最后更新：2026-03-04

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
    scenarios/
      what_precheck.yaml  # 慢轨 WHAT 预审（准备中期，PLD+PLE+PLT+Boundary）
      dor_slow.yaml       # 慢轨 DoR 审查（PLD+PLE+PLT，正式门禁）
      dor_fast.yaml       # 快轨 DoR 审查（PLD+PLT 兼容性半锁）
      how_review.yaml     # HOW 方案审查（PLE+PLT，独立于 WHAT 审查）
      version_scope.yaml  # 版本 scope 健康度评估（PMO）
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
版本级审查：                             │          │
  版本 Feature 列表 ──→ PMO Agent ──────────────────┘
  各 Feature 管线状态
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
- 编写 `dor_review.yaml` 场景配置
- 实现综合器的硬规则（any_block_means_block 等）
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
- 集成到 PmSystem 前端（Feature 页加"审查"按钮，自动带入 feature_meta）
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
