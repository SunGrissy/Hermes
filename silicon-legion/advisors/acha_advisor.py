"""
PM阿茶 Advisor
职责：从项目管理视角，每日生成工作建议
数据源：PmSystem API
人格来源：./acha/SOUL.md（单一真源，修改 SOUL.md 即生效）
"""

import os
import json
from typing import Dict, Any, List
from datetime import datetime
from core.pm_client import get_pm_client


_SOUL_PATH = os.path.join(os.path.dirname(__file__), "acha", "SOUL.md")
_FALLBACK_PROMPT = "你是PM阿茶。SOUL.md 加载失败，请检查文件路径。"


def _load_soul() -> str:
    try:
        with open(_SOUL_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[阿茶] SOUL 加载失败: {e}，使用兜底 prompt")
        return _FALLBACK_PROMPT


SYSTEM_PROMPT = _load_soul()


class AchaAdvisor:
    """PM项目管理Advisor"""

    def __init__(self):
        self.name = "阿茶"
        self.role = "pm"
        self.system_prompt = SYSTEM_PROMPT

    async def generate_advice(self) -> str:
        """生成今日项目管理建议"""
        pm = get_pm_client()

        try:
            # 获取数据
            versions = await pm.get_versions()
            tasks = await pm.get_tasks()
            milestones = await pm.get_milestones()
            calendar = await pm.get_pm_calendar()

            # 构建上下文
            context = self._build_context(versions, tasks, milestones, calendar)

            # TODO: 调用LLM生成建议（当前用模板渐进）
            advice = self._generate_template_advice(context)
            return advice

        except Exception as e:
            return f"[阿茶] 数据获取异常：{str(e)[:100]}"

    def _build_context(self, versions, tasks, milestones, calendar) -> Dict[str, Any]:
        """从原始数据中提取关键信息"""
        today = datetime.now().strftime("%Y-%m-%d")

        # 版本统计
        version_list = versions.get("data", []) if isinstance(versions, dict) else []
        active_versions = [v for v in version_list if v.get("status") in ["active", "in_progress"]]

        # 任务统计
        task_list = tasks.get("data", []) if isinstance(tasks, dict) else []
        overdue_tasks = [t for t in task_list if t.get("status") != "done" and t.get("end_date", "") < today]

        # 里程碑统计
        milestone_list = milestones.get("data", []) if isinstance(milestones, dict) else []
        upcoming_milestones = [m for m in milestone_list if m.get("date", "") >= today]
        upcoming_milestones.sort(key=lambda x: x.get("date", ""))

        return {
            "today": today,
            "active_versions_count": len(active_versions),
            "active_versions": [v.get("name", "unknown") for v in active_versions[:3]],
            "total_tasks": len(task_list),
            "overdue_tasks_count": len(overdue_tasks),
            "overdue_tasks": [t.get("name", "unknown") for t in overdue_tasks[:3]],
            "upcoming_milestones": [(m.get("name"), m.get("date")) for m in upcoming_milestones[:3]],
            "is_workday": self._check_workday(calendar, today),
        }

    def _check_workday(self, calendar, today) -> bool:
        """检查今天是否工作日"""
        try:
            if isinstance(calendar, dict):
                holidays = calendar.get("holidays", [])
                workdays = calendar.get("workdays", [])
                if today in holidays:
                    return False
                if today in workdays:
                    return True
            # 默认用周末判断
            wd = datetime.now().weekday()
            return wd < 5
        except Exception:
            return True

    def _generate_template_advice(self, context: Dict[str, Any]) -> str:
        """模板化建议生成（MVP版，后续替换为LLM）"""
        lines = []
        lines.append(f"📊 版本进度：当前{context['active_versions_count']}个进行中版本")
        if context["active_versions"]:
            lines.append(f"   主要版本：{', '.join(context['active_versions'])}")

        lines.append("")

        if context["overdue_tasks_count"] > 0:
            lines.append(f"⚠️ 风险项：{context['overdue_tasks_count']}个任务已超期")
            lines.append(f"   包括：{', '.join(context['overdue_tasks'])}")
        else:
            lines.append("✅ 风险项：暂无超期任务")

        lines.append("")

        if context["upcoming_milestones"]:
            lines.append("🎯 即将到期里程碑：")
            for name, date in context["upcoming_milestones"]:
                lines.append(f"   • {name} ({date})")

        lines.append("")
        lines.append("💡 今日建议：重点关注超期任务推进，确保里程碑节点按时完成")

        return "\n".join(lines)

    async def handle_task(self, task_description: str, context: str = "") -> str:
        """处理总管分派的通用任务"""
        task_lower = task_description.lower()

        if any(k in task_lower for k in ["建议", "进度", "风险", "里程碑", "今日"]):
            return await self.generate_advice()

        if any(k in task_lower for k in ["版本", "version"]):
            pm = get_pm_client()
            versions = await pm.get_versions()
            version_list = versions.get("data", []) if isinstance(versions, dict) else []
            active = [v.get("name", "unknown") for v in version_list if v.get("status") in ["active", "in_progress"]]
            return f"当前进行中的版本：{', '.join(active) if active else '无'}"

        # 默认回复
        return f"[阿茶] 收到任务：{task_description}\n\n我可以帮你查看项目进度、风险、里程碑等信息，请说「今日建议」或「项目进度」。"


_advisor: AchaAdvisor | None = None


def get_acha_advisor() -> AchaAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = AchaAdvisor()
    return _advisor
