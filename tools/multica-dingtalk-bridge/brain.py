from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class BrainDecision:
    intent: str = ""
    category: str = ""
    confidence: float = 0.0
    missing_info: list[str] = field(default_factory=list)
    suggested_title: str = ""
    suggested_description: str = ""
    definition_of_done: list[str] = field(default_factory=list)
    priority: str = "medium"
    split_suggestion: str = ""
    recommended_action: str = "reply"
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def action(self) -> str:
        return self.recommended_action

    @property
    def title(self) -> str:
        return self.suggested_title

    @property
    def description(self) -> str:
        return self.suggested_description


class LLMProvider(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str:
        ...


class MockLLMProvider:
    def __init__(self, decision: dict[str, Any] | BrainDecision | str | None = None):
        self._decision = decision

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if isinstance(self._decision, BrainDecision):
            return json.dumps(_decision_to_dict(self._decision), ensure_ascii=False)
        if isinstance(self._decision, dict):
            return json.dumps(self._decision, ensure_ascii=False)
        if isinstance(self._decision, str):
            return self._decision

        user_text = _extract_user_text_from_prompt(messages[-1]["content"] if messages else "")
        title = _guess_title(user_text)
        if _has_acceptance_criteria(user_text):
            if not title:
                return json.dumps(
                    _decision_to_dict(
                        BrainDecision(
                            intent="dispatch",
                            category="task",
                            confidence=0.45,
                            missing_info=["需求标题"],
                            recommended_action="ask_clarification",
                        )
                    ),
                    ensure_ascii=False,
                )
            return json.dumps(
                _decision_to_dict(
                    BrainDecision(
                        intent="dispatch",
                        category="task",
                        confidence=0.8,
                        suggested_title=title,
                        suggested_description=_clean_dispatch_description(user_text),
                        definition_of_done=_extract_definition_of_done(user_text),
                        priority="medium",
                        recommended_action="ask_confirm",
                    )
                ),
                ensure_ascii=False,
            )
        return json.dumps(
            _decision_to_dict(
                BrainDecision(
                    intent="dispatch",
                    category="task",
                    confidence=0.5,
                    missing_info=["验收标准"],
                    suggested_title=title,
                    recommended_action="ask_clarification",
                )
            ),
            ensure_ascii=False,
        )


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip() or "gpt-4o-mini"
        self.timeout_seconds = timeout_seconds

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return await asyncio.to_thread(self._complete_sync, messages)

    def _complete_sync(self, messages: list[dict[str, str]]) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc

        data = json.loads(payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("LLM response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError("LLM choice was not an object")
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(first.get("text"), str):
            return first["text"]
        raise RuntimeError("LLM response missing message content")


def parse_brain_decision(text: str) -> BrainDecision:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty brain decision")

    fenced = _extract_fenced_json(raw)
    if fenced is not None:
        try:
            data = json.loads(fenced)
        except json.JSONDecodeError as exc:
            raise ValueError("failed to parse fenced brain decision JSON") from exc
        return _coerce_decision(data)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("failed to parse brain decision JSON") from exc
    return _coerce_decision(data)


def is_confirm_dispatch_phrase(text: str) -> bool:
    normalized = (text or "").strip()
    return normalized in {
        "就按这个派",
        "就按这个派单",
        "确认",
        "确认派单",
        "按这个派",
        "按这个派单",
        "可以派",
        "派吧",
    }


def render_patrol_summary(issues: list[dict[str, Any]]) -> str:
    """Render a read-only issue patrol summary without mutating Multica state."""
    valid_issues = [item for item in issues if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    for issue in valid_issues:
        status = _issue_text(issue, "status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    lines = [
        "Multica 只读巡查摘要",
        "",
        "说明：这是只读巡查，不会自动改状态、分派、评论或创建工单。",
        "",
        f"总数：{len(valid_issues)}",
        "",
        "按 status 分组：",
    ]
    if status_counts:
        for status in sorted(status_counts):
            lines.append(f"- {status}：{status_counts[status]}")
    else:
        lines.append("- （无工单）")

    attention = [issue for issue in valid_issues if _issue_needs_attention(issue)]
    lines.extend(["", "需要关注的工单（最多 5 条）："])
    if not attention:
        lines.append("- 暂无明显需要关注项")
    else:
        for issue in attention[:5]:
            identifier = _issue_text(issue, "identifier") or _issue_text(issue, "id") or "?"
            title = _issue_text(issue, "title") or "（无标题）"
            status = _issue_text(issue, "status") or "unknown"
            assignee = _issue_assignee_text(issue)
            reasons = "、".join(_patrol_attention_reasons(issue))
            lines.append(
                f"- `{identifier}` · {status} · {assignee} · {title}（{reasons}）"
            )
    return "\n".join(lines)


def load_minimal_skill_summary() -> str:
    return "\n".join(
        [
            "派单助手只负责把自然语言整理为 Multica 工单建议，不直接执行代码。",
            "若缺少 DoD / 验收标准，必须先追问；不要生成含糊工单。",
            "若信息足够，recommended_action=ask_confirm，并给出 suggested_title、suggested_description、definition_of_done、priority。",
            "recommended_action 只能是 ask_clarification、ask_confirm、reply；输出必须是 JSON 对象。",
        ]
    )


class Brain:
    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or build_provider_from_env()

    async def decide(
        self,
        user_text: str,
        context: str = "",
        project_context: str = "",
    ) -> BrainDecision:
        system_parts = [
            "你是 Multica 派单桥的结构化大脑。"
            "只输出 JSON，不要自动执行代码、不要创建工单。\n\n",
            load_minimal_skill_summary(),
            "\n\n字段：intent, category, confidence, missing_info, "
            "suggested_title, suggested_description, definition_of_done, "
            "priority, split_suggestion, recommended_action, memory_candidates。",
        ]
        if project_context.strip():
            system_parts.append(
                "\n\n项目结构（供判断任务归属、模块分类时参考）：\n"
                + project_context.strip()
            )
        messages = [
            {"role": "system", "content": "".join(system_parts)},
            {
                "role": "user",
                "content": (
                    "请把用户消息整理成 BrainDecision。\n\n"
                    f"上下文：{context.strip() or '无'}\n\n"
                    f"用户消息：{user_text.strip()}"
                ),
            },
        ]
        output = await self.provider.complete(messages)
        return parse_brain_decision(output)

    def render_reply(self, decision: BrainDecision) -> str:
        action = decision.recommended_action
        if action == "ask_clarification":
            questions = _questions_for_missing_info(decision.missing_info)
            if not questions:
                questions = ["这单的验收标准是什么？"]
            return "\n".join(
                [
                    "这单先别急着派，我还差一个关键信息：",
                    "",
                    *[f"- {q}" for q in questions],
                    "",
                    "补一句“验收：……”就行，我再整理成派单建议。",
                ]
            )
        if action == "ask_confirm":
            title = decision.suggested_title.strip()
            description = decision.suggested_description.strip() or "（无额外描述）"
            dod = decision.definition_of_done or ["补齐验收标准后再落单"]
            split = decision.split_suggestion.strip() or "无需拆分"
            return "\n".join(
                [
                    "我理解这单要解决的是：",
                    "",
                    f"**{title}**",
                    "",
                    description,
                    "",
                    f"我会把它归到 {decision.category or 'task'}，优先级 {decision.priority or 'medium'}。",
                    f"拆分判断：{split}",
                    "",
                    "验收口径我先按这条写：",
                    *[f"- {item}" for item in dod],
                    "",
                    "如果这个理解没跑偏，直接回“就按这个派”，我再真正创建 Multica 工单。",
                ]
            )
        if decision.suggested_description.strip():
            return decision.suggested_description.strip()
        return "收到，我先记录；目前不需要派单。"


def build_provider_from_env() -> LLMProvider:
    provider = (os.environ.get("MULTICA_BOT_LLM_PROVIDER") or "mock").strip().lower()
    if provider == "openai":
        api_key = (os.environ.get("MULTICA_BOT_LLM_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "MULTICA_BOT_LLM_API_KEY is required when MULTICA_BOT_LLM_PROVIDER=openai"
            )
        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=os.environ.get("MULTICA_BOT_LLM_BASE_URL")
            or "https://api.openai.com/v1",
            model=os.environ.get("MULTICA_BOT_LLM_MODEL") or "gpt-4o-mini",
        )
    return MockLLMProvider()


def _decision_to_dict(decision: BrainDecision) -> dict[str, Any]:
    return {
        "intent": decision.intent,
        "category": decision.category,
        "confidence": decision.confidence,
        "missing_info": list(decision.missing_info),
        "suggested_title": decision.suggested_title,
        "suggested_description": decision.suggested_description,
        "definition_of_done": list(decision.definition_of_done),
        "priority": decision.priority,
        "split_suggestion": decision.split_suggestion,
        "recommended_action": decision.recommended_action,
        "memory_candidates": list(decision.memory_candidates),
    }


def _extract_fenced_json(text: str) -> str | None:
    matches = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.I | re.S)
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError("expected a single fenced JSON block")
    return matches[0].strip()


def _coerce_decision(data: Any) -> BrainDecision:
    if isinstance(data, BrainDecision):
        return data
    if not isinstance(data, dict):
        raise ValueError("brain decision JSON must be an object")
    recommended_action = _normalize_action(
        str(
            data.get("recommended_action")
            or data.get("action")
            or data.get("decision")
            or data.get("mode")
            or "reply"
        )
    )
    if recommended_action not in {"ask_clarification", "ask_confirm", "reply"}:
        raise ValueError(f"unknown recommended_action: {recommended_action}")
    suggested_title = str(data.get("suggested_title") or data.get("title") or "").strip()
    if recommended_action == "ask_confirm" and not suggested_title:
        raise ValueError("ask_confirm requires suggested_title")
    return BrainDecision(
        intent=str(data.get("intent") or "").strip(),
        category=str(data.get("category") or "").strip(),
        confidence=_coerce_float(data.get("confidence"), default=0.0),
        missing_info=_coerce_str_list(data.get("missing_info") or data.get("missing_fields")),
        suggested_title=suggested_title,
        suggested_description=str(
            data.get("suggested_description")
            or data.get("description")
            or data.get("body")
            or data.get("details")
            or ""
        ).strip(),
        definition_of_done=_coerce_str_list(data.get("definition_of_done")),
        priority=str(data.get("priority") or "medium").strip() or "medium",
        split_suggestion=str(data.get("split_suggestion") or "").strip(),
        recommended_action=recommended_action,
        memory_candidates=_coerce_memory_candidates(data.get("memory_candidates")),
    )


def _normalize_action(action: str) -> str:
    value = (action or "").strip().lower()
    aliases = {
        "clarify": "ask_clarification",
        "ask": "ask_clarification",
        "ask_clarification": "ask_clarification",
        "confirm": "ask_confirm",
        "dispatch": "ask_confirm",
        "ask_confirm": "ask_confirm",
        "record": "reply",
        "note": "reply",
        "reply": "reply",
    }
    return aliases.get(value, value or "reply")


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_memory_candidates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _issue_text(issue: dict[str, Any], key: str) -> str:
    value = issue.get(key)
    return value.strip() if isinstance(value, str) else ""


def _issue_assignee_text(issue: dict[str, Any]) -> str:
    assignee = issue.get("assignee")
    if isinstance(assignee, str):
        return assignee.strip() or "未分配"
    if isinstance(assignee, dict):
        for key in ("name", "username", "email", "id"):
            value = assignee.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "未分配"


def _issue_needs_attention(issue: dict[str, Any]) -> bool:
    return bool(_patrol_attention_reasons(issue))


def _patrol_attention_reasons(issue: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = _issue_text(issue, "status").lower()
    description = _issue_text(issue, "description")
    description_lower = description.lower()
    if "blocked" in status:
        reasons.append("blocked")
    if "stale" in status:
        reasons.append("stale")
    terminal_statuses = {"done", "closed", "cancelled", "canceled", "resolved"}
    has_dod = (
        "验收" in description
        or "dod" in description_lower
        or "definition of done" in description_lower
    )
    if status not in terminal_statuses and not has_dod:
        reasons.append("missing DoD")
    return reasons


def _questions_for_missing_info(fields: list[str]) -> list[str]:
    questions: list[str] = []
    for field_name in fields:
        if "验收" in field_name or "dod" in field_name.lower():
            questions.append("这单的验收标准是什么？")
        elif "标题" in field_name:
            questions.append("这单的标题想怎么写？")
        else:
            questions.append(f"{field_name} 这项信息怎么补？")
    return questions


def _has_acceptance_criteria(text: str) -> bool:
    lower = (text or "").lower()
    return any(token in lower for token in ("验收", "dod", "definition of done", "完成标准"))


def _extract_user_text_from_prompt(text: str) -> str:
    marker = "用户消息："
    if marker not in text:
        return text
    return text.split(marker, 1)[1].strip()


def _guess_title(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    first = _strip_dispatch_intent_prefix(lines[0])
    if _is_acceptance_line(first):
        return ""
    for prefix in ("#派单", "派单"):
        if first.startswith(prefix):
            first = first[len(prefix) :].strip()
            break
    return first[:120]


def _clean_dispatch_description(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    cleaned: list[str] = []
    for line in lines:
        line = _strip_dispatch_intent_prefix(line)
        if line.startswith("#派单"):
            line = line[len("#派单") :].strip()
        elif line.startswith("派单"):
            line = line[len("派单") :].strip()
        if line and not _is_acceptance_line(line):
            cleaned.append(line)
    return "\n".join(cleaned)


def _extract_definition_of_done(text: str) -> list[str]:
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("验收：") or s.startswith("验收:"):
            out.append(s.split(":", 1)[-1].strip() if ":" in s else s.split("：", 1)[-1].strip())
    return [item for item in out if item]


def _strip_dispatch_intent_prefix(text: str) -> str:
    value = (text or "").strip()
    prefixes = (
        "这个需求怎么派比较好？",
        "这个需求怎么派比较好?",
        "这个需求怎么派？",
        "这个需求怎么派?",
        "需求怎么派比较好？",
        "需求怎么派比较好?",
        "怎么派比较好？",
        "怎么派比较好?",
    )
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix) :].strip(" ：:，,")
    return value


def _is_acceptance_line(text: str) -> bool:
    value = (text or "").strip().lower()
    return value.startswith(("验收：", "验收:", "dod:", "dod：", "完成标准：", "完成标准:"))


# ---------------------------------------------------------------------------
# 自由查询解析
# ---------------------------------------------------------------------------

_QUERY_PARSE_SYSTEM = """\
你是 Multica 工单查询助手，把用户的自然语言查询翻译成结构化参数 JSON。

输出格式（严格 JSON，不含任何额外说明）：
{
  "limit": <整数，默认10，最大100>,
  "status": "<空串=不限|todo|in_progress|done|cancelled>",
  "assignee": "<指定经办人名字，无则空串>",
  "sort_by": "<created_desc|created_asc|priority_desc|updated_desc>",
  "search": "<关键词搜索，无则空串>",
  "include_closed": <true|false>
}

规则：
- "最近创建" → sort_by=created_desc
- "最近更新" → sort_by=updated_desc
- "按优先级" → sort_by=priority_desc
- "待处理" / "待办" → status=todo
- "进行中" → status=in_progress
- "已完成" → status=done, include_closed=true
- "已取消" → status=cancelled, include_closed=true
- 若用户说"所有"/"全部"且没明确状态，status="" include_closed=false（仅返回未完结）
- limit 从用户明确数字提取；没说则默认 10
- sort_by 默认 created_desc（最近创建优先）
"""

_QUERY_PARSE_SYSTEM = _QUERY_PARSE_SYSTEM.strip()


from dataclasses import dataclass as _dc  # noqa: E402 — 文件内已有 import，此处补用于类型标注


@_dc
class IssueQuerySpec:
    limit: int = 10
    status: str = ""
    assignee: str = ""
    sort_by: str = "created_desc"
    search: str = ""
    include_closed: bool = False


def _parse_issue_query_spec(raw: str) -> IssueQuerySpec:
    """从 LLM JSON 输出解析 IssueQuerySpec，容错处理。"""
    data: dict[str, Any] = {}
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
    except Exception:
        pass
    limit = data.get("limit", 10)
    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit = 10
    status = str(data.get("status") or "").strip().lower()
    valid_statuses = {"", "todo", "in_progress", "done", "cancelled"}
    if status not in valid_statuses:
        status = ""
    sort_by = str(data.get("sort_by") or "created_desc").strip().lower()
    valid_sorts = {"created_desc", "created_asc", "priority_desc", "updated_desc"}
    if sort_by not in valid_sorts:
        sort_by = "created_desc"
    return IssueQuerySpec(
        limit=limit,
        status=status,
        assignee=str(data.get("assignee") or "").strip(),
        sort_by=sort_by,
        search=str(data.get("search") or "").strip(),
        include_closed=bool(data.get("include_closed", False)),
    )


async def parse_issue_query(
    user_text: str,
    provider: "LLMProvider | None" = None,
) -> IssueQuerySpec:
    """把自然语言查询解析为 IssueQuerySpec，无 LLM 时走简单规则降级。"""
    if provider is None:
        provider = build_provider_from_env()
    messages = [
        {"role": "system", "content": _QUERY_PARSE_SYSTEM},
        {"role": "user", "content": user_text.strip()},
    ]
    try:
        raw = await provider.complete(messages)
        return _parse_issue_query_spec(raw)
    except Exception:
        return _fallback_query_spec(user_text)


def _fallback_query_spec(text: str) -> IssueQuerySpec:
    """LLM 不可用时的正则规则降级。"""
    spec = IssueQuerySpec()
    t = (text or "").lower()
    import re as _re
    m = _re.search(r"(\d+)\s*条", t)
    if m:
        spec.limit = max(1, min(100, int(m.group(1))))
    if "待处理" in t or "待办" in t:
        spec.status = "todo"
    elif "进行中" in t:
        spec.status = "in_progress"
    elif "已完成" in t:
        spec.status, spec.include_closed = "done", True
    elif "已取消" in t:
        spec.status, spec.include_closed = "cancelled", True
    if "最近更新" in t:
        spec.sort_by = "updated_desc"
    elif "优先级" in t:
        spec.sort_by = "priority_desc"
    else:
        spec.sort_by = "created_desc"
    return spec
