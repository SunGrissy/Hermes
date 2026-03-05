"""Palace CLI entry point.

Usage:
    py palace/run.py --scenario what_precheck --input-file doc.md --doc-layer WHAT -v
    py palace/run.py --scenario what_precheck --input-file doc.md --doc-layer mixed --format markdown --output report.md
    py palace/run.py --scenario what_precheck --input-file doc.md --title "Feature" --owner "Owner" --weight slow --stage scoping --doc-layer WHAT
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from palace_engine.config import load_scenario  # noqa: E402
from palace_engine.engine import run_scenario  # noqa: E402
from palace_engine.report import generate_markdown  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Palace - Multi-role AI review engine",
    )
    parser.add_argument(
        "--scenario", required=True,
        help="Scenario ID (e.g. what_precheck, dor_slow, dor_fast)",
    )
    parser.add_argument("--input", help="Feature proposal text (inline)")
    parser.add_argument("--input-file", help="Read feature proposal from file")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--format", choices=["json", "markdown"], default="json",
        help="Output format: json (raw) or markdown (human-readable report)",
    )
    parser.add_argument("--title", help="Feature title for report header")
    parser.add_argument("--owner", help="Feature Owner name for report header")
    parser.add_argument(
        "--weight", choices=["fast", "slow"],
        help="Pipeline weight (overrides scenario default)",
    )
    parser.add_argument(
        "--stage",
        choices=["planning", "scoping", "dor", "production", "scoping_late"],
        help="Pipeline stage (overrides scenario default)",
    )
    parser.add_argument(
        "--doc-layer", choices=["WHAT", "HOW", "BUILD", "mixed"],
        help="Document layer declaration (WHAT/HOW/BUILD/mixed)",
    )
    parser.add_argument(
        "--from-json", help="Skip LLM call, generate report from existing JSON result",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.from_json:
        with open(args.from_json, "r", encoding="utf-8") as f:
            result = json.load(f)
    else:
        if args.input_file:
            with open(args.input_file, "r", encoding="utf-8") as f:
                topic_text = f.read()
        elif args.input:
            topic_text = args.input
        else:
            parser.error("--input or --input-file is required (unless --from-json)")

        result = asyncio.run(run_scenario(
            args.scenario, topic_text, document_layer=args.doc_layer or "",
        ))

    scenario_cfg = load_scenario(args.scenario)
    pipeline_weight = args.weight or scenario_cfg.get("pipeline_weight", "")
    pipeline_stage = args.stage or scenario_cfg.get("pipeline_stage", "")
    scenario_name = scenario_cfg.get("name", args.scenario)

    if args.format == "markdown":
        output_text = generate_markdown(
            result,
            scenario_id=args.scenario,
            feature_title=args.title or "",
            feature_owner=args.owner or "",
            pipeline_weight=pipeline_weight,
            pipeline_stage=pipeline_stage,
            document_layer=args.doc_layer or "",
        )
    else:
        output_text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"Result written to {args.output}")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(output_text)


if __name__ == "__main__":
    main()
