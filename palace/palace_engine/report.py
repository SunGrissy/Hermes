"""Palace report renderer v0.4 — dumb renderer, no analysis.

Receives structured REPORT_DATA from synthesize_v2 and renders Markdown.
All intelligence lives in LLM prompts and synthesis logic, not here.
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
_SE = {"P0": "\u26a1", "P1": "\U0001f527", "WARN": "\u203c\ufe0f", "P2": "\U0001f536", "P3": "\U0001f4a1", "INFO": "\U0001f4ac", "PASS": "\u2705"}
_SL = {"P0": "\u963b\u65ad", "P1": "\u5fc5\u6539", "WARN": "\u9884\u8b66", "P2": "\u91cd\u70b9\u5efa\u8bae", "P3": "\u5efa\u8bae", "INFO": "\u63d0\u9192", "PASS": "\u901a\u8fc7"}
_IE = {"block": "\u274c", "concern": "\U0001f7e1", "pass": "\u2705"}
_COMP = {
    "complete": "\u2705 \u5b8c\u6574",
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

    _meta(lines, feature_owner, pipeline_weight, pipeline_stage, document_layer, ov, bc, cc)

    if layer_overview:
        _layer_overview(lines, layer_overview)

    p0s = [i for i in issues if i.get("severity") == "P0"]

    lines.append("")
    lines.append(f"## {_VE[ov]} {_VL[ov]} \u2014 {_NEXT[ov]}")
    lines.append("")

    _verdict_summary(lines, issues)

    if p0s:
        target = "\u7533\u8bf7\u91cd\u65b0\u63d0\u5ba1" if ov == "block" else "\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5"
        lines.append(f"\u4ee5\u4e0b **{len(p0s)}** \u9879\u5b8c\u6210\u540e\u53ef{target}\uff1a")
        lines.append("")
        _p0_cards(lines, p0s)
        lines.append("")

    lines.append(f"## \U0001f4cb {primary_layer} \u5c42\u6838\u5fc3\u5ba1\u67e5\uff08{len(core_issues)} \u9879\uff09")
    lines.append("")
    lines.append("> \u6bcf\u4e2a\u8bae\u9898\u4ece\u4e09\u4e2a\u89c6\u89d2\u8bc4\u5ba1\uff1a**\u5185\u5bb9\u65b9\u5411**\uff08\u5185\u5bb9\u672c\u8eab\u662f\u5426\u8fbe\u6807\uff09| **\u53ef\u8bbe\u8ba1\u6027**\uff08\u4e0b\u6e38UX\u80fd\u5426\u5f00\u5de5\uff09| **\u53ef\u5b9e\u73b0\u6027**\uff08\u6280\u672f\u4e0a\u662f\u5426\u53ef\u884c\uff09")
    lines.append("")
    for idx, issue in enumerate(core_issues, 1):
        _issue_section(lines, idx, issue)

    all_cross = cross_issues + [{"_obs": True, **obs} for obs in cross_layer]
    if all_cross:
        lines.append(f"## \U0001f517 \u8de8\u5c42\u89c2\u5bdf\u4e0e\u63d0\u9192\uff08{len(cross_issues)} + {len(cross_layer)} \u9879\uff09")
        lines.append("")
        obs_only = [x for x in all_cross if x.get("_obs")]
        issue_only = [x for x in all_cross if not x.get("_obs")]
        if issue_only:
            for idx, issue in enumerate(issue_only, len(core_issues) + 1):
                _issue_section(lines, idx, issue)
        if obs_only:
            _cross_layer_section(lines, [x for x in cross_layer])

    non_p0 = [i for i in issues if i.get("severity") != "P0"]
    if non_p0:
        titles = " | ".join(
            f"#{idx} {i.get('title', '')}"
            for idx, i in enumerate(
                (x for x in issues if x.get("severity") != "P0"),
                len(p0s) + 1,
            )
        )
        lines.append(f"## \U0001f4dd \u5f85\u6539\u8fdb\u7d22\u5f15")
        lines.append("")
        lines.append(f"{_SE['P1']} \u5fc5\u6539\uff1a{titles}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by Palace Engine v0.4 \u00b7 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
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

def _meta(lines, owner, weight, stage, dl, ov, bc, cc):
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
    lines.append(f"| \u5ba1\u67e5\u7ed3\u679c | {_VE[ov]} **{_VL[ov]}** |")


def _layer_overview(lines, overview):
    lines.append("")
    lines.append("## \u6587\u6863\u5206\u5c42\u6982\u89c8")
    lines.append("")
    lines.append("| \u5c42\u7ea7 | \u5185\u5bb9\u5360\u6bd4 | \u5b8c\u6210\u5ea6 | \u5173\u952e\u7f3a\u53e3 |")
    lines.append("|------|----------|--------|----------|")
    for lo in overview:
        comp = _COMP.get(lo.get("completeness", ""), lo.get("completeness", ""))
        gaps = lo.get("key_gaps", "\u2014")
        layer = lo['layer']
        ratio = lo.get('ratio', '\u2014')
        lines.append(f"| {layer} | {ratio} | {comp} | {gaps} |")
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
        lines.append(f"- \U0001f527 **{p1_count}** \u9879\u5fc5\u6539\uff08\u91cd\u8981\u4f46\u4e0d\u963b\u65ad\uff09")
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


def _issue_section(lines, idx, issue):
    sev = issue.get("severity", "P2")
    title = issue.get("title", "")
    layer = issue.get("layer", "")
    status = issue.get("extraction_status", "")
    gap = issue.get("gap_description", "")
    extracted = issue.get("extracted_text", "")
    comments = issue.get("role_comments", [])
    sub_items = issue.get("sub_items", [])

    status_label = {"missing": "\u274c \u7f3a\u5931", "incomplete": "\U0001f7e1 \u4e0d\u5b8c\u6574",
                    "present": "\u2705 \u5df2\u6709", "fragment": "\U0001f7e0 \u7247\u6bb5",
                    "supplementary": "\U0001f50d \u989d\u5916\u53d1\u73b0"}.get(status, status)

    layer_tag = f" [{layer}]" if layer else ""
    lines.append(f"### {idx}. {title}{layer_tag} \u00b7 {_SE.get(sev, '')} {_SL.get(sev, sev)} \u00b7 {status_label}")
    lines.append("")

    if gap:
        lines.append(f"> {gap}")
        lines.append("")

    if sub_items:
        lines.append("\u5173\u8054\u95ee\u9898\uff1a")
        for si in sub_items:
            lines.append(f"- {si}")
        lines.append("")

    if not comments:
        lines.append("*\u672c\u9879\u65e0\u89d2\u8272\u8bc4\u4f30\uff0c\u4ec5\u57fa\u4e8e\u6587\u6863\u63d0\u53d6\u7ed3\u679c\u3002*")
        lines.append("")
    for rc in comments:
        persp = rc.get("perspective", "")
        impact = rc.get("impact", "")
        comment = rc.get("comment", "")
        ie = _IE.get(impact, "\u26aa")
        lines.append(f"**{persp}**\uff1a{comment} \u2192 {ie}")
        lines.append("")

    if extracted:
        lines.append("<details><summary>\u76f8\u5173\u539f\u6587</summary>")
        lines.append("")
        lines.append(extracted)
        lines.append("")
        lines.append("</details>")
        lines.append("")


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
        lines.append(f"**{emoji} {label}** ({len(items)})")
        lines.append("")
        for obs in items:
            desc = obs.get("description", "")
            sug = obs.get("suggestion", "")
            lines.append(f"- {desc}")
            if sug:
                lines.append(f"  \u2192 {sug}")
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
    lines.append(f"# \u7248\u672c\u5185\u5bb9\u6392\u5e03\u9884\u5ba1{ft}")
    lines.append("")

    _health_dashboard(
        lines, pipeline_stage, ov, layer_overview, highlights,
        ver_issues + sup_issues, feat_issues, passed_features,
        p0s, p1s, warns, p2s, p3s, reminders,
    )

    if p0s:
        lines.append(f"\u4ee5\u4e0b **{len(p0s)}** \u9879\u5fc5\u987b\u5728\u7248\u672c\u542f\u52a8\u524d\u89e3\u51b3\uff1a")
        lines.append("")
        _p0_cards(lines, p0s)

    if ver_issues or sup_issues:
        all_ver = ver_issues + sup_issues
        lines.append(f"## \U0001f3d7\ufe0f \u7248\u672c\u7ea7\u95ee\u9898\u8be6\u60c5\uff08{len(all_ver)} \u9879\uff09")
        lines.append("")
        for idx, issue in enumerate(all_ver, 1):
            _ver_issue_detail(lines, idx, issue)

    if feat_issues:
        lines.append(f"## \U0001f4e6 Feature \u95ee\u9898\u8be6\u60c5\uff08{len(feat_issues)} \u9879\uff09")
        lines.append("")
        lines.append("> \u4ee5\u4e0b\u4ec5\u5217\u51fa\u6709\u95ee\u9898\u7684 Feature\uff0c\u5df2\u901a\u8fc7\u7684\u4e0d\u5c55\u5f00\u3002")
        lines.append("")
        for idx, issue in enumerate(feat_issues, 1):
            _feat_issue_detail(lines, idx, issue)

    if cross_layer:
        lines.append(f"## \U0001f517 \u8de8 Feature \u89c2\u5bdf\uff08{len(cross_layer)} \u9879\uff09")
        lines.append("")
        _cross_layer_section(lines, cross_layer)

    if reminders:
        _reminder_section(lines, reminders)

    lines.append("---")
    lines.append(
        f"*Generated by Palace Engine v0.4 \u00b7 "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
    )
    lines.append("")
    return "\n".join(lines)


def _health_dashboard(lines, stage, ov, overview, highlights,
                      ver_issues, feat_issues, passed_features,
                      p0s, p1s, warns, p2s, p3s, reminders):
    """Health dashboard — replaces old speed-scan tables."""
    sl = {"planning": "\u89c4\u5212\u9636\u6bb5", "scoping": "\u51c6\u5907\u9636\u6bb5", "dor": "DoR \u95e8\u7981"}
    stage_label = sl.get(stage, stage) if stage else ""

    lines.append(f"## \U0001f4ca \u89c4\u5212\u5065\u5eb7\u5ea6")
    lines.append("")

    lines.append(f"{_VE[ov]} **{_VL.get(ov, ov)}** \u2014 {_NEXT[ov]}")
    if stage_label:
        lines.append(f"\uff08{stage_label}\uff09")
    lines.append("")

    top_issues = p0s + p1s + warns + p2s
    if top_issues:
        lines.append("**\U0001f511 \u6700\u9700\u5173\u6ce8**")
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
        lines.append("**\u2705 \u4eae\u70b9**")
        lines.append("")
        seen = set()
        for h in highlights:
            aspect = h.get("aspect", "")
            if aspect in seen:
                continue
            seen.add(aspect)
            detail = h.get("detail", "")
            if detail:
                lines.append(f"- {aspect}\uff1a{detail}")
            else:
                lines.append(f"- {aspect}")
        lines.append("")

    total_feat = len(feat_issues) + len(passed_features)
    what_ok = len(passed_features)
    what_problem = len(feat_issues)
    feat_missing = sum(
        1 for i in feat_issues
        if i.get("extraction_status") == "missing"
    )
    feat_incomplete = what_problem - feat_missing

    total_issues = len(ver_issues) + len(feat_issues)
    parts = []
    parts.append(
        f"\u95ee\u9898 {total_issues}\u9879"
        f"\uff08{_SE['P0']}{len(p0s)} {_SE['P1']}{len(p1s)}"
        f" {_SE['WARN']}{len(warns)}"
        f" {_SE['P2']}{len(p2s)} {_SE['P3']}{len(p3s)}\uff09"
    )
    parts.append(
        f"Feature {total_feat}\u4e2a"
        f"\uff08\u2705{what_ok} \U0001f7e1{feat_incomplete} \u274c{feat_missing}\uff09"
    )
    if reminders:
        parts.append(f"\u8fd0\u8425\u63d0\u9192 {len(reminders)}\u9879")

    sep = "  \u00b7  "
    lines.append(f"**\U0001f4cb \u6982\u89c8** \u00a0\u00a0 {sep.join(parts)}")
    lines.append("")

    if overview:
        dim_parts = []
        for lo in overview:
            name = lo.get("layer", "")
            comp = lo.get("completeness", "")
            icon = "\u2705" if comp == "complete" else "\u26a0\ufe0f"
            dim_parts.append(f"{icon}{name}")
        lines.append(f"**\u7ef4\u5ea6** \u00a0\u00a0 {sep.join(dim_parts)}")
        lines.append("")


def _ver_issue_detail(lines, idx, issue):
    """Version-level issue detail with improved long-text formatting."""
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
    for rc in comments:
        persp = rc.get("perspective", "")
        comment = rc.get("comment", "")
        formatted = _format_long_comment(comment)
        lines.append(f"- **{persp}**\uff1a{formatted}")
        lines.append("")
    if not comments:
        lines.append("*\u4ec5\u57fa\u4e8e\u6587\u6863\u63d0\u53d6\u7ed3\u679c\u3002*")
        lines.append("")


def _feat_issue_detail(lines, idx, issue):
    """Feature issue detail — only shows actual problems, not passed items."""
    sev = issue.get("severity", "P2")
    title = issue.get("title", "")
    status = issue.get("extraction_status", "")
    gap = issue.get("gap_description", "")
    comments = issue.get("role_comments", [])

    icon = _STATUS_ICON.get(status, "\u26aa")
    lines.append(
        f"**{idx}. {title}** {icon} \u00b7 {_SE.get(sev, '')} {_SL.get(sev, sev)}"
    )
    if gap:
        lines.append(f"  \u2014 {gap}")
    for rc in comments:
        persp = rc.get("perspective", "")
        comment = rc.get("comment", "")
        formatted = _format_long_comment(comment)
        lines.append(f"  - **{persp}**\uff1a{formatted}")
    lines.append("")


def _format_long_comment(text: str) -> str:
    """Break numbered items in long comments onto separate lines."""
    import re
    text = re.sub(r'[;；]\s*\((\d)\)', r';\n  (\1)', text)
    text = re.sub(r'[;；]\s*(\d)\)', r';\n  \1)', text)
    text = re.sub(r'(?<=[。！])\s*(\(\d+\))', r'\n  \1', text)
    text = re.sub(r'(?<=[。！])\s*(\d+[\)）])', r'\n  \1', text)
    return text


def _reminder_section(lines, reminders):
    """Render operational awareness items in a dedicated section."""
    lines.append(f"## \U0001f4ac \u7248\u672c\u8fd0\u8425\u63d0\u9192\uff08{len(reminders)} \u9879\uff09")
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


def _trunc(text: str, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"
