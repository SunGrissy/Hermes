# -*- coding: utf-8 -*-
"""一次性批量：按 digest_config.pm_system_url 拉版本 → 专项 Markdown → 各版本 progressNotifyWebhooks 推送并 @ PLD+PM。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, ".."))
_PM_BACKEND = os.path.join(_ROOT, "pm-system", "backend")
sys.path.insert(0, _PM_BACKEND)
os.chdir(_PM_BACKEND)

import re

from app.services.pipeline_node_checklist_render import (
    SUPPRESSED_AUTO_CHECK_KEYS,
    _first_incomplete_main_stage_index,
    features_duck_from_pm_api,
    render_pipeline_node_checklists_markdown,
    version_duck_from_pm_api,
)
from app.services.release_checklist_render import PIPELINE_STAGES
from app.services.version_progress_notify import enrich_pipeline_for_version, render_version_status_markdown

_ACCEPTANCE_IDX = next(i for i, (sid, _) in enumerate(PIPELINE_STAGES) if sid == "acceptance")


def _strip_release_checklist_block(text: str) -> str:
    """从 suffix Markdown 中移除「发版检查」段落（含标题到下一个 --- 或末尾）。"""
    return re.sub(r"(?:---\s*\n\s*)?####\s*\*?\*?发版检查.*?(?=\n---|\Z)", "", text, flags=re.DOTALL).strip()

DESKTOP_CFG = os.path.join(_DIR, "digest_config.json")


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_data(payload: dict) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload or {}


class _RemoteVersionLike:
    def __init__(self, remote_version: dict):
        self.pipeline_ddls = (
            remote_version.get("pipelineDDLs")
            or remote_version.get("pipelineDdls")
            or remote_version.get("pipeline_ddls")
            or {}
        )
        self.pipeline_status = (
            remote_version.get("pipelineStatus")
            or remote_version.get("pipeline_status")
            or {}
        )
        self.pld_user_id = remote_version.get("pldUserId")
        self.ple_user_id = remote_version.get("pleUserId")
        self.plt_user_id = remote_version.get("pltUserId")
        self.start_date = _parse_iso_date(remote_version.get("startDate"))
        self.release_date = _parse_iso_date(remote_version.get("releaseDate"))


def _api_get_json(url: str, api_key: str | None) -> dict:
    headers = {}
    if api_key:
        headers["X-Api-Key"] = api_key
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_dor_ready_dict(feat: dict) -> bool:
    r = feat.get("readiness")
    if isinstance(r, dict) and r:
        return bool(r.get("spec")) and bool(r.get("tech")) and bool(r.get("art"))
    st = feat.get("status")
    status_l = (
        str(st).strip().lower()
        if st is not None and str(st).strip() != ""
        else "draft"
    )
    stage_raw = feat.get("stage")
    stage_l = str(stage_raw).strip().lower() if isinstance(stage_raw, str) else ""
    return status_l != "draft" or stage_l in ("done", "qa")


def _missing_dims_dict(feat: dict) -> tuple[bool, bool, bool]:
    r = feat.get("readiness")
    if isinstance(r, dict) and r:
        return (
            not bool(r.get("spec")),
            not bool(r.get("tech")),
            not bool(r.get("art")),
        )
    return (True, True, True)


def _dor_not_ready_from_dicts(feats: list) -> list:
    out = []
    for d in feats:
        if not isinstance(d, dict):
            continue
        if _is_dor_ready_dict(d):
            continue
        miss = []
        r = d.get("readiness")
        if isinstance(r, dict) and r:
            for k in ("spec", "tech", "art"):
                if not bool(r.get(k)):
                    miss.append(k)
        else:
            miss = ["spec", "tech", "art"]
        out.append({"name": str(d.get("name") or "?").strip(), "missing": miss})
        if len(out) >= 5:
            break
    return out


def _blocked_details_from_dicts(feats: list) -> list:
    out = []
    for d in feats:
        if not isinstance(d, dict):
            continue
        ib = d.get("isBlocked") or d.get("is_blocked")
        st = str(d.get("status") or "").strip()
        sg = str(d.get("stage") or "").strip()
        if ib or sg == "blocked" or st == "blocked":
            out.append(
                {
                    "name": str(d.get("name") or "?").strip(),
                    "reason": str(
                        d.get("blockedReason") or d.get("blocked_reason") or ""
                    ).strip(),
                }
            )
        if len(out) >= 5:
            break
    return out


def _enrich_feature_summary(entry: dict, raw_features: list) -> None:
    """补齐 featureSummary（远端 dashboard 缺字段时从 /api/data 的 features 推算）。"""
    fs = entry.get("featureSummary")
    if not isinstance(fs, dict):
        fs = {}
        entry["featureSummary"] = fs
    feats = [f for f in (raw_features or []) if isinstance(f, dict)]

    if fs.get("dorReady") is None:
        dor_ready = sum(1 for f in feats if _is_dor_ready_dict(f))
        miss_spec = miss_tech = miss_art = 0
        for f in feats:
            if _is_dor_ready_dict(f):
                continue
            ms, mt, ma = _missing_dims_dict(f)
            if ms:
                miss_spec += 1
            if mt:
                miss_tech += 1
            if ma:
                miss_art += 1
        status_keys = ("draft", "ready", "in_progress", "testing", "done")
        status_breakdown = {k: 0 for k in status_keys}
        for f in feats:
            st = f.get("status")
            key = (
                str(st).strip().lower()
                if st is not None and str(st).strip() != ""
                else "draft"
            )
            if key not in status_breakdown:
                key = "draft"
            status_breakdown[key] += 1
        fs["dorReady"] = dor_ready
        fs["dorMissing"] = {"spec": miss_spec, "tech": miss_tech, "art": miss_art}
        fs["statusBreakdown"] = status_breakdown

    if not fs.get("dorNotReadyFeatures"):
        fs["dorNotReadyFeatures"] = _dor_not_ready_from_dicts(feats)
    if fs.get("unassignedCount") is None:
        fs["unassignedCount"] = sum(
            1 for f in feats if not str(f.get("assignee") or "").strip()
        )
    if not fs.get("blockedDetails"):
        fs["blockedDetails"] = _blocked_details_from_dicts(feats)


def _render_one(
    pm_url: str,
    api_key: str | None,
    version_name: str,
    *,
    force_pld_user_id: str | None = None,
    pld_name: str = "",
    pm_name: str = "",
) -> tuple[str, str, list[str]]:
    pm_url = pm_url.rstrip("/")
    data_all = _extract_data(_api_get_json(f"{pm_url}/api/data", api_key))
    versions = data_all.get("versions") or []
    target = next((v for v in versions if str(v.get("name", "")) == version_name), None)
    if not target:
        raise SystemExit(f"ERROR: version {version_name!r} not found")

    if force_pld_user_id:
        target = {**target, "pldUserId": force_pld_user_id}

    vid = str(target.get("id") or "").strip()
    if not vid:
        raise SystemExit(f"ERROR: version {version_name} missing id")

    urls = target.get("progressNotifyWebhooks") or target.get("progress_notify_webhooks") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [str(u).strip() for u in urls if str(u).strip()]
    if not urls:
        raise SystemExit(f"ERROR: version {version_name} has empty progressNotifyWebhooks")

    dashboard = _extract_data(_api_get_json(f"{pm_url}/api/dashboard?version_id={vid}", api_key))
    active = dashboard.get("activeVersions") or []
    if not active:
        raise SystemExit(f"ERROR: dashboard has no active version for id={vid}")
    entry = active[0]
    entry["startDate"] = target.get("startDate")
    entry["nodeManualChecks"] = (
        target.get("nodeManualChecks") or target.get("node_manual_checks") or {}
    )
    _enrich_feature_summary(entry, target.get("features") or [])
    rvl = _RemoteVersionLike(target)
    enrich_pipeline_for_version(entry, rvl)
    entry["_pld_name"] = pld_name
    entry["_pm_name"] = pm_name

    suffix = ""
    try:
        blocks = _extract_data(
            _api_get_json(f"{pm_url}/api/internal/version-checklist-blocks?version_ids={vid}", api_key)
        )
        suffix = (blocks.get("blocks") or {}).get(vid) or ""
    except Exception as e:
        print(f"WARN: checklist blocks: {e}", flush=True)

    if suffix and "管线节点待办" not in suffix:
        try:
            v_duck = version_duck_from_pm_api(target)
            feats = features_duck_from_pm_api(target.get("features") or [])
            pipe_md = render_pipeline_node_checklists_markdown(
                None,
                v_duck,
                features_override=feats,
                suppress_auto_keys=set(SUPPRESSED_AUTO_CHECK_KEYS),
            )
            if pipe_md:
                suffix = f"---\n\n{pipe_md}\n\n---\n\n{suffix.strip()}"
        except Exception as e:
            print(f"WARN: merge pipeline checklist: {e}", flush=True)
    elif not suffix:
        try:
            v_duck = version_duck_from_pm_api(target)
            feats = features_duck_from_pm_api(target.get("features") or [])
            pipe_md = render_pipeline_node_checklists_markdown(
                None,
                v_duck,
                features_override=feats,
                suppress_auto_keys=set(SUPPRESSED_AUTO_CHECK_KEYS),
            )
            if pipe_md:
                suffix = f"---\n\n{pipe_md}"
        except Exception as e:
            print(f"WARN: local pipeline checklist: {e}", flush=True)

    ps = target.get("pipelineStatus") or target.get("pipeline_status") or {}
    fi = _first_incomplete_main_stage_index(ps)
    if fi is not None and fi < _ACCEPTANCE_IDX and suffix:
        suffix = _strip_release_checklist_block(suffix)

    sfx_map = {vid: suffix} if suffix else None
    md = render_version_status_markdown([entry], checklist_suffix_by_id=sfx_map)
    return vid, md, urls


def _user_by_id(users: list, uid: str) -> dict | None:
    for u in users:
        if str(u.get("id") or "") == str(uid):
            return u
    return None


def _dingtalk_mobile(u: dict | None) -> str:
    if not u:
        return ""
    ext = u.get("externalIds") or u.get("external_ids") or {}
    if not isinstance(ext, dict):
        ext = {}
    return (str(ext.get("dingtalk_mobile") or "").strip()) or (str(u.get("phone") or "").strip())


def _send_webhook_markdown(text: str, webhook_url: str, at_mobiles: list[str]) -> bool:
    body_text = text.rstrip()
    if at_mobiles:
        body_text += "\n\n" + " ".join(f"@{m}" for m in at_mobiles)
    payload: dict = {
        "msgtype": "markdown",
        "markdown": {
            "title": "小秘书提醒 · 版本状态",
            "text": body_text,
        },
    }
    if at_mobiles:
        payload["at"] = {"atMobiles": list(at_mobiles), "isAtAll": False}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    return r.get("errcode") == 0


def _default_jobs() -> list[tuple[str, str | None]]:
    return [
        ("五一版", None),
        ("五月中", "u062"),
        ("0401", None),
    ]


def run_version_progress_push(
    jobs: list[tuple[str, str | None]],
    *,
    summary_heading: str = "猫姐嘴替 · 版本状态推送",
    report_filename: str = "_version_push_report.md",
    pm_url_override: str | None = None,
) -> None:
    with open(DESKTOP_CFG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    pm_url = (
        (pm_url_override or "").strip()
        or (cfg.get("pm_system_url") or "").strip()
        or (os.environ.get("PM_SYSTEM_URL") or "").strip()
        or "http://172.16.3.197:8000"
    ).rstrip("/")
    api_key = (cfg.get("pm_system_api_key") or "").strip() or None

    data_all = _extract_data(_api_get_json(f"{pm_url}/api/data", api_key))
    users = data_all.get("users") or []
    report_lines: list[str] = []

    pm_uid = (cfg.get("default_pipeline_pm_user_id") or "").strip()
    pm_user = _user_by_id(users, pm_uid) if pm_uid else None
    pm_mobile = _dingtalk_mobile(pm_user)
    pm_name_resolved = (pm_user or {}).get("name") or pm_uid or ""

    for vname, force_pld in jobs:
        print(f"=== {vname} ===", flush=True)
        raw = next(
            (v for v in (data_all.get("versions") or []) if str(v.get("name", "")) == vname),
            {},
        )
        pld_id = force_pld or raw.get("pldUserId") or ""
        pl_user = _user_by_id(users, str(pld_id)) if pld_id else None
        mobile = _dingtalk_mobile(pl_user)
        pl_name = (pl_user or {}).get("name") or pld_id or ""

        vid, md, urls = _render_one(
            pm_url,
            api_key,
            vname,
            force_pld_user_id=force_pld,
            pld_name=pl_name,
            pm_name=pm_name_resolved,
        )

        print(
            f"pld={pl_name or '?'} id={pld_id} mobile={mobile!r} "
            f"pm={pm_name_resolved or '?'} pm_mobile={pm_mobile!r} webhooks={len(urls)}",
            flush=True,
        )

        at_list: list[str] = []
        if mobile:
            at_list.append(mobile)
        if pm_mobile and pm_mobile not in at_list:
            at_list.append(pm_mobile)
        ok_wh = True
        for i, wh in enumerate(urls, 1):
            try:
                ok = _send_webhook_markdown(md, wh, at_list)
            except Exception as e:
                ok = False
                print(f"  webhook#{i} EXCEPTION {e}", flush=True)
            else:
                print(f"  webhook#{i} {'OK' if ok else 'FAIL'}", flush=True)
            ok_wh = ok_wh and ok

        report_lines.append(
            f"- **{vname}** PLD {pl_name or '?'}: 群推送={'OK' if ok_wh else 'FAIL'}"
        )

    summary = f"## {summary_heading}\n\n" + "\n".join(report_lines)
    summary += f"\n\n数据源: `{pm_url}`（基址：--pm-url > digest_config.pm_system_url > PM_SYSTEM_URL > 172 兜底）"
    out_path = os.path.join(_DIR, "logs", report_filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(summary, flush=True)
    print(f"Wrote {out_path}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="专项版本状态 Webhook 推送（与 _send_0401_remote 同一套渲染）")
    ap.add_argument(
        "--only",
        default="",
        help="仅推送指定版本名，逗号分隔（无此项时推送默认列表：五一版、五月中、0401）",
    )
    ap.add_argument(
        "--report",
        default="_version_push_report.md",
        help="写入 logs/ 下的报告文件名",
    )
    ap.add_argument(
        "--pm-url",
        default="",
        help="覆盖本次运行的 PM API 基址（否则：digest_config.pm_system_url > PM_SYSTEM_URL > 172 兜底）",
    )
    args = ap.parse_args()
    if (args.only or "").strip():
        jobs = [(n.strip(), None) for n in args.only.split(",") if n.strip()]
        heading = f"猫姐嘴替 · 专项推送 ({args.only.strip()})"
    else:
        jobs = _default_jobs()
        heading = "猫姐嘴替 · 五一/五月中/0401 已执行"
    ov = (args.pm_url or "").strip() or None
    run_version_progress_push(
        jobs,
        summary_heading=heading,
        report_filename=args.report,
        pm_url_override=ov,
    )


if __name__ == "__main__":
    main()
