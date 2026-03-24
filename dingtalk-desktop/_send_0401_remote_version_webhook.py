# -*- coding: utf-8 -*-
"""从远端 PM（如 192）取版本数据，渲染专项「版本状态」Markdown 并推送到指定 Webhook。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PM_BACKEND = os.path.join(_ROOT, "pm-system", "backend")
sys.path.insert(0, _PM_BACKEND)
os.chdir(_PM_BACKEND)

from app.services.pipeline_node_checklist_render import (
    features_duck_from_pm_api,
    render_pipeline_node_checklists_markdown,
    version_duck_from_pm_api,
)
from app.services.version_progress_notify import enrich_pipeline_for_version, render_version_status_markdown

# 互斥：防止计划任务/多实例叠跑
_RUNNING_LOCK = os.path.join(_ROOT, "dingtalk-desktop", ".send_0401_remote.running")
# 冷却：上次成功推送后 N 秒内不再发（计划任务误配成每分钟时不会刷屏）
_COOLDOWN_FILE = os.path.join(_ROOT, "dingtalk-desktop", ".send_0401_remote.last_ok")
_DEFAULT_COOLDOWN_SEC = 3600


def _load_cfg() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "digest_config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _api_get_json(url: str, api_key: str | None) -> dict:
    headers = {}
    if api_key:
        headers["X-Api-Key"] = api_key
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


@contextmanager
def _running_exclusive():
    """本机单实例互斥；异常退出时由 finally 删除 .running。"""
    try:
        fd = os.open(_RUNNING_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        try:
            age = time.time() - os.path.getmtime(_RUNNING_LOCK)
            if age > 600:
                os.remove(_RUNNING_LOCK)
                fd = os.open(_RUNNING_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
            else:
                print("SKIP: another instance is running", flush=True)
                raise SystemExit(0)
        except FileExistsError:
            print("SKIP: another instance is running", flush=True)
            raise SystemExit(0)
        except OSError:
            print("SKIP: another instance is running", flush=True)
            raise SystemExit(0)
    try:
        yield
    finally:
        try:
            if os.path.isfile(_RUNNING_LOCK):
                os.remove(_RUNNING_LOCK)
        except OSError:
            pass


def _cooldown_remaining(force: bool) -> int:
    if force:
        return 0
    if not os.path.isfile(_COOLDOWN_FILE):
        return 0
    try:
        last = int(open(_COOLDOWN_FILE, "r", encoding="utf-8").read().strip() or "0")
    except Exception:
        return 0
    elapsed = int(time.time()) - last
    if elapsed < _DEFAULT_COOLDOWN_SEC:
        return _DEFAULT_COOLDOWN_SEC - elapsed
    return 0


def _mark_send_ok() -> None:
    try:
        with open(_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def _extract_data(payload: dict) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload or {}


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class _RemoteVersionLike:
    """enrich_pipeline_for_version 所需字段，来自 /api/data 中该版本 JSON。"""

    def __init__(self, remote_version: dict):
        self.pipeline_ddls = (
            remote_version.get("pipelineDDLs")
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


def _assistant_notify_webhook(desktop_cfg: dict) -> str:
    u = (desktop_cfg.get("webhook_url") or "").strip()
    if u:
        return u
    wc_path = os.path.join(os.path.dirname(__file__), "webhook_config.json")
    if os.path.isfile(wc_path):
        with open(wc_path, "r", encoding="utf-8") as f:
            wc = json.load(f)
        u = (wc.get("default") or "").strip()
    return u


def _render_remote_style(pm_url: str, api_key: str | None, version_name: str) -> tuple[str, str, list[str]]:
    data_all = _extract_data(_api_get_json(f"{pm_url}/api/data", api_key))
    versions = data_all.get("versions") or []
    target = next((v for v in versions if str(v.get("name", "")) == version_name), None)
    if not target:
        raise SystemExit(f"ERROR: version {version_name} not found in {pm_url}/api/data")

    vid = str(target.get("id") or "").strip()
    if not vid:
        raise SystemExit(f"ERROR: version {version_name} missing id")

    urls = target.get("progressNotifyWebhooks") or target.get("progress_notify_webhooks") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [str(u).strip() for u in urls if str(u).strip()]

    dashboard = _extract_data(_api_get_json(f"{pm_url}/api/dashboard?version_id={vid}", api_key))
    active = dashboard.get("activeVersions") or []
    if not active:
        raise SystemExit(f"ERROR: dashboard has no active version for id={vid}")
    entry = active[0]
    entry["startDate"] = target.get("startDate")
    enrich_pipeline_for_version(entry, _RemoteVersionLike(target))

    suffix = ""
    try:
        blocks = _extract_data(
            _api_get_json(f"{pm_url}/api/internal/version-checklist-blocks?version_ids={vid}", api_key)
        )
        suffix = (blocks.get("blocks") or {}).get(vid) or ""
    except Exception as e:
        print(f"WARN: fetch checklist blocks failed: {e}", flush=True)

    # 远端 checklist 块常缺「管线节点待办」（192 未部署 pipeline_node_tasks.json 等），用本机 tasks + 192 的 version/features 补全图1样式
    if suffix and "管线节点待办" not in suffix:
        try:
            v_duck = version_duck_from_pm_api(target)
            feats = features_duck_from_pm_api(target.get("features") or [])
            pipe_md = render_pipeline_node_checklists_markdown(
                None, v_duck, features_override=feats
            )
            if pipe_md:
                suffix = f"---\n\n{pipe_md}\n\n---\n\n{suffix.strip()}"
        except Exception as e:
            print(f"WARN: merge local pipeline checklist failed: {e}", flush=True)
    elif not suffix:
        try:
            v_duck = version_duck_from_pm_api(target)
            feats = features_duck_from_pm_api(target.get("features") or [])
            pipe_md = render_pipeline_node_checklists_markdown(
                None, v_duck, features_override=feats
            )
            if pipe_md:
                suffix = f"---\n\n{pipe_md}"
        except Exception as e:
            print(f"WARN: local pipeline checklist only failed: {e}", flush=True)

    sfx_map = {vid: suffix} if suffix else None
    md = render_version_status_markdown([entry], checklist_suffix_by_id=sfx_map)
    return vid, md, urls


def _send_markdown(text: str, webhook_url: str) -> bool:
    body = json.dumps(
        {
            "msgtype": "markdown",
            "markdown": {
                "title": "小秘书提醒 · 版本状态",
                "text": text,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    return r.get("errcode") == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version-name", default="0401")
    ap.add_argument("--webhook", default="", help="仅发送到指定 webhook（覆盖版本配置与其它目标）")
    ap.add_argument(
        "--assistant-notify",
        action="store_true",
        help="发到 digest_config.webhook_url（🐱助理通知群，与 notify_target 配套）",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help="忽略冷却（仍受单实例互斥保护）；用于手工复验",
    )
    args = ap.parse_args()

    wait = _cooldown_remaining(args.force)
    if wait > 0:
        print(f"SKIP: cooldown active, next allowed in ~{wait}s (use --force to override)", flush=True)
        raise SystemExit(0)

    with _running_exclusive():
        cfg = _load_cfg()
        pm_url = (cfg.get("pm_system_url") or "").rstrip("/")
        api_key = cfg.get("pm_system_api_key") or None
        if not pm_url:
            print("ERROR: digest_config.pm_system_url empty", flush=True)
            raise SystemExit(2)

        vid, digest, urls = _render_remote_style(pm_url, api_key, args.version_name)
        if args.webhook.strip():
            urls = [args.webhook.strip()]
        elif args.assistant_notify:
            aw = _assistant_notify_webhook(cfg)
            if not aw:
                print("ERROR: assistant notify webhook empty (digest_config.webhook_url / webhook default)", flush=True)
                raise SystemExit(5)
            urls = [aw]
            print("target=assistant_notify (digest webhook_url / default)", flush=True)
        if not urls:
            print(f"ERROR: version {args.version_name} has empty progressNotifyWebhooks", flush=True)
            print("hint: use --assistant-notify or --webhook <url>", flush=True)
            raise SystemExit(4)
        print(f"version={args.version_name} id={vid} webhook_count={len(urls)}", flush=True)
        if args.dry_run:
            print("DRY_RUN_ONLY", flush=True)
            return

        ok = 0
        for i, u in enumerate(urls, 1):
            try:
                sent = _send_markdown(digest, u)
            except Exception as e:
                sent = False
                print(f"webhook#{i}: EXCEPTION {e}", flush=True)
            else:
                print(f"webhook#{i}: {'OK' if sent else 'FAIL'}", flush=True)
            if sent:
                ok += 1
        if ok != len(urls):
            raise SystemExit(6)
        _mark_send_ok()
        print(f"DONE sent {ok}/{len(urls)}", flush=True)


if __name__ == "__main__":
    main()
