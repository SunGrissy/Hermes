"""Palace core engine v0.4 — two-step extraction + assessment architecture.

Flow (when extraction_role is defined):
  1. Extraction: boundary role reads document, outputs structured checklist
  2. Assessment: PLD/PLE/PLT assess checklist items in parallel
  3. Synthesis: code merges extraction + assessments into report data

Fallback (legacy parallel flow for scenarios without extraction_role):
  Same as v0.3 — all roles run in parallel, then synthesize.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .config import PLAYBOOK_PATH, get_provider, load_role, load_scenario
from .knowledge import get_knowledge_for_role, load_playbook
from .schemas import EXTRACTION_SCHEMA, ROLE_ASSESSMENT_SCHEMA, ROLE_REVIEW_SCHEMA

logger = logging.getLogger("palace.engine")

_PERSP_LABEL = {
    "pld": "WHAT \u5185\u5bb9\u65b9\u5411",
    "ple": "WHAT\u2192HOW \u53ef\u8bbe\u8ba1\u6027",
    "plt": "WHAT\u2192BUILD \u53ef\u5b9e\u73b0\u6027",
    "pmo": "\u7248\u672c Scope",
}

_VERSION_PERSP_LABEL = {
    "pld": "\u5185\u5bb9\u65b9\u5411",
    "pmo": "\u8d44\u6e90\u4e0e\u6392\u671f",
}

# ============================================================
# Public API
# ============================================================

async def run_scenario(
    scenario_id: str,
    topic_text: str,
    provider=None,
    document_layer: str = "",
) -> dict:
    scenario = load_scenario(scenario_id)
    if provider is None:
        provider = get_provider()

    extraction_role_id = scenario.get("extraction_role")

    if extraction_role_id:
        return await _run_two_step(
            provider, scenario, extraction_role_id, topic_text, document_layer,
        )
    return await _run_legacy_parallel(
        provider, scenario, topic_text, document_layer,
    )


# ============================================================
# Two-step flow (v0.4)
# ============================================================

async def _run_two_step(provider, scenario, extraction_role_id, topic_text, document_layer):
    playbook_text = load_playbook(PLAYBOOK_PATH)
    mode = scenario.get("mode", "review")

    extraction_role = load_role(extraction_role_id)
    extraction_result = await _invoke_extraction(
        provider, extraction_role, topic_text, playbook_text, scenario, document_layer,
    )

    assessment_role_ids = scenario.get("assessment_roles", [])
    assessment_roles = [load_role(r) for r in assessment_role_ids]

    logger.info(
        "scenario=%s extraction=%s assessors=%s",
        scenario["id"], extraction_role_id, assessment_role_ids,
    )

    tasks = [
        _invoke_assessment(
            provider, role, topic_text, playbook_text,
            extraction_result, scenario, document_layer,
        )
        for role in assessment_roles
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assessments = []
    errors = []
    for role, result in zip(assessment_roles, results):
        if isinstance(result, Exception):
            logger.error("role=%s error=%s", role["id"], result)
            errors.append({"role_id": role["id"], "error": str(result)})
        else:
            assessments.append(result)

    report_data = synthesize_v2(extraction_result, assessments, scenario)
    if errors:
        report_data["errors"] = errors

    logger.info(
        "scenario=%s verdict=%s blockers=%d concerns=%d",
        scenario["id"], report_data["overall_verdict"],
        report_data["blocker_count"], report_data["concern_count"],
    )
    return report_data


async def _invoke_extraction(provider, role_config, topic_text, playbook_text, scenario, document_layer):
    knowledge = get_knowledge_for_role(role_config, playbook_text)
    system_prompt = _build_extraction_prompt(role_config, knowledge, scenario)
    user_prompt = _build_extraction_user_prompt(topic_text, document_layer, scenario)

    start = time.monotonic()
    result = await provider.complete(system_prompt, user_prompt, EXTRACTION_SCHEMA)
    elapsed = time.monotonic() - start
    logger.info("extraction role=%s elapsed=%.2fs items=%d",
                role_config["id"], elapsed, len(result.get("checklist", [])))
    return result


async def _invoke_assessment(provider, role_config, topic_text, playbook_text,
                             extraction_result, scenario, document_layer):
    effective_config = _apply_role_overrides(role_config, scenario)
    knowledge = get_knowledge_for_role(role_config, playbook_text)
    authority = _resolve_authority(role_config, scenario)
    system_prompt = _build_assessment_prompt(effective_config, knowledge, authority, scenario)
    user_prompt = _build_assessment_user_prompt(
        topic_text, extraction_result, document_layer,
    )

    start = time.monotonic()
    result = await provider.complete(system_prompt, user_prompt, ROLE_ASSESSMENT_SCHEMA)
    elapsed = time.monotonic() - start
    logger.info("assessment role=%s verdict=%s elapsed=%.2fs",
                role_config["id"], result.get("verdict", "?"), elapsed)
    return result


# ============================================================
# Prompt builders (v0.4)
# ============================================================

_SENSITIVITY_RULE = (
    '\n## 输出脱敏规则（必须遵守）\n\n'
    '报告可能被同步给 PLD、Feature Owner 等非管理层角色。'
    '你可以利用参考知识中的组织信息辅助判断，但输出中**禁止**直接暴露以下敏感信息：\n'
    '- 个人绩效状态（如「待处置」「绩效不达标」「试用期」等）\n'
    '- 人事处理决定（如「计划劝退」「降级」等）\n'
    '- 管理层对个人的评价原文\n\n'
    '如需表达人力风险，应转化为**能力/掌控力/可用性**维度：\n'
    '- BAD: 「负责人处于待处置状态」\n'
    '  GOOD: 「建议确认负责人对该功能的理解深度和持续投入能力」\n'
    '- BAD: 「绩效不达标」\n'
    '  GOOD: 「该Feature复杂度高，建议评估负责人是否需要co-owner支持」\n'
    '- BAD: 「可能离职」\n'
    '  GOOD: 「核心Feature建议配置backup Owner，降低人力单点风险」\n'
)

_DEFAULT_EXTRACTION_OUTPUT_SPEC = (
    "以 JSON 格式输出，包含三个字段：\n\n"
    "1. layer_overview: 数组，每层一项 {layer, ratio, completeness(complete/incomplete/fragment/absent), key_gaps}\n"
    "2. checklist: 数组，每个核心交付物一项 {item_id, title, layer, status(present/incomplete/missing), extracted_text, gap_description, acceptance_criteria, group_id}\n"
    "   - item_id 用英文短横线格式如 what-intent, what-success-metrics, how-interaction\n"
    "   - group_id（可选）：语义相关的检查项共享同一 group_id（如术语表和信息架构共享 'terminology'），合成时会合并为一条\n"
    "   - extracted_text 填写从文档中找到的相关原文（至少 2-3 段完整上下文，避免断章取义）\n"
    "   - gap_description 说明缺了什么或哪里不完整\n"
    "   - acceptance_criteria 描述'什么算完成'的验收标准（具体、可检验的交付物描述）\n"
    "3. cross_layer_observations: 数组 {category(intent/readiness/annotate), description, suggestion}\n"
    "   - intent: 体验意图在跨层传递中的一致性风险\n"
    "   - readiness: 下游团队启动工作所需的前置条件缺口\n"
    "   - annotate: 跨层引用的标注建议（参考 vs 决策）"
)


def _build_extraction_prompt(role_config, knowledge, scenario):
    parts = [role_config["persona"].strip()]

    if knowledge:
        parts.append(f"\n## 参考知识\n\n{knowledge}")

    dims = role_config.get("review_dimensions", [])
    if dims:
        dim_text = "\n".join(f"- {d}" for d in dims)
        parts.append(f"\n## 检查维度\n\n{dim_text}")

    parts.append(_SENSITIVITY_RULE)

    output_spec = role_config.get("extraction_output_spec", _DEFAULT_EXTRACTION_OUTPUT_SPEC)
    parts.append(f"\n## 输出要求\n\n{output_spec.strip()}")
    return "\n".join(parts)


def _build_extraction_user_prompt(topic_text, document_layer, scenario=None):
    target = (scenario or {}).get("target", "feature")
    if target == "version":
        return f"\u8bf7\u5bf9\u4ee5\u4e0b\u7248\u672c\u89c4\u5212\u6587\u6863\u8fdb\u884c\u7ed3\u6784\u5316\u63d0\u53d6\uff1a\n\n{topic_text}"
    layer_hint = ""
    if document_layer:
        layer_labels = {
            "WHAT": "WHAT\uff08\u4f53\u9a8c\u8bbe\u8ba1\uff09\u5c42\u6587\u6863",
            "HOW": "HOW\uff08\u4ea4\u4e92\u65b9\u6848\uff09\u5c42\u6587\u6863",
            "BUILD": "BUILD\uff08\u7cfb\u7edf\u65b9\u6848\uff09\u5c42\u6587\u6863",
            "mixed": "\u6df7\u5408\u5c42\u7ea7\u6587\u6863",
        }
        label = layer_labels.get(document_layer.upper(), f"{document_layer} \u5c42\u6587\u6863")
        layer_hint = f"\n\n\u6587\u6863\u5c42\u7ea7\u58f0\u660e: {label}"
    return f"\u8bf7\u5bf9\u4ee5\u4e0b Feature \u6587\u6863\u8fdb\u884c\u7ed3\u6784\u5316\u63d0\u53d6\uff1a\n\n{topic_text}{layer_hint}"


def _build_assessment_prompt(role_config, knowledge, authority, scenario=None):
    parts = [role_config["persona"].strip()]

    if authority == "block":
        parts.append("\n你在本场景中拥有 **block 权**——发现严重问题时 verdict 应为 block。")
    elif authority == "concern":
        parts.append("\n你在本场景中最多给出 **concern**——标记风险，不 block。")
    else:
        parts.append("\n你在本场景中为 **advisory** 角色——给出建议。")

    if knowledge:
        parts.append(f"\n## 参考知识\n\n{knowledge}")

    dims = role_config.get("review_dimensions", [])
    if dims:
        dim_text = "\n".join(f"- {d}" for d in dims)
        parts.append(f"\n## 审查维度\n\n{dim_text}")

    if scenario and scenario.get("pipeline_stage") == "planning":
        parts.append(
            '\n## 阶段边界（必须遵守）\n\n'
            '当前审查的是**规划阶段**文档。规划阶段的 Feature 只需交代 WHAT（做什么、为什么）'
            '和 scope 边界（改什么、不改什么）。\n\n'
            '以下内容属于详设阶段交付物，**不在本次审查范围**，不得作为扣分依据：\n'
            '- 具体处理方案 / 实现路径（HOW）\n'
            '- 数值参数、概率、阈值\n'
            '- 降级方案、兜底策略（除非涉及版本结构性单点故障）\n'
            '- 子系统逐项拆解\n\n'
            '系统级 Feature 写入规划 = 方向已线下对齐。'
            '评审的是"组盘决策质量"，不是"每个棋子的走法"。'
        )

    parts.append(_SENSITIVITY_RULE)

    rid = role_config.get("id", "unknown")
    parts.append(
        "\n## \u8f93\u51fa\u8981\u6c42\n\n"
        "\u524d\u9762\u5df2\u7ecf\u6709\u4e00\u4efd\u6587\u6863\u7ed3\u6784\u63d0\u53d6\u7ed3\u679c\uff08checklist\uff09\uff0c\u8bf7\u57fa\u4e8e\u4f60\u7684\u89c6\u89d2\u9010\u9879\u8bc4\u4f30\u3002\n"
        "\u4ee5 JSON \u683c\u5f0f\u8f93\u51fa\uff0c\u5305\u542b\uff1a\n\n"
        f'1. role_id: "{rid}"  \uff08\u5fc5\u987b\u4f7f\u7528\u8fd9\u4e2a\u7cbe\u786e\u503c\uff09\n'
        "2. verdict: pass / concern / block\n"
        "3. perspective_summary: \u4e00\u6bb5\u8bdd\u6982\u8ff0\u4f60\u7684\u603b\u4f53\u5224\u65ad\n"
        "4. issue_assessments: \u6570\u7ec4\uff0c\u5bf9 checklist \u4e2d\u6bcf\u4e2a\u4e0e\u4f60\u89c6\u89d2\u76f8\u5173\u7684\u9879\u7ed9\u51fa\u8bc4\u4f30\n"
        "   \u6bcf\u9879: {item_id, impact(pass/concern/block), comment}\n"
        "5. supplementary_findings: \u6570\u7ec4\uff08\u53ef\u4e3a\u7a7a\uff09\uff0cchecklist \u6ca1\u8986\u76d6\u5230\u7684\u989d\u5916\u53d1\u73b0\n"
        "   \u6bcf\u9879: {item_id(\u65b0\u7684), title, layer, description, impact, suggested_action}\n"
        "6. highlights: \u6570\u7ec4\uff080-3 \u9879\uff09\uff0c\u4ec5\u6807\u8bb0\u8d85\u51fa\u89c4\u5212\u57fa\u7ebf\u7684\u5de7\u601d\u3002\n"
        "   \u4ee5\u4e0b\u4e0d\u7b97\u4eae\u70b9\uff1a\u6309\u6a21\u677f\u89c4\u8303\u586b\u5199\uff08\u57fa\u7ebf\u8981\u6c42\uff09\u3001\u7eaf\u6362\u76ae\uff08\u4ec5\u66ff\u6362\u7f8e\u672f\u8d44\u6e90\u65e0\u673a\u5236\u53d8\u5316\uff09\u3002\n"
        "   \u4f18\u5148\u8bc6\u522b\uff1a\n"
        "   - \u673a\u5236\u590d\u7528\u521b\u65b0\uff1a\u5728\u73b0\u6709\u73a9\u6cd5\u6846\u67b6\u4e0a\u901a\u8fc7\u53c2\u6570/\u6295\u653e/\u7ec4\u5408\u521b\u9020\u5dee\u5f02\u5316\u4f53\u9a8c\n"
        "   - \u8d44\u6e90\u6548\u7387\u5de7\u601d\uff1a\u7528\u8f83\u5c11\u8d44\u6e90\u8fbe\u6210\u8f83\u5927\u7528\u6237\u4ef7\u503c\n"
        "   - \u957f\u7ebf\u751f\u6001\u94fa\u57ab\uff1a\u4e3a\u56de\u6d41/\u7559\u5b58/\u8de8\u7248\u672c\u8854\u63a5\u7684\u524d\u77bb\u5b89\u6392\n"
        "   \u5982\u679c\u6ca1\u6709\u503c\u5f97\u6807\u8bb0\u7684\u4eae\u70b9\uff0c\u8fd4\u56de\u7a7a\u6570\u7ec4\u3002\n"
        "   \u6bcf\u9879: {aspect: \u4e00\u53e5\u8bdd\u6982\u62ec, detail: \u7b80\u8981\u8bf4\u660e\u4ef7\u503c\u5224\u65ad\u539f\u56e0}\n"
        "\n\u8bed\u6c14\u89c4\u5219\uff1a\n"
        "- comment \u4e2d\u4e0d\u4f7f\u7528\u5938\u8d5e\u6027\u5f62\u5bb9\u8bcd\uff08\u7cbe\u5999\u3001\u51fa\u8272\u3001\u5de7\u5999\u7b49\uff09\n"
        "- \u4eae\u70b9\u53ea\u9648\u8ff0\u4e8b\u5b9e + \u4ef7\u503c\u5224\u65ad\u539f\u56e0\n"
        "- \u95ee\u9898\u63cf\u8ff0\u7528'\u5efa\u8bae...'\u800c\u975e'\u7f3a\u5931...\u9700\u8981...'\n"
        "- \u8de8\u5c42\u5185\u5bb9\u8bc4\u4f30\uff1a\u5173\u6ce8\u4e0b\u6e38\u80fd\u5426\u4ece\u4e2d\u51c6\u786e\u7406\u89e3\u8bbe\u8ba1\u610f\u56fe\uff0c"
        "\u7528'\u53ef\u4f5c\u4e3aXX\u53c2\u8003\uff0c\u5efa\u8bae\u6807\u6ce8\u7528\u9014'\u66ff\u4ee3'\u672c\u5e94\u7531XX\u4ea7\u51fa'\n"
        "- \u8bca\u65ad\u8bed\u53e5\u533a\u5206\u4e8b\u5b9e\u4e0e\u5224\u65ad\uff1a\u5148\u5f15\u7528\u6587\u6863\u539f\u6587\u72b6\u6001\uff08\u5982'\u6587\u6863\u6807\u6ce8XX\u5f85\u786e\u8ba4'\uff09\uff0c"
        "\u518d\u7ed9\u51fa\u5f71\u54cd\u5224\u65ad\uff08\u5982'\u5bfc\u81f4\u4e0b\u6e38\u65e0\u6cd5XX'\uff09\uff0c\u907f\u514d\u8bfb\u8005\u5206\u4e0d\u6e05\u662f\u6587\u6863\u81ea\u8ff0\u8fd8\u662f\u5f15\u64ce\u8bca\u65ad\n"
        "- \u5efa\u8bae\u5fc5\u987b\u5177\u4f53\u53ef\u64cd\u4f5c\uff1a\u8bf4\u660e'\u8c01\u505a\u4ec0\u4e48\u3001\u8fbe\u5230\u4ec0\u4e48\u72b6\u6001'\uff0c"
        "\u907f\u514d\u7b3c\u7edf\u7684\u6d41\u7a0b\u6027\u8868\u8ff0\uff08\u5982'\u786e\u4fddXX\u4ecb\u5165'\uff09"
    )
    return "\n".join(parts)


def _build_assessment_user_prompt(topic_text, extraction_result, document_layer):
    checklist_json = json.dumps(extraction_result, ensure_ascii=False, indent=2)
    layer_hint = f"\n文档层级: {document_layer}" if document_layer else ""
    return (
        f"## 文档结构提取结果\n\n```json\n{checklist_json}\n```\n\n"
        f"## 原始文档{layer_hint}\n\n{topic_text}"
    )


# ============================================================
# Synthesis v0.4 — merge extraction + assessments into report data
# ============================================================

_PIPELINE_KEYWORDS = [
    "\u7ba1\u7ebf\u6743\u91cd", "\u6743\u91cd\u7f3a\u5931", "\u6743\u91cd\u5168\u90e8",
    "\u524d\u7f6e\u6761\u4ef6", "DoR", "\u4f53\u9a8c\u8868", "Feature\u6e05\u5355",
    "\u4fe1\u606f\u4e0d\u5bf9\u79f0", "\u4e0d\u5bf9\u9f50",
    "\u89d2\u8272\u672a\u6307\u6d3e", "PLD/PLE/PLT", "\u7ba1\u7ebf\u89d2\u8272",
    "Owner", "\u6807\u6ce8", "\u6a21\u677f", "\u89d2\u8272\u6307\u6d3e", "\u7ba1\u7ebf",
]

_RHYTHM_KEYWORDS = [
    "\u65f6\u95f4\u7ebf", "\u8282\u594f", "\u624e\u5806", "\u7a7a\u7a97",
    "\u514d\u8d39\u73a9\u5bb6", "\u6162\u8f68\u7ba1\u7ebf\u7a7a\u8f6c",
    "\u8de8\u7248\u672c", "\u8986\u76d6",
]

_VERSION_LEVEL_KEYWORDS = [
    "\u6d88\u8017\u7ade\u4e89", "\u8282\u594f", "\u96c6\u4e2d\u5ea6", "\u6295\u653e\u91cd\u53e0",
    "\u540c\u8d28\u5316", "\u8d44\u6e90\u4e89\u593a", "\u5185\u5bb9\u5bc6\u5ea6",
]


def _reclassify_cross_feature(quality_issues: list[dict]):
    """Promote WHAT-layer issues with version-level scope to VERSION layer."""
    for issue in quality_issues:
        if issue.get("layer") != "WHAT":
            continue
        title = issue.get("title", "")
        if any(kw in title for kw in _VERSION_LEVEL_KEYWORDS):
            issue["layer"] = "VERSION"


def _is_passed_feature(issue: dict) -> bool:
    """A feature is 'passed' if WHAT is present and no serious issues found.

    Pass conditions (any of):
    - status=present and all assessors say pass
    - status=present and severity is P3 (minor suggestion only)
    """
    if issue.get("layer") != "WHAT":
        return False
    if issue.get("extraction_status") != "present":
        return False
    comments = issue.get("role_comments", [])
    if not comments:
        return True
    if all(rc.get("impact") == "pass" for rc in comments):
        return True
    if issue.get("severity") == "P3":
        return True
    return False


def _strip_comment_emoji(issue: dict):
    """Remove trailing emoji markers leaked from assessment impact into comment text."""
    import re
    _TRAILING_EMOJI = re.compile(r'\s*[\U0001f534\U0001f7e1\U0001f7e2\u2705\u274c\u26aa\U0001f7e0]+\s*$')
    for rc in issue.get("role_comments", []):
        comment = rc.get("comment", "")
        rc["comment"] = _TRAILING_EMOJI.sub("", comment)


def _classify_reminder(item: dict, scenario: dict) -> str:
    """Classify an item as pipeline/rhythm reminder or empty string (quality).

    Returns "pipeline", "rhythm", or "" (not a reminder).
    """
    if scenario.get("target") != "version":
        return ""
    cat = item.get("category", "")
    if cat == "quality":
        return ""
    title = item.get("title", "")
    if cat == "reminder":
        if any(kw in title for kw in _RHYTHM_KEYWORDS):
            return "rhythm"
        return "pipeline"
    if any(kw in title for kw in _PIPELINE_KEYWORDS):
        return "pipeline"
    if any(kw in title for kw in _RHYTHM_KEYWORDS):
        return "rhythm"
    return ""


def synthesize_v2(extraction: dict, assessments: list[dict], scenario: dict) -> dict:
    checklist = extraction.get("checklist", [])
    layer_overview = extraction.get("layer_overview", [])
    cross_layer = extraction.get("cross_layer_observations", [])
    target = scenario.get("target", "feature")
    persp_map = _VERSION_PERSP_LABEL if target == "version" else _PERSP_LABEL

    raw_issues = []
    for item in checklist:
        issue = _build_issue(item, assessments, persp_map, target)
        issue["_group_id"] = item.get("group_id", "")
        issue["_category"] = item.get("category", "")
        issue["_severity_hint"] = item.get("severity_hint", "")
        raw_issues.append(issue)

    for asmt in assessments:
        for sf in asmt.get("supplementary_findings", []):
            gid = sf.get("group_id", "")
            if gid and any(i["_group_id"] == gid for i in raw_issues):
                _merge_supplementary_into_group(raw_issues, sf, asmt, gid, persp_map)
            elif not any(i["item_id"] == sf.get("item_id") for i in raw_issues):
                sup_issue = _build_issue_from_supplementary(sf, asmt, persp_map, target)
                sup_issue["_group_id"] = gid
                sup_issue["_category"] = sf.get("category", "")
                sup_issue["_severity_hint"] = sf.get("severity_hint", "")
                raw_issues.append(sup_issue)

    merged = _merge_groups(raw_issues)

    quality_issues = []
    pipeline_reminders = []
    rhythm_reminders = []
    passed_features = []
    for issue in merged:
        cat = issue.pop("_category", "")
        issue["category"] = cat
        _strip_comment_emoji(issue)
        issue["_severity_hint"] = issue.pop("_severity_hint", "")
        reminder_type = _classify_reminder(issue, scenario)
        if reminder_type == "pipeline":
            issue["category"] = "reminder"
            issue["reminder_type"] = "pipeline"
            pipeline_reminders.append(issue)
        elif reminder_type == "rhythm":
            issue["category"] = "reminder"
            issue["reminder_type"] = "rhythm"
            rhythm_reminders.append(issue)
        else:
            issue["category"] = "quality"
            quality_issues.append(issue)

    if target == "version":
        _reclassify_cross_feature(quality_issues)

    reminders = pipeline_reminders + rhythm_reminders

    _assign_severity(quality_issues, scenario)
    for r in reminders:
        r["severity"] = "INFO"

    still_issues = []
    for issue in quality_issues:
        if _is_passed_feature(issue):
            issue["severity"] = "PASS"
            if target == "version":
                passed_features.append(issue)
        else:
            still_issues.append(issue)
    quality_issues = still_issues

    verdicts = [a.get("verdict", "pass") for a in assessments]
    rules = scenario.get("synthesis_rules", {})
    blocker_count = verdicts.count("block")
    concern_count = verdicts.count("concern")

    if rules.get("any_block_means_block") and blocker_count > 0:
        overall = "block"
    elif concern_count >= rules.get("concern_threshold", 2):
        overall = "concern"
    elif concern_count > 0:
        overall = "concern"
    else:
        overall = "pass"

    quality_issues.sort(key=lambda i: {"P0": 0, "P1": 1, "WARN": 2, "P2": 3, "P3": 4}.get(i["severity"], 9))

    highlights = []
    for a in assessments:
        role_id = a.get("role_id", "")
        for h in a.get("highlights", []):
            highlights.append({
                "role_id": role_id,
                "aspect": h.get("aspect", ""),
                "detail": h.get("detail", ""),
            })

    total_cl = len(checklist)
    present_cl = sum(1 for c in checklist if c.get("status") == "present")
    doc_completeness_score = round(present_cl / total_cl * 10) if total_cl else 0

    return {
        "overall_verdict": overall,
        "scenario_id": scenario.get("id", ""),
        "layer_overview": layer_overview,
        "issues": quality_issues,
        "passed_features": passed_features,
        "reminders": reminders,
        "pipeline_reminders": pipeline_reminders,
        "rhythm_reminders": rhythm_reminders,
        "cross_layer": cross_layer,
        "highlights": highlights,
        "blocker_count": blocker_count,
        "concern_count": concern_count,
        "doc_completeness_score": doc_completeness_score,
    }


def _merge_groups(raw_issues: list[dict]) -> list[dict]:
    """Merge issues sharing the same group_id into a single composite issue."""
    result = []
    seen_groups: dict[str, int] = {}

    for issue in raw_issues:
        gid = issue.pop("_group_id", "")
        cat = issue.pop("_category", "")
        hint = issue.pop("_severity_hint", "")
        if not gid:
            issue["_category"] = cat
            issue["_severity_hint"] = hint
            result.append(issue)
            continue

        if gid in seen_groups:
            target_issue = result[seen_groups[gid]]
            target_issue["role_comments"].extend(issue.get("role_comments", []))
            sub = issue.get("title", "")
            gap = issue.get("gap_description", "")
            if gap:
                sub = f"{sub}: {gap}"
            target_issue.setdefault("sub_items", []).append(sub)
            et = issue.get("extracted_text", "")
            if et and et not in target_issue.get("extracted_text", ""):
                target_issue["extracted_text"] = (target_issue.get("extracted_text", "") + "\n\n" + et).strip()
        else:
            seen_groups[gid] = len(result)
            issue.setdefault("sub_items", [])
            issue["_category"] = cat
            issue["_severity_hint"] = hint
            result.append(issue)

    for issue in result:
        by_persp: dict[str, list] = {}
        for rc in issue.get("role_comments", []):
            persp = rc.get("perspective", "")
            by_persp.setdefault(persp, []).append(rc)
        deduped = []
        for persp, rcs in by_persp.items():
            best = max(rcs, key=lambda r: len(r.get("comment", "")))
            deduped.append(best)
        issue["role_comments"] = deduped

    return result


def _merge_supplementary_into_group(issues: list[dict], sf: dict, asmt: dict, gid: str,
                                    persp_map: dict | None = None):
    """Merge a supplementary finding's comment into an existing group issue."""
    pm = persp_map or _PERSP_LABEL
    rid = asmt.get("role_id", "")
    for issue in issues:
        if issue.get("_group_id") == gid:
            issue["role_comments"].append({
                "perspective": pm.get(rid, rid.upper()),
                "impact": sf.get("impact", "concern"),
                "comment": sf.get("suggested_action", sf.get("description", "")),
            })
            break


def _build_issue(checklist_item: dict, assessments: list[dict],
                 persp_map: dict | None = None, scenario_target: str = "feature") -> dict:
    pm = persp_map or _PERSP_LABEL
    item_id = checklist_item["item_id"]
    role_comments = []
    for asmt in assessments:
        rid = asmt.get("role_id", "")
        for ia in asmt.get("issue_assessments", []):
            if ia.get("item_id") == item_id:
                role_comments.append({
                    "perspective": pm.get(rid, rid.upper()),
                    "impact": ia.get("impact", "pass"),
                    "comment": ia.get("comment", ""),
                })

    gap = checklist_item.get("gap_description", "")
    status = checklist_item.get("status", "missing")
    status_label = {
        "missing": "\u7f3a\u5931", "incomplete": "\u4e0d\u5b8c\u6574",
        "present": "\u5df2\u6709", "fragment": "\u7247\u6bb5",
    }.get(status, status)

    ac = checklist_item.get("acceptance_criteria", "")
    if not ac:
        ac = gap

    title = checklist_item.get("title", item_id)
    target_state = _natural_target_state(title, status, scenario_target)
    initiator = "PLD" if scenario_target == "version" else "Feature Owner"

    return {
        "item_id": item_id,
        "title": title,
        "layer": checklist_item.get("layer", ""),
        "extraction_status": status,
        "gap_description": gap,
        "extracted_text": checklist_item.get("extracted_text", ""),
        "role_comments": role_comments,
        "action": {
            "target_state": target_state,
            "current_status": status_label,
            "acceptance_criteria": ac,
            "initiator": initiator,
        },
        "severity": "P2",
    }


_TARGET_TEMPLATES = {
    "\u4f53\u9a8c\u610f\u56fe\u58f0\u660e": "\u6587\u6863\u5305\u542b\u4e00\u53e5\u8bdd\u7ea7\u4f53\u9a8c\u610f\u56fe\u58f0\u660e",
    "\u5206\u5c42\u4f53\u9a8c\u76ee\u6807": "\u5404\u5c42\u73a9\u5bb6\u6709\u660e\u786e\u7684\u60c5\u7eea\u76ee\u6807",
    "\u5185\u5bb9\u7ed3\u6784": "\u4e09\u5c42\u5faa\u73af\u5173\u952e\u8fde\u63a5\u70b9\u5df2\u95ed\u5408",
    "\u6210\u529f\u6307\u6807": "\u5df2\u5b9a\u4e49\u5317\u6781\u661f\u3001\u53c2\u4e0e\u3001\u5065\u5eb7\u5ea6\u6307\u6807",
    "\u51b3\u7b56\u6e05\u5355": "\u6240\u6709\u5f85\u5b9a\u9879\u5df2\u6536\u655b\u4e14\u9644\u4f9d\u636e",
    "\u6570\u503c/\u7ecf\u6d4e\u6a21\u578b\u534f\u8c03": "\u5956\u52b1\u9884\u7b97\u4e0e\u6570\u503c\u7b56\u5212\u5df2\u534f\u8c03",
    "\u4ea4\u4e92\u9700\u6c42\u8f93\u5165\u8d28\u91cf": "\u4e0b\u6e38UX\u6240\u9700\u7684\u8bbe\u8ba1\u8f93\u5165\u5df2\u5145\u5206",
    "\u672f\u8bed\u8868": "\u6587\u6863\u5305\u542b\u672f\u8bed\u8868",
    "\u7ba1\u7ebf\u6743\u91cd\u6807\u6ce8": "\u7ba1\u7ebf\u6743\u91cd\u5df2\u6807\u6ce8",
    "\u4ea4\u4e92\u65b9\u6848": "\u8de8\u5c42\u5185\u5bb9\u5df2\u6807\u6ce8\u4e3a\u53c2\u8003",
    "\u4fe1\u606f\u67b6\u6784": "\u672f\u8bed\u547d\u540d\u4f53\u7cfb\u5df2\u7edf\u4e00",
    "\u7cfb\u7edf\u67b6\u6784\u65b9\u6848": "BUILD\u5c42\u53c2\u6570\u5df2\u6807\u6ce8\u4e3a\u610f\u56fe\u7ea7",
}


def _natural_target_state(title: str, status: str, scenario_target: str = "feature") -> str:
    if title in _TARGET_TEMPLATES:
        return _TARGET_TEMPLATES[title]
    if scenario_target == "version":
        if status == "missing":
            return f"\u786e\u8ba4{title}\u7684\u5b9a\u4f4d\u548c\u6743\u91cd"
        return f"{title}\u5df2\u660e\u786e"
    if status == "missing":
        return f"\u6587\u6863\u5305\u542b{title}"
    return f"{title}\u5df2\u8fbe\u6807"


def _build_issue_from_supplementary(sf: dict, asmt: dict,
                                    persp_map: dict | None = None,
                                    scenario_target: str = "feature") -> dict:
    pm = persp_map or _PERSP_LABEL
    rid = asmt.get("role_id", "")
    initiator = "PLD" if scenario_target == "version" else "Feature Owner"
    return {
        "item_id": sf.get("item_id", ""),
        "title": sf.get("title", ""),
        "layer": sf.get("layer", ""),
        "extraction_status": "supplementary",
        "gap_description": sf.get("description", ""),
        "extracted_text": "",
        "role_comments": [{
            "perspective": pm.get(rid, rid.upper()),
            "impact": sf.get("impact", "concern"),
            "comment": sf.get("suggested_action", sf.get("description", "")),
        }],
        "action": {
            "target_state": sf.get("title", ""),
            "current_status": "\u5f85\u8bc4\u4f30",
            "acceptance_criteria": sf.get("suggested_action", sf.get("description", "")),
            "initiator": initiator,
        },
        "severity": "P2",
    }


def _assign_severity(issues: list[dict], scenario: dict):
    pipeline_stage = scenario.get("pipeline_stage", "")
    target = scenario.get("target", "feature")
    is_planning_version = (target == "version" and pipeline_stage == "planning")

    for issue in issues:
        impacts = [rc["impact"] for rc in issue.get("role_comments", [])]
        hint = issue.get("_severity_hint", "")

        if "block" in impacts:
            issue["severity"] = "P0"
        elif hint and hint in ("P0", "P1", "WARN", "P2", "P3"):
            issue["severity"] = hint
        elif "concern" in impacts:
            if is_planning_version:
                issue["severity"] = "P2"
            else:
                issue["severity"] = "P1"
        else:
            status = issue.get("extraction_status", "")
            if status == "missing":
                issue["severity"] = "P2" if is_planning_version else "P1"
            else:
                issue["severity"] = "P3" if is_planning_version else "P2"


# ============================================================
# Legacy parallel flow (for scenarios without extraction_role)
# ============================================================

async def _run_legacy_parallel(provider, scenario, topic_text, document_layer):
    roles = [load_role(r) for r in scenario.get("roles", scenario.get("assessment_roles", []))]
    playbook_text = load_playbook(PLAYBOOK_PATH)
    mode = scenario.get("mode", "review")

    logger.info("legacy scenario=%s roles=%s", scenario["id"], [r["id"] for r in roles])

    tasks = [
        _invoke_legacy_role(provider, role, topic_text, playbook_text, mode, scenario, document_layer)
        for role in roles
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid, errors = [], []
    for role, result in zip(roles, results):
        if isinstance(result, Exception):
            logger.error("role=%s error=%s", role["id"], result)
            errors.append({"role_id": role["id"], "error": str(result)})
        else:
            valid.append(result)

    if not valid:
        return {
            "overall_verdict": "error",
            "summary": "All roles returned errors",
            "role_results": [], "boundary_violations": [], "action_items": [],
            "dor_status": "blocked", "blocker_count": 0, "concern_count": 0,
            "errors": errors,
        }

    synthesis = _legacy_synthesize(valid, scenario.get("synthesis_rules", {}))
    if errors:
        synthesis["errors"] = errors
    return synthesis


async def _invoke_legacy_role(provider, role_config, topic_text, playbook_text, mode, scenario, document_layer):
    knowledge = get_knowledge_for_role(role_config, playbook_text)

    parts = [role_config["persona"].strip()]
    authority = _resolve_authority(role_config, scenario)
    if authority == "block":
        parts.append("\n你拥有 block 权。")
    elif authority == "concern":
        parts.append("\n你最多给出 concern。")
    if knowledge:
        parts.append(f"\n## 参考知识\n\n{knowledge}")
    dims = role_config.get("review_dimensions", [])
    if dims:
        parts.append(f"\n## 审查维度\n\n" + "\n".join(f"- {d}" for d in dims))
    parts.append("\n## 输出要求\n\n以JSON格式输出：role_id, verdict, reasoning, dimension_checks, boundary_violations, action_items")
    system_prompt = "\n".join(parts)

    layer_hint = f"\n文档层级: {document_layer}" if document_layer else ""
    user_prompt = f"请审查以下Feature方案：\n\n{topic_text}{layer_hint}"

    return await provider.complete(system_prompt, user_prompt, ROLE_REVIEW_SCHEMA)


def _legacy_synthesize(role_results, rules):
    verdicts = [r.get("verdict", "error") for r in role_results]
    bc = verdicts.count("block")
    cc = verdicts.count("concern")
    if rules.get("any_block_means_block") and bc > 0:
        overall = "block"
    elif cc >= rules.get("concern_threshold", 2):
        overall = "concern"
    elif cc > 0:
        overall = "concern"
    else:
        overall = "pass"
    return {
        "overall_verdict": overall,
        "role_results": role_results,
        "blocker_count": bc, "concern_count": cc,
        "dor_status": "blocked" if overall == "block" else ("needs_attention" if overall == "concern" else "passed"),
    }


# ============================================================
# Shared helpers
# ============================================================

def _apply_role_overrides(role_config: dict, scenario: dict) -> dict:
    """Merge scenario-level role_overrides into role_config (except authority)."""
    overrides = scenario.get("role_overrides", {}).get(role_config["id"], {})
    if not overrides:
        return role_config
    merged = {**role_config}
    for key, value in overrides.items():
        if key != "authority":
            merged[key] = value
    return merged


def _resolve_authority(role_config: dict, scenario: dict) -> str:
    overrides = scenario.get("role_overrides", {}).get(role_config["id"], {})
    if "authority" in overrides:
        return overrides["authority"]
    by_scenario = role_config.get("authority_by_scenario", {})
    if scenario.get("id") in by_scenario:
        return by_scenario[scenario["id"]] or "advisory"
    return role_config.get("authority", "advisory")
