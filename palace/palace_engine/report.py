"""Palace report renderer v0.6 — information density and architecture overhaul.

Changes from v0.5:
- Dashboard: two tables (overview + dimensions), filtered top concerns, compressed highlights
- Version issues: merge role comments into bullet points (no role labels)
- Feature precheck: merge perspectives into bullet list with dimension tags
- Version report: 2+2 section structure (risk+feature / pipeline+rhythm)
- Doc completeness score in overview table
"""
from __future__ import annotations

from datetime import datetime

_VE = {"block": "\U0001f534", "concern": "\U0001f7e1", "pass": "\U0001f7e2", "error": "\u26aa"}
_VL = {"block": "\u672a\u8fbe\u6807", "concern": "\u6709\u98ce\u9669", "pass": "\u8fbe\u6807", "error": "\u5f02\u5e38"}
_NEXT = {
    "block": "\u9700\u4fee\u6539\u540e\u91cd\u65b0\u63d0\u5ba1",
    "concern": "\u53ef\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5\uff0c\u9700\u5173\u6ce8\u98ce\u9669\u9879",
    "pass": "\u53ef\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5",
    "error": "\u5ba1\u67e5\u5f02\u5e38",
}
_SE = {"P0": "\u26a1", "P1": "\U0001f6a9", "WARN": "\u203c\ufe0f", "P2": "\U0001f536", "P3": "\U0001f4a1", "INFO": "\U0001f4ac", "PASS": "\u2705"}
_SL = {"P0": "\u963b\u65ad", "P1": "\u5fc5\u6539", "WARN": "\u9884\u8b66", "P2": "\u91cd\u70b9\u5efa\u8bae", "P3": "\u5efa\u8bae", "INFO": "\u63d0\u9192", "PASS": "\u901a\u8fc7"}
_IE = {"block": "\u274c", "concern": "\U0001f7e1", "pass": "\u2705"}
_COMP = {
    "complete": "\u2705 \u5b8c\u6574",
    "present": "\u2705 \u5b8c\u6574",
    "incomplete": "\U0001f7e1 \u4e0d\u5b8c\u6574",
    "fragment": "\U0001f7e0 \u7247\u6bb5",
    "absent": "\u26aa \u672a\u6d89\u53ca",
}

_SCENARIO_TITLE = {
    "what_precheck": "Feature \u9884\u5ba1\u62a5\u544a",
    "dor_slow": "DoR \u5ba1\u67e5\u62a5\u544a",
    "dor_fast": "\u5feb\u8f68 DoR \u62a5\u544a",
    "how_review": "HOW \u5ba1\u67e5\u62a5\u544a",
    "version_layout": "\u7248\u672c\u5185\u5bb9\u6392\u5e03\u9884\u5ba1",
}

_CAT_TITLE = {
    "intent": ("\U0001f3af", "\u610f\u56fe\u4f20\u9012"),
    "readiness": ("\u23f3", "\u4e0b\u6e38\u5c31\u7eea\u5ea6"),
    "annotate": ("\U0001f3f7\ufe0f", "\u6807\u6ce8\u5efa\u8bae"),
}


# ============================================================
# Main entry
# ============================================================

def generate_markdown(
    data: dict, *,
    scenario_id: str = "",
    feature_title: str = "",
    feature_owner: str = "",
    pipeline_weight: str = "",
    pipeline_stage: str = "",
    document_layer: str = "",
) -> str:
    sid = scenario_id or data.get("scenario_id", "")
    if sid == "version_layout":
        return _generate_version_layout(
            data, feature_title=feature_title, pipeline_stage=pipeline_stage,
        )
    ov = data.get("overall_verdict", "error")
    bc = data.get("blocker_count", 0)
    cc = data.get("concern_count", 0)
    issues = data.get("issues", [])
    layer_overview = data.get("layer_overview", [])
    cross_layer = data.get("cross_layer", [])

    primary_layer = _detect_primary_layer(sid, document_layer)
    core_issues = [i for i in issues if i.get("layer", "") == primary_layer]
    cross_issues = [i for i in issues if i.get("layer", "") != primary_layer]

    lines: list[str] = []

    title = _SCENARIO_TITLE.get(sid, "\u5ba1\u67e5\u62a5\u544a")
    ft = f" \u00b7 {feature_title}" if feature_title else ""
    lines.append(f"# {title}{ft}")
    lines.append("")

    doc_score = data.get("doc_completeness_score")
    _meta(lines, feature_owner, pipeline_weight, pipeline_stage, document_layer, ov, bc, cc,
          doc_completeness_score=doc_score)

    if layer_overview:
        _layer_overview(lines, layer_overview)

    p0s = [i for i in issues if i.get("severity") == "P0"]

    lines.append("")
    lines.append(f"## {_VE[ov]} {_VL[ov]} \u2014 {_NEXT[ov]}")
    lines.append("")

    _verdict_summary(lines, issues)

    if p0s:
        target = "\u7533\u8bf7\u91cd\u65b0\u63d0\u5ba1" if ov == "block" else "\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5"
        lines.append(f"## \u26a1 \u5fc5\u987b\u5904\u7406\uff08{len(p0s)} \u9879\uff09")
        lines.append("")
        lines.append(f"\u4ee5\u4e0b\u5404\u9879\u5b8c\u6210\u540e\u53ef{target}\uff1a")
        lines.append("")
        _p0_cards(lines, p0s)
        lines.append("")

    if cross_layer:
        _cross_layer_section(lines, cross_layer)

    lines.append(f"## {primary_layer} \u5c42\u5ba1\u67e5\u8be6\u60c5\uff08{len(core_issues)} \u9879\uff09")
    lines.append("")
    for idx, issue in enumerate(core_issues, 1):
        _issue_section(lines, idx, issue)

    build_cross = [i for i in cross_issues
                   if i.get("layer", "").upper() == "BUILD"]
    if build_cross:
        lines.append(f"## BUILD \u5c42\u98ce\u9669\u63d0\u793a\uff08{len(build_cross)} \u9879\uff09")
        lines.append("")
        lines.append("> \u4ee5\u4e0b\u4e3a\u6280\u672f\u4fa7\u98ce\u9669\u4e0e\u4f9d\u8d56\u63d0\u793a\uff0c\u4f9b PLT \u53c2\u8003\u3002")
        lines.append("")
        for idx, issue in enumerate(build_cross, 1):
            _issue_section(lines, idx, issue)

    rendered = core_issues + build_cross
    non_p0 = [i for i in rendered if i.get("severity") != "P0"]
    if non_p0:
        lines.append("## \u5f85\u6539\u8fdb\u7d22\u5f15")
        lines.append("")
        by_sev: dict[str, list[str]] = {}
        for issue in non_p0:
            sev = issue.get("severity", "P2")
            by_sev.setdefault(sev, []).append(issue.get("title", ""))
        for sev_key in ["P1", "WARN", "P2", "P3"]:
            items = by_sev.get(sev_key)
            if items:
                lines.append(f"{_SE.get(sev_key, '')} {_SL.get(sev_key, sev_key)}\uff1a{' | '.join(items)}")
        lines.append("")

    lines.append("---")
    lines.append("")
    report_text = "\n".join(lines)
    char_count = len(report_text)
    gen_line = f"*Generated by Palace Engine v0.6 \u00b7 {datetime.now().strftime('%Y-%m-%d %H:%M')} \u00b7 {char_count} \u5b57*"
    lines.insert(2, gen_line)
    lines.insert(3, "")
    return "\n".join(lines)


def _detect_primary_layer(scenario_id: str, document_layer: str) -> str:
    if "what" in scenario_id.lower():
        return "WHAT"
    if "how" in scenario_id.lower():
        return "HOW"
    if "build" in scenario_id.lower():
        return "BUILD"
    if document_layer and document_layer.upper() != "MIXED":
        return document_layer.upper()
    return "WHAT"


# ============================================================
# Section renderers (shared)
# ============================================================

def _meta(lines, owner, weight, stage, dl, ov, bc, cc,
          doc_completeness_score=None):
    lines.append("| \u9879\u76ee | \u5185\u5bb9 |")
    lines.append("|------|------|")
    if owner:
        lines.append(f"| Owner | {owner} |")
    if dl:
        ll = {"WHAT": "WHAT (\u4f53\u9a8c\u8bbe\u8ba1)", "HOW": "HOW (\u4ea4\u4e92\u65b9\u6848)",
              "BUILD": "BUILD (\u7cfb\u7edf\u65b9\u6848)", "MIXED": "\u6df7\u5408\u5c42\u7ea7"}
        lines.append(f"| \u6587\u6863\u5c42\u7ea7 | {ll.get(dl.upper(), dl)} |")
    if weight:
        wl = "\U0001f422 \u6162\u8f68" if weight == "slow" else "\U0001f407 \u5feb\u8f68"
        lines.append(f"| \u7ba1\u7ebf\u6743\u91cd | {wl} |")
    if stage:
        sl = {"planning": "\u89c4\u5212\u9636\u6bb5", "scoping": "\u51c6\u5907\u9636\u6bb5",
              "dor": "DoR \u95e8\u7981", "production": "\u751f\u4ea7\u9636\u6bb5"}
        lines.append(f"| \u7ba1\u7ebf\u9636\u6bb5 | {sl.get(stage, stage)} |")
    if doc_completeness_score is not None:
        lines.append(f"| \u6587\u6863\u5b8c\u5907\u5ea6 | {doc_completeness_score}/10 |")
    lines.append(f"| \u5ba1\u67e5\u7ed3\u679c | {_VE[ov]} **{_VL[ov]}** |")


def _layer_overview(lines, overview):
    lines.append("")
    lines.append("## \u6587\u6863\u5206\u5c42\u6982\u89c8")
    lines.append("")
    lines.append("| \u5c42\u7ea7 | \u5185\u5bb9\u5360\u6bd4 | \u5b8c\u6210\u5ea6 | \u5173\u952e\u7f3a\u53e3 |")
    lines.append("|------|----------|--------|----------|")
    for lo in overview:
        comp = _COMP.get(lo.get("completeness", ""), lo.get("completeness", ""))
        raw_gaps = lo.get("key_gaps", "\u2014")
        if isinstance(raw_gaps, list):
            short = [_trunc(g, _MAX_TABLE_GAP) for g in raw_gaps[:3]]
            gaps = "\uff1b".join(short) or "\u2014"
            if len(raw_gaps) > 3:
                gaps += f" \u7b49 {len(raw_gaps)} \u9879"
        else:
            gaps = raw_gaps if raw_gaps else "\u2014"
        layer = lo['layer']
        ratio = lo.get('ratio', '\u2014')
        lines.append(f"| {layer} | {ratio} | {comp} | {gaps} |")
    lines.append("")
    lines.append(
        "*\u5b8c\u6210\u5ea6\uff1a\u2705\u5b8c\u6574 \U0001f7e1\u6709\u7f3a\u9879"
        " \U0001f7e0\u7247\u6bb5(\u975e\u672c\u5c42\u6b63\u5f0f\u4ea4\u4ed8\uff0c\u5c5e\u53c2\u8003\u5185\u5bb9)"
        " \u26aa\u672a\u6d89\u53ca*"
    )
    lines.append("")


def _verdict_summary(lines, issues):
    p0_count = sum(1 for i in issues if i.get("severity") == "P0")
    p1_count = sum(1 for i in issues if i.get("severity") == "P1")
    warn_count = sum(1 for i in issues if i.get("severity") == "WARN")
    p2_count = sum(1 for i in issues if i.get("severity") == "P2")
    p3_count = sum(1 for i in issues if i.get("severity") == "P3")
    if p0_count:
        lines.append(f"- \u26a1 **{p0_count}** \u9879\u963b\u65ad\uff08\u5fc5\u987b\u89e3\u51b3\uff09")
    if p1_count:
        lines.append(f"- \U0001f6a9 **{p1_count}** \u9879\u5fc5\u6539\uff08\u91cd\u8981\u4f46\u4e0d\u963b\u65ad\uff09")
    if warn_count:
        lines.append(f"- \u203c\ufe0f **{warn_count}** \u9879\u9884\u8b66\uff08\u7248\u672c\u7ed3\u6784\u6027\u98ce\u9669\uff0c\u9700 PLD \u663e\u5f0f\u5e94\u5bf9\uff09")
    if p2_count:
        lines.append(f"- \U0001f536 **{p2_count}** \u9879\u91cd\u70b9\u5efa\u8bae\uff08\u5f71\u54cd\u7248\u672c\u7ed3\u6784\uff0c\u5efa\u8bae\u89c4\u5212\u9636\u6bb5\u5904\u7406\uff09")
    if p3_count:
        lines.append(f"- \U0001f4a1 **{p3_count}** \u9879\u5efa\u8bae\uff08\u4fe1\u606f\u8865\u5145\uff0c\u53ef\u540e\u7eed\u8ddf\u8fdb\uff09")
    lines.append("")


def _p0_cards(lines, p0_issues):
    for idx, issue in enumerate(p0_issues, 1):
        act = issue.get("action", {})
        ts = act.get("target_state", issue.get("title", ""))
        cs = act.get("current_status", "")
        ac = act.get("acceptance_criteria", "")
        lines.append(f"> **{idx}. {ts}** \u00b7 \u73b0\u72b6\uff1a{cs}")
        lines.append(f">")
        lines.append(f"> \u8fbe\u6807\u8981\u6c42\uff1a{ac}")
        lines.append("")


def _extract_short_reason(gap: str) -> str:
    """Extract a short reason phrase from gap_description for P0/P1 headings."""
    first = gap.split("\u3002")[0] if "\u3002" in gap else gap
    if len(first) > 40 and "\uff1a" in first:
        first = first.split("\uff1a")[0]
    if len(first) > 40 and "\uff0c" in first:
        first = first.split("\uff0c")[0]
    if len(first) > 45:
        first = first[:42] + "\u2026"
    return first


def _issue_section(lines, idx, issue):
    sev = issue.get("severity", "P2")
    title = issue.get("title", "")
    layer = issue.get("layer", "")
    status = issue.get("extraction_status", "")
    gap = issue.get("gap_description", "")
    extracted = issue.get("extracted_text", "")
    comments = issue.get("role_comments", [])
    sub_items = issue.get("sub_items", [])

    layer_tag = f" [{layer}]" if layer else ""
    if sev in ("P0", "P1") and gap:
        reason = _extract_short_reason(gap)
        status_part = f" \u00b7 {reason}" if reason else ""
    else:
        status_label = {"missing": "\u274c \u7f3a\u5931", "incomplete": "\U0001f7e1 \u4e0d\u5b8c\u6574",
                        "present": "\u2705 \u5df2\u6709", "fragment": "\U0001f7e0 \u7247\u6bb5",
                        "supplementary": ""}.get(status, status)
        status_part = f" \u00b7 {status_label}" if status_label else ""
    lines.append(f"### {idx}. {title}{layer_tag} \u00b7 {_SE.get(sev, '')} {_SL.get(sev, sev)}{status_part}")
    lines.append("")

    if gap:
        gap_bullets = _split_to_bullets(gap)
        lines.append(f"> {gap_bullets[0]}")
        for gb in gap_bullets[1:]:
            lines.append(f"> - {gb}")
        lines.append("")

    if sev == "P0":
        lines.append("*\u2191 \u5df2\u5217\u5165\u4e0a\u65b9\u300c\u26a1 \u5fc5\u987b\u5904\u7406\u300d\u7ae0\u8282\uff0c\u5904\u7406\u540e\u53ef\u91cd\u65b0\u63d0\u5ba1*")
        lines.append("")

    if sub_items:
        lines.append("\u5177\u4f53\u7f3a\u53e3\uff1a")
        for si in sub_items:
            si_bullets = _split_to_bullets(si)
            lines.append(f"- {si_bullets[0]}")
            for sb in si_bullets[1:]:
                lines.append(f"  - {sb}")
        lines.append("")

    if comments:
        _PASS_NOISE = ("\u65e0\u660e\u663e", "\u65e0\u98ce\u9669", "\u65e0\u6280\u672f",
                       "\u4e0d\u6d89\u53ca", "\u4e0d\u5b58\u5728", "\u53ef\u884c", "\u6ca1\u6709",
                       "\u65e0\u9700", "\u6682\u65e0", "\u8fbe\u6807")
        is_pass = sev in ("PASS", "INFO", "P3")
        for rc in comments:
            persp = rc.get("perspective", "")
            comment = rc.get("comment", "").strip()
            if not comment:
                continue
            if is_pass and any(comment.startswith(w) for w in _PASS_NOISE):
                continue
            dim_label = _dim_short_label(persp)
            c_bullets = _split_to_bullets(comment)
            prefix = f"**{dim_label}**\uff1a" if dim_label else ""
            lines.append(f"- {prefix}{c_bullets[0]}")
            for cb in c_bullets[1:]:
                lines.append(f"  - {cb}")
        lines.append("")

    if extracted and len(extracted) > 15 and ("\u201c" in extracted or "\u300c" in extracted):
        lines.append("<details>")
        lines.append("<summary>\u76f8\u5173\u539f\u6587</summary>")
        lines.append("")
        lines.append(extracted)
        lines.append("")
        lines.append("</details>")
        lines.append("")


def _split_to_bullets(text: str) -> list[str]:
    """Split long text into bullet points by sentence boundaries and numbered patterns."""
    import re
    text = re.sub(r'(?<=[；。])\s*(\d+[)）])', r'\n\1', text)
    text = re.sub(r'(?<=[^。；\n])\s*(\d+[)）])', r'\n\1', text)
    parts: list[str] = []
    for chunk in text.split('\n'):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _cross_layer_section(lines, observations):
    grouped: dict[str, list] = {}
    for obs in observations:
        cat = obs.get("category", "annotate")
        grouped.setdefault(cat, []).append(obs)

    for cat_key in ["intent", "readiness", "annotate"]:
        items = grouped.get(cat_key, [])
        if not items:
            continue
        emoji, label = _CAT_TITLE.get(cat_key, ("\U0001f4cc", cat_key))
        lines.append(f"## {emoji} {label}")
        lines.append("")
        for obs in items:
            desc = obs.get("description", "")
            sug = obs.get("suggestion", "")
            if sug:
                lines.append(f"**\u5efa\u8bae**\uff1a{sug}")
                lines.append("")
            bullets = _split_to_bullets(desc)
            for b in bullets:
                lines.append(f"- {b}")
            lines.append("")


# ============================================================
# Version layout report renderer
# ============================================================

_STATUS_ICON = {
    "missing": "\u274c", "incomplete": "\U0001f7e1", "present": "\u2705",
    "fragment": "\U0001f7e0", "supplementary": "\U0001f50d",
}

_MAX_DASH_GAP = 40
_MAX_TABLE_GAP = 25


def _generate_version_layout(data, *, feature_title="", pipeline_stage=""):
    ov = data.get("overall_verdict", "error")
    issues = data.get("issues", [])
    passed_features = data.get("passed_features", [])
    reminders = data.get("reminders", [])
    layer_overview = data.get("layer_overview", [])
    cross_layer = data.get("cross_layer", [])
    highlights = data.get("highlights", [])
    detected_doc_type = data.get("detected_doc_type", "version")
    is_feature_mode = (detected_doc_type == "feature")

    if is_feature_mode:
        layer_overview = [
            lo for lo in layer_overview
            if lo.get("completeness") != "absent"
        ]

    feat_issues = [i for i in issues if i.get("layer", "") == "WHAT"]
    ver_issues = [i for i in issues if i.get("layer", "") == "VERSION"]
    sup_issues = [i for i in issues
                  if i.get("layer", "") not in ("WHAT", "VERSION")]

    p0s = [i for i in issues if i.get("severity") == "P0"]
    p1s = [i for i in issues if i.get("severity") == "P1"]
    warns = [i for i in issues if i.get("severity") == "WARN"]
    p2s = [i for i in issues if i.get("severity") == "P2"]
    p3s = [i for i in issues if i.get("severity") == "P3"]

    lines: list[str] = []

    ft = f" \u00b7 {feature_title}" if feature_title else ""
    mode_suffix = " \u00b7 Feature \u6a21\u5f0f" if is_feature_mode else ""
    lines.append(f"# \u7248\u672c\u5185\u5bb9\u6392\u5e03\u9884\u5ba1{ft}{mode_suffix}")
    lines.append("")

    if is_feature_mode:
        lines.append(
            "> \u26a0\ufe0f **\u6587\u6863\u7c7b\u578b\u68c0\u6d4b\uff1a\u5355 Feature \u6587\u6863\uff08\u975e\u7248\u672c\u89c4\u5212\uff09\u3002**"
            " \u7cfb\u7edf\u5df2\u81ea\u52a8\u8c03\u6574\u4e3a Feature \u7ea7\u89c6\u89d2\uff0c"
            "\u7248\u672c\u7ea7\u7ef4\u5ea6\uff08\u5feb\u6162\u8f68\u914d\u6bd4\u3001Owner\u8d1f\u8377\u7b49\uff09"
            "\u5df2\u8df3\u8fc7\u3002\u5982\u9700\u7248\u672c\u7ea7\u5b8c\u6574\u5206\u6790\uff0c"
            "\u8bf7\u63d0\u4f9b\u7248\u672c\u89c4\u5212\u6587\u6863\u3002"
        )
        lines.append("")

    doc_score = data.get("doc_completeness_score")
    _health_dashboard(
        lines, pipeline_stage, ov, layer_overview, highlights,
        ver_issues + sup_issues, feat_issues, passed_features,
        p0s, p1s, warns, p2s, p3s, reminders,
        doc_completeness_score=doc_score,
        is_feature_mode=is_feature_mode,
    )

    pipeline_rem = data.get("pipeline_reminders", [])
    rhythm_rem = data.get("rhythm_reminders", [])

    cl_risk = [o for o in cross_layer
               if o.get("category") in ("intent", "readiness")]
    cl_annotate = [o for o in cross_layer
                   if o.get("category") == "annotate"]

    if p0s:
        lines.append(f"> \u26a0\ufe0f \u4ee5\u4e0b **{len(p0s)}** \u9879\u5fc5\u987b\u5728\u7248\u672c\u542f\u52a8\u524d\u89e3\u51b3\uff1a")
        lines.append("")
        _p0_cards(lines, p0s)

    all_risk = ver_issues + sup_issues
    if all_risk:
        risk_title = "\u98ce\u9669\u4e0e\u4f9d\u8d56\u5206\u6790" if is_feature_mode else "\u7248\u672c\u98ce\u9669\u4e0e\u51b3\u7b56\u7f3a\u53e3"
        lines.append(f"## {risk_title}\uff08{len(all_risk)} \u9879\uff09")
        lines.append("")
        for idx, issue in enumerate(all_risk, 1):
            _ver_issue_detail(lines, idx, issue)

    if rhythm_rem:
        lines.append(f"## \u8fd0\u8425\u8282\u594f\u89c2\u5bdf\uff08{len(rhythm_rem)} \u9879\uff09")
        lines.append("")
        lines.append("> \u4ee5\u4e0b\u4e3a\u7248\u672c\u5185\u5bb9\u8282\u594f\u89c2\u5bdf\uff0c\u4f9b PLD \u5728\u7ec4\u76d8\u51b3\u7b56\u65f6\u53c2\u8003\u3002")
        lines.append("")
        for idx, r in enumerate(rhythm_rem, 1):
            _render_reminder_item(lines, idx, r)
        lines.append("")

    if cl_risk:
        lines.append(f"## \u8de8 Feature \u89c2\u5bdf\uff08{len(cl_risk)} \u9879\uff09")
        lines.append("")
        lines.append(
            "> Feature \u4e4b\u95f4\uff08\u6216 Feature \u5185\u90e8\u5b50\u6a21\u5757\u4e4b\u95f4\uff09"
            "\u7684\u4f53\u9a8c\u610f\u56fe\u4f20\u9012\u3001\u4f9d\u8d56\u5173\u7cfb\u548c"
            "\u4e0b\u6e38\u5c31\u7eea\u5ea6\u89c2\u5bdf\u3002"
        )
        lines.append("")
        _CL_CAT_LABEL = {
            "intent": ("\U0001f3af", "\u610f\u56fe\u4f20\u9012"),
            "readiness": ("\u231b", "\u4e0b\u6e38\u5c31\u7eea\u5ea6"),
        }
        grouped: dict[str, list] = {}
        for obs in cl_risk:
            cat = obs.get("category", "readiness")
            grouped.setdefault(cat, []).append(obs)
        for cat_key in ["intent", "readiness"]:
            items = grouped.get(cat_key, [])
            if not items:
                continue
            emoji, label = _CL_CAT_LABEL.get(cat_key, ("\U0001f4cc", cat_key))
            lines.append(f"**{emoji} {label}** ({len(items)})")
            lines.append("")
            for idx, obs in enumerate(items, 1):
                desc = obs.get("description", "")
                sug = obs.get("suggestion", "")
                paras = _break_long_text(desc)
                lines.append(f"{idx}. {paras[0]}")
                for p in paras[1:]:
                    lines.append("")
                    lines.append(f"   {p}")
                if sug:
                    lines.append("")
                    lines.append(f"   \u2192 {sug}")
                lines.append("")

    _feature_completeness_table(lines, feat_issues, passed_features)

    pipe_total = len(pipeline_rem) + len(cl_annotate)
    if pipe_total:
        lines.append(f"## \u7ba1\u7ebf\u63a8\u8fdb\u63d0\u9192\uff08{pipe_total} \u9879\uff09")
        lines.append("")
        lines.append("> \u4ee5\u4e0b\u4e3a\u7ba1\u7ebf\u6d41\u7a0b\u4e8b\u9879\uff0c\u4e0d\u5f71\u54cd\u4e3b\u5ba1\u7ed3\u8bba\u3002")
        lines.append("")
        for idx, r in enumerate(pipeline_rem, 1):
            _render_reminder_item(lines, idx, r)
        if pipeline_rem:
            lines.append("")
        if cl_annotate:
            _cross_layer_section(lines, cl_annotate)

    lines.append("---")
    lines.append("")
    report_text = "\n".join(lines)
    vl_char_count = len(report_text)
    vl_gen_line = (
        f"*Generated by Palace Engine v0.6 \u00b7 "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} \u00b7 {vl_char_count} \u5b57*"
    )
    lines.insert(2, vl_gen_line)
    lines.insert(3, "")
    result = "\n".join(lines)
    import re
    result = re.sub(
        r'\u514d\u8d39\u73a9\u5bb6(?!\uff08)',
        '\u514d\u8d39\u73a9\u5bb6\uff08\u6682\u65f6\u4e0d\u60f3\u4ed8\u8d39\u7684\u73a9\u5bb6\uff09',
        result, count=1,
    )
    return result


def _health_dashboard(lines, stage, ov, overview, highlights,
                      ver_issues, feat_issues, passed_features,
                      p0s, p1s, warns, p2s, p3s, reminders,
                      doc_completeness_score=None,
                      is_feature_mode=False):
    """Health dashboard — two tables, filtered concerns, compressed highlights."""
    sl = {"planning": "\u89c4\u5212\u9636\u6bb5", "scoping": "\u51c6\u5907\u9636\u6bb5", "dor": "DoR \u95e8\u7981"}
    stage_label = sl.get(stage, stage) if stage else ""

    dashboard_title = "Feature \u5065\u5eb7\u5ea6" if is_feature_mode else "\u89c4\u5212\u5065\u5eb7\u5ea6"
    lines.append(f"## {dashboard_title}")
    lines.append("")
    if is_feature_mode:
        lines.append(
            "> Feature \u5185\u90e8\u7684\u8bbe\u8ba1\u5b8c\u6574\u6027\u3001"
            "\u4f9d\u8d56\u98ce\u9669\u548c\u51b3\u7b56\u8d28\u91cf\u7efc\u5408\u8bc4\u4f30\u3002"
        )
    else:
        lines.append(
            "> \u7248\u672c\u7ec4\u76d8\u7684\u6574\u4f53\u5065\u5eb7\u5ea6\u8bc4\u4f30\uff0c"
            "\u542b\u5feb\u6162\u8f68\u914d\u6bd4\u3001\u7528\u6237\u4ef7\u503c\u8986\u76d6\u3001"
            "\u5185\u5bb9\u8282\u594f\u3001\u7814\u53d1\u8d1f\u8377\u7b49\u7ef4\u5ea6\u3002"
        )
    lines.append("")

    stage_suffix = f" \u00b7 {stage_label}" if stage_label else ""
    lines.append(f"{_VE[ov]} **{_VL.get(ov, ov)}** \u2014 {_NEXT[ov]}{stage_suffix}")
    lines.append("")

    top_issues = []
    for issue in p0s + p1s + warns:
        impacts = [rc.get("impact", "pass") for rc in issue.get("role_comments", [])]
        if not impacts or any(i != "pass" for i in impacts):
            top_issues.append(issue)
    if top_issues:
        lines.append("**\u6700\u9700\u5173\u6ce8**")
        lines.append("")
        for idx, issue in enumerate(top_issues[:5], 1):
            sev = issue.get("severity", "P2")
            title = issue.get("title", "")
            gap = issue.get("gap_description", "")
            first_sentence = gap.split("\u3002")[0] + "\u3002" if "\u3002" in gap else gap
            lines.append(
                f"{idx}. {_SE.get(sev, '')} **{title}** \u2014 {first_sentence}"
            )
        lines.append("")

    if highlights:
        seen = set()
        aspects = []
        for h in highlights:
            aspect = h.get("aspect", "")
            if aspect and aspect not in seen and len(aspects) < 3:
                seen.add(aspect)
                aspects.append(aspect)
        if aspects:
            joined = "\u3001".join(aspects)
            lines.append(f"**\u4eae\u70b9**\uff1a{joined}")
            lines.append("")

    lines.append("---")
    lines.append("")

    total_feat = len(feat_issues) + len(passed_features)
    what_ok = len(passed_features)
    feat_missing = sum(
        1 for i in feat_issues
        if i.get("extraction_status") == "missing"
    )
    feat_incomplete = len(feat_issues) - feat_missing

    total_issues = len(ver_issues) + len(feat_issues)
    issue_cell = (
        f"{total_issues}\u9879"
        f"\uff08{_SE['P0']}{len(p0s)} {_SE['P1']}{len(p1s)}"
        f" {_SE['WARN']}{len(warns)}"
        f" {_SE['P2']}{len(p2s)} {_SE['P3']}{len(p3s)}\uff09"
    )
    feat_cell = (
        f"{total_feat}\u4e2a"
        f"\uff08\u2705{what_ok} \U0001f7e1{feat_incomplete} \u274c{feat_missing}\uff09"
    )
    reminder_cell = f"{len(reminders)}\u9879" if reminders else "0\u9879"

    if doc_completeness_score is not None:
        lines.append("| \u95ee\u9898 | Feature | \u5b8c\u5907\u5ea6 | \u63d0\u9192 |")
        lines.append("|------|---------|--------|------|")
        lines.append(f"| {issue_cell} | {feat_cell} | {doc_completeness_score}/10 | {reminder_cell} |")
    else:
        lines.append("| \u95ee\u9898 | Feature | \u63d0\u9192 |")
        lines.append("|------|---------|------|")
        lines.append(f"| {issue_cell} | {feat_cell} | {reminder_cell} |")
    lines.append("")
    lines.append(
        "*\u26a1\u963b\u65ad \U0001f6a9\u5fc5\u6539 \u203c\ufe0f\u9884\u8b66"
        " \U0001f536\u5efa\u8bae \U0001f4a1\u4fe1\u606f"
        " \u00b7 \u2705\u901a\u8fc7 \U0001f7e1\u4e0d\u5b8c\u6574 \u274c\u7f3a\u5931*"
    )
    lines.append("")

    if overview and not is_feature_mode:
        names = [lo.get("layer", "") for lo in overview]
        icons = []
        for lo in overview:
            comp = lo.get("completeness", "")
            icon = "\u2705" if comp == "complete" else "\u26a0\ufe0f"
            icons.append(icon)
        lines.append("| " + " | ".join(names) + " |")
        lines.append("|" + "|".join(" ------ " for _ in names) + "|")
        lines.append("| " + " | ".join(icons) + " |")
        lines.append("")
        lines.append("*\u2705\u8fbe\u6807 \u26a0\ufe0f\u6709\u98ce\u9669*")
        lines.append("")


def _ver_issue_detail(lines, idx, issue):
    """Version-level issue detail — merge all comments into bullet points."""
    sev = issue.get("severity", "P2")
    title = issue.get("title", "")
    gap = issue.get("gap_description", "")
    comments = issue.get("role_comments", [])

    lines.append(
        f"### {idx}. {title} \u00b7 {_SE.get(sev, '')} {_SL.get(sev, sev)}"
    )
    lines.append("")
    if gap:
        lines.append(f"> {gap}")
        lines.append("")
    all_points = _collect_comment_points(comments)
    if not all_points:
        lines.append("*\u4ec5\u57fa\u4e8e\u6587\u6863\u63d0\u53d6\u7ed3\u679c\u3002*")
    elif len(all_points) == 1 and len(all_points[0]) < 80:
        lines.append(all_points[0])
    else:
        for pt in all_points:
            lines.append(f"- {pt}")
    lines.append("")


def _dedup_comments_with_labels(comments: list[dict], gap: str = "") -> list[dict]:
    """Cross-perspective dedup that preserves the first contributing perspective label."""
    if not comments:
        return []
    gap_sents = [s.strip() for s in _split_sentences(gap) if s.strip()] if gap else []
    seen: list[str] = list(gap_sents)
    result: list[dict] = []
    for rc in comments:
        text = rc.get("comment", "").strip()
        if not text:
            continue
        unique_parts = []
        for sent in _split_sentences(text):
            s = sent.strip()
            if s and not any(_text_overlap(s, existing) for existing in seen):
                seen.append(s)
                unique_parts.append(s)
        if unique_parts:
            result.append({
                "perspective": rc.get("perspective", ""),
                "comment": "".join(unique_parts),
            })
    return result


def _feat_issue_detail(lines, idx, issue):
    """Feature issue detail — compact format with dimension labels."""
    sev = issue.get("severity", "P2")
    title = issue.get("title", "")
    status = issue.get("extraction_status", "")
    gap = issue.get("gap_description", "")
    comments = issue.get("role_comments", [])

    if sev in ("P0", "P1") and gap:
        reason = _extract_short_reason(gap)
        status_part = f" \u00b7 {reason}" if reason else ""
    else:
        icon = _STATUS_ICON.get(status, "\u26aa")
        status_part = f" {icon}"
    lines.append(
        f"**{idx}. {title}**{status_part} \u00b7 {_SE.get(sev, '')} {_SL.get(sev, sev)}"
    )
    if gap:
        lines.append("")
        lines.append(f"> {gap}")
    lines.append("")
    deduped = _dedup_comments_with_labels(comments, gap)
    for rc in deduped:
        persp = rc.get("perspective", "")
        comment = rc.get("comment", "").strip()
        if not comment:
            continue
        dim_label = _dim_short_label(persp)
        c_bullets = _split_to_bullets(comment)
        prefix = f"**{dim_label}**\uff1a" if dim_label else ""
        lines.append(f"- {prefix}{c_bullets[0]}")
        for cb in c_bullets[1:]:
            lines.append(f"  - {cb}")
    if deduped:
        lines.append("")


def _feature_completeness_table(lines, feat_issues, passed_features):
    """Compact Feature completeness table — replaces expanded Feature section."""
    rows: list[tuple[str, str, str, int]] = []
    _SEV_ORDER = {"P0": 0, "P1": 1, "WARN": 2, "P2": 3, "P3": 4, "INFO": 8, "PASS": 9}

    for f in feat_issues:
        status = f.get("extraction_status", "")
        icon = _STATUS_ICON.get(status, "\u26aa")
        sev = f.get("severity", "P2")
        sev_tag = f"{_SE.get(sev, '')} {_SL.get(sev, sev)}"
        gap = f.get("gap_description", "")
        note = gap.split("\u3002")[0] if "\u3002" in gap else gap
        note = _trunc(note, 80)
        rows.append((f.get("title", ""), f"{icon} {sev_tag}", note or "\u2014", _SEV_ORDER.get(sev, 5)))

    for f in passed_features:
        rows.append((f.get("title", ""), "\u2705", "\u2014", 9))

    if not rows:
        return

    rows.sort(key=lambda r: r[3])
    total = len(rows)
    ok = sum(1 for _, _, _, s in rows if s >= 9)

    lines.append(f"## Feature \u5b8c\u5907\u5ea6\u901f\u67e5\uff08{ok}/{total} \u901a\u8fc7\uff09")
    lines.append("")
    lines.append(
        "> \u9010\u9879\u68c0\u67e5\u6bcf\u4e2a Feature \u7684 WHAT \u4ea4\u4ee3\u662f\u5426\u6e05\u6670\uff0c"
        "\u901a\u8fc7 = \u547d\u9898\u6e05\u6670\u53ef\u542f\u52a8\u8be6\u8bbe\uff0c"
        "\u4e0d\u5b8c\u6574 = \u9700\u8865\u5145\u4fe1\u606f\u540e\u518d\u63a8\u8fdb\u3002"
    )
    lines.append("")
    lines.append("| # | Feature | \u72b6\u6001 | \u5907\u6ce8 |")
    lines.append("|---|---------|------|------|")
    for idx, (title, status_cell, note, _) in enumerate(rows, 1):
        lines.append(f"| {idx} | {title} | {status_cell} | {note} |")
    lines.append("")


def _format_long_comment(text: str) -> str:
    """Break numbered items in long comments onto separate lines."""
    import re
    text = re.sub(r'[;；]\s*\((\d)\)', r';\n  (\1)', text)
    text = re.sub(r'[;；]\s*(\d)\)', r';\n  \1)', text)
    text = re.sub(r'(?<=[。！])\s*(\(\d+\))', r'\n  \1', text)
    text = re.sub(r'(?<=[。！])\s*(\d+[\)）])', r'\n  \1', text)
    return text


_DIM_LABELS = {
    "WHAT \u5185\u5bb9\u65b9\u5411": None,
    "WHAT\u2192HOW \u53ef\u8bbe\u8ba1\u6027": "\u53ef\u8bbe\u8ba1\u6027",
    "WHAT\u2192BUILD \u53ef\u5b9e\u73b0\u6027": "\u53ef\u5b9e\u73b0\u6027",
    "\u7248\u672c Scope": "Scope",
    "\u5185\u5bb9\u65b9\u5411": None,
    "\u8d44\u6e90\u4e0e\u6392\u671f": "\u8d44\u6e90\u4e0e\u6392\u671f",
}


def _dim_short_label(perspective: str) -> str | None:
    """Return short dimension label, or None for the primary/first perspective."""
    return _DIM_LABELS.get(perspective, perspective)


def _collect_comment_points(comments: list[dict]) -> list[str]:
    """Merge role_comments into deduplicated discussion points (no role labels)."""
    if not comments:
        return []
    raw = []
    for rc in comments:
        text = rc.get("comment", "").strip()
        if not text:
            continue
        for sent in _split_sentences(text):
            s = sent.strip()
            if s:
                raw.append(s)
    seen: list[str] = []
    for pt in raw:
        if not any(_text_overlap(pt, existing) for existing in seen):
            seen.append(pt)
    return seen


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence-ending punctuation, keeping each as a point."""
    import re
    parts = re.split(r'(?<=[。；！])\s*', text)
    return [p for p in parts if p.strip()]


def _text_overlap(a: str, b: str, threshold: float = 0.6) -> bool:
    """Return True if two short texts share >threshold of their characters."""
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    common = sum(1 for c in short if c in long_)
    return common / len(short) > threshold


def _render_reminder_item(lines, idx, r):
    """Render a single reminder, marking items whose role assessments flag concern/block."""
    title = r.get("title", "")
    gap = r.get("gap_description", "")
    cmt = ""
    if r.get("role_comments"):
        cmt = r["role_comments"][0].get("comment", "")
    detail = gap or cmt
    is_key = any(
        rc.get("impact") not in ("pass", "", None)
        for rc in r.get("role_comments", [])
    )
    marker = " \u26a0\ufe0f" if is_key else ""
    lines.append(f"{idx}. **{title}**{marker}")
    if detail:
        lines.append(f"   {detail}")


def _reminder_section(lines, reminders):
    """Render operational awareness items in a dedicated section."""
    lines.append(f"## \u8fd0\u8425\u63d0\u9192\uff08{len(reminders)} \u9879\uff09")
    lines.append("")
    lines.append("> \u4ee5\u4e0b\u4e3a\u8fd0\u8425 awareness \u63d0\u9192\uff0c\u4e0d\u5f71\u54cd\u4e3b\u5ba1\u7ed3\u8bba\u3002")
    lines.append("")
    for idx, r in enumerate(reminders, 1):
        title = r.get("title", "")
        gap = r.get("gap_description", "")
        comments = r.get("role_comments", [])
        first_comment = ""
        if comments:
            first_comment = comments[0].get("comment", "")
        detail = gap or first_comment
        lines.append(f"{idx}. **{title}**")
        if detail:
            lines.append(f"   {detail}")
    lines.append("")


def _break_long_text(text: str) -> list[str]:
    """Split long text into visual paragraphs at logical transition points."""
    import re
    parts = re.split(r'(?<=\u3002)(?=[\u4f46\u6839\u636e\u8bf7\u5982\u679c\u540c\u65f6\u6b64\u5916])', text)
    return [p.strip() for p in parts if p.strip()] or [text]


def _trunc(text: str, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"
