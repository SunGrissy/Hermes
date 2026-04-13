"""Generic interview checklist/evaluation generator for multiple roles."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from .config import PALACE_PROVIDER, PALACE_ROOT
from .interview_records import (
    append_evaluation_record,
    build_candidate_key,
    upsert_checklist_record,
)

logger = logging.getLogger("palace.interview_checklist")

_ROOT = PALACE_ROOT.parent
_CHECKLIST_DIR = _ROOT / "performeval" / "面试" / "简历初筛"

_ROLE_TO_CHECKLIST = {
    "运营策划": "简历初筛清单_运营策划.md",
    "系统策划": "简历初筛清单_系统策划.md",
    "战斗策划": "简历初筛清单_战斗策划.md",
    "主策划": "简历初筛清单_主策划.md",
    "fresh": "简历初筛清单_应届生.md",
}

_ROLE_TO_RUBRIC = {
    "运营策划": ("rubric_ops.json", "ops", "L3"),
    "系统策划": ("rubric_system_planning.json", "system_planning", "L3"),
}

ROLE_RULES = {
    "运营策划": {
        "target": "L3 运营策划",
        "core": [
            "活动Owner能力：能独立负责活动从目标设定到上线复盘的全流程",
            "数据驱动优化：基于埋点/看板数据做归因分析并持续优化活动效果",
            "商业化理解：理解分层付费与大R用户需求，能兼顾体验与营收目标",
            "节奏与协同：可统筹排期并与研发、美术、数据等团队高效协作",
            "方法沉淀：能把活动经验沉淀为模板或机制，提升团队复用效率",
        ],
    },
    "系统策划": {
        "target": "L3 系统策划",
        "core": [
            "多系统耦合：有多个系统间数据流转和接口边界设计经验",
            "框架扩展：能抽象可复用框架并设计可扩展架构",
            "快轨复用：支持配置化/模板化快速搭建",
            "WHAT->HOW->BUILD 全链路：能独立定义需求并产出可开发文档",
            "Spec交付：有清晰规格文档与配表产出能力",
        ],
    },
    "战斗策划": {
        "target": "L3 战斗策划",
        "core": [
            "战斗系统化能力：不仅做单点，还能构建战斗规则与节奏体系",
            "体验与数值平衡：能在手感、节奏与数值之间做取舍",
            "全流程落地：文档/配置/联调/验收闭环",
            "跨职能协作：能与程序/动画/特效有效协作",
            "复盘迭代：能基于数据与反馈持续优化战斗体验",
        ],
    },
    "主策划": {
        "target": "L4 主策划",
        "core": [
            "方向定义：能定义产品玩法方向与长线节奏",
            "全局架构：有跨系统顶层规划能力",
            "团队管理：有团队机制建设与人才培养经验",
            "跨职能决策：可与主美/主程/运营达成关键共识",
            "品类与商业：对目标用户和商业化有体系认知",
        ],
    },
    "fresh": {
        "target": "应届/准应届（通用）",
        "core": [
            "游戏热情与玩家理解",
            "思维逻辑与问题拆解",
            "学习速度与自驱探索",
            "协作意识与表达能力",
        ],
    },
}

COMMON_THINKING = (
    "【通用思维考察】"
    "关注 AI与进化力、深度思考、第一性原理；"
    "无证据不加分，不得臆测。"
)

SCHEMA_CHECKLIST: dict[str, Any] = {
    "type": "object",
    "properties": {"markdown": {"type": "string"}},
    "required": ["markdown"],
}

SCHEMA_EVAL: dict[str, Any] = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "summary": {"type": "string"},
        "verdict": {"type": "string"},
        "risk_level": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["markdown", "summary", "verdict", "risk_level", "evidence"],
}


def _parse_doc_type(doc_type: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in (doc_type or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, v = part.split(":", 1)
        parsed[k.strip().lower()] = v.strip()
    return parsed


def _extract_candidate(text: str) -> str:
    head = (text or "").splitlines()[:5]
    for line in head:
        line = line.strip()
        if not line:
            continue
        m = re.search(r"([\u4e00-\u9fa5]{2,4})[-_ ]?简历", line)
        if m:
            return m.group(1)
    return "候选人"


def _checklist_text(role: str) -> str:
    path = _CHECKLIST_DIR / _ROLE_TO_CHECKLIST[role]
    if not path.exists():
        return f"[未找到岗位清单: {path}]"
    return path.read_text(encoding="utf-8")


def _rubric_excerpt(role: str) -> str:
    cfg = _ROLE_TO_RUBRIC.get(role)
    if not cfg:
        return "[]"
    file_name, job_function, level = cfg
    path = _ROOT / "performeval" / file_name
    if not path.exists():
        return "[]"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        r
        for r in data.get("rubrics", [])
        if r.get("job_function") == job_function and r.get("capability_level") == level
    ]
    return json.dumps(rows, ensure_ascii=False, indent=2)


def _system_prompt(role: str, mode: str) -> str:
    rr = ROLE_RULES[role]
    core = "\n".join(f"{idx+1}. {x}" for idx, x in enumerate(rr["core"]))
    checklist = _checklist_text(role)
    rubric = _rubric_excerpt(role)
    if mode == "evaluation":
        return (
            f"你是资深面试官助理，目标岗位：{rr['target']}。\n"
            f"请严格按下述能力标准与岗位清单评估面试记录，不得臆测。\n"
            f"【能力标准】\n{core}\n\n{COMMON_THINKING}\n\n"
            f"【岗位初筛清单】\n{checklist}\n\n"
            f"【相关rubric摘录】\n{rubric}\n\n"
            "输出JSON，字段：markdown/summary/verdict/risk_level/evidence。"
        )
    return (
        f"你是资深面试官助理，目标岗位：{rr['target']}。\n"
        f"请基于简历生成可执行的初面清单，不得臆测。\n"
        f"【能力标准】\n{core}\n\n{COMMON_THINKING}\n\n"
        f"【岗位初筛清单】\n{checklist}\n\n"
        f"【相关rubric摘录】\n{rubric}\n\n"
        "输出JSON，字段：markdown。"
    )


def _user_prompt(role: str, mode: str, text: str, candidate_name: str) -> str:
    if mode == "evaluation":
        return (
            f"候选人：{candidate_name}\n岗位：{role}\n\n"
            "以下是面试记录（含问答摘录/观察）：\n"
            f"{text}\n\n"
            "请输出：\n"
            "1) 面试评价Markdown（含结论、证据、风险、建议）\n"
            "2) summary（1句）\n"
            "3) verdict（录用/备选/不录用）\n"
            "4) risk_level（低/中/高）\n"
            "5) evidence（3条内）"
        )
    return (
        f"候选人：{candidate_name}\n岗位：{role}\n\n"
        "以下是候选人简历文本：\n"
        f"{text}\n\n"
        "请输出初面清单Markdown，必须包含：\n"
        "- 预审对齐摘要（命中/待验证）\n"
        "- 核心能力的必问题+追问+红灯信号\n"
        "- 评分表（贴合岗位）\n"
        "- 场景题\n"
        "- 结论区"
    )


def _mock_markdown(mode: str, role: str) -> str:
    if mode == "evaluation":
        return (
            "# 面试评价（Mock）\n\n"
            f"- 岗位：{role}\n"
            "- 说明：当前 PALACE_PROVIDER=mock，未调用真实 LLM。\n"
        )
    return (
        "# 初面清单（Mock）\n\n"
        f"- 岗位：{role}\n"
        "- 说明：当前 PALACE_PROVIDER=mock，未调用真实 LLM。\n"
    )


async def run_interview_checklist(provider, topic_text: str, scenario: dict, doc_type: str = "") -> dict:
    parsed = _parse_doc_type(doc_type)
    role = parsed.get("role", "")
    mode = parsed.get("mode", "checklist")
    candidate_name = parsed.get("candidate") or _extract_candidate(topic_text)
    mobile_tail = parsed.get("mobile_tail", "")
    if role not in ROLE_RULES:
        return {
            "overall_verdict": "error",
            "scenario_id": scenario.get("id", "interview_checklist"),
            "markdown_report": "错误：role 必须为 运营策划/系统策划/战斗策划/主策划/fresh",
            "blocker_count": 1,
            "concern_count": 0,
            "issues": [],
            "layer_overview": [],
        }
    if mode not in ("checklist", "evaluation"):
        mode = "checklist"

    candidate_key = build_candidate_key(candidate_name, role, mobile_tail)
    src_hash = hashlib.sha1(topic_text.encode("utf-8")).hexdigest()[:12]

    if PALACE_PROVIDER == "mock":
        md = _mock_markdown(mode, role)
        if mode == "evaluation":
            append_evaluation_record(
                candidate_key,
                candidate_name,
                role,
                {
                    "summary": "mock summary",
                    "verdict": "备选",
                    "risk_level": "中",
                    "evidence": ["mock provider"],
                    "markdown": md,
                },
            )
        else:
            upsert_checklist_record(candidate_key, candidate_name, role, md, source_resume_hash=src_hash)
        return {
            "overall_verdict": "pass",
            "scenario_id": scenario.get("id", "interview_checklist"),
            "markdown_report": md,
            "role": role,
            "mode": mode,
            "candidate_name": candidate_name,
            "candidate_key": candidate_key,
            "blocker_count": 0,
            "concern_count": 0,
            "issues": [],
            "layer_overview": [],
        }

    system = _system_prompt(role, mode)
    user = _user_prompt(role, mode, topic_text, candidate_name)
    schema = SCHEMA_EVAL if mode == "evaluation" else SCHEMA_CHECKLIST
    result = await provider.complete(system, user, schema)
    md = (result.get("markdown") or "").strip() or "[LLM 返回为空]"
    if mode == "evaluation":
        append_evaluation_record(
            candidate_key,
            candidate_name,
            role,
            {
                "summary": result.get("summary", ""),
                "verdict": result.get("verdict", ""),
                "risk_level": result.get("risk_level", ""),
                "evidence": result.get("evidence", []),
                "markdown": md,
            },
        )
    else:
        upsert_checklist_record(candidate_key, candidate_name, role, md, source_resume_hash=src_hash)

    return {
        "overall_verdict": "pass",
        "scenario_id": scenario.get("id", "interview_checklist"),
        "markdown_report": md,
        "role": role,
        "mode": mode,
        "candidate_name": candidate_name,
        "candidate_key": candidate_key,
        "blocker_count": 0,
        "concern_count": 0,
        "issues": [],
        "layer_overview": [],
    }
