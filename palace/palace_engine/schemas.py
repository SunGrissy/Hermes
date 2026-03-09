"""Palace v0.4 schemas — two-step extraction + assessment architecture.

Step 1 (Extraction): boundary role extracts structured checklist from document.
Step 2 (Assessment): PLD/PLE/PLT each assess checklist items from their perspective.
Synthesis: code merges extraction + assessments into REPORT_DATA for rendering.
"""

# ---------------------------------------------------------------------------
# Step 1: Extraction output (boundary role)
# ---------------------------------------------------------------------------

LAYER_OVERVIEW_ITEM = {
    "type": "object",
    "properties": {
        "layer": {"type": "string", "enum": ["WHAT", "HOW", "BUILD"]},
        "ratio": {"type": "string"},
        "completeness": {"type": "string", "enum": ["complete", "incomplete", "fragment", "absent"]},
        "key_gaps": {"type": "string"},
    },
    "required": ["layer", "ratio", "completeness"],
}

CHECKLIST_ITEM = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "title": {"type": "string"},
        "layer": {"type": "string", "enum": ["WHAT", "HOW", "BUILD"]},
        "status": {"type": "string", "enum": ["present", "incomplete", "missing"]},
        "extracted_text": {"type": "string"},
        "gap_description": {"type": "string"},
        "acceptance_criteria": {"type": "string"},
        "group_id": {"type": "string"},
    },
    "required": ["item_id", "title", "layer", "status"],
}

CROSS_LAYER_OBS = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["intent", "readiness", "annotate"]},
        "description": {"type": "string"},
        "suggestion": {"type": "string"},
    },
    "required": ["category", "description"],
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "layer_overview": {"type": "array", "items": LAYER_OVERVIEW_ITEM},
        "checklist": {"type": "array", "items": CHECKLIST_ITEM},
        "cross_layer_observations": {"type": "array", "items": CROSS_LAYER_OBS},
    },
    "required": ["layer_overview", "checklist", "cross_layer_observations"],
}

# ---------------------------------------------------------------------------
# Step 2: Role assessment output (PLD / PLE / PLT)
# ---------------------------------------------------------------------------

ISSUE_ASSESSMENT = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "impact": {"type": "string", "enum": ["pass", "concern", "block"]},
        "comment": {"type": "string"},
    },
    "required": ["item_id", "impact", "comment"],
}

SUPPLEMENTARY_FINDING = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "title": {"type": "string"},
        "layer": {"type": "string"},
        "description": {"type": "string"},
        "impact": {"type": "string", "enum": ["pass", "concern", "block"]},
        "suggested_action": {"type": "string"},
    },
    "required": ["item_id", "title", "impact"],
}

ROLE_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "role_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "concern", "block"]},
        "perspective_summary": {"type": "string"},
        "issue_assessments": {"type": "array", "items": ISSUE_ASSESSMENT},
        "supplementary_findings": {"type": "array", "items": SUPPLEMENTARY_FINDING},
    },
    "required": ["role_id", "verdict", "perspective_summary", "issue_assessments"],
}

# ---------------------------------------------------------------------------
# Synthesis output (what report.py receives)
# ---------------------------------------------------------------------------

ACTION = {
    "type": "object",
    "properties": {
        "target_state": {"type": "string"},
        "current_status": {"type": "string"},
        "acceptance_criteria": {"type": "string"},
        "initiator": {"type": "string"},
    },
    "required": ["target_state", "current_status", "acceptance_criteria", "initiator"],
}

ISSUE = {
    "type": "object",
    "properties": {
        "item_id": {"type": "string"},
        "title": {"type": "string"},
        "layer": {"type": "string"},
        "extraction_status": {"type": "string"},
        "severity": {"type": "string", "enum": ["P0", "P1", "P2"]},
        "gap_description": {"type": "string"},
        "extracted_text": {"type": "string"},
        "role_comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "perspective": {"type": "string"},
                    "impact": {"type": "string"},
                    "comment": {"type": "string"},
                },
            },
        },
        "action": ACTION,
    },
    "required": ["item_id", "title", "layer", "severity"],
}

REPORT_DATA = {
    "type": "object",
    "properties": {
        "overall_verdict": {"type": "string", "enum": ["pass", "concern", "block", "error"]},
        "scenario_id": {"type": "string"},
        "layer_overview": {"type": "array", "items": LAYER_OVERVIEW_ITEM},
        "issues": {"type": "array", "items": ISSUE},
        "cross_layer": {"type": "array", "items": CROSS_LAYER_OBS},
        "blocker_count": {"type": "integer"},
        "concern_count": {"type": "integer"},
    },
    "required": ["overall_verdict", "issues", "blocker_count", "concern_count"],
}

# ---------------------------------------------------------------------------
# Legacy schemas (kept for old parallel-flow scenarios)
# ---------------------------------------------------------------------------

_LEGACY_ACTION_ITEM = {
    "type": "object",
    "properties": {
        "priority": {"type": "string", "enum": ["P0", "P1", "P2"]},
        "owner": {"type": "string"},
        "action": {"type": "string"},
        "deadline": {"type": "string"},
    },
    "required": ["priority", "owner", "action"],
}

ROLE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "role_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "concern", "block"]},
        "reasoning": {"type": "string"},
        "dimension_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "status": {"type": "string", "enum": ["pass", "concern", "block"]},
                    "note": {"type": "string"},
                },
                "required": ["question", "status", "note"],
            },
        },
        "boundary_violations": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": _LEGACY_ACTION_ITEM},
    },
    "required": [
        "role_id", "verdict", "reasoning",
        "dimension_checks", "boundary_violations", "action_items",
    ],
}
