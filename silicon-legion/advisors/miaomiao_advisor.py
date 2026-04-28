"""
关怀师妙妙 Advisor
职责：从团队关怀视角，关注成员状态和团队氛围
人格来源：./miaomiao/SOUL.md（单一真源，修改 SOUL.md 即生效）
"""

import os
from typing import Dict, Any
from datetime import datetime

from core.llm_client import LLMClient
from core.config import get_settings

_SOUL_PATH = os.path.join(os.path.dirname(__file__), "miaomiao", "SOUL.md")
_FALLBACK_PROMPT = "你是关怀师妙妙。SOUL.md 加载失败，请检查文件路径。"


def _load_soul() -> str:
    try:
        with open(_SOUL_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[妙妙] SOUL 加载失败: {e}，使用兑底 prompt")
        return _FALLBACK_PROMPT


SYSTEM_PROMPT = _load_soul()


class MiaomiaoAdvisor:
    """团队关怀Advisor"""

    def __init__(self):
        self.name = "妙妙"
        self.role = "care"
        self.system_prompt = SYSTEM_PROMPT
        # 加载 .env 配置中的 LLM 参数
        env_path = os.path.join(os.path.dirname(__file__), "miaomiao", ".env")
        settings = get_settings(env_path)
        self.llm = LLMClient(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            model=settings.kimi_model,
            api_type=settings.kimi_api_type,
        )

    async def generate_advice(self) -> str:
        """生成今日团队关怀建议"""
        today = datetime.now().strftime("%Y-%m-%d")
        user_msg = f"今天是 {today}，请从团队关怀视角生成今日建议。"
        try:
            reply = await self.llm.chat(self.system_prompt, user_msg, temperature=0.7)
            return reply
        except Exception as e:
            print(f"[妙妙] LLM 调用失败: {e}")
            return self._fallback_advice(today)

    async def handle_query(self, query: str) -> str:
        """处理用户查询"""
        try:
            reply = await self.llm.chat(self.system_prompt, query, temperature=0.7)
            return reply
        except Exception as e:
            print(f"[妙妙] LLM 调用失败: {e}")
            return self._fallback_reply(query)

    async def handle_task(self, task_description: str, context: str = "") -> str:
        """处理总管分派的通用任务"""
        user_msg = f"任务：{task_description}"
        if context:
            user_msg += f"\n\n上下文：{context}"
        try:
            reply = await self.llm.chat(self.system_prompt, user_msg, temperature=0.7)
            return reply
        except Exception as e:
            print(f"[妙妙] LLM 调用失败: {e}")
            return f"[妙妙] 收到任务：{task_description}\n\n（LLM 调用异常，暂时无法生成智能回复）"

    def _fallback_advice(self, today: str) -> str:
        """兑底建议（LLM 失败时使用）"""
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

    def _fallback_reply(self, query: str) -> str:
        """兑底回复（LLM 失败时使用）"""
        return f"[妙妙] 收到你的消息：{query}\n\n我可以帮你关注团队状态、成员负荷、沟通效率，请直接说「今日建议」或「团队关怀」"


_advisor: MiaomiaoAdvisor | None = None


def get_miaomiao_advisor() -> MiaomiaoAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = MiaomiaoAdvisor()
    return _advisor
