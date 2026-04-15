# -*- coding: utf-8 -*-
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pm_work_calendar import (
    fetch_pm_calendar_http,
    is_pm_workday,
    previous_pm_workday,
    try_load_pm_calendar,
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
# 与 PM 后端 data/gamedev_pm_data.json 默认相对路径（含 holidays / workdays）
_DEFAULT_PM_DATA_REL = "pm-system/backend/data/gamedev_pm_data.json"
_CONFIG_NAME = "work_report_assistant_config.json"
_ROSTER_NAME = "work_report_assistant_roster.json"
_CHAT_PATH = "/api/v1/chat"
_MAX_MARKDOWN_CHUNK = 12000
_WEBHOOK_SCRIPT = os.path.join(
    _ROOT,
    ".cursor",
    "skills",
    "dingtalk-actions",
    "scripts",
    "send_result_webhook.py",
)


def _log(line: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[work_report_assistant] {ts} {line}"
    print(msg, flush=True)
    log_dir = os.path.join(_THIS_DIR, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_name = f"work_report_assistant_{datetime.now().strftime('%Y%m%d')}.log"
        with open(os.path.join(log_dir, log_name), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_config() -> dict[str, Any]:
    path = os.path.join(_THIS_DIR, _CONFIG_NAME)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"missing {_CONFIG_NAME} (copy from .example)")
    return _load_json(path)


def _load_roster() -> dict[str, Any]:
    path = os.path.join(_THIS_DIR, _ROSTER_NAME)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"missing {_ROSTER_NAME}")
    return _load_json(path)


def previous_workday_weekday_only(today: date) -> date:
    """未配置 PM 日历时：前一工作日 = 向前跳过周末（与旧逻辑一致）。"""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _load_pm_calendar_tuple(cfg: dict[str, Any]) -> Optional[Tuple[List[Dict[str, Any]], List[str], str]]:
    """
    加载 PM 假日/调休：优先请求 PmSystem 的 /api/pm-calendar，失败再读本地 gamedev_pm_data.json。
    成功返回 (holidays, workdays, source_label)，source_label 为请求 URL 或本地路径。
    """
    timeout = int(cfg.get("pm_calendar_timeout_sec") or 15)
    full_url = (os.environ.get("WORK_REPORT_PM_CALENDAR_URL") or "").strip()
    base = (os.environ.get("WORK_REPORT_PM_CALENDAR_BASE_URL") or "").strip()
    if not base:
        base = (cfg.get("pm_calendar_base_url") or "").strip()
    if full_url:
        loaded = fetch_pm_calendar_http(full_url, timeout)
        if loaded:
            return loaded
    elif base:
        url = base.rstrip("/") + "/api/pm-calendar"
        loaded = fetch_pm_calendar_http(url, timeout)
        if loaded:
            return loaded
    path = (os.environ.get("WORK_REPORT_PM_DATA_JSON") or "").strip()
    if not path:
        path = (cfg.get("pm_data_json_path") or "").strip()
    if not path:
        path = _DEFAULT_PM_DATA_REL
    loaded = try_load_pm_calendar(path, _ROOT)
    if not loaded:
        return None
    h, w, resolved = loaded
    return (h, w, resolved)


def scenario_date_context(
    scenario_id: str,
    today: date,
    cal: Optional[Tuple[List[Dict[str, Any]], List[str], str]] = None,
) -> dict[str, str]:
    """返回模板用到的日期字符串（YYYY-MM-DD）。"""
    if scenario_id == "morning_digest":
        if cal is not None:
            h, w, _resolved = cal
            p = previous_pm_workday(today, h, w)
            src = "pm_data"
        else:
            p = previous_workday_weekday_only(today)
            src = "fallback_weekday"
        return {
            "prev_workday": p.isoformat(),
            "today": today.isoformat(),
            "calendar_source": src,
        }
    if scenario_id == "weekly_material":
        start = monday_of_week(today)
        return {
            "range_start": start.isoformat(),
            "range_end": today.isoformat(),
            "today": today.isoformat(),
        }
    if scenario_id == "weekly_px_insight":
        this_mon = monday_of_week(today)
        last_mon = this_mon - timedelta(days=7)
        last_sun = this_mon - timedelta(days=1)
        return {
            "range_start": last_mon.isoformat(),
            "range_end": last_sun.isoformat(),
            "today": today.isoformat(),
        }
    if scenario_id == "weekly_ai_px_report":
        start = monday_of_week(today)
        return {
            "range_start": start.isoformat(),
            "range_end": today.isoformat(),
            "today": today.isoformat(),
        }
    raise ValueError(f"unknown scenario: {scenario_id}")


def format_roster_lines(roster_data: dict[str, Any]) -> str:
    groups = roster_data.get("groups") or {}
    lines = []
    for gname, names in groups.items():
        if isinstance(names, list):
            lines.append(f"- {gname}：{'、'.join(names)}")
    return "\n".join(lines)


def build_message(scenario_id: str, roster_data: dict[str, Any], ctx: dict[str, str]) -> str:
    roster_lines = format_roster_lines(roster_data)
    tech_note = (roster_data.get("tech_focus_note") or "").strip()
    pmo_ref = roster_data.get("pmo_template_ref") or "performeval/PMO_管线汇报模板.md"

    hard = (
        "【硬约束】必须基于系统中汇报正文全文检索与归纳，禁止仅用系统摘要或标题级信息作答。"
        "若只能拿到摘要，须明确说明并列出缺口。\n"
        f"【权威模板口径（仓库路径）】{pmo_ref}\n"
        "【汇总范围仅限下列人员】\n"
        f"{roster_lines}\n"
    )

    if scenario_id == "morning_digest":
        pw = ctx["prev_workday"]
        cal_src = ctx.get("calendar_source") or "fallback_weekday"
        if cal_src == "pm_data":
            cal_line = "【日历口径】「上一工作日」以 PM 系统「假日与调休管理」为准（与版本规划工作日历一致）。\n"
        else:
            cal_line = (
                "【日历口径】未读取到 PM 主数据文件时，「上一工作日」暂按周一至周五（不含周末）推算；"
                "请在 work_report_assistant_config.json 中配置 pm_data_json_path，或设置环境变量 WORK_REPORT_PM_DATA_JSON。\n"
            )
        return (
            f"{hard}\n"
            "【任务类型】工作日早报\n"
            f"{cal_line}"
            f"【目标日报日期】{pw}（前一工作日，相对运行日）\n\n"
            "【非技术组】请对照模板「四要素」与上下游表述，识别是否存在信息不对称或可对齐而未对齐之处。\n"
            f"【技术组】{tech_note}\n\n"
            "【输出结构】\n"
            "1) 上述范围内人员在目标日期的日报提交情况（已交/未交）\n"
            "2) 未交名单（姓名）\n"
            "3) 从正文中识别的信息不对称或风险点（分人分点，技术组侧重在做什么与阻塞是否说清）\n"
        )

    if scenario_id == "weekly_material":
        title_line = f"# {ctx['range_start']} ~ {ctx['range_end']} 周报素材"
        return (
            f"{hard}\n"
            "【任务类型】周报素材\n"
            f"【时间窗】{ctx['range_start']} 至 {ctx['range_end']}（含）内，上述范围内人员日/周/月报全文。\n\n"
            "【格式铁律（必须严格遵守）】\n"
            "- 回复必须是 Markdown 格式\n"
            f"- 第一行：{title_line}\n"
            "- 每个大节用 ## 标题\n"
            "- 每个分组用 **加粗组名** 起头\n"
            "- 所有信息用「- 」无序列表，每条一行，简洁到位\n"
            "- 每条格式：「- **关键词/事项**：一句话说清（姓名）」\n"
            "- 禁止大段叙述、禁止贴原文、禁止超过两行的段落\n"
            "- 没有信息的组写「- 本周无相关产出」\n\n"
            "【正文结构（严格按此四节，不增不减）】\n\n"
            "## 一、分组核心产出 & 近期计划\n\n"
            "按下列四组，每组先写 **组名**，下面用列表逐条写核心产出和近期计划：\n\n"
            "**UE（体验组）**\n"
            "- 产出1：xxx（姓名）\n"
            "- 近期计划：xxx\n\n"
            "**运营**\n"
            "- 产出1：xxx（姓名）\n\n"
            "**数据**\n"
            "- 产出1：xxx（姓名）\n\n"
            "**技术**\n"
            "- 产出1：xxx（姓名）\n"
            "（技术组不按 PMO 管线模板，写在做什么和近期计划即可）\n\n"
            "## 二、管线进展\n\n"
            "提炼版本进度与风险，用列表，每条一个要点：\n"
            "- **版本/阶段**：进度一句话 + 风险一句话\n\n"
            "## 三、卡点与风险汇总\n\n"
            "跨组阻塞、依赖、延期，每条标注来源：\n"
            "- **问题**：描述（来源组/姓名）\n\n"
            "## 四、AI 应用汇总\n\n"
            "相似场景聚类，每条后标注姓名：\n"
            "- **场景**：效果描述（姓名1、姓名2）\n\n"
            "信息不足处注明缺口。\n"
        )

    if scenario_id == "weekly_px_insight":
        return (
            f"{hard}\n"
            "【任务类型】产品体验提炼（周一）\n"
            f"【时间窗】上一自然周 {ctx['range_start']} 至 {ctx['range_end']}（含）内日/周/月报全文。\n\n"
            "【范围排除】技术组（杨玉涛、车君怡、乔子骜）不纳入本次统计，跳过他们的数据。\n\n"
            "【格式铁律】\n"
            "- 回复必须是 Markdown 格式\n"
            "- 禁止使用表格，全部用列表 + 加粗\n"
            "- 禁止逐日展开明细（如「3/30 本品3h; 3/31 本品5h...」），只写汇总值\n"
            "- 禁止贴原文、禁止大段叙述\n\n"
            "【正文结构（严格按此三节，不增不减）】\n\n"
            "## 一、体验时长汇总\n\n"
            "按小组每人一行，只写周汇总值：\n"
            "**组名**\n"
            "- 姓名：本品 Xh / 竞品 Xh（竞品名）\n"
            "（禁止写每日明细，禁止展开日期维度）\n\n"
            "## 二、产品体验洞察（聚类）\n\n"
            "从全文抽取「产品体验洞察」（痛点、传播观察、竞品思考等），"
            "将相似内容聚类合并，每条格式：\n"
            "- **主题关键词**：一句话描述（姓名1、姓名2）\n\n"
            "## 三、贡献统计\n\n"
            "按小组统计每人贡献了几条洞察：\n"
            "**组名**\n"
            "- 姓名：X 条\n"
        )

    if scenario_id == "weekly_ai_px_report":
        return (
            f"{hard}\n"
            "【任务类型】AI 应用周报（周五）\n"
            f"【时间窗】当周工作日 {ctx['range_start']} 至 {ctx['range_end']}（含）内所有日/周/月报全文。\n\n"
            "【格式铁律】\n"
            "- 回复必须是 Markdown 格式\n"
            "- 禁止使用表格，全部用列表 + 加粗\n"
            "- 只汇总 AI 使用，不要写产品体验相关内容（时长、洞察、竞品等一律不要）\n"
            "- 禁止贴原文、禁止大段叙述\n\n"
            "【正文结构（严格只有以下内容）】\n\n"
            "## 一、AI 应用汇总（聚类）\n\n"
            "从全文抽取所有 AI 使用记录，将相似场景聚类。\n"
            "每个聚类主题用 ### 三级标题单独一行，下面用 bullet 列出具体内容。示例：\n\n"
            "### AI 视频/图片素材生成\n"
            "- 用 Seedance 2.0 生成摩托车 BOSS 设计参考（胡亚飞）\n"
            "- 用 AI 生成壮汉形象，计划完成脚本与视频 demo（赵宇驰）\n\n"
            "### Cursor 辅助开发\n"
            "- 用 Cursor Skill 书写 iOS 活动页文案（张颖）\n\n"
            "以此类推，每个聚类一个 ### 标题 + bullet 列表。\n\n"
            "## 二、各组 AI 使用条数统计\n\n"
            "按小组统计每人条数，格式：\n"
            "### 组名\n"
            "- 姓名：X 条\n\n"
            f"【技术组】{tech_note}\n"
        )

    raise ValueError(f"unknown scenario: {scenario_id}")


def scenario_title(scenario_id: str, ctx: dict[str, str] | None = None) -> str:
    if scenario_id == "weekly_material" and ctx:
        return f"{ctx.get('range_start', '')}~{ctx.get('range_end', '')} 周报素材"
    titles = {
        "morning_digest": "日志助手-工作日早报",
        "weekly_material": "日志助手-周报素材",
        "weekly_px_insight": "日志助手-产品体验提炼",
        "weekly_ai_px_report": "日志助手-AI应用周报",
    }
    if scenario_id not in titles:
        raise ValueError(f"unknown scenario: {scenario_id}")
    return titles[scenario_id]


def post_chat(base_url: str, api_key: str, message: str, timeout: int) -> str:
    url = base_url.rstrip("/") + _CHAT_PATH
    body = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"network error: {e}") from e

    data = json.loads(raw)
    if "error" in data:
        raise RuntimeError(str(data.get("error")))
    reply = data.get("reply")
    if not reply:
        raise RuntimeError(f"unexpected response: {raw[:500]}")
    return str(reply)


def chunk_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            parts.append(rest)
            break
        cut = rest.rfind("\n\n", 0, max_len)
        if cut < max_len // 2:
            cut = rest.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        parts.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    return [p for p in parts if p]


def send_dingtalk_markdown(title: str, text: str, webhook_key: str) -> None:
    if not os.path.isfile(_WEBHOOK_SCRIPT):
        raise FileNotFoundError(f"missing webhook script: {_WEBHOOK_SCRIPT}")

    chunks = chunk_text(text, _MAX_MARKDOWN_CHUNK)
    n = len(chunks)
    for i, chunk in enumerate(chunks):
        t = title[:50]
        if n > 1:
            t = f"{title} ({i + 1}/{n})"[:50]
        env = os.environ.copy()
        env["DINGTALK_TITLE"] = t
        env["DINGTALK_WEBHOOK_KEY"] = webhook_key

        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="wra_", text=False)
        try:
            os.close(fd)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(chunk)
            r = subprocess.run(
                [sys.executable, _WEBHOOK_SCRIPT, tmp_path],
                cwd=_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                raise RuntimeError(f"webhook failed: {err}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="work-report chat -> DingTalk webhook")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=[
            "morning_digest",
            "weekly_material",
            "weekly_px_insight",
            "weekly_ai_px_report",
        ],
    )
    parser.add_argument(
        "--date",
        default="",
        help="override today as YYYY-MM-DD (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only print message, no HTTP",
    )
    args = parser.parse_args()

    if args.date:
        today = date.fromisoformat(args.date)
    else:
        today = date.today()

    cfg = _load_config()
    roster_data = _load_roster()
    timeout = int(cfg.get("default_timeout_sec") or 300)
    wk = (cfg.get("webhook_key") or "hr").strip()

    cal = _load_pm_calendar_tuple(cfg)
    if args.scenario == "morning_digest":
        if cal is not None:
            _log(f"pm calendar loaded: {cal[2]}")
        else:
            _log("pm calendar: file not found, using Mon-Fri weekday fallback")
        if cal is not None:
            h, w, _rp = cal
            if not is_pm_workday(today, h, w):
                _log(f"skip morning_digest: {today.isoformat()} is not PM workday (holiday/weekend)")
                return 0
        else:
            if today.weekday() >= 5:
                _log(f"skip morning_digest: {today.isoformat()} is weekend (no PM calendar, Mon-Fri only)")
                return 0

    ctx = scenario_date_context(
        args.scenario,
        today,
        cal if args.scenario == "morning_digest" else None,
    )
    message = build_message(args.scenario, roster_data, ctx)
    title = scenario_title(args.scenario, ctx)

    if args.dry_run:
        sys.stdout.buffer.write((message + "\n").encode("utf-8"))
        return 0

    api_key = (os.environ.get("WORK_REPORT_API_KEY") or cfg.get("api_key") or "").strip()
    if not api_key:
        _log("error: set WORK_REPORT_API_KEY or api_key in config")
        return 1

    base_url = (cfg.get("base_url") or os.environ.get("WORK_REPORT_BASE_URL") or "").strip()
    if not base_url:
        _log("error: base_url missing")
        return 1

    _log(f"scenario={args.scenario} today={today.isoformat()} webhook_key={wk}")

    try:
        reply = post_chat(base_url, api_key, message, timeout)
    except Exception as e:
        _log(f"chat API error: {e}")
        return 1

    _log(f"reply length={len(reply)}")
    try:
        send_dingtalk_markdown(title, reply, wk)
    except Exception as e:
        _log(f"dingtalk error: {e}")
        return 1

    _log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
