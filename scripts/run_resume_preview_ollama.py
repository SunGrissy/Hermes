# -*- coding: utf-8 -*-
"""
本地 Ollama 跑一轮策划简历初筛（与 dingtalk-desktop/skills/resume_screen.py 共用清单与 prompt）。

用法（PowerShell）:
  cd d:\\MyAgents
  $env:RESUME_LLM_API_BASE = "http://127.0.0.1:11434/v1"
  $env:RESUME_LLM_MODEL = "gemma4:latest"
  py scripts/run_resume_preview_ollama.py --demo

  py scripts/run_resume_preview_ollama.py --text-file path/to/resume.txt --role 系统策划

依赖: Ollama 已启动并已 ollama pull gemma4:latest（或改 MODEL 环境变量）
"""
from __future__ import annotations

import argparse
import os
import sys

# Windows 终端避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# dingtalk-desktop 为包根
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DT = os.path.join(_ROOT, "dingtalk-desktop")
if _DT not in sys.path:
    sys.path.insert(0, _DT)


_DEMO_RESUME = """
张三 | 系统策划 | 工作年限5年
手机：13800000000 | 邮箱：zhangsan@example.com

【教育背景】
2014-2019 某大学 本科 计算机

【工作经历】
2020-至今 某中年男性向MMO 系统策划
- 负责养成线与经济系统耦合，输出 WHAT-HOW 规格并与程序对齐配表
- 主导过跨系统数据流转与边界定义，有线上复盘与迭代记录
- 熟悉配置化活动框架，支持运营快轨复用

【项目】近3年均为写实三国题材MMO，有大R付费分层设计经验。

【游戏经历】累计充值约8万，深度体验多款SLG与MMO。

【技能】熟悉Office、配表工具、AI辅助文档与需求拆解（Copilot/Cursor）。
"""


def main() -> int:
    p = argparse.ArgumentParser(description="Ollama + gemma4 简历初筛预览")
    p.add_argument("--text-file", "-f", help="简历纯文本文件路径（UTF-8）")
    p.add_argument("--role", "-r", default=None, help="岗位：系统策划/战斗策划/运营策划/主策划/PM 等；省略则自动猜")
    p.add_argument("--fresh", action="store_true", help="按应届生清单（可与 --role 同用）")
    p.add_argument("--demo", action="store_true", help="使用内置示例简历文本")
    p.add_argument("--file-name", default="预览_候选人.pdf", help="用于猜岗位/应届的文件名提示")
    args = p.parse_args()

    os.environ.setdefault("RESUME_LLM_API_BASE", "http://127.0.0.1:11434/v1")
    os.environ.setdefault("RESUME_LLM_API_KEY", "ollama")
    os.environ.setdefault("RESUME_LLM_MODEL", "gemma4:latest")

    if args.demo:
        text = _DEMO_RESUME.strip()
    elif args.text_file:
        path = os.path.abspath(args.text_file)
        if not os.path.isfile(path):
            print(f"文件不存在: {path}", file=sys.stderr)
            return 1
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        print("请指定 --demo 或 --text-file", file=sys.stderr)
        return 1

    if len(text.strip()) < 30:
        print("简历文本过短", file=sys.stderr)
        return 1

    from skills.resume_screen import screen_resume_text

    role = args.role
    is_fresh = True if args.fresh else None
    raw, parsed, role_guess, is_fresh_guess = screen_resume_text(
        text,
        file_name=args.file_name,
        role=role,
        is_fresh=is_fresh,
    )

    print("=== Ollama 配置 ===")
    print(f"  RESUME_LLM_API_BASE={os.environ.get('RESUME_LLM_API_BASE')}")
    print(f"  RESUME_LLM_MODEL={os.environ.get('RESUME_LLM_MODEL')}")
    print()
    print("=== 识别 ===")
    print(f"  岗位: {role_guess}  |  应届: {is_fresh_guess}")
    print()
    print("=== 模型原文 ===")
    print(raw)
    print()
    print("=== 解析字段 ===")
    for k in ("verdict", "core", "l3_assess", "l4_assess", "level", "reason", "highlights", "redlines"):
        v = parsed.get(k, "")
        if v:
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
