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
_SE = {"P0": "\u26a1", "P1": "\U0001f527", "P2": "\U0001f4a1", "INFO": "\U0001f4ac", "PASS": "\u2705"}
_SL = {"P0": "\u963b\u65ad", "P1": "\u5fc5\u6539", "P2": "\u5efa\u8bae", "INFO": "\u63d0\u9192", "PASS": "\u901a\u8fc7"}
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

    feat_issues = [i for i in issues if i.get("layer", "") == "WHAT"]
    ver_issues = [i for i in issues if i.get("layer", "") == "VERSION"]
    sup_issues = [i for i in issues
                  if i.get("layer", "") not in ("WHAT", "VERSION")]

    p0s = [i for i in issues if i.get("severity") == "P0"]
    p1s = [i for i in issues if i.get("severity") == "P1"]
    p2s = [i for i in issues if i.get("severity") == "P2"]

    lines: list[str] = []

    ft = f" \u00b7 {feature_title}" if feature_title else ""
    lines.append(f"# \u7248\u672c\u5185\u5bb9\u6392\u5e03\u9884\u5ba1{ft}")
    lines.append("")

    _version_summary(lines, pipeline_stage, ov, layer_overview,
                     len(p0s), len(p1s), len(p2s), len(reminders),
                     ver_issues, p0s)

    if ver_issues or sup_issues:
        all_ver = ver_issues + sup_issues
        _version_issue_table(lines, all_ver)

    all_feat = feat_issues + passed_features
    if all_feat:
        _feature_status_table(lines, all_feat)

    if p0s:
        lines.append(f"\u4ee5\u4e0b **{len(p0s)}** \u9879\u5fc5\u987b\u5728\u7248\u672c\u542f\u52a8\u524d\u89e3\u51b3\uff1a")
        lines.append("")
        _p0_cards(lines, p0s)

    if ver_issues or sup_issues:
        all_ver = ver_issues + sup_issues
        lines.append(f"## \U0001f3d7\ufe0f \u7248\u672c\u7ea7\u95ee\u9898\u8be6\u60c5\uff08{len(all_ver)} \u9879\uff09")
        lines.append("")
        for idx, issue in enumerate(all_ver, 1):
            _ver_issue_compact(lines, idx, issue)

    if feat_issues:
        lines.append(f"## \U0001f4e6 Feature \u95ee\u9898\u8be6\u60c5\uff08{len(feat_issues)} \u9879\uff09")
        lines.append("")
        lines.append(f"> \u4ee5\u4e0b\u4ec5\u5217\u51fa\u6709\u95ee\u9898\u7684 Feature\uff0c\u5df2\u901a\u8fc7\u7684\u4e0d\u5c55\u5f00\u3002")
        lines.append("")
        for idx, issue in enumerate(feat_issues, 1):
            _feat_issue_compact(lines, idx, issue)

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


def _version_summary(lines, stage, ov, overview, p0, p1, p2, reminder_count,
                     ver_issues, p0_issues):
    """Render the version summary section — exception-first approach."""
    complete_count = sum(1 for lo in overview if lo.get("completeness") == "complete")
    total_count = len(overview) or 1
    problem_dims = [lo for lo in overview if lo.get("completeness") != "complete"]

    lines.append("## \U0001f3af \u7248\u672c\u603b\u89c8")
    lines.append("")
    lines.append("| \u9879\u76ee | \u5185\u5bb9 |")
    lines.append("|------|------|")
    if stage:
        sl = {"planning": "\u89c4\u5212\u9636\u6bb5", "scoping": "\u51c6\u5907\u9636\u6bb5", "dor": "DoR \u95e8\u7981"}
        lines.append(f"| \u7ba1\u7ebf\u9636\u6bb5 | {sl.get(stage, stage)} |")

    if complete_count == total_count:
        health = f"\u2705 {complete_count}/{total_count} \u7ef4\u5ea6\u8fbe\u6807"
    else:
        dim_names = "\u3001".join(_trunc(d.get("layer", ""), 6) for d in problem_dims)
        health = f"{complete_count}/{total_count} \u7ef4\u5ea6\u8fbe\u6807 \u00b7 \u26a0\ufe0f {dim_names}\u9700\u5173\u6ce8"
    lines.append(f"| \u7ec4\u76d8\u5065\u5eb7\u5ea6 | {health} |")

    severity_parts = f"\u26a1{p0} \U0001f527{p1} \U0001f4a1{p2}"
    if reminder_count:
        severity_parts += f" \U0001f4ac{reminder_count}"
    lines.append(f"| \u9884\u5ba1\u7ed3\u679c | {_VE[ov]} **{_VL[ov]}** \u00b7 {severity_parts} |")
    lines.append("")

    action = _NEXT[ov]
    if p1 > 0:
        top_titles = "\u3001".join(
            _trunc(i.get("title", ""), 12)
            for i in (ver_issues or []) if i.get("severity") == "P1"
        )
        if top_titles:
            action += f"\uff0c\u4f18\u5148\u89e3\u51b3\uff1a{top_titles}"
    lines.append(f"> {_VE[ov]} {action}")
    lines.append("")

    if problem_dims:
        lines.append("### \u26a0\ufe0f \u9700\u5173\u6ce8\u7ef4\u5ea6")
        lines.append("")
        lines.append("| \u7ef4\u5ea6 | \u73b0\u72b6 | \u95ee\u9898 |")
        lines.append("|------|------|------|")
        for lo in problem_dims:
            dim = lo.get("layer", "")
            ratio = lo.get("ratio", "\u2014")
            gaps = _trunc(lo.get("key_gaps", "") or "\u2014", _MAX_DASH_GAP)
            lines.append(f"| {dim} | {ratio} | {gaps} |")
        lines.append("")


def _version_issue_table(lines, ver_issues):
    """Quick-scan table for version-level issues, placed before Feature table."""
    lines.append("## \U0001f3d7\ufe0f \u7248\u672c\u7ea7\u95ee\u9898\u901f\u67e5")
    lines.append("")
    lines.append("| # | \u95ee\u9898 | \u4e25\u91cd\u5ea6 | \u8981\u70b9 |")
    lines.append("|---|------|--------|------|")
    for idx, issue in enumerate(ver_issues, 1):
        title = _trunc(issue.get("title", ""), 20)
        sev = issue.get("severity", "P2")
        sev_label = f"{_SE.get(sev, '')} {_SL.get(sev, sev)}"
        gap = _trunc(issue.get("gap_description", ""), 30)
        lines.append(f"| {idx} | {title} | {sev_label} | {gap} |")
    lines.append("")


def _feature_status_table(lines, feat_issues):
    lines.append("## \U0001f4cb Feature \u72b6\u6001\u901f\u67e5")
    lines.append("")
    lines.append(
        "| # | Feature | WHAT \u72b6\u6001 | \u5ba1\u67e5\u7ed3\u679c | \u5907\u6ce8 |"
    )
    lines.append("|---|---------|------------|----------|------|")
    for idx, issue in enumerate(feat_issues, 1):
        title = issue.get("title", "")
        status = issue.get("extraction_status", "")
        icon = _STATUS_ICON.get(status, "\u26aa")
        sev = issue.get("severity", "P2")
        if sev == "PASS":
            sev_label = "\u2705 \u901a\u8fc7"
            short_gap = "\u2014"
        else:
            sev_label = f"{_SE.get(sev, '')} {_SL.get(sev, sev)}"
            gap = issue.get("gap_description", "")
            short_gap = _trunc(gap, _MAX_TABLE_GAP)
        lines.append(f"| {idx} | {title} | {icon} | {sev_label} | {short_gap} |")
    lines.append("")


def _ver_issue_compact(lines, idx, issue):
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
    if sev == "P2":
        combined = _merge_role_comments(comments)
        if combined:
            lines.append(f"{combined}")
        lines.append("")
    else:
        for rc in comments:
            persp = rc.get("perspective", "")
            comment = _trunc(rc.get("comment", ""), 120)
            lines.append(f"- **{persp}**\uff1a{comment}")
        if not comments:
            lines.append("*\u4ec5\u57fa\u4e8e\u6587\u6863\u63d0\u53d6\u7ed3\u679c\u3002*")
        lines.append("")


def _merge_role_comments(comments: list[dict]) -> str:
    """Merge multiple role comments into a single concise line for P2 issues."""
    if not comments:
        return ""
    parts = []
    for rc in comments:
        comment = rc.get("comment", "")
        if comment:
            parts.append(_trunc(comment, 80))
    if len(parts) == 1:
        return parts[0]
    return " / ".join(parts)


def _feat_issue_compact(lines, idx, issue):
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
        lines.append(f"  \u2014 {_trunc(gap, 80)}")
    if sev in ("P0", "P1"):
        for rc in comments:
            persp = rc.get("perspective", "")
            comment = _trunc(rc.get("comment", ""), 100)
            lines.append(f"  - **{persp}**\uff1a{comment}")
    lines.append("")


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
        detail = _trunc(gap or first_comment, 60)
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
