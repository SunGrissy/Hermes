"""Import a Palace engine output JSON into the web annotation system.

Usage:
    py palace/palace_web/import_report.py <json_file> [--title "Report Title"]

The JSON file should contain REPORT_DATA from the Palace engine
(with overall_verdict, issues[], layer_overview[], etc.).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
REPORTS_DIR = DATA_DIR / "reports"


def import_report(
    json_path: str,
    title: str = "",
    scenario_id: str = "",
    feature_title: str = "",
    pipeline_weight: str = "",
    pipeline_stage: str = "",
    document_layer: str = "",
) -> str:
    src = Path(json_path)
    if not src.exists():
        print(f"[ERROR] File not found: {json_path}")
        sys.exit(1)

    raw = json.loads(src.read_text(encoding="utf-8"))

    if not title:
        title = raw.get("title") or feature_title or src.stem

    if not scenario_id:
        scenario_id = raw.get("scenario_id", "")

    report_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    doc = {
        "id": report_id,
        "title": title,
        "scenario_id": scenario_id,
        "feature_title": feature_title or raw.get("feature_title", ""),
        "pipeline_weight": pipeline_weight or raw.get("pipeline_weight", ""),
        "pipeline_stage": pipeline_stage or raw.get("pipeline_stage", ""),
        "document_layer": document_layer or raw.get("document_layer", ""),
        "data": raw,
        "created_at": datetime.now().isoformat(),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{report_id}.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Imported: {out_path.name}")
    print(f"  Title: {title}")
    print(f"  Issues: {len(raw.get('issues', []))}")
    print(f"  Verdict: {raw.get('overall_verdict', '?')}")
    print(f"  URL: http://localhost:8300/report/{report_id}")
    return report_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Palace report JSON")
    parser.add_argument("json_file", help="Path to engine output JSON")
    parser.add_argument("--title", default="", help="Report title")
    parser.add_argument("--scenario", default="", help="Scenario ID")
    parser.add_argument("--feature", default="", help="Feature title")
    parser.add_argument("--weight", default="", help="Pipeline weight (fast/slow)")
    parser.add_argument("--stage", default="", help="Pipeline stage")
    parser.add_argument("--layer", default="", help="Document layer")
    args = parser.parse_args()

    import_report(
        args.json_file,
        title=args.title,
        scenario_id=args.scenario,
        feature_title=args.feature,
        pipeline_weight=args.weight,
        pipeline_stage=args.stage,
        document_layer=args.layer,
    )
