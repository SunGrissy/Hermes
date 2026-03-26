# -*- coding: utf-8 -*-
"""一次性批量：按 digest_config.pm_system_url 拉版本 → 专项 Markdown → Webhook 推送并 @ PM/PLD/PLE/PLT/PLQA。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, ".."))
_PM_BACKEND = os.path.join(_ROOT, "pm-system", "backend")
sys.path.insert(0, _PM_BACKEND)

import re

from app.services.pipeline_node_checklist_render import (
    SUPPRESSED_AUTO_CHECK_KEYS,
    _first_incomplete_main_stage_index,
    features_duck_from_pm_api,
    render_pipeline_node_checklists_markdown,
    version_duck_from_pm_api,
)
from app.services.release_checklist_render import PIPELINE_STAGES
from app.services.demand_pool_health import compute_demand_pool_health
from app.services.version_progress_notify import enrich_pipeline_for_version, render_version_status_markdown

_ACCEPTANCE_IDX = next(i for i, (sid, _) in enumerate(PIPELINE_STAGES) if sid == "acceptance")


class VersionProgressRenderError(Exception):
    """专项版本 Markdown 拼装失败（缺版本、dashboard 无数据等）。"""


def _strip_release_checklist_block(text: str) -> str:
    """从 suffix Markdown 中移除「发版检查」段落（含标题到下一个 --- 或末尾）。"""
    return re.sub(r"(?:---\s*\n\s*)?####\s*\*?\*?发版检查.*?(?=\n---|\Z)", "", text, flags=re.DOTALL).strip()


def _replace_pipeline_node_block_with_local(suffix: str, pipe_md: str) -> str:
    """用本机 pm-system 渲染的「管线节点待办」覆盖接口返回的同名块。

    接口 bundle 与 `build_version_checklist_markdown_bundle` 一致时，第一段为
    ``---\\n\\n#### **管线节点待办** ...``，其后接 ``\\n\\n---\\n\\n`` 发版检查等。
    若服务端未部署最新 `pipeline_node_checklist_render`，仍应与本机 dingtalk 依赖一致。
    """
    if not pipe_md or not suffix:
        return suffix
    pipe_md = pipe_md.strip()
    norm = suffix.replace("\r\n", "\n")
    # 非贪婪到「下一段」分隔符前，或整段仅为管线时到文末
    pat = r"(?ms)^---\s*\n\s*#### \*\*管线节点待办\*\*.*?(?=\n\n---\n\n|\Z)"
    repl = f"---\n\n{pipe_md}\n\n"
    out = re.sub(pat, repl, norm, count=1)
    if out != norm:
        return out
    pat2 = r"(?ms)#### \*\*管线节点待办\*\*.*?(?=\n\n---\n\n|\Z)"
    out = re.sub(pat2, repl, norm, count=1)
    if out != norm:
        return out
    return f"---\n\n{pipe_md}\n\n---\n\n{norm.strip()}"

DESKTOP_CFG = os.path.join(_DIR, "digest_config.json")


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


WEBHOOK_CFG = os.path.join(_DIR, "webhook_config.json")


def _load_default_progress_webhook() -> str:
    if not os.path.isfile(WEBHOOK_CFG):
        return ""
    try:
        with open(WEBHOOK_CFG, "r", encoding="utf-8") as f:
            j = json.load(f)
        return str(j.get("default") or "").strip()
    except (OSError, json.JSONDecodeError):
        return ""


def _explicit_planning_ddl(v: dict) -> date | None:
    """仅使用规划节点在 PM 里填写的 DDL（pipelineDdls.planning）。

    不再用 startDate-7 天推算：否则会把「规划 DDL 填在六月」的版本，在 startDate 较近时误判进 28 天窗口。
    """
    ddls = v.get("pipelineDdls") or v.get("pipeline_ddls") or {}
    if not isinstance(ddls, dict):
        return None
    raw = ddls.get("planning")
    if raw:
        return _parse_iso_date(raw)
    return None


def _version_eligible_for_scheduled_pipeline_reminder(v: dict) -> bool:
    """定时管线提醒：排除已发布版本、需求池、以及管线「发版」节点已完成的版本。"""
    ph = str(v.get("phase") or "").strip().lower()
    if ph == "released":
        return False
    vt = str(v.get("versionType") or v.get("version_type") or "").strip().lower()
    if vt == "demand_pool":
        return False
    ps = v.get("pipelineStatus") or v.get("pipeline_status") or {}
    if bool(ps.get("release")):
        return False
    return True


def _version_matches_scheduled_window(v: dict, today: date) -> bool:
    """规划节点 DDL：距今 <=28 天或已过期；且未发版（phase + 管线发版节点）。"""
    if not _version_eligible_for_scheduled_pipeline_reminder(v):
        return False
    d = _explicit_planning_ddl(v)
    if d is None:
        return False
    delta = (d - today).days
    return delta <= 28


def _scheduled_version_names(versions: list) -> list[str]:
    today = date.today()
    out: list[str] = []
    for v in versions or []:
        if not isinstance(v, dict):
            continue
        name = str(v.get("name") or "").strip()
        if not name:
            continue
        if _version_matches_scheduled_window(v, today):
            out.append(name)
    return sorted(set(out))


def _extract_data(payload: dict) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload or {}


class _RemoteVersionLike:
    def __init__(self, remote_version: dict):
        self.version_type = remote_version.get("versionType") or remote_version.get(
            "version_type"
        )
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
        self.plt_f_user_id = remote_version.get("pltFUserId")
        self.plt_b_user_id = remote_version.get("pltBUserId")
        if not self.plt_f_user_id and self.plt_user_id:
            self.plt_f_user_id = self.plt_user_id
        self.plqa_user_id = remote_version.get("plqaUserId") or remote_version.get(
            "plqa_user_id"
        )
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


def _pipeline_at_mobiles(cfg: dict, users: list, raw: dict) -> list[str]:
    pm_uid = str((cfg.get("default_pipeline_pm_user_id") or "")).strip()
    apm_uid = str((cfg.get("default_pipeline_apm_user_id") or "")).strip()
    plt_f = raw.get("pltFUserId") or raw.get("plt_user_id")
    plt_b = raw.get("pltBUserId") or raw.get("plt_b_user_id")
    if not plt_f and raw.get("pltUserId"):
        plt_f = raw.get("pltUserId")
    order = [
        pm_uid,
        apm_uid,
        raw.get("pldUserId"),
        raw.get("pleUserId"),
        plt_f,
        plt_b,
        raw.get("plqaUserId") or raw.get("plqa_user_id"),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for uid in order:
        if not uid:
            continue
        u = _user_by_id(users, str(uid))
        m = _dingtalk_mobile(u)
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _resolve_progress_webhooks(target: dict) -> list[str]:
    urls = target.get("progressNotifyWebhooks") or target.get("progress_notify_webhooks") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [str(u).strip() for u in urls if str(u).strip()]
    if not urls:
        dw = _load_default_progress_webhook()
        if dw:
            urls = [dw]
    return urls


def _build_entry_suffix(
    pm_url: str,
    api_key: str | None,
    version_name: str,
    *,
    force_pld_user_id: str | None = None,
    cfg: dict | None = None,
    data_all: dict | None = None,
    users: list | None = None,
) -> tuple[dict, str, str, dict]:
    pm_url = pm_url.rstrip("/")
    cfg = cfg or {}
    if data_all is None:
        data_all = _extract_data(_api_get_json(f"{pm_url}/api/data", api_key))
    if users is None:
        users = data_all.get("users") or []
    versions = data_all.get("versions") or []
    target = next((v for v in versions if str(v.get("name", "")) == version_name), None)
    if not target:
        raise VersionProgressRenderError(f"version {version_name!r} not found")

    if force_pld_user_id:
        target = {**target, "pldUserId": force_pld_user_id}

    vid = str(target.get("id") or "").strip()
    if not vid:
        raise VersionProgressRenderError(f"version {version_name} missing id")

    dashboard = _extract_data(_api_get_json(f"{pm_url}/api/dashboard?version_id={vid}", api_key))
    active = dashboard.get("activeVersions") or []
    if not active:
        raise VersionProgressRenderError(f"dashboard has no active version for id={vid}")
    entry = active[0]
    vt = str(target.get("versionType") or target.get("version_type") or "").strip()
    entry["versionType"] = vt
    pm_uid = str((cfg.get("default_pipeline_pm_user_id") or "")).strip()
    pld_id_eff = force_pld_user_id or target.get("pldUserId") or ""
    entry["_pld_name"] = (_user_by_id(users, str(pld_id_eff)) or {}).get("name") or ""
    entry["_pm_name"] = (_user_by_id(users, pm_uid) or {}).get("name") or ""
    entry["startDate"] = target.get("startDate")
    entry["nodeManualChecks"] = (
        target.get("nodeManualChecks") or target.get("node_manual_checks") or {}
    )
    _enrich_feature_summary(entry, target.get("features") or [])
    rvl = _RemoteVersionLike(target)
    enrich_pipeline_for_version(entry, rvl)

    suffix = ""
    if vt == "demand_pool":
        fs = entry.get("featureSummary") if isinstance(entry.get("featureSummary"), dict) else {}
        if not isinstance(fs.get("poolHealth"), dict):
            fs = dict(fs) if isinstance(fs, dict) else {}
            fs["poolHealth"] = compute_demand_pool_health(target.get("features") or [])
            entry["featureSummary"] = fs
    else:
        try:
            blocks = _extract_data(
                _api_get_json(
                    f"{pm_url}/api/internal/version-checklist-blocks?version_ids={vid}",
                    api_key,
                )
            )
            suffix = (blocks.get("blocks") or {}).get(vid) or ""
        except Exception as e:
            print(f"WARN: checklist blocks: {e}", flush=True)

        pipe_md = None
        try:
            v_duck = version_duck_from_pm_api(target)
            feats = features_duck_from_pm_api(target.get("features") or [])
            pipe_md = render_pipeline_node_checklists_markdown(
                None,
                v_duck,
                features_override=feats,
                suppress_auto_keys=set(SUPPRESSED_AUTO_CHECK_KEYS),
            )
        except Exception as e:
            print(f"WARN: local pipeline checklist: {e}", flush=True)

        if pipe_md:
            if suffix and "管线节点待办" in suffix:
                suffix = _replace_pipeline_node_block_with_local(suffix, pipe_md)
            elif suffix:
                suffix = f"---\n\n{pipe_md}\n\n---\n\n{suffix.strip()}"
            else:
                suffix = f"---\n\n{pipe_md}"

        ps = target.get("pipelineStatus") or target.get("pipeline_status") or {}
        fi = _first_incomplete_main_stage_index(ps)
        if fi is not None and fi < _ACCEPTANCE_IDX and suffix:
            suffix = _strip_release_checklist_block(suffix)

    return entry, suffix.strip(), vid, target


def render_multi_version_digest_markdown(
    pm_url: str,
    api_key: str | None,
    version_names: list[str],
    cfg: dict,
    *,
    log_to_stdout: bool = True,
) -> tuple[str, list[str], int]:
    """与定时管线推送同源：多版本合并为一条 Markdown；@ 人为各版本管线角色手机号去重并集。"""
    pm_url = pm_url.rstrip("/")
    data_all = _extract_data(_api_get_json(f"{pm_url}/api/data", api_key))
    users = data_all.get("users") or []
    entries: list = []
    sfx_by_id: dict[str, str] = {}
    at_out: list[str] = []
    seen_m: set[str] = set()
    for vname in version_names:
        vn = str(vname or "").strip()
        if not vn:
            continue
        try:
            entry, suffix, vid, target = _build_entry_suffix(
                pm_url,
                api_key,
                vn,
                force_pld_user_id=None,
                cfg=cfg,
                data_all=data_all,
                users=users,
            )
        except VersionProgressRenderError as e:
            if log_to_stdout:
                print(f"[version-digest-body] skip {vn}: {e}", flush=True)
            continue
        entries.append(entry)
        if suffix:
            sfx_by_id[vid] = suffix
        for m in _pipeline_at_mobiles(cfg, users, target):
            if m not in seen_m:
                seen_m.add(m)
                at_out.append(m)
    if not entries:
        return "", [], 0
    md = render_version_status_markdown(
        entries,
        checklist_suffix_by_id=sfx_by_id if sfx_by_id else None,
    )
    return md, at_out, len(entries)


def _render_one(
    pm_url: str,
    api_key: str | None,
    version_name: str,
    *,
    force_pld_user_id: str | None = None,
    cfg: dict | None = None,
    data_all: dict | None = None,
    users: list | None = None,
) -> tuple[str, str, list[str]]:
    try:
        entry, suffix, vid, target = _build_entry_suffix(
            pm_url,
            api_key,
            version_name,
            force_pld_user_id=force_pld_user_id,
            cfg=cfg,
            data_all=data_all,
            users=users,
        )
    except VersionProgressRenderError as e:
        raise SystemExit(f"ERROR: {e}") from e
    urls = _resolve_progress_webhooks(target)
    if not urls:
        raise SystemExit(
            f"ERROR: version {version_name} has empty progressNotifyWebhooks "
            "and webhook_config.json default is empty"
        )
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
    skip_demand_pool_in_batch: bool = False,
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

    for vname, force_pld in jobs:
        print(f"=== {vname} ===", flush=True)
        raw = next(
            (v for v in (data_all.get("versions") or []) if str(v.get("name", "")) == vname),
            {},
        )
        if skip_demand_pool_in_batch and str(
            raw.get("versionType") or raw.get("version_type") or ""
        ).strip() == "demand_pool":
            print(f"SKIP: {vname} 为需求池类型，默认批次不推送", flush=True)
            report_lines.append(f"- **{vname}** 跳过（需求池不在默认推送列表）")
            continue
        pld_id = force_pld or raw.get("pldUserId") or ""
        pl_name = (_user_by_id(users, str(pld_id)) or {}).get("name") if pld_id else ""

        vid, md, urls = _render_one(
            pm_url,
            api_key,
            vname,
            force_pld_user_id=force_pld,
            cfg=cfg,
            data_all=data_all,
            users=users,
        )

        at_list = _pipeline_at_mobiles(cfg, users, raw if not force_pld else {**raw, "pldUserId": force_pld})
        print(
            f"pld={pl_name or '?'} id={pld_id} at={len(at_list)} webhooks={len(urls)}",
            flush=True,
        )
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
        "--auto-scheduled",
        action="store_true",
        help="按规划节点窗口筛选：仅用 pipelineDdls.planning；距今<=28天或已过期；排除 phase=released、管线发版已完成、demand_pool；Webhook 空则用 default",
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
    ov = (args.pm_url or "").strip() or None
    if args.auto_scheduled:
        with open(DESKTOP_CFG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        pm_url = (
            ov
            or (cfg.get("pm_system_url") or "").strip()
            or (os.environ.get("PM_SYSTEM_URL") or "").strip()
            or "http://172.16.3.197:8000"
        ).rstrip("/")
        api_key = (cfg.get("pm_system_api_key") or "").strip() or None
        data_all = _extract_data(_api_get_json(f"{pm_url}/api/data", api_key))
        names = _scheduled_version_names(data_all.get("versions") or [])
        if not names:
            print(
                "AUTO_SCHEDULED: no versions match (explicit planning DDL within 28d or overdue, not released)",
                flush=True,
            )
            raise SystemExit(0)
        jobs = [(n, None) for n in names]
        heading = f"猫姐嘴替 · 定时管线提醒 ({','.join(names)})"
        run_version_progress_push(
            jobs,
            summary_heading=heading,
            report_filename=args.report or "_pipeline_scheduled_report.md",
            pm_url_override=ov,
        )
        return
    if (args.only or "").strip():
        jobs = [(n.strip(), None) for n in args.only.split(",") if n.strip()]
        heading = f"猫姐嘴替 · 专项推送 ({args.only.strip()})"
        skip_pool = False
    else:
        jobs = _default_jobs()
        heading = "猫姐嘴替 · 五一/五月中/0401 已执行"
        skip_pool = True
    ov = (args.pm_url or "").strip() or None
    run_version_progress_push(
        jobs,
        summary_heading=heading,
        report_filename=args.report,
        pm_url_override=ov,
        skip_demand_pool_in_batch=skip_pool,
    )


if __name__ == "__main__":
    main()
