"""Palace core engine v0.4 — two-step extraction + assessment architecture.

Flow (when extraction_role is defined):
  1. Extraction: boundary role reads document, outputs structured checklist
  2. Assessment: PLD/PLE/PLT assess checklist items in parallel
  3. Synthesis: code merges extraction + assessments into report data

Fallback (legacy parallel flow for scenarios without extraction_role):
  Same as v0.3 — all roles run in parallel, then synthesize.
"""

import asyncio
import json
import logging
import time

from .config import PLAYBOOK_PATH, get_provider, load_role, load_scenario
from .knowledge import get_knowledge_for_role, load_playbook
from .schemas import EXTRACTION_SCHEMA, ROLE_ASSESSMENT_SCHEMA, ROLE_REVIEW_SCHEMA

logger = logging.getLogger("palace.engine")

_PERSP_LABEL = {
    "pld": "WHAT 内容方向",
    "ple": "WHAT\u2192HOW 可设计性",
    "plt": "WHAT\u2192BUILD 可实现性",
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
    user_prompt = _build_extraction_user_prompt(topic_text, document_layer)

    start = time.monotonic()
    result = await provider.complete(system_prompt, user_prompt, EXTRACTION_SCHEMA)
    elapsed = time.monotonic() - start
    logger.info("extraction role=%s elapsed=%.2fs items=%d",
                role_config["id"], elapsed, len(result.get("checklist", [])))
    return result


async def _invoke_assessment(provider, role_config, topic_text, playbook_text,
                             extraction_result, scenario, document_layer):
    knowledge = get_knowledge_for_role(role_config, playbook_text)
    authority = _resolve_authority(role_config, scenario)
    system_prompt = _build_assessment_prompt(role_config, knowledge, authority)
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

def _build_extraction_prompt(role_config, knowledge, scenario):
    parts = [role_config["persona"].strip()]

    if knowledge:
        parts.append(f"\n## 参考知识\n\n{knowledge}")

    dims = role_config.get("review_dimensions", [])
    if dims:
        dim_text = "\n".join(f"- {d}" for d in dims)
        parts.append(f"\n## 检查维度\n\n{dim_text}")

    parts.append(
        "\n## 输出要求\n\n"
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
    return "\n".join(parts)


def _build_extraction_user_prompt(topic_text, document_layer):
    layer_hint = ""
    if document_layer:
        layer_labels = {
            "WHAT": "WHAT（体验设计）层文档",
            "HOW": "HOW（交互方案）层文档",
            "BUILD": "BUILD（系统方案）层文档",
            "mixed": "混合层级文档",
        }
        label = layer_labels.get(document_layer.upper(), f"{document_layer} 层文档")
        layer_hint = f"\n\n文档层级声明: {label}"
    return f"请对以下 Feature 文档进行结构化提取：\n\n{topic_text}{layer_hint}"


def _build_assessment_prompt(role_config, knowledge, authority):
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

    parts.append(
        "\n## 输出要求\n\n"
        "前面已经有一份文档结构提取结果（checklist），请基于你的视角逐项评估。\n"
        "以 JSON 格式输出，包含：\n\n"
        "1. role_id: 你的角色 ID\n"
        "2. verdict: pass / concern / block\n"
        "3. perspective_summary: 一段话概述你的总体判断\n"
        "4. issue_assessments: 数组，对 checklist 中每个与你视角相关的项给出评估\n"
        "   每项: {item_id, impact(pass/concern/block), comment}\n"
        "5. supplementary_findings: 数组（可为空），checklist 没覆盖到的额外发现\n"
        "   每项: {item_id(新的), title, layer, description, impact, suggested_action}"
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

def synthesize_v2(extraction: dict, assessments: list[dict], scenario: dict) -> dict:
    checklist = extraction.get("checklist", [])
    layer_overview = extraction.get("layer_overview", [])
    cross_layer = extraction.get("cross_layer_observations", [])

    raw_issues = []
    for item in checklist:
        issue = _build_issue(item, assessments)
        issue["_group_id"] = item.get("group_id", "")
        raw_issues.append(issue)

    for asmt in assessments:
        for sf in asmt.get("supplementary_findings", []):
            gid = sf.get("group_id", "")
            if gid and any(i["_group_id"] == gid for i in raw_issues):
                _merge_supplementary_into_group(raw_issues, sf, asmt, gid)
            elif not any(i["item_id"] == sf.get("item_id") for i in raw_issues):
                sup_issue = _build_issue_from_supplementary(sf, asmt)
                sup_issue["_group_id"] = gid
                raw_issues.append(sup_issue)

    issues = _merge_groups(raw_issues)

    _assign_severity(issues, scenario)

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

    issues.sort(key=lambda i: {"P0": 0, "P1": 1, "P2": 2}.get(i["severity"], 9))

    return {
        "overall_verdict": overall,
        "scenario_id": scenario.get("id", ""),
        "layer_overview": layer_overview,
        "issues": issues,
        "cross_layer": cross_layer,
        "blocker_count": blocker_count,
        "concern_count": concern_count,
    }


def _merge_groups(raw_issues: list[dict]) -> list[dict]:
    """Merge issues sharing the same group_id into a single composite issue."""
    result = []
    seen_groups: dict[str, int] = {}

    for issue in raw_issues:
        gid = issue.pop("_group_id", "")
        if not gid:
            result.append(issue)
            continue

        if gid in seen_groups:
            target = result[seen_groups[gid]]
            target["role_comments"].extend(issue.get("role_comments", []))
            sub = issue.get("title", "")
            gap = issue.get("gap_description", "")
            if gap:
                sub = f"{sub}: {gap}"
            target.setdefault("sub_items", []).append(sub)
            et = issue.get("extracted_text", "")
            if et and et not in target.get("extracted_text", ""):
                target["extracted_text"] = (target.get("extracted_text", "") + "\n\n" + et).strip()
        else:
            seen_groups[gid] = len(result)
            issue.setdefault("sub_items", [])
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


def _merge_supplementary_into_group(issues: list[dict], sf: dict, asmt: dict, gid: str):
    """Merge a supplementary finding's comment into an existing group issue."""
    rid = asmt.get("role_id", "")
    for issue in issues:
        if issue.get("_group_id") == gid:
            issue["role_comments"].append({
                "perspective": _PERSP_LABEL.get(rid, rid.upper()),
                "impact": sf.get("impact", "concern"),
                "comment": sf.get("suggested_action", sf.get("description", "")),
            })
            break


def _build_issue(checklist_item: dict, assessments: list[dict]) -> dict:
    item_id = checklist_item["item_id"]
    role_comments = []
    for asmt in assessments:
        rid = asmt.get("role_id", "")
        for ia in asmt.get("issue_assessments", []):
            if ia.get("item_id") == item_id:
                role_comments.append({
                    "perspective": _PERSP_LABEL.get(rid, rid.upper()),
                    "impact": ia.get("impact", "pass"),
                    "comment": ia.get("comment", ""),
                })

    gap = checklist_item.get("gap_description", "")
    status = checklist_item.get("status", "missing")
    status_label = {"missing": "缺失", "incomplete": "不完整", "present": "已有", "fragment": "片段"}.get(status, status)

    ac = checklist_item.get("acceptance_criteria", "")
    if not ac:
        ac = gap

    title = checklist_item.get("title", item_id)
    target = _natural_target_state(title, status)

    return {
        "item_id": item_id,
        "title": title,
        "layer": checklist_item.get("layer", ""),
        "extraction_status": status,
        "gap_description": gap,
        "extracted_text": checklist_item.get("extracted_text", ""),
        "role_comments": role_comments,
        "action": {
            "target_state": target,
            "current_status": status_label,
            "acceptance_criteria": ac,
            "initiator": "Feature Owner",
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


def _natural_target_state(title: str, status: str) -> str:
    if title in _TARGET_TEMPLATES:
        return _TARGET_TEMPLATES[title]
    if status == "missing":
        return f"\u6587\u6863\u5305\u542b{title}"
    return f"{title}\u5df2\u8fbe\u6807"


def _build_issue_from_supplementary(sf: dict, asmt: dict) -> dict:
    rid = asmt.get("role_id", "")
    return {
        "item_id": sf.get("item_id", ""),
        "title": sf.get("title", ""),
        "layer": sf.get("layer", ""),
        "extraction_status": "supplementary",
        "gap_description": sf.get("description", ""),
        "extracted_text": "",
        "role_comments": [{
            "perspective": _PERSP_LABEL.get(rid, rid.upper()),
            "impact": sf.get("impact", "concern"),
            "comment": sf.get("suggested_action", sf.get("description", "")),
        }],
        "action": {
            "target_state": sf.get("title", ""),
            "current_status": "\u5f85\u8bc4\u4f30",
            "acceptance_criteria": sf.get("suggested_action", sf.get("description", "")),
            "initiator": "Feature Owner",
        },
        "severity": "P2",
    }


def _assign_severity(issues: list[dict], scenario: dict):
    for issue in issues:
        impacts = [rc["impact"] for rc in issue.get("role_comments", [])]
        if "block" in impacts:
            issue["severity"] = "P0"
        elif "concern" in impacts:
            issue["severity"] = "P1"
        else:
            status = issue.get("extraction_status", "")
            if status == "missing":
                issue["severity"] = "P1"
            else:
                issue["severity"] = "P2"


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

def _resolve_authority(role_config: dict, scenario: dict) -> str:
    overrides = scenario.get("role_overrides", {}).get(role_config["id"], {})
    if "authority" in overrides:
        return overrides["authority"]
    by_scenario = role_config.get("authority_by_scenario", {})
    if scenario.get("id") in by_scenario:
        return by_scenario[scenario["id"]] or "advisory"
    return role_config.get("authority", "advisory")
