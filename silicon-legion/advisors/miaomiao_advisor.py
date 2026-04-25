"""
关怀师妙妙 Advisor
职责：从团队关怀视角，关注成员状态和团队氛围
人格来源：./miaomiao/SOUL.md（单一真源，修改 SOUL.md 即生效）
"""

import os
from typing import Dict, Any
from datetime import datetime


_SOUL_PATH = os.path.join(os.path.dirname(__file__), "miaomiao", "SOUL.md")
_FALLBACK_PROMPT = "你是关怀师妙妙。SOUL.md 加载失败，请检查文件路径。"


def _load_soul() -> str:
    try:
        with open(_SOUL_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[妙妙] SOUL 加载失败: {e}，使用兜底 prompt")
        return _FALLBACK_PROMPT


SYSTEM_PROMPT = _load_soul()


class MiaomiaoAdvisor:
    """团队关怀Advisor"""

    def __init__(self):
        self.name = "妙妙"
        self.role = "care"
        self.system_prompt = SYSTEM_PROMPT

    async def generate_advice(self) -> str:
        """生成今日团队关怀建议"""
        today = datetime.now().strftime("%Y-%m-%d")
        lines = []
        lines.append(f"[妙妙] {today} 团队关怀报告")
        lines.append("")
        lines.append("团队氛围：当前团队整体氛围良好，建议今日下午可以安排一次短暂的休息交流")
        lines.append("")
        lines.append("工作负荷：最近版本临近重要节点，部分同学可能压力较大，建议制作人关注一下")
        lines.append("")
        lines.append("沟通效率：周会信息同步较为充分，建议保持目前频率")
        lines.append("")
        lines.append("今日建议：可以给连续加班的同学一些肯定，或者安排一次轻松的团队小活动")
        return "\n".join(lines)

    async def handle_query(self, query: str) -> str:
        """处理用户查询"""
        if "建议" in query or "今日" in query or "团队" in query:
            return await self.generate_advice()
        return f"[妙妙] 收到你的消息：{query}\n\n我可以帮你关注团队状态、成员负荷、沟通效率，请直接说「今日建议」或「团队关怀」"


_advisor: MiaomiaoAdvisor | None = None


def get_miaomiao_advisor() -> MiaomiaoAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = MiaomiaoAdvisor()
    return _advisor
