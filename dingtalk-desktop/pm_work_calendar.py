# -*- coding: utf-8 -*-
"""
与 PM 系统「版本规划 / 假日与调休」同一套工作日判定逻辑。
参考：pm-system/ui/components/version-planning-view.js isWorkday()
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

# 与 PM 前端一致：最多向前找上一工作日，避免异常数据死循环
_MAX_PREV_SCAN_DAYS = 400


def _date_str(d: date) -> str:
    return d.isoformat()


def is_pm_workday(
    d: date,
    holidays: Optional[List[Dict[str, Any]]],
    workdays: Optional[List[str]],
) -> bool:
    """某日是否为工作日（法定假日、调休上班、周末规则与 PM 前端一致）。"""
    date_str = _date_str(d)
    hol = holidays or []
    for h in hol:
        if not isinstance(h, dict):
            continue
        start = h.get("start")
        end = h.get("end")
        if isinstance(start, str) and isinstance(end, str) and start <= date_str <= end:
            return False

    wd = workdays or []
    if date_str in wd:
        return True

    # 周六、周日：Python weekday 5=周六 6=周日
    if d.weekday() >= 5:
        return False
    return True


def previous_pm_workday(
    today: date,
    holidays: Optional[List[Dict[str, Any]]],
    workdays: Optional[List[str]],
) -> date:
    """从 today 的前一天起向前找最近一个 PM 工作日。"""
    d = today - timedelta(days=1)
    for _ in range(_MAX_PREV_SCAN_DAYS):
        if is_pm_workday(d, holidays, workdays):
            return d
        d -= timedelta(days=1)
    raise ValueError("在日历中未找到上一工作日（请检查假日/调休数据）")


def load_holidays_workdays_from_pm_data(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """从 PM 主数据 JSON 根对象解析 holidays / workdays。"""
    raw_h = data.get("holidays")
    raw_w = data.get("workdays")
    holidays: List[Dict[str, Any]] = raw_h if isinstance(raw_h, list) else []
    workdays: List[str] = raw_w if isinstance(raw_w, list) else []
    return holidays, workdays


def load_pm_calendar_file(path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return [], []
    return load_holidays_workdays_from_pm_data(data)


def resolve_pm_data_path(configured: str, root: str) -> str:
    """configured 为绝对路径或相对 root 的路径。"""
    p = configured.strip()
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(root, p))


def try_load_pm_calendar(
    pm_data_json_path: str,
    root: str,
) -> Optional[Tuple[List[Dict[str, Any]], List[str], str]]:
    """
    若文件存在且可读则返回 (holidays, workdays, resolved_path)，否则 None。
    """
    if not pm_data_json_path or not pm_data_json_path.strip():
        return None
    resolved = resolve_pm_data_path(pm_data_json_path, root)
    if not os.path.isfile(resolved):
        return None
    try:
        h, w = load_pm_calendar_file(resolved)
    except (OSError, json.JSONDecodeError):
        return None
    return h, w, resolved


def fetch_pm_calendar_http(api_url: str, timeout_sec: int = 15) -> Optional[Tuple[List[Dict[str, Any]], List[str], str]]:
    """
    从 PmSystem 后端 GET 拉取 /api/pm-calendar（与 PM 主数据同源）。
    成功返回 (holidays, workdays, source_label)；失败返回 None。
    """
    url = api_url.strip()
    if not url:
        return None
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=max(3, int(timeout_sec))) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    h, w = load_holidays_workdays_from_pm_data(data)
    return h, w, url
