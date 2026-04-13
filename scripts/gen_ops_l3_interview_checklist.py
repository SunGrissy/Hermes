# -*- coding: utf-8 -*-
"""兼容入口：默认按运营策划生成初面清单。

推荐改用 `scripts/gen_interview_checklist.py`（支持所有岗位）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PALACE = ROOT / "palace"
OUT_DEFAULT = ROOT / "面试" / "interviews" / "xubo_ops_2026-04-01" / "徐博-L3运营初面清单.md"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resume", nargs="?", default=str(ROOT / "面试" / "interviews" / "xubo_ops_2026-04-01" / "_resume_extract.txt"))
    parser.add_argument("--role", default="运营策划")
    parser.add_argument("--mode", default="checklist", choices=["checklist", "evaluation"])
    parser.add_argument("--candidate", default="")
    parser.add_argument("--output", default=str(OUT_DEFAULT))
    args = parser.parse_args()

    resume_path = Path(args.resume)
    if not resume_path.is_file():
        print("请传入简历文本文件路径，或放置 _resume_extract.txt", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, str(PALACE))
    from palace_engine.engine import run_scenario
    from palace_engine.report import generate_markdown

    text = resume_path.read_text(encoding="utf-8", errors="replace")
    candidate = args.candidate or resume_path.stem
    doc_type = f"role:{args.role};mode:{args.mode};candidate:{candidate}"
    result = asyncio.run(run_scenario("interview_checklist", text, doc_type=doc_type))
    md = generate_markdown(
        result,
        scenario_id="interview_checklist",
        feature_title=resume_path.stem,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "<!-- 由 scripts/gen_ops_l3_interview_checklist.py 调用 Palace interview_checklist -->\n\n"
    )
    output_path.write_text(header + md, encoding="utf-8")
    print(f"Wrote {output_path}")
    mr = result.get("markdown_report") or ""
    if "初面清单（Mock）" in mr or "PALACE_PROVIDER=mock" in mr:
        print("Note: 当前为 mock 占位输出；请在 palace/.env 设置 openai_compatible 与 API 后重跑", file=sys.stderr)


if __name__ == "__main__":
    main()
