# Palace Instructor 集成方案

> v0.1 · 2026-03-03
> 目标：用 Instructor 替代手工 JSON 解析，提升 LLM 结构化输出的可靠性，为 Phase 5（真实 LLM 接入）扫清障碍。

---

## 一、背景

### 当前状态

- Phase 1-4 已完成：引擎骨架、角色配置、两步流程、CLI、Mock 端到端验证
- Phase 5 半完成：`OpenAICompatibleProvider` 代码已写，但未经真实 LLM 调用验证
- `_robust_json_parse()` 是当前唯一的 LLM 输出容错机制——多层正则 + 引号修复 + 尾逗号清理 + 调试转储

### 问题

`_robust_json_parse()` 本质是**被动补丁**——每遇到一种 LLM 格式错误就加一层修复。随着接入真实 LLM，格式错误的种类会增加，维护成本线性增长。

### 目标

引入 [Instructor](https://github.com/instructor-ai/instructor)（8k+ Stars），用 Pydantic 模型约束 LLM 输出：
- 自动验证 + 自动重试（将验证错误反馈给 LLM 让它修正）
- 类型安全的 schema 定义（Pydantic 模型替代手写 dict schema）
- 保留 `_robust_json_parse()` 作为 fallback，不是替代而是增强

---

## 二、改造范围

### 改动文件

| 文件 | 改动内容 | 量级 |
|------|---------|:---:|
| `schemas.py` | 新增 Pydantic 模型（与现有 dict schema 1:1 对应），**保留原有 dict schema 不删** | 中 |
| `llm_client.py` | `OpenAICompatibleProvider.complete()` 内部使用 Instructor，返回值仍为 dict | 中 |
| `requirements.txt` | 新增 `instructor` 和 `pydantic` 依赖 | 微 |

### 不改动文件

| 文件 | 为什么不改 |
|------|----------|
| `engine.py` | 调用 `provider.complete()` 获得 dict，通过 `.get()` 访问字段——上游 Provider 内部怎么实现不影响它 |
| `report.py` | 消费 `synthesize_v2()` 返回的 dict，与 LLM 层无关 |
| `MockProvider` | 返回预设 dict，不经过 JSON 解析，不经过 Instructor |
| `config.py` | Provider 工厂不变 |
| `knowledge.py` | 知识注入逻辑不变 |
| `run.py` | CLI 入口不变 |
| 所有 YAML（roles / scenarios） | 角色和场景配置不变 |

---

## 三、详细设计

### 3.1 schemas.py：新增 Pydantic 模型

在现有 dict schema 下方新增对应的 Pydantic 模型。命名规范：`Model` 后缀。

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

# --- Step 1: Extraction ---

class LayerOverviewItem(BaseModel):
    layer: Literal["WHAT", "HOW", "BUILD"]
    ratio: str = ""
    completeness: Literal["complete", "incomplete", "fragment", "absent"]
    key_gaps: str = ""

class ChecklistItem(BaseModel):
    item_id: str
    title: str
    layer: Literal["WHAT", "HOW", "BUILD"]
    status: Literal["present", "incomplete", "missing"]
    extracted_text: str = ""
    gap_description: str = ""
    acceptance_criteria: str = ""
    group_id: str = ""  # R1 修复：显式声明

class CrossLayerObs(BaseModel):
    category: Literal["intent", "readiness", "annotate"]
    description: str
    suggestion: str = ""

class ExtractionResult(BaseModel):
    layer_overview: list[LayerOverviewItem]
    checklist: list[ChecklistItem]
    cross_layer_observations: list[CrossLayerObs]

# --- Step 2: Assessment ---

class IssueAssessment(BaseModel):
    item_id: str
    impact: Literal["pass", "concern", "block"]
    comment: str

class SupplementaryFinding(BaseModel):
    item_id: str
    title: str
    layer: str = ""
    description: str = ""
    impact: Literal["pass", "concern", "block"]
    suggested_action: str = ""
    group_id: str = ""  # R1 修复：显式声明

class RoleAssessmentResult(BaseModel):
    role_id: str
    verdict: Literal["pass", "concern", "block"]
    perspective_summary: str
    issue_assessments: list[IssueAssessment]
    supplementary_findings: list[SupplementaryFinding] = []

# --- Legacy ---

class LegacyActionItem(BaseModel):
    priority: Literal["P0", "P1", "P2"]
    owner: str
    action: str
    deadline: str = ""

class DimensionCheck(BaseModel):
    question: str
    status: Literal["pass", "concern", "block"]
    note: str

class LegacyRoleReview(BaseModel):
    role_id: str
    verdict: Literal["pass", "concern", "block"]
    reasoning: str
    dimension_checks: list[DimensionCheck]
    boundary_violations: list[str]
    action_items: list[LegacyActionItem]
```

**设计要点**：
- 所有 Optional 字段用 `= ""` 默认值（非 `None`），避免 R4 风险（`.model_dump()` 产生 `null`，engine.py `.get("key", "")` 拿到 `None`）
- `group_id` 在 `ChecklistItem` 和 `SupplementaryFinding` 中显式声明（R1 修复）
- dict schema 保留不删——MockProvider 的 preset 数据仍以 dict 形式存在，且 prompt builder 中引用了 schema 结构描述

### 3.2 llm_client.py：OpenAICompatibleProvider 改造

```python
class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        from openai import AsyncOpenAI
        import instructor

        raw_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._instructor_client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
        self._raw_client = raw_client  # fallback 用
        self._model = model

    async def complete(self, system_prompt: str, user_prompt: str,
                       schema: dict | None = None) -> dict:
        # 根据传入的 dict schema 确定对应的 Pydantic 模型
        pydantic_model = _SCHEMA_TO_MODEL.get(id(schema))

        if pydantic_model:
            return await self._complete_with_instructor(
                system_prompt, user_prompt, pydantic_model,
            )
        # 无对应模型时走原始路径
        return await self._complete_raw(system_prompt, user_prompt, schema)

    async def _complete_with_instructor(self, system_prompt, user_prompt, model_cls):
        """Instructor 路径：自动验证 + 重试 → .model_dump() → dict"""
        try:
            result = await self._instructor_client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=model_cls,
                temperature=0.3,
                max_retries=2,
            )
            return result.model_dump()
        except Exception as e:
            logger.warning("Instructor failed (%s), falling back to raw parse", e)
            return await self._complete_raw(system_prompt, user_prompt, schema=None)

    async def _complete_raw(self, system_prompt, user_prompt, schema):
        """原始路径（fallback）：JSON mode + _robust_json_parse"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs = {"model": self._model, "messages": messages, "temperature": 0.3}
        if schema:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._raw_client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        logger.debug("LLM raw response length=%d", len(text))
        return _robust_json_parse(text)
```

**Schema 到 Pydantic 模型的映射**（模块级）：

```python
from .schemas import (
    EXTRACTION_SCHEMA, ROLE_ASSESSMENT_SCHEMA, ROLE_REVIEW_SCHEMA,
    ExtractionResult, RoleAssessmentResult, LegacyRoleReview,
)

_SCHEMA_TO_MODEL = {
    id(EXTRACTION_SCHEMA): ExtractionResult,
    id(ROLE_ASSESSMENT_SCHEMA): RoleAssessmentResult,
    id(ROLE_REVIEW_SCHEMA): LegacyRoleReview,
}
```

**为什么用 `id()` 映射**：`engine.py` 传入的 `schema` 参数是 `schemas.py` 的模块级常量引用（如 `EXTRACTION_SCHEMA`），Python 保证同一模块级对象的 `id()` 在进程生命周期内稳定。这比字符串匹配更安全、不依赖 schema 内容。

### 3.3 容错策略

```
OpenAICompatibleProvider.complete()
  │
  ├─ 找到对应 Pydantic 模型？
  │   ├─ YES → Instructor 路径
  │   │   ├─ 成功 → .model_dump() → return dict  ✅
  │   │   └─ 失败（max_retries 用完）
  │   │       └─ 降级为原始路径 → _robust_json_parse()
  │   │           ├─ 成功 → return dict  ✅
  │   │           └─ 失败 → raise + _dump_debug()  ❌
  │   │
  │   └─ NO → 直接走原始路径（当前行为不变）
  │
  └─ MockProvider → 不经过此路径（返回预设 dict）
```

---

## 四、已识别风险

| # | 风险 | 严重度 | 原因 | 应对措施 |
|---|------|:---:|------|---------|
| **R1** | `group_id` 字段在原 dict schema 中未声明 | 高 | `SUPPLEMENTARY_FINDING` dict schema 没有 `group_id`，但 engine.py L241 使用了它。若 Pydantic `extra="forbid"` 会拒绝含此字段的 LLM 输出 | Pydantic 模型中显式声明 `group_id: str = ""` |
| **R2** | GLM-4 对 function calling 支持不稳定 | 中 | Instructor 默认用 function calling 提取结构化数据 | 使用 `mode=instructor.Mode.JSON`，与当前 `response_format: json_object` 行为一致 |
| **R3** | Instructor 重试 vs `_robust_json_parse` 策略不同 | 中 | Instructor 重试 = 重新调 LLM；`_robust_json_parse` = 正则修复残缺 JSON | 保留 `_robust_json_parse` 作为 fallback，两种策略叠加使用 |
| **R4** | Optional 字段 `.model_dump()` 输出 `null` | 中 | `engine.py` 用 `.get("key", "")` 取默认值，如果 Pydantic 默认是 `None`，`.get()` 拿到的是 `None` 而非 `""` | 所有 Optional 字段用 `= ""` 而非 `= None` |
| **R5** | `id()` 映射的稳定性 | 低 | `_SCHEMA_TO_MODEL` 用 `id(EXTRACTION_SCHEMA)` 做 key。如果有人 `copy()` 了 schema dict 再传入，映射失败 | 当前代码中 engine.py 直接传模块常量，不会 copy。如果未来改了传入方式，映射会 graceful 降级为原始路径（不会报错，只是不走 Instructor） |
| **R6** | Legacy flow 的 `ROLE_REVIEW_SCHEMA` | 低 | `dor_slow`、`dor_fast`、`how_review`、`version_scope` 场景没有 `extraction_role`，走 legacy flow | Legacy flow 同样建了 `LegacyRoleReview` Pydantic 模型，也能受益于 Instructor |
| **R7** | Instructor 依赖版本冲突 | 低 | Instructor 依赖 `openai>=1.0` + `pydantic>=2.0` | 当前 `requirements.txt` 已有 `openai>=1.0`，兼容 |

---

## 五、字段一致性验证清单

以下是 `engine.py` 和 `report.py` 中所有通过 `.get()` 访问的字段，Pydantic 模型**必须**使用完全一致的名称：

### ExtractionResult → engine.py synthesize_v2()

| dict key | engine.py 访问位置 | Pydantic 字段 | 默认值 |
|---------|-------------------|-------------|--------|
| `layer_overview` | L230 | `layer_overview` | `[]` |
| `checklist` | L229 | `checklist` | `[]` |
| `cross_layer_observations` | L231 | `cross_layer_observations` | `[]` |

### ChecklistItem → engine.py _build_issue()

| dict key | engine.py 访问位置 | Pydantic 字段 | 默认值 |
|---------|-------------------|-------------|--------|
| `item_id` | L335 | `item_id` | 必填 |
| `title` | L355 | `title` | 必填 |
| `layer` | L361 | `layer` | 必填 |
| `status` | L349 | `status` | 必填 |
| `extracted_text` | L364 | `extracted_text` | `""` |
| `gap_description` | L347 | `gap_description` | `""` |
| `acceptance_criteria` | L351 | `acceptance_criteria` | `""` |
| `group_id` | L236 | `group_id` | `""` |

### RoleAssessmentResult → engine.py _run_two_step() / synthesize_v2()

| dict key | engine.py 访问位置 | Pydantic 字段 | 默认值 |
|---------|-------------------|-------------|--------|
| `role_id` | L323, L88 | `role_id` | 必填 |
| `verdict` | L131, L253 | `verdict` | 必填 |
| `perspective_summary` | — (透传至 report) | `perspective_summary` | 必填 |
| `issue_assessments` | L339 | `issue_assessments` | `[]` |
| `supplementary_findings` | L240 | `supplementary_findings` | `[]` |

### SupplementaryFinding → engine.py synthesize_v2()

| dict key | engine.py 访问位置 | Pydantic 字段 | 默认值 |
|---------|-------------------|-------------|--------|
| `group_id` | L241 | `group_id` | `""` |
| `item_id` | L244 | `item_id` | 必填 |
| `title` | L245 (via _build_issue_from_supplementary) | `title` | 必填 |
| `layer` | L405 | `layer` | `""` |
| `description` | L329, L406 | `description` | `""` |
| `impact` | L329 | `impact` | 必填 |
| `suggested_action` | L329 | `suggested_action` | `""` |

### IssueAssessment → engine.py _build_issue()

| dict key | engine.py 访问位置 | Pydantic 字段 | 默认值 |
|---------|-------------------|-------------|--------|
| `item_id` | L340 | `item_id` | 必填 |
| `impact` | L342 | `impact` | 必填 |
| `comment` | L343 | `comment` | 必填 |

---

## 六、测试验证计划

| # | 测试 | 方法 | 验证目标 |
|---|------|------|---------|
| T1 | Mock 端到端回归 | `py run.py --scenario what_precheck --input-file palace/【锦标赛】锦标月赛功能设计.md --format markdown`，对比改造前后输出 | MockProvider 路径零影响 |
| T2 | Pydantic 模型一致性 | 用 MockProvider preset 数据构造 Pydantic model 实例 → `.model_dump()` → 与原始 preset dict 逐字段比对 | 字段名、默认值、Optional 行为 |
| T3 | Instructor 解析 | 切换 `PALACE_PROVIDER=openai_compatible`（需 API key），跑 `what_precheck` 场景 | Instructor 能否正确约束 GLM-4 输出 |
| T4 | Instructor 降级 | mock 一个返回残缺 JSON 的 provider，触发 Instructor 失败 → 验证 fallback 到 `_robust_json_parse` | 容错链完整性 |
| T5 | Legacy flow | `py run.py --scenario dor_slow --input-file ...`（legacy 路径），确认 Instructor 也能处理 `LegacyRoleReview` | Legacy 场景不退化 |
| T6 | 所有场景覆盖 | 依次跑 `what_precheck` / `dor_slow` / `dor_fast` / `how_review` / `version_scope`，确认无报错 | 全场景兼容 |

---

## 七、不在本次范围的事项

| 事项 | 原因 |
|------|------|
| 删除 dict schema | MockProvider preset 和 prompt builder 仍依赖 dict schema 结构描述，保留不删 |
| 删除 `_robust_json_parse` | 作为 fallback 保留，后续观察 Instructor 稳定性后再决定 |
| 改造 engine.py 接口 | Provider 内部消化类型转换，engine.py 接口不变 |
| 改造 MockProvider | 不走 JSON 解析路径，无需改 |
| 接入真实 LLM 并调优 prompt | 属于 Phase 5 后续任务，本次只提供基础设施 |
| 升级版本号 | 等 Phase 5 完整验证后统一升级至 v0.5 |

---

## 八、依赖变更

`requirements.txt` 新增：

```
instructor>=1.0
pydantic>=2.0
```

与现有依赖无冲突（`openai>=1.0` 已存在）。

---

## 九、实施步骤

1. `schemas.py`：新增 Pydantic 模型（第三节代码）
2. `llm_client.py`：改造 `OpenAICompatibleProvider`（第三节代码）
3. `requirements.txt`：新增依赖
4. T1 验证：Mock 端到端回归，确认 MockProvider 路径不受影响
5. T2 验证：Pydantic 模型一致性测试
6. （Phase 5 后续）T3-T6：真实 LLM 测试、降级测试、全场景覆盖
