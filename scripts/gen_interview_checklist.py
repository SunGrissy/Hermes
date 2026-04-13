# -*- coding: utf-8 -*-
"""通用面试清单/评价生成脚本（多岗位）。"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PALACE = ROOT / "palace"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="输入文本：简历(清单)或面试记录(评价)")
    parser.add_argument("--role", required=True, choices=["运营策划", "系统策划", "战斗策划", "主策划", "fresh"])
    parser.add_argument("--mode", default="checklist", choices=["checklist", "evaluation"])
    parser.add_argument("--candidate", default="")
    parser.add_argument("--mobile-tail", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print("输入文件不存在", file=sys.stderr)
        sys.exit(1)
    text = input_path.read_text(encoding="utf-8", errors="replace")
    candidate = args.candidate or input_path.stem

    sys.path.insert(0, str(PALACE))
    from palace_engine.engine import run_scenario
    from palace_engine.report import generate_markdown

    doc_type = (
        f"role:{args.role};mode:{args.mode};candidate:{candidate};mobile_tail:{args.mobile_tail}"
    )
    result = asyncio.run(run_scenario("interview_checklist", text, doc_type=doc_type))
    md = generate_markdown(result, scenario_id="interview_checklist", feature_title=candidate)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
