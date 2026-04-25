"""
sync_soul_to_hermes.py
将 silicon-legion 仓库内的 4 份 SOUL.md 同步到 D:/hermes 运行环境。

来源（正本，silicon-legion 仓库内）：
  director/SOUL.md
  advisors/acha/SOUL.md
  advisors/xiaomei/SOUL.md
  advisors/miaomiao/SOUL.md

目标（运行环境，Hermes 实际加载位置）：
  D:/hermes/SOUL.md
  D:/hermes/acha/SOUL.md
  D:/hermes/xiaomei/SOUL.md
  D:/hermes/miaomiao/SOUL.md

使用：在仓库根执行 `py scripts/sync_soul_to_hermes.py`，或加 --check 仅做差异检查。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HERMES_ROOT = Path("D:/hermes")

PAIRS = [
    (REPO_ROOT / "director" / "SOUL.md", HERMES_ROOT / "SOUL.md"),
    (REPO_ROOT / "advisors" / "acha" / "SOUL.md", HERMES_ROOT / "acha" / "SOUL.md"),
    (REPO_ROOT / "advisors" / "xiaomei" / "SOUL.md", HERMES_ROOT / "xiaomei" / "SOUL.md"),
    (REPO_ROOT / "advisors" / "miaomiao" / "SOUL.md", HERMES_ROOT / "miaomiao" / "SOUL.md"),
]


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只检查差异，不写入")
    args = parser.parse_args()

    print(f"silicon-legion 仓库: {REPO_ROOT}")
    print(f"Hermes 运行环境  : {HERMES_ROOT}")
    print()

    any_diff = False
    for src, dst in PAIRS:
        src_txt = read_text(src)
        dst_txt = read_text(dst)
        if not src.exists():
            print(f"[跳过] 源文件不存在: {src}")
            continue
        if src_txt == dst_txt:
            print(f"[一致] {dst.relative_to(HERMES_ROOT)}  ({len(src_txt)} chars)")
            continue
        any_diff = True
        print(
            f"[差异] {dst.relative_to(HERMES_ROOT)}  "
            f"src={len(src_txt)} chars / dst={len(dst_txt)} chars"
        )
        if not args.check:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"        -> 已写入 {dst}")

    print()
    if args.check:
        print("仅检查模式：未写入文件。")
        return 1 if any_diff else 0
    print("同步完成。" if any_diff else "无变化。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
