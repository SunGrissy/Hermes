# Palace 多角色协商引擎

> 基于管线角色（PLD/PLE/PLT）的 AI 审查与决策系统
> 创建日期：2026-03-03

## 定位

Palace 是 MyAgent 下的新项目，定位为**管线决策服务层**——读取 PLAYBOOK 规则和 PmSystem 数据，通过多角色 AI 并行审查，产出结构化决策报告。

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
      pld.yaml            # 管线主策角色配置
      ple.yaml            # 管线体验角色配置
      plt.yaml            # 管线技术角色配置
      boundary.yaml       # 职权边界检查角色配置
    scenarios/
      dor_review.yaml     # DoR 审查场景配置（召唤哪些角色、用什么综合规则）
    run.py                # CLI 入口（测试用）
    requirements.txt
    .env.example
```

## 核心架构

```
输入                          Palace Engine                         输出
─────────                     ─────────────                         ─────
                              ┌─────────────┐
Feature 方案文本 ──→ 议题路由器 ─┤ PLD Agent   ├──┐
                              │ PLE Agent   │  │
场景配置 YAML ────→            │ PLT Agent   │  ├──→ 综合器 ──→ 结构化审查报告 JSON
                              │ 边界检查     │  │
                              └──────┬──────┘  │
                                     │         │
                              LLM Provider 接口 ─┘
                              ├── MockProvider（开发/测试）
                              └── OpenAI Compatible（智谱 GLM-4）
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

每个角色 YAML 包含四层——身份、知识、行为、输出：

```yaml
# roles/pld.yaml 示例
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

### 3. 场景配置

```yaml
# scenarios/dor_review.yaml
id: dor_review
name: "Feature DoR 审查"
mode: review                  # review（审查）或 advisory（咨询）
roles: [pld, ple, plt, boundary]

synthesis_rules:
  any_block_means_block: true
  concern_threshold: 2
  must_list_action_items: true
  no_hedging: true

output_includes:
  - overall_verdict
  - per_role_verdicts
  - boundary_violations
  - action_items
  - dor_checklist_status
```

### 4. 知识切片

从 PLAYBOOK.md 按行号范围提取章节，按角色按需注入：

```python
PLAYBOOK_SECTIONS = {
    "pipeline_roles":  (112, 156),   # §三 管线角色体系
    "authority_model": (159, 234),   # §四 职权边界模型
    "dor_standards":   (236, 255),   # §五 DoR 分级
    "dual_track":      (76, 110),    # §二 双轨制
    "evaluation":      (258, 302),   # §六 评价哲学
    "org_diagnosis":   (354, 388),   # §八 组织诊断
    "north_star":      (10, 46),     # §零 北极星
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

## 后续扩展路径（不在本次范围，架构预留）

- 接入 PmSystem API（从 `/api/features/{id}` 拉取真实 Feature 数据）
- 新增场景：版本健康度（PMO Agent）、运营规划（advisory 模式）
- 集成到 PmSystem 前端（Feature 页加"审查"按钮）
- 集成到 Cursor AgentX（作为 Agent Skill 被调用）
