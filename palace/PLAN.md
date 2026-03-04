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
      pld.yaml            # 管线主策角色配置（WHAT 层）
      ple.yaml            # 管线体验角色配置（HOW 层）
      plt.yaml            # 管线技术角色配置（BUILD 层）
      boundary.yaml       # 职权边界检查角色配置（跨层）
      pmo.yaml            # 管线总管角色配置（管线运营域）
      personnel.yaml      # 吏部尚书角色配置（人才组织域）
    scenarios/
      dor_review.yaml     # Feature DoR 审查（PLD+PLE+PLT+边界检查）
      version_health.yaml # 版本健康度检查（PMO 主导）
      org_advisory.yaml   # 组织架构咨询（吏部尚书主导）
      resume_screening.yaml # 简历筛选（吏部尚书主导）
      version_planning.yaml # 版本规划综合审查（跨域联合：PLD+PLT+PMO+吏部尚书）
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

**角色配置新增 `data_sources` 字段**：`knowledge_sections` 引用 PLAYBOOK 章节（静态文档），`data_sources` 引用系统 API 和文件数据（动态数据）。PMO 和吏部尚书比 PLD/PLE/PLT 更依赖动态数据。开发阶段 data_sources 用 mock 数据，Phase 5+ 接真实 API。

### 3. 场景配置

引擎支持两种模式：`review`（审查，有 pass/block 结论）和 `advisory`（咨询，给建议和选择）。

```yaml
# scenarios/dor_review.yaml — Feature 审查域
id: dor_review
name: "Feature DoR 审查"
mode: review
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
# scenarios/version_planning.yaml — 跨域联合
id: version_planning
name: "版本规划综合审查"
mode: review
roles: [pld, plt, pmo, personnel]

synthesis_rules:
  any_block_means_block: true
  must_list_action_items: true
  no_hedging: true

output_includes:
  - overall_verdict
  - per_role_verdicts
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
| PMO | §三§五§二 | ~115 行 |
| Personnel | §零§三§六§七§八 | ~200 行 |

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

- 编写 6 个角色 YAML（PLD/PLE/PLT/边界检查/PMO/吏部尚书）
- 实现 `knowledge.py`（PLAYBOOK 章节切片 + data_sources 抽象，动态数据先用 mock）
- 实现 `schemas.py`（结构化输出 JSON Schema，review_result + advisory_result 两种）

### Phase 3：引擎核心 + 场景配置（Mock 驱动）

- 实现 `engine.py`（角色调度 + asyncio.gather 并行 + 综合器）
- 编写 5 个场景 YAML（dor_review / version_health / org_advisory / resume_screening / version_planning）
- 实现综合器同时支持 review 模式（pass/block）和 advisory 模式（建议+选择）
- 全部用 MockProvider 驱动，验证调度逻辑和综合逻辑正确

### Phase 4：CLI 入口 + Mock 端到端验证

- 实现 `run.py` CLI 入口
- 准备三域测试用例：
  - Feature 审查：一个应通过、一个应 block、一个边界情况
  - 管线运营：一个版本健康度检查（PMO 视角）
  - 人才组织：一个组织诊断咨询（如"体验组无组长，怎么办"）
- 用 mock 端到端跑通完整流程
- 验证：并行调度正确、review/advisory 两种模式正确、输出格式合规、错误降级正常

### Phase 5：接入真实 LLM API

- 实现 `OpenAICompatibleProvider`（智谱 GLM-4）
- 通过环境变量 `PALACE_PROVIDER=openai_compatible` 切换 mock/真实
- 用测试 Feature 方案对比 mock 和真实输出
- 调优角色 persona 和 review_dimensions
- 验证结构化输出解析的鲁棒性

## 后续扩展路径（不在本次范围，架构预留）

- 接入 PmSystem API（PMO 角色从 `/api/features` `/api/versions` 拉取真实数据）
- 接入 PerformEval API（吏部尚书从 `/api/members` `/api/evaluations` 拉取成员和评价数据）
- 解析 org-structure.html 中的组织架构数据供吏部尚书使用
- 新增场景：运营活动规划（advisory 模式）、考核标准设计（eval_design）
- 集成到 PmSystem 前端（Feature 页加"审查"按钮，版本页加"健康度检查"按钮）
- 集成到 Cursor AgentX（作为 Agent Skill 被调用）
- 简历筛选批量处理（接入邮件/文件夹自动读取候选人简历）
