"""Palace report renderer v0.4 — dumb renderer, no analysis.

Receives structured REPORT_DATA from synthesize_v2 and renders Markdown.
All intelligence lives in LLM prompts and synthesis logic, not here.
"""

from datetime import datetime

_VE = {"block": "\U0001f534", "concern": "\U0001f7e1", "pass": "\U0001f7e2", "error": "\u26aa"}
_VL = {"block": "\u672a\u8fbe\u6807", "concern": "\u6709\u98ce\u9669", "pass": "\u8fbe\u6807", "error": "\u5f02\u5e38"}
_NEXT = {
    "block": "\u9700\u4fee\u6539\u540e\u91cd\u65b0\u63d0\u5ba1",
    "concern": "\u53ef\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5\uff0c\u9700\u5173\u6ce8\u98ce\u9669\u9879",
    "pass": "\u53ef\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5",
    "error": "\u5ba1\u67e5\u5f02\u5e38",
}
_SE = {"P0": "\u26a1", "P1": "\U0001f527", "P2": "\U0001f4a1"}
_SL = {"P0": "\u963b\u65ad", "P1": "\u5fc5\u6539", "P2": "\u5efa\u8bae"}
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
# Section renderers
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
    p2_count = sum(1 for i in issues if i.get("severity") == "P2")
    if p0_count:
        lines.append(f"- \u26a1 **{p0_count}** \u9879\u963b\u65ad\uff08\u5fc5\u987b\u89e3\u51b3\uff09")
    if p1_count:
        lines.append(f"- \U0001f527 **{p1_count}** \u9879\u5fc5\u6539\uff08\u91cd\u8981\u4f46\u4e0d\u963b\u65ad\uff09")
    if p2_count:
        lines.append(f"- \U0001f4a1 **{p2_count}** \u9879\u5efa\u8bae\uff08\u53ef\u540e\u7eed\u8ddf\u8fdb\uff09")
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
