"""
策划小美 Advisor
职责：从游戏策划视角，提供设计建议和玩法分析
人格来源：./xiaomei/SOUL.md（单一真源，修改 SOUL.md 即生效）
"""

import os
from typing import Dict, Any
from datetime import datetime


_SOUL_PATH = os.path.join(os.path.dirname(__file__), "xiaomei", "SOUL.md")
_FALLBACK_PROMPT = "你是策划小美。SOUL.md 加载失败，请检查文件路径。"


def _load_soul() -> str:
    try:
        with open(_SOUL_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[小美] SOUL 加载失败: {e}，使用兜底 prompt")
        return _FALLBACK_PROMPT


SYSTEM_PROMPT = _load_soul()


class XiaomeiAdvisor:
    """游戏策划Advisor"""

    def __init__(self):
        self.name = "小美"
        self.role = "design"
        self.system_prompt = SYSTEM_PROMPT

    async def generate_advice(self) -> str:
        """生成今日策划建议"""
        today = datetime.now().strftime("%Y-%m-%d")
        lines = []
        lines.append(f"[小美] {today} 策划视角建议")
        lines.append("")
        lines.append("玩法设计：当前版本核心玩法梳理完毕，建议关注新手引导体验是否流畅")
        lines.append("")
        lines.append("数值平衡：建议抽时对最近上线的活动进行数据回顾，确保奖励放出比例合理")
        lines.append("")
        lines.append("用户体验：关注玩家反馈中的高频痛点，优先纠正影响留存的问题")
        lines.append("")
        lines.append("今日建议：安排一场小规模玩法验证，收集真实用户反馈后再扩大投放")
        return "\n".join(lines)

    async def handle_query(self, query: str) -> str:
        """处理用户查询"""
        if "建议" in query or "今日" in query:
            return await self.generate_advice()
        return f"[小美] 收到你的消息：{query}\n\n我可以帮你提供策划建议、玩法分析、体验评估，请直接说「今日建议」或「玩法分析」"

    async def handle_task(self, task_description: str, context: str = "") -> str:
        """处理总管分派的通用任务"""
        task_lower = task_description.lower()
        if any(k in task_lower for k in ["建议", "玩法", "设计", "体验", "数值", "今日"]):
            return await self.generate_advice()
        return f"[小美] 收到任务：{task_description}\n\n我可以帮你提供策划建议、玩法分析、体验评估，请说「今日建议」或「玩法分析」。"


_advisor: XiaomeiAdvisor | None = None


def get_xiaomei_advisor() -> XiaomeiAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = XiaomeiAdvisor()
    return _advisor
