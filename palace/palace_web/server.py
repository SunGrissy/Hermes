"""Palace Web — 报告批注系统 v0.2

FastAPI 服务：报告展示 + 批注持久化 + 钉钉通知。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

APP_VERSION = "0.2.0"
_server_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
ANNOTATIONS_DIR = DATA_DIR / "annotations"
STATIC_DIR = PROJECT_ROOT / "static"

for d in (REPORTS_DIR, ANNOTATIONS_DIR):
    d.mkdir(parents=True, exist_ok=True)

_KEY_FILES = [
    "palace_web/server.py",
    "palace_web/static/index.html",
    "palace_web/static/report.html",
    "palace_web/static/styles.css",
    "palace_web/static/app.js",
    "palace_web/import_report.py",
]

PALACE_ROOT = PROJECT_ROOT.parent

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ReportUpload(BaseModel):
    """CLI or external tool uploads a report JSON."""
    title: str
    scenario_id: str = ""
    feature_title: str = ""
    pipeline_weight: str = ""
    pipeline_stage: str = ""
    document_layer: str = ""
    data: dict  # raw REPORT_DATA from engine


class AnnotationUpdate(BaseModel):
    mark: str  # adopt / discuss / known / na
    comment: str = ""
    annotator_role: str = ""
    annotator_name: str = ""


class SubmitRequest(BaseModel):
    annotator_role: str = ""
    annotator_name: str = ""
    dingtalk_webhook: str = ""


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Palace Annotation System", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Health / Version
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "palace-web", "version": APP_VERSION}


@app.get("/api/version")
def version():
    files = {}
    latest = 0.0
    for f in _KEY_FILES:
        try:
            fpath = PALACE_ROOT / f
            mtime = os.path.getmtime(fpath)
            files[f] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            latest = max(latest, mtime)
        except OSError:
            pass
    return {
        "app_version": APP_VERSION,
        "server_start": _server_start_time,
        "last_update": datetime.fromtimestamp(latest).strftime("%m/%d %H:%M") if latest else "",
        "last_update_ts": int(latest) if latest else 0,
        "files": files,
    }


# ---------------------------------------------------------------------------
# Reports CRUD
# ---------------------------------------------------------------------------

def _validate_id(report_id: str):
    if not report_id or "/" in report_id or "\\" in report_id or ".." in report_id:
        raise HTTPException(400, "Invalid report ID")


def _load_report(report_id: str) -> dict:
    _validate_id(report_id)
    p = REPORTS_DIR / f"{report_id}.json"
    if not p.exists():
        raise HTTPException(404, f"Report {report_id} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_report(report_id: str, data: dict):
    p = REPORTS_DIR / f"{report_id}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/reports")
def list_reports():
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            ann_file = ANNOTATIONS_DIR / f.name
            ann_count = 0
            submitted = False
            if ann_file.exists():
                ann = json.loads(ann_file.read_text(encoding="utf-8"))
                ann_count = len(ann.get("items", {}))
                submitted = ann.get("submitted", False)
            reports.append({
                "id": f.stem,
                "title": d.get("title", f.stem),
                "scenario_id": d.get("scenario_id", ""),
                "overall_verdict": d.get("data", {}).get("overall_verdict", ""),
                "created_at": d.get("created_at", ""),
                "annotation_count": ann_count,
                "submitted": submitted,
            })
        except Exception:
            continue
    return reports


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    report = _load_report(report_id)
    ann_file = ANNOTATIONS_DIR / f"{report_id}.json"
    annotations = {}
    if ann_file.exists():
        annotations = json.loads(ann_file.read_text(encoding="utf-8"))
    return {"report": report, "annotations": annotations}


@app.post("/api/reports")
def create_report(body: ReportUpload):
    report_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    doc = {
        "id": report_id,
        "title": body.title,
        "scenario_id": body.scenario_id,
        "feature_title": body.feature_title,
        "pipeline_weight": body.pipeline_weight,
        "pipeline_stage": body.pipeline_stage,
        "document_layer": body.document_layer,
        "data": body.data,
        "created_at": datetime.now().isoformat(),
    }
    _save_report(report_id, doc)
    return {"id": report_id, "message": "Report created"}


# ---------------------------------------------------------------------------
# Annotations CRUD
# ---------------------------------------------------------------------------

def _load_annotations(report_id: str) -> dict:
    p = ANNOTATIONS_DIR / f"{report_id}.json"
    if not p.exists():
        return {"report_id": report_id, "items": {}, "submitted": False, "submitted_at": None}
    return json.loads(p.read_text(encoding="utf-8"))


def _save_annotations(report_id: str, data: dict):
    p = ANNOTATIONS_DIR / f"{report_id}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/annotations/{report_id}")
def get_annotations(report_id: str):
    _load_report(report_id)  # ensure report exists
    return _load_annotations(report_id)


@app.put("/api/annotations/{report_id}/{item_id}")
def update_annotation(report_id: str, item_id: str, body: AnnotationUpdate):
    _load_report(report_id)
    ann = _load_annotations(report_id)
    ann["items"][item_id] = {
        "mark": body.mark,
        "comment": body.comment,
        "annotator": {
            "role": body.annotator_role,
            "name": body.annotator_name,
            "source": "manual",
        },
        "updated_at": datetime.now().isoformat(),
    }
    _save_annotations(report_id, ann)
    return {"ok": True}


@app.post("/api/annotations/{report_id}/submit")
async def submit_annotations(report_id: str, body: SubmitRequest):
    report = _load_report(report_id)
    ann = _load_annotations(report_id)

    if ann.get("submitted"):
        raise HTTPException(409, "Annotations already submitted")

    ann["submitted"] = True
    ann["submitted_at"] = datetime.now().isoformat()
    ann["submitted_by"] = {
        "role": body.annotator_role,
        "name": body.annotator_name,
        "source": "manual",
    }
    _save_annotations(report_id, ann)

    marks = {}
    for item in ann.get("items", {}).values():
        m = item.get("mark", "")
        marks[m] = marks.get(m, 0) + 1

    issue_count = len(report.get("data", {}).get("issues", []))
    unmarked = issue_count - sum(marks.values())
    if unmarked < 0:
        unmarked = 0

    _MARK_EMOJI = {"adopt": "\U0001f534", "discuss": "\U0001f7e1", "known": "\U0001f7e2", "na": "\u26aa"}
    _MARK_LABEL = {"adopt": "\u91c7\u7eb3", "discuss": "\u5f85\u8bae", "known": "\u5df2\u77e5", "na": "\u4e0d\u9002\u7528"}
    stats_parts = []
    for mk in ("adopt", "discuss", "known", "na"):
        cnt = marks.get(mk, 0)
        stats_parts.append(f"{_MARK_EMOJI[mk]}{_MARK_LABEL[mk]} {cnt}")
    stats_parts.append(f"\u672a\u6279 {unmarked}")
    stats_text = " \u00b7 ".join(stats_parts)

    # DingTalk notification (if webhook provided)
    dingtalk_sent = False
    if body.dingtalk_webhook:
        dingtalk_sent = await _send_dingtalk(
            webhook=body.dingtalk_webhook,
            title=report.get("title", report_id),
            annotator_name=body.annotator_name or body.annotator_role or "unknown",
            stats_text=stats_text,
            report_id=report_id,
        )

    return {
        "ok": True,
        "stats": marks,
        "unmarked": unmarked,
        "dingtalk_sent": dingtalk_sent,
    }


async def _send_dingtalk(
    webhook: str, title: str, annotator_name: str, stats_text: str, report_id: str
) -> bool:
    """Send DingTalk markdown notification."""
    try:
        import httpx
    except ImportError:
        print("[palace-web] httpx not installed, skipping dingtalk notification")
        return False

    _ROLE_LABELS = {
        "producer": "\u5236\u4f5c\u4eba", "pld": "\u7ba1\u7ebf\u4e3b\u7b56",
        "pmo": "\u7ba1\u7ebf\u603b\u7ba1", "ple": "\u7ba1\u7ebf\u4f53\u9a8c", "plt": "\u7ba1\u7ebf\u6280\u672f",
    }
    role_label = _ROLE_LABELS.get(annotator_name.split("|")[0] if "|" in annotator_name else "", annotator_name)

    md_text = (
        f"### \U0001f4cb \u5ba1\u67e5\u62a5\u544a\u6279\u6ce8\u5b8c\u6210\n\n"
        f"**\u62a5\u544a**\uff1a{title}\n\n"
        f"**\u6279\u6ce8\u4eba**\uff1a{annotator_name}\n\n"
        f"**\u6279\u6ce8\u7ed3\u679c**\uff1a{stats_text}\n\n"
    )

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": f"\u6279\u6ce8\u5b8c\u6210\uff1a{title}", "text": md_text},
        "at": {"isAtAll": False},
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook, json=payload)
            return resp.status_code == 200
    except Exception as e:
        print(f"[palace-web] DingTalk send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Static files + SPA fallback
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/report/{report_id}")
def report_page(report_id: str):
    return FileResponse(STATIC_DIR / "report.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("palace_web.server:app", host="0.0.0.0", port=8300, reload=True)
