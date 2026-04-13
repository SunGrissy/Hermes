"""Local interview records storage (JSON file)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PALACE_ROOT

_DATA_DIR = PALACE_ROOT / "palace_web" / "data"
_RECORD_FILE = _DATA_DIR / "interview_records.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_store() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _RECORD_FILE.exists():
        _RECORD_FILE.write_text(
            json.dumps({"records": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _load_store() -> dict[str, Any]:
    _ensure_store()
    return json.loads(_RECORD_FILE.read_text(encoding="utf-8"))


def _save_store(data: dict[str, Any]) -> None:
    _RECORD_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_candidate_key(candidate_name: str, role: str, mobile_tail: str = "") -> str:
    name = re.sub(r"\s+", "", candidate_name or "").strip() or "unknown"
    role_norm = (role or "").strip() or "unknown"
    tail = re.sub(r"\D+", "", mobile_tail or "")[-4:]
    if not tail:
        tail = "0000"
    return f"{name}|{role_norm}|{tail}"


def upsert_checklist_record(
    candidate_key: str,
    candidate_name: str,
    role: str,
    checklist_markdown: str,
    source_resume_hash: str = "",
) -> dict[str, Any]:
    store = _load_store()
    records = store.setdefault("records", {})
    now = _now_iso()
    current = records.get(candidate_key, {})
    current.update(
        {
            "candidate_key": candidate_key,
            "candidate_name": candidate_name,
            "role": role,
            "checklist_markdown": checklist_markdown,
            "source_resume_hash": source_resume_hash,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
            "evaluations": current.get("evaluations") or [],
        }
    )
    records[candidate_key] = current
    _save_store(store)
    return current


def append_evaluation_record(
    candidate_key: str,
    candidate_name: str,
    role: str,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    store = _load_store()
    records = store.setdefault("records", {})
    now = _now_iso()
    current = records.get(candidate_key, {})
    evals = current.get("evaluations") or []
    evals.append(
        {
            "created_at": now,
            "summary": evaluation.get("summary", ""),
            "verdict": evaluation.get("verdict", ""),
            "risk_level": evaluation.get("risk_level", ""),
            "evidence": evaluation.get("evidence", []),
            "markdown": evaluation.get("markdown", ""),
        }
    )
    current.update(
        {
            "candidate_key": candidate_key,
            "candidate_name": candidate_name,
            "role": role,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
            "evaluations": evals,
        }
    )
    records[candidate_key] = current
    _save_store(store)
    return current
