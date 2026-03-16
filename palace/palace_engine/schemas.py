"""Palace v0.5 schemas — two-step extraction + assessment with doc classification.

Step 0 (Classification): auto-detect or accept user-provided doc_type → resolve review_tier
Step 1 (Extraction): boundary role extracts structured checklist from document.
Step 2 (Assessment): PLD/PLE/PLT each assess checklist items from their perspective.
Synthesis: code merges extraction + assessments into REPORT_DATA for rendering.

Doc types: full_spec / delta / campaign / hotfix / version
Review tiers: full / incremental / campaign / minimal / version
"""

# ---------------------------------------------------------------------------
# Doc classification constants
# ---------------------------------------------------------------------------

DOC_TYPES = ("full_spec", "delta", "campaign", "hotfix", "version")

REVIEW_TIERS = ("full", "incremental", "campaign", "minimal", "version")

TIER_RESOLUTION = {
    ("full_spec", "slow"): "full",
    ("full_spec", "fast"): "full",
    ("full_spec", ""): "full",
    ("delta", "fast"): "incremental",
    ("delta", "slow"): "incremental",
    ("delta", ""): "incremental",
    ("campaign", "fast"): "campaign",
    ("campaign", "slow"): "campaign",
    ("campaign", ""): "campaign",
    ("hotfix", "fast"): "minimal",
    ("hotfix", "slow"): "minimal",
    ("hotfix", ""): "minimal",
    ("version", ""): "version",
    ("version", "slow"): "version",
    ("version", "fast"): "version",
}

TIER_SEVERITY_MAP = {
    "full": {
        "what-intent": "P0",
        "what-success-metrics": "P0",
        "what-content-structure": "P1",
        "what-decision-list": "P1",
        "what-interaction-input": "P1",
        "how-interaction": "P1",
        "how-info-architecture": "P1",
        "build-architecture": "P1",
        "build-api": "P1",
        "build-performance": "P1",
        "doc-terminology": "P1",
        "doc-pipeline-weight": "P1",
        "doc-scope": "P1",
        "_default_block": "P0",
        "_default_concern": "P1",
        "_default_missing": "P1",
        "_default_other": "P2",
    },
    "incremental": {
        "what-intent": "P2",
        "what-success-metrics": "P0",
        "what-content-structure": "P1",
        "what-decision-list": "P1",
        "what-interaction-input": "P2",
        "how-interaction": "SKIP",
        "how-info-architecture": "SKIP",
        "build-architecture": "SKIP",
        "build-api": "SKIP",
        "build-performance": "SKIP",
        "doc-terminology": "P2",
        "doc-pipeline-weight": "P2",
        "doc-scope": "P1",
        "delta-base-system": "P0",
        "delta-diff-completeness": "P0",
        "delta-compatibility": "P0",
        "delta-downstream-impact": "P1",
        "_default_block": "P0",
        "_default_concern": "P1",
        "_default_missing": "P2",
        "_default_other": "P3",
    },
    "campaign": {
        "what-intent": "P1",
        "what-success-metrics": "P0",
        "what-content-structure": "P0",
        "what-decision-list": "P1",
        "what-interaction-input": "P1",
        "how-interaction": "P1",
        "build-architecture": "P2",
        "build-api": "P2",
        "build-performance": "P2",
        "_default_block": "P0",
        "_default_concern": "P1",
        "_default_missing": "P1",
        "_default_other": "P2",
    },
    "minimal": {
        "what-intent": "SKIP",
        "what-success-metrics": "SKIP",
        "what-content-structure": "SKIP",
        "what-decision-list": "SKIP",
        "what-interaction-input": "SKIP",
        "build-architecture": "SKIP",
        "_default_block": "P0",
        "_default_concern": "P1",
        "_default_missing": "P2",
        "_default_other": "P3",
    },
}

# ---------------------------------------------------------------------------
# Step 1: Extraction output (boundary role)
# ---------------------------------------------------------------------------

LAYER_OVERVIEW_ITEM = {
    "type": "object",
    "properties": {
        "layer": {"type": "string"},
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
        "layer": {"type": "string"},
        "status": {"type": "string", "enum": ["present", "incomplete", "missing"]},
        "extracted_text": {"type": "string"},
        "gap_description": {"type": "string"},
        "acceptance_criteria": {"type": "string"},
        "group_id": {"type": "string"},
        "category": {"type": "string", "enum": ["quality", "reminder"]},
        "severity_hint": {"type": "string", "enum": ["P1", "P2"]},
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
        "detected_doc_type": {
            "type": "string",
            "enum": ["full_spec", "delta", "campaign", "hotfix", "version"],
            "description": "Document type classification: full_spec (new system), delta (variant), campaign (ops activity), hotfix, version (release plan)",
        },
        "review_tier": {
            "type": "string",
            "enum": ["full", "incremental", "campaign", "minimal", "version"],
            "description": "Resolved review tier based on doc_type + pipeline_weight",
        },
        "layer_overview": {"type": "array", "items": LAYER_OVERVIEW_ITEM},
        "checklist": {"type": "array", "items": CHECKLIST_ITEM},
        "cross_layer_observations": {"type": "array", "items": CROSS_LAYER_OBS},
    },
    "required": ["detected_doc_type", "review_tier", "layer_overview", "checklist", "cross_layer_observations"],
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
