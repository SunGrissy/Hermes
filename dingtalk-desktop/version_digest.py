# -*- coding: utf-8 -*-
"""Version status digest - fetch from PmSystem dashboard and push via webhook.

正文与定时管线任务同源：`_push_versions_webhook_at_dm` 的 `render_version_status_markdown`
+ 管线 checklist / 内部清单后缀；PMO/管线/PLD 走 `digest_config`+webhook_config，版本快报走各版本 `progressNotifyWebhooks`。
@ 人按 `version_digest_webhook_at_policy` 与 webhook 下标一一对应（见配置说明），不再对三群使用同一套管线 @。

Usage:
    py version_digest.py              # fetch + send
    py version_digest.py --dry-run    # fetch + print only
    py version_digest.py --dry-run --audience pm   # 只预览 PM 受众正文（不发）
    py version_digest.py --version-name 五一版     # 单版本：三群+管线群各一条（读 digest_config pm_system_url）
    py version_digest.py --assistant-batch        # 助理群连发4条（见 version_digest_assistant_batch）
    py version_digest.py --audience-sweep           # 助理群连发4条：同版本×四受众（核对标题）
    py version_digest.py --output x.md  # save to file
    py version_digest.py --ignore-workday  # 假日也发（补发）
    py version_digest.py --mode pmo-evening --dry-run  # PMO晚报（默认同早间 producer 机器人，见 digest_config）
    py version_digest.py --mode pm-evening --dry-run   # 管线晚报（PMO 群 @ PM+APM，行动视角）
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# [AgentVchg Task] 开始时间: 2026-04-01 20:20
# [AgentVchg Task] 任务目标: VCHG-001 双推送（早上现状+傍晚今日变化）
# 单版本合并 digest 三群 + 版本 progressNotifyWebhooks 时，管线群 webhook 的虚拟键（见 version_digest_webhook_at.__progress__）
_PROGRESS_WC_KEY = '__progress__'

_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_DIR, 'digest_config.json')
_TEMPLATE_PATH = os.path.join(_DIR, 'message_templates.json')
_STATE_PATH_DEFAULT = os.path.join(_DIR, 'data', 'dingtalk', 'version_digest_state.json')
# VersionDigest 文末固定引导 PM 打开前台（与定时管线 digest 的 pm_system_url 可不同）
VERSION_DIGEST_PM_DETAIL_URL = 'http://192.168.20.160:8112/index.html'

_DEFAULT_TEMPLATE = {
    'title': '## 版本状态 [{timestamp}]',
    'top_separator': '---',
    'show': {
        'milestone': True,
        'overdue_nodes': True,
        'risks': True,
    },
    'limits': {'risks': 3, 'overdue_nodes': 5},
    'separator': '---',
    'footer': '###### ※ 小秘书提醒',
}

# 与 pm-system `version_progress_notify` 渲染文末一致，供 append_pm_detail_footer 插入「请 PM」块
DIGEST_MD_FOOTER = '\n\n---\n\n###### ※ 小秘书提醒'


def _load_template():
    if os.path.exists(_TEMPLATE_PATH):
        try:
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Support both unified file (version_digest key) and legacy flat file
            tmpl = data.get('version_digest', data)
            tmpl.pop('_comment', None)
            return tmpl
        except Exception as e:
            print(f'[warn] failed to load template: {e}, using defaults', flush=True)
    return _DEFAULT_TEMPLATE

PIPELINE_STAGES = [
    ('planning', '规划'),
    ('feasibility', '可行性初评'),
    ('capacity', '容量评估'),
    ('scoping', '规格锁定'),
    ('dev', '开发'),
    ('acceptance', '验收'),
    ('goLiveReview', '上线评审'),
    ('freezeConfirm', '封版确认'),
    ('releaseTesting', '发布测试'),
    ('release', '发版'),
    ('retro', '复盘'),
]

# 与 pm-system 前端 PIPELINE_STAGES 偏移一致，用于推算「按时间应处于」的节点
STAGE_SCHEDULE_SPEC: List[Tuple[str, str, str, int]] = [
    ('planning', '规划', 'start', -7),
    ('feasibility', '可行性初评', 'start', -3),
    ('capacity', '容量评估', 'start', -2),
    ('scoping', '规格锁定', 'start', -1),
    ('dev', '开发', 'release', -10),
    ('acceptance', '验收', 'release', -7),
    ('goLiveReview', '上线评审', 'release', -5),
    ('freezeConfirm', '封版确认', 'release', -3),
    ('releaseTesting', '发布测试', 'release', -1),
    ('release', '发版', 'release', 0),
]

# 钉钉 Markdown 对「emoji + **」粘连解析易错位，容量告警仅用文字标记
ALERT_ICONS = {
    'critical': '（容量透支）',
    'warning': '（容量偏高）',
    'normal': '',
}

# 钉钉机器人 Markdown 需用 <font color="#RRGGBB"> 才有颜色，纯中文「红/黄」不会着色
_DT_COLOR_RED = '#dc2626'
_DT_COLOR_AMBER = '#d97706'
_DT_COLOR_BLUE = '#2563eb'
_DT_COLOR_GRAY = '#64748b'
_DT_COLOR_GREEN = '#16a34a'
# 数据快照 #### 标题默认色（容量正常时），比浅灰更易辨认
_DT_COLOR_SNAPSHOT_NAVY = '#1e3a8a'


def _parse_iso_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _dt_font(color_hex: str, inner: str) -> str:
    """为钉钉 Markdown 包一层字体颜色（避免与 ** 混用 emoji 导致错位）。"""
    if not inner:
        return inner
    return f'<font color="{color_hex}">{inner}</font>'


def _dt_font_bold(color_hex: str, inner: str) -> str:
    """着色行同时加粗（标题类更易扫读）。"""
    if not inner:
        return inner
    t = inner.strip()
    if not (t.startswith('**') and t.endswith('**')):
        t = f'**{t}**'
    return _dt_font(color_hex, t)


def _dt_heading4(color_hex: str, title: str) -> str:
    """四级标题：#### + 着色 + 加粗。"""
    return f'#### {_dt_font_bold(color_hex, title)}'


# 列表前缀（U+2022 实心圆点，比「·」更易辨认）
_VD_BULLET = '\u2022 '


def _append_change_digest_bullets(lines: List[str], items: List[str]) -> None:
    """钉钉 Markdown 中单 \\n 常被渲染成同一段；条目间插入空行以形成分段换行。"""
    for i, x in enumerate(items):
        lines.append(f'{_VD_BULLET}{x}')
        if i < len(items) - 1:
            lines.append('')


class FetchAuthError(Exception):
    """Raised when PM API authentication fails."""


def _load_config():
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _now_mmdd_hhmm() -> str:
    return datetime.now().strftime('%m/%d %H:%M')


def _json_stable_hash(obj: Any) -> str:
    try:
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        s = str(obj)
    return _sha256_text(s)


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def _state_path_from_config(config: dict) -> str:
    p = str(config.get('version_change_state_file') or '').strip()
    if not p:
        return _STATE_PATH_DEFAULT
    if os.path.isabs(p):
        return p
    return os.path.join(_DIR, p)


def _load_state(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _state_scope_key(pm_url: str, version_id: str) -> str:
    return f"{pm_url.rstrip('/')}::{str(version_id or '').strip()}"


def _get_scoped_state(state: dict, pm_url: str, version_id: str) -> dict:
    if not isinstance(state, dict):
        return {}
    scopes = state.get('version_scopes')
    if not isinstance(scopes, dict):
        scopes = {}
        state['version_scopes'] = scopes
    key = _state_scope_key(pm_url, version_id)
    cur = scopes.get(key)
    if not isinstance(cur, dict):
        cur = {}
        scopes[key] = cur
    return cur


def _load_release_template() -> dict:
    default = {
        'title': '## 版本已发布 [{timestamp}]',
        'line_1': '### {version_name}',
        'line_2': '该版本状态已变更为 **已发布**。',
        'line_3_snapshot': '今日早间检测到发布状态，今日晚间起不再推送该版本消息。',
        'line_3_change': '今日晚间检测到发布状态，明日早间起不再推送该版本消息。',
        'footer': '<font color="#999999">小秘书提醒</font>',
    }
    try:
        if os.path.isfile(_TEMPLATE_PATH):
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                root = json.load(f)
            obj = root.get('version_release') if isinstance(root, dict) else None
            if isinstance(obj, dict):
                out = dict(default)
                out.update(obj)
                return out
    except Exception:
        pass
    return default


def _load_change_template() -> dict:
    default = {
        'title': '## 今日变化 | {version_name}',
        'progress_header': '### 今日实际进展',
        'action_header': '### 行动提醒',
        'stale_header': '### 连续无变化',
        'no_change_line': '今日各版本暂无显著变化。',
        'lead_with_progress': '{version_name}：有推进，但仍需处理',
        'lead_no_progress': '{version_name}：今日无推进',
        'progress_fmt_done': '完成+{count}',
        'progress_fmt_dor_ready': 'DoR通过+{count}',
        'progress_fmt_assigned': '已指派+{count}',
        'progress_fmt_manual_checked': '节点勾选+{count}',
        'progress_fmt_in_progress': '开发中+{count}',
        'progress_fmt_testing': '测试中+{count}',
        'progress_fmt_draft_drop': '草稿减少{count}',
        'progress_fmt_delivery_groups': '交付检查完成+{count}（{names}）',
        'progress_fmt_delivery_cat_complete': (
            '<font color="#166534">**{label}完成**</font>：{count}项（{names}）'
        ),
        'progress_fmt_delivery_cat_progress': (
            '<font color="#1e40af">**{label}有进展**</font>：{count}项（{names}）'
        ),
        'action_fmt_blocked_names': '阻塞：{names}',
        'action_fmt_blocked_count': '阻塞 {count} 项',
        'action_fmt_unassigned': '未指派负责人 {count} 项 {pm_mention}',
        'action_fmt_dor_names': 'DoR 未就绪：{names} {pld_mention}',
        'action_fmt_dor_count': 'DoR 未就绪 {count} 项 {pld_mention}',
        'stale_fmt': '{version_name}：连续 {days} 个工作日无推进{detail}',
        'stale_detail_dor': '（DoR 未就绪：{names}）',
        'quiet_day_header': '### 看板无数据变化',
        'quiet_day_line1': '相对今日早间基线，未检测到指标或勾选上的变化。',
        'quiet_day_line2': (
            '{pm_mention} 请核对团队实际进展是否已在 PMS 中体现；'
            '若已推进但未同步，请尽快更新状态、节点与交付项，避免看板与事实脱节。'
        ),
        'followup_header': '### 早间关注暂无进展',
        'followup_pld_stale': '{pld_mention} 早间「PLD 行动项」（DoR）相对早间基线无变化，请抓紧推进。',
        'followup_pm_stale': '{pm_mention} 早间「PM 行动项」相对早间基线无变化，请抓紧跟进。',
        'followup_pipeline_stale': '早间「管线节点待办」相对早间基线无进展，请核对阻塞项与节点勾选。',
        'followup_combined_stale': (
            '早间「PLD 行动项」「PM 行动项」「管线节点待办」相对早间基线均无变化；'
            '若线下已推进，请同步更新 PMS。'
        ),
        'footer': '<font color="#999999">小秘书提醒 · {timestamp}</font>',
    }
    try:
        if os.path.isfile(_TEMPLATE_PATH):
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                root = json.load(f)
            obj = root.get('version_change') if isinstance(root, dict) else None
            if isinstance(obj, dict):
                out = dict(default)
                out.update(obj)
                return out
    except Exception:
        pass
    return default


def _load_pmo_evening_template() -> dict:
    default = {
        'dingtalk_title': '小秘书提醒 · PMO晚报[{mmdd}]',
        'body_layout': (
            '{heading}\n\n{sep}\n\n{hdr_progress}\n\n{sec_progress}\n\n'
            '{sep}\n\n{hdr_risk}\n\n{sec_risk}\n\n'
            '{sep}\n\n{footer}'
        ),
        'heading': '## PMO晚报[{mmdd}]',
        'separator': '---',
        'section_progress_header': '## <font color="#166534">今日实际进展</font>',
        'section_risk_header': '## <font color="#b45309">风险预警</font>',
        'footer': '###### \u203b 小秘书提醒 \u00b7 {mmdd} {hhmm}',
        'version_label': '**\u3010{version}\u3011**',
        'bullet': '\u2022 ',
        'body_progress_quiet': '\u2022 暂无相对早间的新增可量化进展。',
        'body_progress_first_run': '\u2022 首次运行已建基线，明日起对比晚间变化。',
        'body_progress_empty': '\u2022 暂无相对早间的新增可量化进展。',
        'suffix_risk_no_change': '<font color="#6b7280">（没变化项）</font>',
        'suffix_risk_stale': '<font color="#dc2626">（连续无变化风险）</font>',
        'suffix_risk_pending': '<font color="#b45309">（待跟进）</font>',
        'calendar_err_line': '\u2022 工作日历读取异常：{detail}',
        'body_risk_empty': '\u2022 暂无需要单独预警的「相对早间无变化」项。',
    }
    try:
        if os.path.isfile(_TEMPLATE_PATH):
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                root = json.load(f)
            obj = root.get('pmo_evening') if isinstance(root, dict) else None
            if isinstance(obj, dict):
                out = dict(default)
                out.update(obj)
                return out
    except Exception:
        pass
    return default


def _load_pm_evening_template() -> dict:
    default = {
        'dingtalk_title': '小秘书提醒 · 管线晚报[{mmdd}]',
        'body_layout': (
            '{heading}\n\n{sep}\n\n{hdr_action}\n\n{sec_action}\n\n'
            '{sep}\n\n{hdr_progress}\n\n{sec_progress}\n\n'
            '{sep}\n\n{hdr_followup}\n\n{sec_followup}\n\n'
            '{sep}\n\n{footer}'
        ),
        'heading': '## 管线晚报[{mmdd}]',
        'separator': '---',
        'section_action_header': '## <font color="#b45309">需处理事项</font>',
        'section_progress_header': '## <font color="#166534">今日进展</font>',
        'section_followup_header': '## <font color="#1e40af">跟进提醒</font>',
        'version_label': '**\u3010{version}\u3011**',
        'version_summary': '<font color="#6b7280">距发版{days_remaining}天 \u00b7 进度 {done}/{total}</font>',
        'version_summary_no_date': '<font color="#6b7280">进度 {done}/{total}</font>',
        'emoji_critical': '\u274c',
        'emoji_warning': '\u26a0\ufe0f',
        'emoji_ok': '\u2705',
        'color_blocked': '#dc2626',
        'color_unassigned': '#b45309',
        'color_dor': '#6b7280',
        'bullet': '\u2022 ',
        'body_action_empty': '\u2705 当前各版本无阻塞、未指派、DoR 缺口项。',
        'body_progress_quiet': '\u2022 暂无相对早间的新增可量化进展。',
        'body_progress_first_run': '\u2022 首次运行已建基线，明日起对比晚间变化。',
        'body_progress_empty': '\u2022 暂无相对早间的新增可量化进展。',
        'body_followup_empty': '\u2022 暂无需跟进的无变化项。',
        'calendar_err_line': '\u2022 工作日历读取异常：{detail}',
        'footer': '###### ※ 小秘书提醒 · {mmdd} {hhmm}',
    }
    try:
        if os.path.isfile(_TEMPLATE_PATH):
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                root = json.load(f)
            obj = root.get('pm_evening') if isinstance(root, dict) else None
            if isinstance(obj, dict):
                out = dict(default)
                out.update(obj)
                return out
    except Exception:
        pass
    return default


def _fmt_pm_evening(tpl: dict, key: str, default: str, **kwargs) -> str:
    raw = str(tpl.get(key) or default)
    try:
        return raw.format(**kwargs)
    except Exception:
        return default


def _fmt_pmo_evening(tpl: dict, key: str, default: str, **kwargs) -> str:
    raw = str(tpl.get(key) or default)
    try:
        return raw.format(**kwargs)
    except Exception:
        try:
            return default.format(**kwargs)
        except Exception:
            return raw


def _fmt_change_tpl(tpl: dict, key: str, default: str, **kwargs) -> str:
    raw = str(tpl.get(key) or default)
    try:
        return raw.format(**kwargs)
    except Exception:
        return default.format(**kwargs)


def _render_change_digest_quiet_day(
    *,
    version_name: str,
    pm_mention: str,
    timestamp: str,
) -> str:
    t = _load_change_template()
    vn = str(version_name or '').strip() or '多版本'
    pm = str(pm_mention or '').strip() or '@张梦君'
    ts = str(timestamp or '').strip()
    lines = [
        str(t.get('title') or '## 今日变化 | {version_name}').format(version_name=vn, timestamp=ts),
        '',
        str(t.get('quiet_day_header') or '### 看板无数据变化'),
        '',
        _fmt_change_tpl(
            t, 'quiet_day_line1', '相对今日早间基线，未检测到指标或勾选上的变化。',
            version_name=vn, pm_mention=pm, timestamp=ts,
        ),
        '',
        _fmt_change_tpl(
            t,
            'quiet_day_line2',
            '{pm_mention} 请核对团队实际进展是否已在 PMS 中体现；'
            '若已推进但未同步，请尽快更新状态、节点与交付项，避免看板与事实脱节。',
            version_name=vn, pm_mention=pm, timestamp=ts,
        ),
        '',
        str(t.get('footer') or '<font color="#999999">小秘书提醒 · {timestamp}</font>').format(
            version_name=vn, timestamp=ts, pm_mention=pm,
        ),
    ]
    return '\n'.join(lines)


def _load_online_template() -> dict:
    default = {
        'title': '## 版本已上线 [{timestamp}]',
        'line_1': '### {version_name}',
        'line_2': '发版留存引导已全部完成，版本已上线。',
        'line_3_snapshot': '请 PM 准备发版复盘，请 PLD 预约版本数据复盘。今日晚间起不再推送该版本消息。',
        'line_3_change': '请 PM 准备发版复盘，请 PLD 预约版本数据复盘。明日早间起不再推送该版本消息。',
        'footer': '<font color="#999999">小秘书提醒</font>',
    }
    try:
        if os.path.isfile(_TEMPLATE_PATH):
            with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                root = json.load(f)
            obj = root.get('version_online') if isinstance(root, dict) else None
            if isinstance(obj, dict):
                out = dict(default)
                out.update(obj)
                return out
    except Exception:
        pass
    return default


def _is_released_phase(phase: str) -> bool:
    p = str(phase or '').strip().lower()
    return p in ('released', 'release_done', 'done_released')


def _fetch_version_from_data(pm_url: str, api_key: Optional[str], version_id: str) -> Optional[dict]:
    try:
        raw = _api_get(f'{pm_url.rstrip("/")}/api/data', api_key=api_key)
    except Exception:
        return None
    data = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
    if not isinstance(data, dict):
        return None
    versions = data.get('versions')
    if not isinstance(versions, list):
        return None
    vid = str(version_id or '').strip()
    for v in versions:
        if not isinstance(v, dict):
            continue
        if str(v.get('id') or '').strip() == vid:
            return v
    return None


def _render_release_digest(
    *,
    version_name: str,
    detail_url: str,
    mode: str,
    pm_mention: str = '@张梦君',
    pld_mention: str = '@PLD',
) -> str:
    t = _load_release_template()
    now = _now_mmdd_hhmm()
    lines = [
        str(t.get('title') or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
        '',
        str(t.get('line_1') or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
        str(t.get('line_2') or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
    ]
    key3 = 'line_3_change' if mode == 'change' else 'line_3_snapshot'
    lines.append(
        str(t.get(key3) or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        )
    )
    if mode != 'change':
        lines.extend(['', f'请 PM 前往 [查看版本详情]({detail_url})。'])
    lines.extend([
        '',
        str(t.get('footer') or '<font color="#999999">小秘书提醒</font>').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
    ])
    return '\n'.join([x for x in lines if x is not None])


def _render_online_digest(
    *,
    version_name: str,
    detail_url: str,
    mode: str,
    pm_mention: str,
    pld_mention: str,
) -> str:
    t = _load_online_template()
    now = _now_mmdd_hhmm()
    lines = [
        str(t.get('title') or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
        '',
        str(t.get('line_1') or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
        str(t.get('line_2') or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
    ]
    key3 = 'line_3_change' if mode == 'change' else 'line_3_snapshot'
    lines.append(
        str(t.get(key3) or '').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        )
    )
    if mode != 'change':
        lines.extend(['', f'请 PM 前往 [查看版本详情]({detail_url})。'])
    lines.extend([
        '',
        str(t.get('footer') or '<font color="#999999">小秘书提醒</font>').format(
            timestamp=now, version_name=version_name, detail_url=detail_url,
            pm_mention=pm_mention, pld_mention=pld_mention,
        ),
    ])
    return '\n'.join([x for x in lines if x is not None])


def _collect_completed_groups(obj: Any, path_prefix: str = '') -> set:
    completed: set = set()
    if not isinstance(obj, dict):
        return completed

    def _scan(n: Any, path: str) -> Tuple[int, int]:
        if isinstance(n, dict):
            total = 0
            checked = 0
            for k, v in n.items():
                np = f'{path}.{k}' if path else str(k)
                t, c = _scan(v, np)
                total += t
                checked += c
            if total >= 2 and checked == total and path:
                completed.add(path)
            return total, checked
        if isinstance(n, list):
            total = 0
            checked = 0
            for i, v in enumerate(n):
                np = f'{path}[{i}]'
                t, c = _scan(v, np)
                total += t
                checked += c
            if total >= 2 and checked == total and path:
                completed.add(path)
            return total, checked
        if isinstance(n, bool):
            return 1, 1 if n else 0
        return 0, 0

    _scan(obj, path_prefix)
    return completed


def _is_release_guidance_complete(node_manual_checks: Any) -> bool:
    if not isinstance(node_manual_checks, dict):
        return False
    release_part = node_manual_checks.get('release')
    if not isinstance(release_part, dict):
        return False
    total, checked = 0, 0
    for p in _collect_completed_groups({'release': release_part}):
        if p.startswith('release'):
            # 仅用于判定：release 分支至少有一个组完成即可
            return True

    # 回退：若 release 里全是单 bool，直接全真判定
    def _count_bool(n: Any) -> Tuple[int, int]:
        if isinstance(n, dict):
            t = c = 0
            for v in n.values():
                tt, cc = _count_bool(v)
                t += tt
                c += cc
            return t, c
        if isinstance(n, list):
            t = c = 0
            for v in n:
                tt, cc = _count_bool(v)
                t += tt
                c += cc
            return t, c
        if isinstance(n, bool):
            return 1, 1 if n else 0
        return 0, 0

    total, checked = _count_bool(release_part)
    return total > 0 and checked == total


def _should_send_online_notice(scoped_state: dict, release_guidance_complete: bool) -> bool:
    if not release_guidance_complete:
        return False
    if str(scoped_state.get('online_notified_at') or '').strip():
        return False
    prev = bool(scoped_state.get('last_release_guidance_complete'))
    had_baseline = bool(
        scoped_state.get('morning') or scoped_state.get('latest') or scoped_state.get('latest_metrics')
    )
    if not prev and had_baseline:
        return True
    return False


def _should_send_release_notice(scoped_state: dict, current_phase: str) -> bool:
    if not _is_released_phase(current_phase):
        return False
    if str(scoped_state.get('released_notified_at') or '').strip():
        return False
    prev_phase = str(scoped_state.get('last_phase') or '').strip()
    had_baseline = bool(
        scoped_state.get('morning') or scoped_state.get('latest') or scoped_state.get('latest_metrics')
    )
    if prev_phase and not _is_released_phase(prev_phase):
        return True
    if not prev_phase and had_baseline:
        return True
    return False


def _extract_config_list(resp: dict) -> List[str]:
    if not isinstance(resp, dict):
        return []
    data = resp.get('data')
    if isinstance(data, list):
        return [str(x)[:10] for x in data if str(x).strip()]
    if isinstance(data, dict):
        out = data.get('items')
        if isinstance(out, list):
            return [str(x)[:10] for x in out if str(x).strip()]
    return []


def _fetch_workday_calendar(pm_url: str, api_key: Optional[str]) -> Tuple[List[str], List[str], Optional[str]]:
    """从 PMSystem 远端后端读取 holidays/workdays。"""
    try:
        base = pm_url.rstrip('/')
        holidays = _extract_config_list(_api_get(f'{base}/api/config/holidays', api_key=api_key))
        workdays = _extract_config_list(_api_get(f'{base}/api/config/workdays', api_key=api_key))
        return holidays, workdays, None
    except Exception as e:
        return [], [], str(e)


def _is_workday(d: date, holidays: set, workdays: set) -> bool:
    ds = d.strftime('%Y-%m-%d')
    if ds in workdays:
        return True
    if ds in holidays:
        return False
    return d.weekday() < 5


def _count_workdays_between(start_date: date, end_date: date, holidays: set, workdays: set) -> int:
    """统计 (start_date, end_date] 的工作日数量。"""
    if end_date <= start_date:
        return 0
    cur = start_date + timedelta(days=1)
    cnt = 0
    while cur <= end_date:
        if _is_workday(cur, holidays, workdays):
            cnt += 1
        cur += timedelta(days=1)
    return cnt


def _parse_holiday_ranges_from_pm(raw: Any) -> List[Tuple[str, str]]:
    """PM 配置 holidays：多为 [{start,end,...}, ...]；兼容 ['YYYY-MM-DD', ...]。"""
    out: List[Tuple[str, str]] = []
    if not raw:
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                s = str(item.get('start') or '')[:10]
                e = str(item.get('end') or s)[:10]
                if s:
                    out.append((s, e or s))
            elif isinstance(item, str) and item.strip():
                s = item.strip()[:10]
                out.append((s, s))
    return out


def _parse_workdays_set_from_pm(raw: Any) -> set:
    """PM 配置 workdays：调休上班日，字符串日期列表。"""
    if isinstance(raw, list):
        return {str(x)[:10] for x in raw if str(x).strip()}
    if isinstance(raw, dict) and isinstance(raw.get('items'), list):
        return {str(x)[:10] for x in raw['items'] if str(x).strip()}
    return set()


def _fetch_pm_calendar_for_workday(
    pm_url: str, api_key: Optional[str],
) -> Tuple[List[Tuple[str, str]], set, Optional[str]]:
    """拉取 PM holidays 区间 + workdays，用于早间是否推送。失败时 err 非空。"""
    try:
        base = pm_url.rstrip('/')
        h_resp = _api_get(f'{base}/api/config/holidays', api_key=api_key)
        w_resp = _api_get(f'{base}/api/config/workdays', api_key=api_key)
        h_raw = h_resp.get('data') if isinstance(h_resp, dict) else None
        w_raw = w_resp.get('data') if isinstance(w_resp, dict) else None
        return _parse_holiday_ranges_from_pm(h_raw), _parse_workdays_set_from_pm(w_raw), None
    except Exception as e:
        return [], set(), str(e)


def _is_pm_calendar_workday(
    d: date,
    holiday_ranges: List[Tuple[str, str]],
    workdays: set,
) -> bool:
    """与 pm-system VersionPlanningView.isWorkday 一致：调休 -> 上班；区间内 -> 假日；周末 -> 非工作日。"""
    ds = d.strftime('%Y-%m-%d')
    if ds in workdays:
        return True
    for s, e in holiday_ranges:
        if s <= ds <= e:
            return False
    if d.weekday() >= 5:
        return False
    return True


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _delivery_category_labels() -> Dict[str, str]:
    return {
        'code': '代码交付',
        'asset': '资源交付',
        'content': '内容交付',
        'performance': '性能与兼容',
        'submission': '提测流程',
    }


def _checkbox_signature(part: dict) -> str:
    if not isinstance(part, dict):
        return ''
    items: List[str] = []
    for k in sorted(part.keys()):
        v = part.get(k)
        if isinstance(v, bool):
            items.append(f'{k}={int(v)}')
    return '|'.join(items)


def _category_all_checked(part: dict) -> bool:
    if not isinstance(part, dict):
        return False
    vals = [v for v in part.values() if isinstance(v, bool)]
    return bool(vals) and all(vals)


def _extract_delivery_feature_states(features: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """feature_name -> category_key -> { complete, sig }"""
    labels = _delivery_category_labels()
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    if not isinstance(features, list):
        return out
    for f in features:
        if not isinstance(f, dict):
            continue
        fname = str(f.get('name') or '').strip() or '?'
        delivery = f.get('delivery') or {}
        if not isinstance(delivery, dict):
            continue
        fe: Dict[str, Dict[str, Any]] = {}
        for grp in labels.keys():
            part = delivery.get(grp)
            if not isinstance(part, dict) or not part:
                continue
            if not any(isinstance(v, bool) for v in part.values()):
                continue
            fe[grp] = {
                'complete': _category_all_checked(part),
                'sig': _checkbox_signature(part),
            }
        if fe:
            out[fname] = fe
    return out


def _format_feature_names_for_digest(names: List[str], *, max_names: int = 12) -> str:
    xs = [str(x).strip() for x in names if str(x).strip()]
    if not xs:
        return ''
    if len(xs) > max_names:
        return '、'.join(xs[:max_names]) + '等'
    if len(xs) == 1:
        return xs[0]
    if len(xs) == 2:
        return f'{xs[0]}、{xs[1]}'
    return '、'.join(xs)


def _delivery_diff_lines(
    tpl: dict,
    baseline_states: Dict[str, Dict[str, Any]],
    current_states: Dict[str, Dict[str, Any]],
) -> List[str]:
    """先输出全部「交付完成」，再输出全部「有进展」；类别顺序：代码>资源>内容>性能>提测。"""
    labels = _delivery_category_labels()
    complete_bucket: List[Tuple[str, List[str]]] = []
    progress_bucket: List[Tuple[str, List[str]]] = []
    for grp, label in labels.items():
        complete_names: List[str] = []
        progress_names: List[str] = []
        all_fnames = set(baseline_states.keys()) | set(current_states.keys())
        for fname in sorted(all_fnames):
            cur_cats = current_states.get(fname) or {}
            base_cats = baseline_states.get(fname) or {}
            if grp not in cur_cats:
                continue
            cur = cur_cats.get(grp) or {}
            base = base_cats.get(grp) if grp in base_cats else None
            base_complete = bool(base and base.get('complete'))
            base_sig = str((base or {}).get('sig') or '')
            cur_complete = bool(cur.get('complete'))
            cur_sig = str(cur.get('sig') or '')
            if cur_complete and (not base_complete):
                complete_names.append(fname)
            elif (not cur_complete) and cur_sig != base_sig:
                progress_names.append(fname)
        if complete_names:
            complete_names.sort()
            complete_bucket.append((label, complete_names))
        if progress_names:
            progress_names.sort()
            progress_bucket.append((label, progress_names))
    lines: List[str] = []
    for label, complete_names in complete_bucket:
        lines.append(
            _fmt_change_tpl(
                tpl,
                'progress_fmt_delivery_cat_complete',
                '<font color="#166534">**{label}完成**</font>：{count}项（{names}）',
                label=label,
                count=len(complete_names),
                names=_format_feature_names_for_digest(complete_names),
            )
        )
    for label, progress_names in progress_bucket:
        lines.append(
            _fmt_change_tpl(
                tpl,
                'progress_fmt_delivery_cat_progress',
                '<font color="#1e40af">**{label}有进展**</font>：{count}项（{names}）',
                label=label,
                count=len(progress_names),
                names=_format_feature_names_for_digest(progress_names),
            )
        )
    return lines


def _delivery_diff_lines_safe(
    tpl: dict,
    baseline_entry: Optional[dict],
    current_entry: Optional[dict],
) -> List[str]:
    if not isinstance(baseline_entry, dict):
        baseline_entry = {}
    if 'delivery_feature_states' not in baseline_entry:
        return []
    base_states = baseline_entry.get('delivery_feature_states')
    if not isinstance(base_states, dict):
        base_states = {}
    cur_raw = current_entry if isinstance(current_entry, dict) else {}
    cur_states = (
        cur_raw.get('delivery_feature_states')
        if isinstance(cur_raw.get('delivery_feature_states'), dict)
        else {}
    )
    return _delivery_diff_lines(tpl, base_states, cur_states)


def _build_metrics_map(
    versions: List[dict],
    *,
    users_by_id: Optional[Dict[str, dict]] = None,
    default_pm_user_id: str = '',
) -> Dict[str, dict]:
    out: Dict[str, dict] = {}

    def _count_manual_checks(obj) -> Tuple[int, int]:
        total = 0
        checked = 0
        if isinstance(obj, dict):
            for v in obj.values():
                t, c = _count_manual_checks(v)
                total += t
                checked += c
        elif isinstance(obj, list):
            for v in obj:
                t, c = _count_manual_checks(v)
                total += t
                checked += c
        elif isinstance(obj, bool):
            total = 1
            checked = 1 if obj else 0
        return total, checked

    users_by_id = users_by_id or {}
    pm_uid = str(default_pm_user_id or '').strip()
    pm_name = ''
    pm_mention = '@张梦君'
    if pm_uid and isinstance(users_by_id.get(pm_uid), dict):
        u_pm = users_by_id.get(pm_uid)
        pm_name = str(u_pm.get('name') or '').strip()
        ext = u_pm.get('externalIds') or u_pm.get('external_ids') or {}
        if not isinstance(ext, dict):
            ext = {}
        pm_mobile = (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u_pm.get('phone') or '').strip())
        if pm_mobile:
            pm_mention = f'@{pm_mobile}'
    if not pm_name:
        pm_name = '张梦君'
        if pm_mention == '@张梦君':
            pm_mention = '@张梦君'

    for v in versions or []:
        vid = str(v.get('id') or '').strip()
        name = str(v.get('name') or '').strip()
        if not vid or not name:
            continue
        fs = v.get('featureSummary') or {}
        if not isinstance(fs, dict):
            fs = {}
        total = int(fs.get('total') or 0)
        done = int(fs.get('done') or 0)
        dor_ready = int(fs.get('dorReady') or 0)
        unassigned = int(fs.get('unassignedCount') or 0)
        blocked = int(fs.get('blocked') or 0)
        status_bd = fs.get('statusBreakdown') or {}
        dor_not_ready = fs.get('dorNotReadyFeatures') or []
        blocked_details = fs.get('blockedDetails') or []
        manual_checks = v.get('nodeManualChecks') or {}
        manual_total, manual_checked = _count_manual_checks(manual_checks)
        completed_groups = sorted(_collect_completed_groups(manual_checks))
        delivery_completed_groups = [
            g for g in completed_groups
            if any(k in g.lower() for k in ('code', 'resource', 'content', 'release_prep', 'release_test'))
            or any(k in g for k in ('交付', '代码', '资源', '内容'))
        ]
        pld_uid = str(v.get('pldUserId') or v.get('pld_user_id') or '').strip()
        pld_name = ''
        pld_mention = '@PLD'
        if pld_uid and isinstance(users_by_id.get(pld_uid), dict):
            u_pld = users_by_id.get(pld_uid)
            pld_name = str(u_pld.get('name') or '').strip()
            ext = u_pld.get('externalIds') or u_pld.get('external_ids') or {}
            if not isinstance(ext, dict):
                ext = {}
            pld_mobile = (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u_pld.get('phone') or '').strip())
            if pld_mobile:
                pld_mention = f'@{pld_mobile}'
        if not pld_name:
            pld_name = 'PLD'
        delivery_feature_states = _extract_delivery_feature_states(v.get('features') or [])
        dr_raw = v.get('daysRemaining')
        days_remaining: Optional[int] = None
        if dr_raw is not None and str(dr_raw).strip() != '':
            try:
                days_remaining = int(dr_raw)
            except (TypeError, ValueError):
                days_remaining = None
        if days_remaining is None:
            rd = _parse_iso_date(v.get('releaseDate') or v.get('release_date'))
            if rd:
                days_remaining = (rd - date.today()).days
        nmc = v.get('nodeManualChecks') or v.get('node_manual_checks') or {}
        pipeline_node_sig = _json_stable_hash(nmc if isinstance(nmc, dict) else {})
        out[vid] = {
            'id': vid,
            'name': name,
            'total': total,
            'done': done,
            'dor_ready': dor_ready,
            'dor_gap': max(total - dor_ready, 0),
            'unassigned': max(unassigned, 0),
            'blocked': max(blocked, 0),
            'testing': int((status_bd if isinstance(status_bd, dict) else {}).get('testing') or 0),
            'in_progress': int((status_bd if isinstance(status_bd, dict) else {}).get('in_progress') or 0),
            'draft': int((status_bd if isinstance(status_bd, dict) else {}).get('draft') or 0),
            'manual_total': manual_total,
            'manual_checked': manual_checked,
            'completed_groups': completed_groups,
            'delivery_completed_groups': delivery_completed_groups,
            'delivery_feature_states': delivery_feature_states,
            'pm_name': pm_name,
            'pld_name': pld_name,
            'pm_mention': pm_mention,
            'pld_mention': pld_mention,
            'dor_not_ready_names': [
                str(f.get('name') or '').strip()
                for f in (dor_not_ready if isinstance(dor_not_ready, list) else [])
                if str(f.get('name') or '').strip()
            ],
            'blocked_names': [
                str(f.get('name') or f.get('featureName') or '').strip()
                for f in (blocked_details if isinstance(blocked_details, list) else [])
                if str(f.get('name') or f.get('featureName') or '').strip()
            ],
            'days_remaining': days_remaining,
            'pipeline_node_sig': pipeline_node_sig,
        }
    return out


def _followup_sig_pld(x: dict) -> str:
    return _sha256_text(
        json.dumps(
            {
                'dor_gap': int(x.get('dor_gap') or 0),
                'names': sorted(x.get('dor_not_ready_names') or []),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _followup_sig_pm(x: dict) -> str:
    return _sha256_text(
        json.dumps(
            {
                'u': int(x.get('unassigned') or 0),
                'b': int(x.get('blocked') or 0),
                'bn': sorted(x.get('blocked_names') or []),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _build_change_facts(
    baseline_map: Dict[str, dict],
    current_map: Dict[str, dict],
    stale_days: Optional[int],
    stale_threshold: int,
    config: Optional[dict] = None,
) -> Dict[str, Any]:
    progress: List[str] = []
    no_change: List[str] = []
    stale_alert: List[str] = []
    followup_stale: List[str] = []
    tpl = _load_change_template()
    if not current_map:
        return {
            'progress': progress,
            'no_change': no_change,
            'stale_alert': stale_alert,
            'followup_stale': followup_stale,
        }

    SEP_CN = '，'
    SEP_PAUSE = '、'

    cur_items = list(current_map.values())
    cur_items.sort(key=lambda x: x.get('name', ''))
    multi_version = len(current_map) > 1
    for c in cur_items:
        b = baseline_map.get(c['id']) or {}
        progressed_today = False
        if b:
            d_done = c['done'] - int(b.get('done') or 0)
            d_dor = c['dor_ready'] - int(b.get('dor_ready') or 0)
            d_unassigned = int(b.get('unassigned') or 0) - c['unassigned']
            d_manual = int(c.get('manual_checked') or 0) - int(b.get('manual_checked') or 0)
            d_in_progress = int(c.get('in_progress') or 0) - int(b.get('in_progress') or 0)
            d_testing = int(c.get('testing') or 0) - int(b.get('testing') or 0)
            d_draft_drop = int(b.get('draft') or 0) - int(c.get('draft') or 0)
            delivery_lines = _delivery_diff_lines_safe(tpl, b, c)
            cur_delivery = set(c.get('delivery_completed_groups') or [])
            base_delivery = set(b.get('delivery_completed_groups') or [])
            d_delivery_groups = sorted(cur_delivery - base_delivery)
            if (
                d_done > 0
                or d_dor > 0
                or d_unassigned > 0
                or d_manual > 0
                or d_in_progress > 0
                or d_testing > 0
                or d_draft_drop > 0
                or len(d_delivery_groups) > 0
                or len(delivery_lines) > 0
            ):
                progressed_today = True
                parts = []
                if d_done > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_done', '完成+{count}', count=d_done))
                if d_dor > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_dor_ready', 'DoR通过+{count}', count=d_dor))
                if d_unassigned > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_assigned', '已指派+{count}', count=d_unassigned))
                if d_manual > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_manual_checked', '节点勾选+{count}', count=d_manual))
                if d_in_progress > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_in_progress', '开发中+{count}', count=d_in_progress))
                if d_testing > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_testing', '测试中+{count}', count=d_testing))
                if d_draft_drop > 0:
                    parts.append(_fmt_change_tpl(tpl, 'progress_fmt_draft_drop', '草稿减少{count}', count=d_draft_drop))
                if d_delivery_groups:
                    shown = '、'.join(d_delivery_groups[:2])
                    parts.append(
                        _fmt_change_tpl(
                            tpl, 'progress_fmt_delivery_groups', '交付检查完成+{count}（{names}）',
                            count=len(d_delivery_groups), names=shown,
                        )
                    )
                prefix = f"{c['name']}：" if multi_version else ''
                if parts:
                    progress.append(f"{prefix}{SEP_CN.join(parts)}")
                for dl in delivery_lines:
                    progress.append(f"{prefix}{dl}" if prefix else dl)
        else:
            progressed_today = False

        detail_lines: List[str] = []
        if c['blocked'] > 0:
            bnames = c.get('blocked_names') or []
            if bnames:
                joined_b = SEP_PAUSE.join(bnames[:3])
                detail_lines.append(
                    _fmt_change_tpl(tpl, 'action_fmt_blocked_names', '阻塞：{names}', names=joined_b)
                )
            else:
                detail_lines.append(
                    _fmt_change_tpl(tpl, 'action_fmt_blocked_count', '阻塞 {count} 项', count=c['blocked'])
                )
        if c['unassigned'] > 0:
            pm_m = str(c.get('pm_mention') or '').strip() or '@张梦君'
            detail_lines.append(
                _fmt_change_tpl(
                    tpl, 'action_fmt_unassigned', '未指派负责人 {count} 项 {pm_mention}',
                    count=c['unassigned'], pm_mention=pm_m,
                )
            )
        if c['dor_gap'] > 0:
            pld_m = str(c.get('pld_mention') or '').strip() or '@PLD'
            dnames = c.get('dor_not_ready_names') or []
            if dnames:
                joined_d = SEP_PAUSE.join(dnames[:3])
                detail_lines.append(
                    _fmt_change_tpl(
                        tpl, 'action_fmt_dor_names', 'DoR 未就绪：{names} {pld_mention}',
                        names=joined_d, pld_mention=pld_m,
                    )
                )
            else:
                detail_lines.append(
                    _fmt_change_tpl(
                        tpl, 'action_fmt_dor_count', 'DoR 未就绪 {count} 项 {pld_mention}',
                        count=c['dor_gap'], pld_mention=pld_m,
                    )
                )
        if detail_lines:
            body = '\n'.join(f'  - {x}' for x in detail_lines)
            lead = _fmt_change_tpl(
                tpl, 'lead_with_progress', '{version_name}：有推进，但仍需处理', version_name=c['name']
            )
            if not progressed_today:
                lead = _fmt_change_tpl(
                    tpl, 'lead_no_progress', '{version_name}：今日无推进', version_name=c['name']
                )
            no_change.append(f"{lead}\n{body}")

        if b:
            vn = str(c.get('name') or '').strip()
            prefix = f'{vn}：' if multi_version else ''
            max_days_pipe = int(
                (config or {}).get('version_evening_pipeline_followup_max_days_remaining', 45)
                or 45
            )
            dr = c.get('days_remaining')
            dr_ok = dr is None or dr <= max_days_pipe
            bps = b.get('pipeline_node_sig') or ''
            cps = c.get('pipeline_node_sig') or ''
            pipe_same = (bps == cps) and dr_ok
            pld_same = _followup_sig_pld(b) == _followup_sig_pld(c)
            pm_same = _followup_sig_pm(b) == _followup_sig_pm(c)
            b_open = max(int(b.get('manual_total') or 0) - int(b.get('manual_checked') or 0), 0)
            morning_had_work = (
                int(b.get('dor_gap') or 0) > 0
                or int(b.get('unassigned') or 0) > 0
                or int(b.get('blocked') or 0) > 0
                or b_open > 0
            )

            combined = False
            if morning_had_work and pld_same and pm_same and pipe_same:
                line = _fmt_change_tpl(
                    tpl,
                    'followup_combined_stale',
                    (
                        '早间「PLD 行动项」「PM 行动项」「管线节点待办」相对早间基线均无变化；'
                        '若线下已推进，请同步更新 PMS。'
                    ),
                    version_name=vn,
                )
                followup_stale.append(f'{prefix}{line}' if prefix else line)
                combined = True

            if not combined:
                b_dor = int(b.get('dor_gap') or 0)
                c_dor = int(c.get('dor_gap') or 0)
                b_dn = tuple(sorted(b.get('dor_not_ready_names') or []))
                c_dn = tuple(sorted(c.get('dor_not_ready_names') or []))
                if b_dor > 0 and c_dor == b_dor and b_dn == c_dn:
                    line = _fmt_change_tpl(
                        tpl,
                        'followup_pld_stale',
                        '{pld_mention} 早间「PLD 行动项」（DoR）相对早间基线无变化，请抓紧推进。',
                        pld_mention=str(c.get('pld_mention') or '').strip() or '@PLD',
                        version_name=vn,
                    )
                    followup_stale.append(f'{prefix}{line}' if prefix else line)

                b_u = int(b.get('unassigned') or 0)
                c_u = int(c.get('unassigned') or 0)
                b_bk = int(b.get('blocked') or 0)
                c_bk = int(c.get('blocked') or 0)
                if (b_u > 0 or b_bk > 0) and c_u == b_u and c_bk == b_bk:
                    line = _fmt_change_tpl(
                        tpl,
                        'followup_pm_stale',
                        '{pm_mention} 早间「PM 行动项」相对早间基线无变化，请抓紧跟进。',
                        pm_mention=str(c.get('pm_mention') or '').strip() or '@张梦君',
                        version_name=vn,
                    )
                    followup_stale.append(f'{prefix}{line}' if prefix else line)

                b_open_pipe = max(int(b.get('manual_total') or 0) - int(b.get('manual_checked') or 0), 0)
                if b_open_pipe > 0 and bps and bps == cps and dr_ok:
                    line = _fmt_change_tpl(
                        tpl,
                        'followup_pipeline_stale',
                        '早间「管线节点待办」相对早间基线无进展，请核对阻塞项与节点勾选。',
                        version_name=vn,
                    )
                    followup_stale.append(f'{prefix}{line}' if prefix else line)

    if stale_days is not None and stale_days >= stale_threshold:
        ranked = sorted(
            cur_items,
            key=lambda x: (x['unassigned'] * 3 + x['dor_gap'] * 2 + x['blocked'] * 4, x['name']),
            reverse=True,
        )
        for c in ranked:
            risk = c['unassigned'] + c['dor_gap'] + c['blocked']
            if risk <= 0:
                continue
            dnames = c.get('dor_not_ready_names') or []
            detail = ''
            if dnames:
                joined_s = SEP_PAUSE.join(dnames[:2])
                detail = _fmt_change_tpl(
                    tpl, 'stale_detail_dor', '（DoR 未就绪：{names}）', names=joined_s
                )
            stale_alert.append(
                _fmt_change_tpl(
                    tpl, 'stale_fmt', '{version_name}：连续 {days} 个工作日无推进{detail}',
                    version_name=c['name'], days=stale_days, detail=detail,
                )
            )
            if len(stale_alert) >= 3:
                break

    return {
        'progress': progress[:25],
        'no_change': no_change[:5],
        'stale_alert': stale_alert[:3],
        'followup_stale': followup_stale[:10],
    }


def _resolve_llm_config() -> Tuple[str, str, str]:
    key = os.environ.get('LLM_API_KEY', '').strip()
    base = os.environ.get('LLM_API_BASE', '').strip()
    model = os.environ.get('LLM_MODEL', '').strip()
    if not key:
        palace_env = os.path.join(_DIR, '..', 'palace', '.env')
        if os.path.exists(palace_env):
            try:
                with open(palace_env, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip()
                        if k == 'PALACE_API_KEY' and v and not key:
                            key = v
                        elif k == 'PALACE_API_BASE' and v and not base:
                            base = v
                        elif k == 'PALACE_MODEL' and v and not model:
                            model = v
            except Exception:
                pass
    return key, (base or 'https://api.openai.com/v1'), (model or 'gpt-4o-mini')


def _call_llm_change_json(
    baseline_text: str,
    current_text: str,
    stale_days: Optional[int],
    stale_threshold: int,
) -> Optional[dict]:
    key, base, model = _resolve_llm_config()
    if not key:
        return None
    prompt = (
        '你是版本管线跟进助手。请基于早间基线与当前状态，输出 JSON。'
        '要求：短句、可执行、面向 PM/PLD。'
        'JSON schema:'
        '{"progress":[str],"no_change":[str],"stale_alert":[str],"next_action":str}.'
        f'当前连续无变化工作日: {stale_days if stale_days is not None else "unknown"}，'
        f'阈值: {stale_threshold}。'
        '\n--- baseline ---\n'
        + (baseline_text or '')[:7000]
        + '\n--- current ---\n'
        + (current_text or '')[:7000]
    )
    body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.2,
        'response_format': {'type': 'json_object'},
    }).encode('utf-8')
    req = urllib.request.Request(
        f'{base.rstrip("/")}/chat/completions',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        out = json.loads(resp.read().decode('utf-8'))
    txt = ((out.get('choices') or [{}])[0].get('message') or {}).get('content', '')
    if not txt:
        return None
    try:
        parsed = json.loads(txt)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None

def _load_webhook_config() -> dict:
    path = os.path.join(_DIR, 'webhook_config.json')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _notify_version_digest_all_skipped(pm_url: str, *, log_to_stdout: bool = True) -> bool:
    """早间多群因过滤后全部无可发正文时，向助理群机器人推一条说明（webhook_config.version_digest_assistant）。"""
    wc = _load_webhook_config()
    url = str(wc.get('version_digest_assistant') or '').strip()
    if not url:
        if log_to_stdout:
            print(
                '[version-digest] all webhooks skipped but assistant notify skipped: '
                'webhook_config.json missing version_digest_assistant',
                flush=True,
            )
        return False
    ts = datetime.now().strftime('%m/%d %H:%M')
    body = (
        f'## 早间版本推送已全部跳过 [{ts}]\n\n'
        '- 原因：配置的各群在过滤后均无有效正文（例如 PLD/版本快报无版本等）。\n'
        f'- 数据源：`{pm_url}`\n\n'
        '###### ※ 小秘书提醒'
    )
    title = f'小秘书提醒 · 早间版本推送跳过[{ts}]'
    r = send_via_webhook(
        body, url, quiet=not log_to_stdout, at_mobiles=None, markdown_title=title,
    )
    ok = bool(r.get('success'))
    if log_to_stdout:
        print(
            f'[version-digest] assistant skip-notify {"OK" if ok else "FAIL"}',
            flush=True,
        )
    return ok


def _collect_version_digest_webhooks_urls_only(config: dict) -> List[str]:
    """仅解析 URL 列表（未用 webhook_config 键名时）。"""
    raw = config.get('version_digest_webhooks')
    urls: List[str] = []
    if isinstance(raw, list):
        for u in raw:
            s = str(u).strip()
            if s:
                urls.append(s)
    if urls:
        seen = set()
        out: List[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out
    main = (config.get('version_digest_webhook') or '').strip()
    if main:
        urls.append(main)
    extra = config.get('version_digest_webhook_extra') or []
    if isinstance(extra, list):
        for u in extra:
            s = str(u).strip()
            if s:
                urls.append(s)
    if not urls:
        fb = (config.get('webhook_url') or '').strip()
        if fb:
            urls.append(fb)
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _collect_version_digest_targets(config: dict) -> Tuple[List[str], List[Optional[str]]]:
    """返回 (urls, webhook_config 键名)；键名为 None 表示走 legacy URL 列表 + 下标对齐 @ 策略。"""
    wc = _load_webhook_config()
    keys = config.get('version_digest_webhook_keys')
    if isinstance(keys, list) and keys:
        urls: List[str] = []
        key_out: List[Optional[str]] = []
        for k in keys:
            rawk = str(k).strip()
            if not rawk:
                continue
            u = str(wc.get(rawk) or '').strip()
            if u:
                urls.append(u)
                key_out.append(rawk)
            else:
                print(
                    f'[version-digest] webhook_config.json 缺少键 {rawk!r}，已跳过',
                    flush=True,
                )
        if urls:
            return urls, key_out
    urls = _collect_version_digest_webhooks_urls_only(config)
    return urls, [None] * len(urls)


def _collect_version_digest_webhooks(config: dict) -> List[str]:
    """版本状态推送 URL 列表（兼容旧调用）。"""
    urls, _ = _collect_version_digest_targets(config)
    return urls


def _dingtalk_mobile_from_user(u: Optional[dict]) -> str:
    if not u or not isinstance(u, dict):
        return ''
    ext = u.get('externalIds') or u.get('external_ids') or {}
    if not isinstance(ext, dict):
        ext = {}
    return (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u.get('phone') or '').strip())


def _normalize_person_name(s: str) -> str:
    return str(s or '').replace(' ', '').strip()


def _policy_for_target(
    config: dict, index: int, wc_key: Optional[str],
) -> Optional[str]:
    """优先 version_digest_webhook_at[键名]；否则 legacy 的 version_digest_webhook_at_policy 数组下标。"""
    if str(wc_key or '').strip() == _PROGRESS_WC_KEY:
        d = config.get('version_digest_webhook_at')
        if isinstance(d, dict) and _PROGRESS_WC_KEY in d:
            v = d.get(_PROGRESS_WC_KEY)
            if v is None:
                return None
            s = str(v).strip()
            return s if s else None
        return 'pipeline'
    d = config.get('version_digest_webhook_at')
    if isinstance(d, dict) and wc_key:
        if wc_key in d:
            v = d.get(wc_key)
            if v is None:
                return None
            s = str(v).strip()
            return s if s else None
    arr = config.get('version_digest_webhook_at_policy')
    if isinstance(arr, list) and index < len(arr):
        return str(arr[index]).strip()
    return None


def _ops_member_names_for_digest(config: dict) -> List[str]:
    explicit = config.get('version_digest_ops_member_names')
    if isinstance(explicit, list) and explicit:
        return [_normalize_person_name(x) for x in explicit if _normalize_person_name(x)]
    mr = config.get('member_roles') or {}
    for key in ('operations_team', 'operations'):
        ot = mr.get(key)
        if isinstance(ot, dict):
            mem = ot.get('members')
            if isinstance(mem, list):
                return [_normalize_person_name(x) for x in mem if _normalize_person_name(x)]
    return []


def _at_mobiles_pm_apm(config: dict, users: List[dict]) -> List[str]:
    by_id = {str(u.get('id') or ''): u for u in users if u.get('id')}
    out: List[str] = []
    seen: set = set()
    for uid in (config.get('default_pipeline_pm_user_id'), config.get('default_pipeline_apm_user_id')):
        u = by_id.get(str(uid or '').strip())
        m = _dingtalk_mobile_from_user(u)
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _at_mobiles_ops_team(config: dict, users: List[dict]) -> List[str]:
    want = {_normalize_person_name(n) for n in _ops_member_names_for_digest(config)}
    if not want:
        return []
    out: List[str] = []
    seen: set = set()
    for u in users:
        if not isinstance(u, dict):
            continue
        uname = _normalize_person_name(str(u.get('name') or ''))
        if uname not in want:
            continue
        m = _dingtalk_mobile_from_user(u)
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _build_version_digest_at_per_url(
    config: dict,
    users: List[dict],
    webhook_urls: List[str],
    wc_keys: List[Optional[str]],
    legacy_pipeline_at: List[str],
) -> List[Optional[List[str]]]:
    """每个 webhook 一份 @ 手机号列表；None 表示不圈人。wc_keys 与 webhook_config 键名对齐。"""
    n = len(webhook_urls)
    out: List[Optional[List[str]]] = []
    for i in range(n):
        k = wc_keys[i] if i < len(wc_keys) else None
        pol = _policy_for_target(config, i, k)
        if pol is None or str(pol).strip() == '':
            out.append(list(legacy_pipeline_at))
            continue
        p = str(pol).strip().lower()
        if p in ('none', 'off', 'no', '-', 'empty'):
            out.append(None)
        elif p in ('pm_apm', 'pmo', 'pm_apm_only'):
            out.append(_at_mobiles_pm_apm(config, users))
        elif p in ('ops_team', 'ops', 'operations'):
            out.append(_at_mobiles_ops_team(config, users))
        elif p in ('pipeline', 'full', 'all', 'legacy'):
            out.append(list(legacy_pipeline_at))
        else:
            out.append(list(legacy_pipeline_at))
    return out


def _send_digest_to_webhooks(
    text: str,
    webhook_urls: List[str],
    *,
    quiet: bool,
    at_mobiles: Optional[List[str]] = None,
) -> dict:
    """同一正文依次 POST（如异常通知）；全部成功才算 success。"""
    if not webhook_urls:
        return {'success': False, 'error': 'no_webhook'}
    last_err = None
    for idx, url in enumerate(webhook_urls):
        r = send_via_webhook(text, url, quiet=quiet, at_mobiles=at_mobiles)
        if not r.get('success'):
            last_err = r.get('error') or 'send failed'
            if not quiet:
                print(f'[send] webhook #{idx + 1} failed: {last_err}', flush=True)
    if last_err is None:
        return {'success': True}
    return {'success': False, 'error': last_err}


def _send_digest_body_to_webhooks(
    digest_body: str,
    webhook_urls: List[str],
    at_mobiles_per_url: List[Optional[List[str]]],
    *,
    quiet: bool,
    markdown_titles: Optional[List[str]] = None,
) -> dict:
    """digest_body 不含 @ 行；按 webhook 下标附加对应 @ 后发送。"""
    n = len(webhook_urls)
    bodies = [digest_body] * n if n else []
    return _send_digest_body_to_webhooks_multi(
        bodies, webhook_urls, at_mobiles_per_url, quiet=quiet,
        markdown_titles=markdown_titles,
    )


def _send_digest_body_to_webhooks_multi(
    digest_bodies: List[str],
    webhook_urls: List[str],
    at_mobiles_per_url: List[Optional[List[str]]],
    *,
    quiet: bool,
    delay_seconds: float = 0.0,
    markdown_titles: Optional[List[str]] = None,
) -> dict:
    """每个 webhook 可对应不同正文（受众分流）；digest_bodies 与 webhook_urls 等长。"""
    if not webhook_urls:
        return {'success': False, 'error': 'no_webhook'}
    if len(digest_bodies) < len(webhook_urls):
        digest_bodies = list(digest_bodies) + [digest_bodies[-1]] * (
            len(webhook_urls) - len(digest_bodies)
        )
    last_err = None
    n = len(webhook_urls)
    for idx, url in enumerate(webhook_urls):
        body = digest_bodies[idx] if idx < len(digest_bodies) else digest_bodies[-1]
        raw = at_mobiles_per_url[idx] if idx < len(at_mobiles_per_url) else []
        if raw is None:
            raw = []
        full = body
        mt = None
        if markdown_titles and idx < len(markdown_titles):
            mt = markdown_titles[idx]
        r = send_via_webhook(
            full, url, quiet=quiet, at_mobiles=None, markdown_title=mt,
        )
        if not r.get('success'):
            last_err = r.get('error') or 'send failed'
            if not quiet:
                print(f'[send] webhook #{idx + 1} failed: {last_err}', flush=True)
        elif delay_seconds > 0 and idx < n - 1:
            time.sleep(delay_seconds)
    if last_err is None:
        return {'success': True}
    return {'success': False, 'error': last_err}


def _resolve_version_digest_raw_audiences(
    config: dict,
    send_wc_keys: List[Optional[str]],
    *,
    single_mode: bool,
) -> List[str]:
    """每条 webhook 对应的受众：pm/pld/group/full/producer；__progress__ 与 None 走管线群受众。"""
    _ = single_mode
    progress_aud = str(config.get('version_digest_progress_webhook_audience') or 'group').strip() or 'group'
    m = config.get('version_digest_audience_by_key')
    if not isinstance(m, dict):
        m = {}
    out: List[str] = []
    for wc in send_wc_keys:
        if wc is None or str(wc).strip() == '':
            out.append(progress_aud)
            continue
        if str(wc).strip() == _PROGRESS_WC_KEY:
            out.append(progress_aud)
            continue
        k = str(wc).strip()
        raw = str(m.get(k) or 'full').strip() or 'full'
        out.append(raw)
    return out


def _merge_snapshot_webhooks_single_version(
    config: dict,
    base_urls: List[str],
    base_keys: List[Optional[str]],
    target_version: dict,
) -> Tuple[List[str], List[Optional[str]]]:
    """单版本：先 digest_config 三群，再追加 PM 版本上的 progressNotifyWebhooks（短版 group）。"""
    try:
        import _push_versions_webhook_at_dm as _pvd
    except Exception:
        return list(base_urls), list(base_keys)
    progress = list(_pvd._resolve_progress_webhooks(target_version))
    if not progress:
        return list(base_urls), list(base_keys)
    if not base_urls:
        return progress, [_PROGRESS_WC_KEY] * len(progress)
    out_u = list(base_urls)
    out_k: List[Optional[str]] = list(base_keys)
    for u in progress:
        su = str(u or '').strip()
        if su:
            out_u.append(su)
            out_k.append(_PROGRESS_WC_KEY)
    return out_u, out_k


def _api_get(url, timeout=10, api_key=None):
    headers = {}
    if api_key:
        headers['X-Api-Key'] = api_key
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_checklist_blocks(pm_url, version_ids, api_key=None):
    """从 PM 内部接口拉取各版本发版检查清单 Markdown 片段（与专项推送同源）。"""
    if not version_ids:
        return {}
    try:
        qs = urllib.parse.urlencode({'version_ids': ','.join(version_ids)})
        url = f'{pm_url}/api/internal/version-checklist-blocks?{qs}'
        data = _api_get(url, api_key=api_key)
        inner = data.get('data') if isinstance(data, dict) else None
        if not isinstance(inner, dict):
            return {}
        return inner.get('blocks') or {}
    except Exception as e:
        print(f'[warn] checklist blocks: {e}', flush=True)
        return {}


def fetch_pm_users(pm_url: str, api_key=None) -> List[dict]:
    """从 GET /api/data 取 users 数组（含 externalIds），用于 Webhook @ 手机号。"""
    try:
        data = _api_get(f'{pm_url.rstrip("/")}/api/data', api_key=api_key)
        if not isinstance(data, dict):
            return []
        users = data.get('users')
        return users if isinstance(users, list) else []
    except Exception as e:
        print(f'[warn] fetch_pm_users: {e}', flush=True)
        return []


def resolve_pm_pld_mentions(config: dict, users: List[dict], version_obj: dict) -> Tuple[str, str]:
    pm_name = '张梦君'
    pld_name = 'PLD'
    by_id = {str(u.get('id') or '').strip(): u for u in users if isinstance(u, dict)}
    by_mobile: Dict[str, str] = {}
    for u in users:
        if not isinstance(u, dict):
            continue
        ext = u.get('externalIds') or u.get('external_ids') or {}
        if not isinstance(ext, dict):
            ext = {}
        m = (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u.get('phone') or '').strip())
        if m:
            by_mobile[str(u.get('id') or '').strip()] = m

    pm_uid = str(config.get('default_pipeline_pm_user_id') or '').strip()
    if pm_uid and isinstance(by_id.get(pm_uid), dict):
        n = str(by_id.get(pm_uid).get('name') or '').strip()
        if n:
            pm_name = n

    pld_uid = str((version_obj or {}).get('pldUserId') or (version_obj or {}).get('pld_user_id') or '').strip()
    if pld_uid and isinstance(by_id.get(pld_uid), dict):
        n = str(by_id.get(pld_uid).get('name') or '').strip()
        if n:
            pld_name = n

    pm_m = by_mobile.get(pm_uid) or ''
    pld_m = by_mobile.get(pld_uid) or ''
    pm_mention = f'@{pm_m}' if pm_m else f'@{pm_name}'
    pld_mention = f'@{pld_m}' if pld_m else f'@{pld_name}'
    return pm_mention, pld_mention


def fetch_pm_data_maps(pm_url: str, api_key=None) -> Tuple[Dict[str, dict], Dict[str, dict], Optional[dict]]:
    """从 /api/data 读取 versions/users，返回按 id 建索引与提取后的 data 载荷。

    第三项供 ``render_multi_version_digest_markdown(..., data_all=...)`` 复用，早间多受众连渲时少打重复 /api/data。
    """
    versions_by_id: Dict[str, dict] = {}
    users_by_id: Dict[str, dict] = {}
    data_extracted: Optional[dict] = None
    try:
        raw = _api_get(f'{pm_url.rstrip("/")}/api/data', api_key=api_key)
        data = raw.get('data') if isinstance(raw, dict) and isinstance(raw.get('data'), dict) else raw
        if not isinstance(data, dict):
            return versions_by_id, users_by_id, data_extracted
        data_extracted = data
        for u in (data.get('users') or []):
            if not isinstance(u, dict):
                continue
            uid = str(u.get('id') or '').strip()
            if uid:
                users_by_id[uid] = u
        for v in (data.get('versions') or []):
            if not isinstance(v, dict):
                continue
            vid = str(v.get('id') or '').strip()
            if vid:
                versions_by_id[vid] = v
    except Exception:
        return versions_by_id, users_by_id, data_extracted
    return versions_by_id, users_by_id, data_extracted


def merge_versions_with_data(selected_versions: List[dict], versions_by_id: Dict[str, dict]) -> List[dict]:
    out: List[dict] = []
    for v in selected_versions or []:
        vid = str(v.get('id') or '').strip()
        full = versions_by_id.get(vid)
        if isinstance(full, dict):
            merged = dict(v)
            merged.update(full)
            # /api/data 里可能是空 dict，不能覆盖 dashboard 的管线状态/DDL
            for key in ('pipelineStatus', 'pipelineDdls', 'nodeManualChecks'):
                if not merged.get(key) and v.get(key):
                    merged[key] = v.get(key)
            out.append(merged)
        else:
            out.append(v)
    return out


def collect_at_mobiles_for_versions(versions: List[dict], users: List[dict]) -> List[str]:
    """汇总当前摘要中各版本 PLD/PLE/PLT-F/PLT-B 对应成员的钉钉手机号（去重）。"""
    by_id = {str(u.get('id') or ''): u for u in users if u.get('id')}
    out: List[str] = []
    seen: set = set()
    for v in versions:
        for key in ('_pld', '_ple', '_plt_f', '_plt_b', '_plt'):
            uid = v.get(key) or ''
            if not uid:
                continue
            u = by_id.get(str(uid))
            if not u:
                continue
            ext = u.get('externalIds') or u.get('external_ids') or {}
            if not isinstance(ext, dict):
                ext = {}
            m = (str(ext.get('dingtalk_mobile') or '').strip()) or (str(u.get('phone') or '').strip())
            if m and m not in seen:
                seen.add(m)
                out.append(m)
    return out


def append_dingtalk_at_line(markdown: str, mobiles: List[str]) -> str:
    if not mobiles:
        return markdown
    line = ' '.join(f'@{m}' for m in mobiles)
    return markdown.rstrip() + '\n\n' + line


def append_pm_detail_footer(markdown: str, url: str = VERSION_DIGEST_PM_DETAIL_URL) -> str:
    """在「※ 小秘书提醒」之前增加 PM 查看版本详情链接（小秘书保持全文最末）。"""
    u = (url or '').strip()
    if not u:
        return markdown
    block = f'\n\n---\n\n请 PM 前往 [查看版本详情]({u})。'
    suf = DIGEST_MD_FOOTER
    m = markdown.rstrip()
    if len(m) >= len(suf) and m.endswith(suf):
        core = m[: -len(suf)].rstrip()
        return core + block + suf
    return m + block + suf


def _version_release_node_done(v: Optional[dict]) -> bool:
    if not v or not isinstance(v, dict):
        return False
    ps = v.get('_pipeline_status') or v.get('pipelineStatus') or {}
    return isinstance(ps, dict) and bool(ps.get('release'))


def _all_selected_versions_release_done(versions: List[dict]) -> bool:
    if not versions:
        return False
    return all(_version_release_node_done(v) for v in versions)


def _explicit_planning_ddl_from_dashboard_version(v: dict) -> Optional[date]:
    ddls = v.get('pipelineDdls') or v.get('pipeline_ddls') or {}
    if isinstance(ddls, dict):
        raw = ddls.get('planning')
        if raw:
            try:
                return datetime.strptime(str(raw)[:10], '%Y-%m-%d').date()
            except ValueError:
                pass
    # 回退：与 PM 界面一致，planning 默认 = startDate - 7 天
    st = v.get('startDate') or v.get('start_date') or v.get('createdAt') or v.get('created_at')
    if st:
        try:
            sd = datetime.strptime(str(st)[:10], '%Y-%m-%d').date()
            return sd - timedelta(days=7)
        except ValueError:
            pass
    # 最末回退：缺 startDate 时，使用 releaseDate - 37（= start 默认 release-30，再 planning=-7）
    rel = v.get('releaseDate') or v.get('release_date')
    if rel:
        try:
            rd = datetime.strptime(str(rel)[:10], '%Y-%m-%d').date()
            return rd - timedelta(days=37)
        except ValueError:
            return None
    return None


def _pipeline_retro_done(v: Optional[dict]) -> bool:
    if not v or not isinstance(v, dict):
        return False
    ps = v.get('_pipeline_status') or v.get('pipelineStatus') or {}
    return isinstance(ps, dict) and bool(ps.get('retro'))


def _planning_ddl_within_days(v: dict, max_days: int) -> bool:
    d = _explicit_planning_ddl_from_dashboard_version(v)
    if d is None:
        return False
    return (d - date.today()).days <= max_days


def _planning_ddl_exclude_far_ahead(v: dict, min_days: int) -> bool:
    """若存在规划节点 DDL 且 (ddl-今天).days >= min_days，返回 True（应排除）。"""
    d = _explicit_planning_ddl_from_dashboard_version(v)
    if d is None:
        return False
    return (d - date.today()).days >= min_days


def _version_in_pmo_or_pm_scope(v: dict, n_planning: int) -> bool:
    """PMO/管线：发版未完成 |（发版完成且复盘未完成）| 规划 DDL 距今窗口内（与既有 producer 逻辑一致：delta<=N）。"""
    if not _version_release_node_done(v):
        return True
    if _version_release_node_done(v) and not _pipeline_retro_done(v):
        return True
    if _planning_ddl_within_days(v, n_planning):
        return True
    return False


def _version_in_pm_scope(v: dict, n_planning: int, config: dict) -> bool:
    """管线快报：先排除「规划 DDL 距今>=N 天」；再按 PMO 并集规则（N 为规划窗口天数）。"""
    ex = int(config.get('version_digest_pm_planning_exclude_days_ahead', 7) or 7)
    if _planning_ddl_exclude_far_ahead(v, ex):
        return False
    return _version_in_pmo_or_pm_scope(v, n_planning)


def _version_in_pld_scope(v: dict, n_planning: int, config: dict) -> bool:
    """PLD：先排除「规划 DDL 距今>=N 天」；发版未完成 | 规划 DDL 窗口内。"""
    ex = int(config.get('version_digest_pld_planning_exclude_days_ahead', 3) or 3)
    if _planning_ddl_exclude_far_ahead(v, ex):
        return False
    if not _version_release_node_done(v):
        return True
    if _planning_ddl_within_days(v, n_planning):
        return True
    return False


def _version_in_group_scope(v: dict, config: dict) -> bool:
    """版本快报：发版节点未完成；若填写了规划 DDL，则「距规划 DDL 还有 >=N 天」的不纳入（默认 N=3）。"""
    if _version_release_node_done(v):
        return False
    n = int(config.get('version_digest_group_planning_exclude_days_ahead', 3) or 3)
    d = _explicit_planning_ddl_from_dashboard_version(v)
    if d is None:
        return True
    delta = (d - date.today()).days
    if delta >= n:
        return False
    return True


def _morning_names_from_merged(
    merged_versions: List[dict],
    audience: str,
    config: dict,
) -> List[str]:
    """早间各受众版本名列表（已合并 /api/data，含 pipelineStatus）。"""
    ra = str(audience or '').strip() or 'full'
    _pmo_raw = config.get('version_digest_pmo_planning_days')
    if _pmo_raw is None or (isinstance(_pmo_raw, str) and not str(_pmo_raw).strip()):
        _pmo_raw = config.get('version_digest_producer_planning_days', 28)
    pmo_n = int(_pmo_raw or 28)
    pm_n = int(config.get('version_digest_pm_planning_days', 7) or 7)
    pld_n = int(config.get('version_digest_pld_planning_days', 14) or 14)
    out: List[str] = []
    seen: set[str] = set()
    for v in merged_versions:
        nm = str(v.get('name') or '').strip()
        if not nm or nm in seen:
            continue
        ok = False
        if ra in ('producer', 'full'):
            ok = _version_in_pmo_or_pm_scope(v, pmo_n)
        elif ra == 'pm':
            ok = _version_in_pm_scope(v, pm_n, config)
        elif ra == 'pld':
            ok = _version_in_pld_scope(v, pld_n, config)
        elif ra == 'group':
            ok = _version_in_group_scope(v, config)
        else:
            ok = True
        if ok:
            out.append(nm)
            seen.add(nm)
    return out


def _dingtalk_markdown_title_for_digest_audience(raw_audience: str) -> str:
    """晨间多群：钉钉 Markdown 消息标题（须含「小秘书提醒」以匹配机器人关键词）。"""
    ts = datetime.now().strftime('%m/%d %H:%M')
    ra = (raw_audience or 'full').strip()
    if ra == 'producer':
        return f'小秘书提醒 · PMO早报[{ts}]'
    if ra == 'pm':
        return f'小秘书提醒 · 管线快报[{ts}]'
    if ra == 'pld':
        return f'小秘书提醒 · PLD快报[{ts}]'
    if ra == 'group':
        return f'小秘书提醒 · 版本快报[{ts}]'
    return '小秘书提醒 · 版本状态'


def _dingtalk_markdown_title_pld_single_version(version_name: str) -> str:
    """PLD 按版本拆条时标题带版本名，便于会话列表区分。"""
    ts = datetime.now().strftime('%m/%d %H:%M')
    vn = str(version_name or '').strip() or '版本'
    return f'小秘书提醒 · PLD快报 · {vn}[{ts}]'


def _dingtalk_markdown_title_group_single_version(version_name: str) -> str:
    """版本快报按版本拆条时标题带版本名（与 PLD 一致便于会话列表区分）。"""
    ts = datetime.now().strftime('%m/%d %H:%M')
    vn = str(version_name or '').strip() or '版本'
    return f'小秘书提醒 · 版本快报 · {vn}[{ts}]'


def _group_progress_webhooks_from_version_data(v: dict) -> List[str]:
    """版本快报目标 URL：仅读 PM 数据源 version 上的 progressNotifyWebhooks，不用 webhook_config。"""
    raw = v.get('progressNotifyWebhooks') or v.get('progress_notify_webhooks') or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(u).strip() for u in raw if str(u).strip()]


def _group_has_any_data_webhook(
    merged_versions: List[dict],
    names_group: List[str],
) -> bool:
    by_name = {str(v.get('name') or '').strip(): v for v in merged_versions}
    for nm in names_group:
        v = by_name.get(str(nm).strip())
        if v and _group_progress_webhooks_from_version_data(v):
            return True
    return False


def _strip_group_rows_from_digest_webhook_targets(
    urls: List[str],
    keys: List[Optional[str]],
    config: dict,
    *,
    log_to_stdout: bool = True,
) -> Tuple[List[str], List[Optional[str]]]:
    """去掉 digest_config 里显式映射为 group 的行；单版本 ``__progress__`` 来自版本 URL，保留。"""
    auds = _resolve_version_digest_raw_audiences(config, keys, single_mode=False)
    out_u: List[str] = []
    out_k: List[Optional[str]] = []
    for u, k, a in zip(urls, keys, auds):
        k_s = str(k or '').strip()
        if str(a).strip() == 'group' and k_s != _PROGRESS_WC_KEY:
            if log_to_stdout:
                print(
                    '[version-digest] skip digest_config row audience=group '
                    '(版本快报改为按版本读 progressNotifyWebhooks；__progress__ 保留)',
                    flush=True,
                )
            continue
        out_u.append(u)
        out_k.append(k)
    return out_u, out_k


def _send_group_digests_from_version_webhooks(
    *,
    merged_versions: List[dict],
    names_group: List[str],
    pm_url: str,
    api_key: Optional[str],
    config: dict,
    pm_data_payload: Optional[dict],
    _pvd: Any,
    log_to_stdout: bool,
    quiet: bool,
    send_webhook: bool,
    delay_s: float,
) -> Tuple[bool, int]:
    """版本快报：按版本渲染 group 正文，POST 到该版本在数据源中配置的 progressNotifyWebhooks。"""
    if not send_webhook or not names_group:
        return True, 0
    by_name = {str(v.get('name') or '').strip(): v for v in merged_versions}
    sent = 0
    any_fail = False
    for vn in names_group:
        v = by_name.get(str(vn).strip())
        if not v:
            continue
        urls = _group_progress_webhooks_from_version_data(v)
        if not urls:
            if log_to_stdout:
                print(
                    f'[version-digest] group skip {vn!r}: version has no progressNotifyWebhooks',
                    flush=True,
                )
            continue
        body, _at, nb = _pvd.render_multi_version_digest_markdown(
            pm_url,
            api_key,
            [str(vn).strip()],
            config,
            log_to_stdout=log_to_stdout,
            audience='group',
            data_all=pm_data_payload,
        )
        if not (body or '').strip() or nb == 0:
            if log_to_stdout:
                print(f'[version-digest] group skip {vn!r}: empty body', flush=True)
            continue
        title = _dingtalk_markdown_title_group_single_version(vn)
        for u in urls:
            r = send_via_webhook(
                body, u, quiet=quiet, at_mobiles=None, markdown_title=title,
            )
            if r.get('success'):
                sent += 1
                if log_to_stdout:
                    print(f'[version-digest] group sent version={vn!r}', flush=True)
            else:
                any_fail = True
                if log_to_stdout:
                    print(
                        f'[version-digest] group send failed version={vn!r}: '
                        f'{r.get("error")}',
                        flush=True,
                    )
            if delay_s > 0:
                time.sleep(delay_s)
    return (not any_fail), sent


def _detail_url_for_version_name(
    pm_url: str,
    all_versions: List[dict],
    version_name: str,
) -> str:
    base = f'{pm_url.rstrip("/")}/index.html'
    vn = str(version_name or '').strip()
    for v in all_versions or []:
        if str(v.get('name') or '').strip() == vn:
            vid = str(v.get('id') or '').strip()
            if vid:
                return f'{base}#version={vid}'
            break
    return base


def _group_digest_primary_version_name(
    pm_url: str,
    version_names: List[str],
    api_key: Optional[str],
) -> str:
    """与 `render_multi_version_digest_markdown` 中 PLD/group 一致：活跃列表里首个发版节点未勾选的版本名。"""
    import _push_versions_webhook_at_dm as _pvd

    pm_url = pm_url.rstrip('/')
    names = [str(x or '').strip() for x in version_names if str(x or '').strip()]
    if not names:
        return ''
    try:
        data_all = _pvd._extract_data(
            _pvd._api_get_json(f'{pm_url}/api/data', api_key or None)
        )
        filtered = _pvd._filter_names_exclude_release_done(names, data_all)
        return filtered[0] if filtered else names[0]
    except Exception:
        return names[0]


def _detail_url_for_group_digest(
    pm_url: str,
    all_versions: List[dict],
    version_names: List[str],
    api_key: Optional[str],
) -> str:
    """PLD/版本快报实际渲染的首个「发版节点未完成」版本之前台链接。"""
    vn = _group_digest_primary_version_name(pm_url, version_names, api_key)
    if not vn:
        return f'{pm_url.rstrip("/")}/index.html'
    return _detail_url_for_version_name(pm_url, all_versions, vn)


def run_version_digest_assistant_batch(
    *,
    send_webhook: bool = True,
    log_to_stdout: bool = True,
) -> dict:
    """助理通知群连发：活跃版本取前 3 中的第 1、2 名各一条；指定名称版本两条（默认五一版）。

    目标 URL 来自 webhook_config[version_digest_assistant_batch.webhook_key]。
    不写 state，不覆盖早间快照。
    """
    import _push_versions_webhook_at_dm as _pvd

    config = _load_config()
    batch = config.get('version_digest_assistant_batch')
    if not isinstance(batch, dict):
        batch = {}
    wkey = str(batch.get('webhook_key') or 'version_digest_assistant').strip()
    may_day = str(batch.get('may_day_version_name') or '五一版').strip() or '五一版'
    aud12 = str(batch.get('slot12_audience') or 'producer').strip() or 'producer'
    aud3 = str(batch.get('slot3_audience') or 'full').strip() or 'full'
    aud4 = str(batch.get('slot4_audience') or 'pm').strip() or 'pm'

    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    wc = _load_webhook_config()
    url = str(wc.get(wkey) or '').strip()
    if not url:
        err = f'webhook_config.json missing key {wkey!r}'
        if log_to_stdout:
            print(f'[assistant-batch] {err}', flush=True)
        return {'ok': False, 'digest': '', 'error': err, 'sent': 0, 'digests': []}

    delay_s = float(
        batch.get('send_interval_seconds', config.get('version_digest_send_interval_seconds') or 1)
        or 0
    )

    if log_to_stdout:
        print(f'[assistant-batch] pm={pm_url} webhook_key={wkey}', flush=True)

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except Exception as e:
        if log_to_stdout:
            print(f'[assistant-batch] fetch failed: {e}', flush=True)
        return {'ok': False, 'digest': '', 'error': str(e), 'sent': 0, 'digests': []}

    if not all_versions:
        return {'ok': False, 'digest': '', 'error': 'empty_active_versions', 'sent': 0, 'digests': []}

    top3 = filter_active(all_versions, 3)
    _, _, pm_data_payload = fetch_pm_data_maps(pm_url, api_key=api_key or None)
    pm_users: List[dict] = []
    if isinstance(pm_data_payload, dict):
        u_raw = pm_data_payload.get('users')
        if isinstance(u_raw, list) and u_raw:
            pm_users = [x for x in u_raw if isinstance(x, dict)]
    if not pm_users:
        pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    at_per_url = _build_version_digest_at_per_url(
        config, pm_users, [url], [wkey], [],
    )
    raw_at = at_per_url[0] if at_per_url else None
    if raw_at is None:
        raw_at = []

    slots: List[Tuple[str, str, str]] = []
    if len(top3) >= 1:
        n1 = str(top3[0].get('name') or '').strip()
        if n1:
            slots.append(('slot1_top1', n1, aud12))
    if len(top3) >= 2:
        n2 = str(top3[1].get('name') or '').strip()
        if n2:
            slots.append(('slot2_top2', n2, aud12))
    slots.append(('slot3_mayday', may_day, aud3))
    slots.append(('slot4_mayday', may_day, aud4))

    md_names = {str(v.get('name') or '').strip() for v in all_versions}
    if may_day not in md_names and log_to_stdout:
        print(
            f'[assistant-batch] warn: may_day version {may_day!r} not in dashboard',
            flush=True,
        )

    pending: List[Tuple[str, str, str, str]] = []
    last_digest = ''
    for label, vname, aud in slots:
        digest, _at_ms, n_built = _pvd.render_multi_version_digest_markdown(
            pm_url,
            api_key or None,
            [vname],
            config,
            log_to_stdout=log_to_stdout,
            audience=aud,
            data_all=pm_data_payload,
        )
        if n_built == 0:
            if log_to_stdout:
                print(f'[assistant-batch] skip {label} {vname!r} audience={aud}: empty', flush=True)
            continue
        last_digest = digest
        pending.append((label, vname, aud, digest))

    digests = [d for _, _, _, d in pending]
    if not pending:
        return {
            'ok': False,
            'digest': '',
            'error': 'no_slot_rendered',
            'sent': 0,
            'digests': [],
        }

    if not send_webhook:
        return {
            'ok': True,
            'digest': last_digest,
            'error': None,
            'sent': 0,
            'digests': digests,
        }

    quiet = not log_to_stdout
    successes = 0
    failures = 0
    last_err: Optional[str] = None
    for i, (label, vname, aud, digest) in enumerate(pending):
        full = digest
        mt = _dingtalk_markdown_title_for_digest_audience(str(aud))
        r = send_via_webhook(
            full, url, quiet=quiet, at_mobiles=None, markdown_title=mt,
        )
        if r.get('success'):
            successes += 1
            if log_to_stdout:
                print(f'[assistant-batch] sent {label} {vname!r} audience={aud}', flush=True)
        else:
            failures += 1
            last_err = str(r.get('error') or 'send failed')
            if log_to_stdout:
                print(f'[assistant-batch] send failed {label}: {last_err}', flush=True)
        if delay_s > 0 and i < len(pending) - 1:
            time.sleep(delay_s)

    ok = failures == 0 and successes > 0
    err_out: Optional[str] = None
    if failures:
        err_out = last_err or 'partial_send_failure'
    elif successes == 0:
        err_out = last_err or 'send failed'

    return {
        'ok': ok,
        'digest': last_digest,
        'error': err_out,
        'sent': successes,
        'digests': digests,
    }


def run_version_digest_audience_sweep(
    *,
    send_webhook: bool = True,
    log_to_stdout: bool = True,
    version_name: Optional[str] = None,
) -> dict:
    """助理群连发 4 条：与早间同一套版本筛选与文末链接规则。不写 state。"""
    import _push_versions_webhook_at_dm as _pvd

    config = _load_config()
    batch = config.get('version_digest_assistant_batch')
    wkey = 'version_digest_assistant'
    if isinstance(batch, dict) and str(batch.get('webhook_key') or '').strip():
        wkey = str(batch.get('webhook_key')).strip()

    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    wc = _load_webhook_config()
    url = str(wc.get(wkey) or '').strip()
    if not url:
        err = f'webhook_config.json missing key {wkey!r}'
        if log_to_stdout:
            print(f'[audience-sweep] {err}', flush=True)
        return {'ok': False, 'error': err, 'sent': 0}

    delay_s = float(config.get('version_digest_send_interval_seconds') or 1)

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except Exception as e:
        if log_to_stdout:
            print(f'[audience-sweep] fetch failed: {e}', flush=True)
        return {'ok': False, 'error': str(e), 'sent': 0}

    if not all_versions:
        return {'ok': False, 'error': 'empty_active_versions', 'sent': 0}

    top = filter_active(all_versions, None)
    vn_spec = str(version_name or '').strip()
    if vn_spec:
        if not any(str(v.get('name') or '').strip() == vn_spec for v in all_versions):
            return {'ok': False, 'error': f'version_not_found:{vn_spec}', 'sent': 0}
        found = next(
            (v for v in all_versions if str(v.get('name') or '').strip() == vn_spec),
            None,
        )
        if found:
            top = [found] + [v for v in top if str(v.get('name') or '').strip() != vn_spec]

    versions_by_id, _, pm_data_payload = fetch_pm_data_maps(pm_url, api_key=api_key or None)
    merged = merge_versions_with_data(top, versions_by_id)
    if log_to_stdout:
        print(
            f'[audience-sweep] merged={len(merged)} version(s) webhook_key={wkey} pm={pm_url}',
            flush=True,
        )

    pm_users: List[dict] = []
    if isinstance(pm_data_payload, dict):
        u_raw = pm_data_payload.get('users')
        if isinstance(u_raw, list) and u_raw:
            pm_users = [x for x in u_raw if isinstance(x, dict)]
    if not pm_users:
        pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    at_per_url = _build_version_digest_at_per_url(
        config, pm_users, [url], [wkey], [],
    )
    raw_at = at_per_url[0] if at_per_url else None
    if raw_at is None:
        raw_at = []

    audiences = ('producer', 'pm', 'pld', 'group')
    successes = 0
    failures = 0
    last_err: Optional[str] = None
    by_name_merged = {str(v.get('name') or '').strip(): v for v in merged}

    for i, aud in enumerate(audiences):
        vnames_arg = _morning_names_from_merged(merged, aud, config)
        if aud == 'group':
            for vn in vnames_arg:
                v = by_name_merged.get(str(vn).strip())
                urls = _group_progress_webhooks_from_version_data(v) if v else []
                if not urls:
                    if log_to_stdout:
                        print(
                            f'[audience-sweep] skip group {vn!r}: no progressNotifyWebhooks on version',
                            flush=True,
                        )
                    continue
                one_d, _a2, nb = _pvd.render_multi_version_digest_markdown(
                    pm_url,
                    api_key or None,
                    [str(vn).strip()],
                    config,
                    log_to_stdout=log_to_stdout,
                    audience='group',
                    data_all=pm_data_payload,
                )
                if nb == 0 or not (one_d or '').strip():
                    continue
                mt = _dingtalk_markdown_title_group_single_version(vn)
                if not send_webhook:
                    successes += 1
                    if log_to_stdout:
                        print(f'[audience-sweep] dry-run audience=group title={mt!r}', flush=True)
                    continue
                for u in urls:
                    r = send_via_webhook(
                        one_d,
                        u,
                        quiet=not log_to_stdout,
                        at_mobiles=None,
                        markdown_title=mt,
                    )
                    if r.get('success'):
                        successes += 1
                        if log_to_stdout:
                            print(f'[audience-sweep] sent audience=group version={vn!r}', flush=True)
                    else:
                        failures += 1
                        last_err = str(r.get('error') or 'send failed')
                        if log_to_stdout:
                            print(
                                f'[audience-sweep] send failed audience=group: {last_err}',
                                flush=True,
                            )
                    if delay_s > 0:
                        time.sleep(delay_s)
            if delay_s > 0 and i < len(audiences) - 1:
                time.sleep(delay_s)
            continue
        if aud == 'pld' and len(vnames_arg) > 1:
            sends: List[Tuple[str, str]] = []
            for vn in vnames_arg:
                one_d, _a2, nb = _pvd.render_multi_version_digest_markdown(
                    pm_url,
                    api_key or None,
                    [vn],
                    config,
                    log_to_stdout=log_to_stdout,
                    audience='pld',
                    data_all=pm_data_payload,
                )
                if nb == 0 or not (one_d or '').strip():
                    continue
                sends.append((one_d, _dingtalk_markdown_title_pld_single_version(vn)))
            if not sends:
                if log_to_stdout:
                    print('[audience-sweep] skip audience=pld: all split bodies empty', flush=True)
                if delay_s > 0 and i < len(audiences) - 1:
                    time.sleep(delay_s)
                continue
            if not send_webhook:
                successes += 1
                if log_to_stdout:
                    for _full, mt in sends:
                        print(f'[audience-sweep] dry-run audience=pld title={mt!r}', flush=True)
                if delay_s > 0 and i < len(audiences) - 1:
                    time.sleep(delay_s)
                continue
            for si, (full, mt) in enumerate(sends):
                r = send_via_webhook(
                    full,
                    url,
                    quiet=not log_to_stdout,
                    at_mobiles=None,
                    markdown_title=mt,
                )
                if r.get('success'):
                    successes += 1
                    if log_to_stdout:
                        print(f'[audience-sweep] sent audience=pld split={si + 1}/{len(sends)}', flush=True)
                else:
                    failures += 1
                    last_err = str(r.get('error') or 'send failed')
                    if log_to_stdout:
                        print(f'[audience-sweep] send failed audience=pld: {last_err}', flush=True)
                if delay_s > 0 and si < len(sends) - 1:
                    time.sleep(delay_s)
            if delay_s > 0 and i < len(audiences) - 1:
                time.sleep(delay_s)
            continue
        digest, _at_ms, n_built = _pvd.render_multi_version_digest_markdown(
            pm_url,
            api_key or None,
            vnames_arg,
            config,
            log_to_stdout=log_to_stdout,
            audience=aud,
            data_all=pm_data_payload,
        )
        if n_built == 0:
            if log_to_stdout:
                print(f'[audience-sweep] skip audience={aud}: empty body', flush=True)
            if aud in ('pld', 'group'):
                continue
            failures += 1
            continue
        full = digest
        mt = _dingtalk_markdown_title_for_digest_audience(aud)
        if not send_webhook:
            successes += 1
            if log_to_stdout:
                print(f'[audience-sweep] dry-run audience={aud} title={mt!r}', flush=True)
            continue
        r = send_via_webhook(
            full,
            url,
            quiet=not log_to_stdout,
            at_mobiles=None,
            markdown_title=mt,
        )
        if r.get('success'):
            successes += 1
            if log_to_stdout:
                print(f'[audience-sweep] sent audience={aud}', flush=True)
        else:
            failures += 1
            last_err = str(r.get('error') or 'send failed')
            if log_to_stdout:
                print(f'[audience-sweep] send failed audience={aud}: {last_err}', flush=True)
        if delay_s > 0 and i < len(audiences) - 1:
            time.sleep(delay_s)

    ok = failures == 0
    err_out: Optional[str] = None
    if failures:
        err_out = last_err or 'partial_failure'
    return {'ok': ok, 'error': err_out, 'sent': successes}


def _render_change_digest_fallback(
    *,
    has_baseline: bool,
    changed: bool,
    stale_days: Optional[int],
    stale_threshold: int,
    calendar_err: Optional[str],
    change_facts: Optional[Dict[str, List[str]]] = None,
    version_name: str = '',
) -> str:
    vtitle = str(version_name or '').strip() or '多版本'
    ts = _now_mmdd_hhmm()
    t = _load_change_template()
    lines = [str(t.get('title') or '## 今日变化 | {version_name}').format(version_name=vtitle, timestamp=ts), '']
    if not has_baseline:
        lines.append(f'{_VD_BULLET}首次运行，已建立基线。明日起开始对比推送。')
        return '\n'.join(lines)

    facts = change_facts or {}
    f_progress = list(facts.get('progress') or [])[:25]
    f_no_change = list(facts.get('no_change') or [])[:5]
    f_stale = list(facts.get('stale_alert') or [])[:3]
    f_follow = list(facts.get('followup_stale') or [])[:10]

    if f_progress:
        lines.append(str(t.get('progress_header') or '### 今日实际进展'))
        _append_change_digest_bullets(lines, f_progress)
        lines.append('')

    if f_no_change:
        lines.append(str(t.get('action_header') or '### 行动提醒'))
        for x in f_no_change:
            for j, sub in enumerate(x.split('\n')):
                if j == 0:
                    lines.append(f'{_VD_BULLET}{sub}')
                else:
                    lines.append(sub)
        lines.append('')

    if f_follow:
        lines.append(str(t.get('followup_header') or '### 早间关注暂无进展'))
        _append_change_digest_bullets(lines, f_follow)
        lines.append('')

    if f_stale:
        lines.append(str(t.get('stale_header') or '### 连续无变化'))
        for x in f_stale:
            lines.append(f'{_VD_BULLET}{x}')
        lines.append('')
    elif calendar_err:
        lines.append(f'{_VD_BULLET}工作日历读取失败，无法统计连续天数。')
        lines.append('')

    if not f_progress and not f_no_change and not f_stale and not f_follow:
        lines.append(f"{_VD_BULLET}{str(t.get('no_change_line') or '今日各版本暂无显著变化。')}")

    lines.extend(['', str(t.get('footer') or '<font color="#999999">小秘书提醒 · {timestamp}</font>').format(version_name=vtitle, timestamp=ts)])
    return '\n'.join(lines)


def _render_change_digest(
    *,
    baseline_text: str,
    current_text: str,
    has_baseline: bool,
    changed: bool,
    stale_days: Optional[int],
    stale_threshold: int,
    calendar_err: Optional[str],
    change_facts: Optional[Dict[str, List[str]]] = None,
    version_name: str = '',
) -> str:
    vtitle = str(version_name or '').strip() or '多版本'
    ts = _now_mmdd_hhmm()
    t = _load_change_template()
    facts = change_facts or {}
    f_progress = list(facts.get('progress') or [])[:25]
    f_no_change = list(facts.get('no_change') or [])[:5]
    f_stale = list(facts.get('stale_alert') or [])[:3]
    f_follow = list(facts.get('followup_stale') or [])[:10]

    if f_progress or f_no_change or f_stale or f_follow:
        lines = [str(t.get('title') or '## 今日变化 | {version_name}').format(version_name=vtitle, timestamp=ts), '']
        if f_progress:
            lines.append(str(t.get('progress_header') or '### 今日实际进展'))
            _append_change_digest_bullets(lines, f_progress)
            lines.append('')
        if f_no_change:
            lines.append(str(t.get('action_header') or '### 行动提醒'))
            for x in f_no_change:
                for j, sub in enumerate(x.split('\n')):
                    if j == 0:
                        lines.append(f'{_VD_BULLET}{sub}')
                    else:
                        lines.append(sub)
            lines.append('')
        if f_follow:
            lines.append(str(t.get('followup_header') or '### 早间关注暂无进展'))
            _append_change_digest_bullets(lines, f_follow)
            lines.append('')
        if f_stale:
            lines.append(str(t.get('stale_header') or '### 连续无变化'))
            for x in f_stale:
                lines.append(f'{_VD_BULLET}{x}')
            lines.append('')
        elif calendar_err:
            lines.append(f'{_VD_BULLET}工作日历读取失败，无法统计连续天数。')
            lines.append('')
        lines.extend([str(t.get('footer') or '<font color="#999999">小秘书提醒 · {timestamp}</font>').format(version_name=vtitle, timestamp=ts)])
        return '\n'.join(lines)

    try:
        llm_obj = _call_llm_change_json(
            baseline_text=baseline_text,
            current_text=current_text,
            stale_days=stale_days,
            stale_threshold=stale_threshold,
        )
    except Exception:
        llm_obj = None
    if not isinstance(llm_obj, dict):
        return _render_change_digest_fallback(
            has_baseline=has_baseline,
            changed=changed,
            stale_days=stale_days,
            stale_threshold=stale_threshold,
            calendar_err=calendar_err,
            change_facts=change_facts,
            version_name=version_name,
        )

    def _items(key: str) -> List[str]:
        raw = llm_obj.get(key)
        if not isinstance(raw, list):
            return []
        out: List[str] = []
        for x in raw:
            s = str(x or '').strip()
            if s:
                out.append(s)
        return out[:5]

    progress = _items('progress')
    no_ch = _items('no_change')
    stale_alert = _items('stale_alert')
    f_follow_llm = list((change_facts or {}).get('followup_stale') or [])[:10]

    lines = [str(t.get('title') or '## 今日变化 | {version_name}').format(version_name=vtitle, timestamp=ts), '']
    if progress:
        lines.append(str(t.get('progress_header') or '### 今日实际进展'))
        _append_change_digest_bullets(lines, progress)
        lines.append('')
    if no_ch:
        lines.append(str(t.get('action_header') or '### 行动提醒'))
        for x in no_ch:
            for j, sub in enumerate(x.split('\n')):
                if j == 0:
                    lines.append(f'{_VD_BULLET}{sub}')
                else:
                    lines.append(sub)
        lines.append('')
    if f_follow_llm:
        lines.append(str(t.get('followup_header') or '### 早间关注暂无进展'))
        _append_change_digest_bullets(lines, f_follow_llm)
        lines.append('')
    if stale_alert:
        lines.append(str(t.get('stale_header') or '### 连续无变化'))
        for x in stale_alert:
            lines.append(f'{_VD_BULLET}{x}')
        lines.append('')
    elif calendar_err:
        lines.append(f'{_VD_BULLET}工作日历读取失败，无法统计连续天数。')
        lines.append('')
    lines.extend([str(t.get('footer') or '<font color="#999999">小秘书提醒 · {timestamp}</font>').format(version_name=vtitle, timestamp=ts)])
    return '\n'.join(lines)


def fetch_dashboard(pm_url, api_key=None):
    try:
        data = _api_get(f'{pm_url}/api/dashboard', api_key=api_key)
        versions = data.get('data', {}).get('activeVersions', [])
        if versions:
            return versions
        return []
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise FetchAuthError(f'HTTP {e.code}: Unauthorized')
        print(f'[warn] dashboard API failed: {e}', flush=True)
    except Exception as e:
        print(f'[warn] dashboard API failed: {e}', flush=True)
    return []


def _render_auth_fail_notice(pm_url, err_text):
    now_str = datetime.now().strftime('%m/%d %H:%M')
    lines = [
        f'## 版本状态拉取失败 [{now_str}]',
        '',
        f'- 数据源：`{pm_url}/api/dashboard`',
        f'- 结果：鉴权失败（{err_text}）',
        '- 处理：本次已跳过版本摘要推送，避免发送旧数据',
        '',
        '### 行动建议',
        '1. 在 PM 后端 `backend/.env` 设置 `SERVICE_API_KEY`，须与 `dingtalk-desktop/digest_config.json` 的 `pm_system_api_key` 一致',
        f'2. 确认本通知中的数据源地址 `{pm_url}` 可达，且进程已重启使 `.env` 生效',
        '3. 访问 `GET /api/health`，若 `service_api_key_configured` 为 false，说明服务端未读到密钥（常见原因：`.env` 不在 `backend/` 或启动方式导致旧版相对路径未加载）',
        '4. 本机执行 `py version_digest.py --dry-run` 复测，确认不再出现 401',
        '5. 若 key 已更新，重跑一次定时脚本或手动触发「版本咋样了」',
        '',
        '<font color="#999999">小秘书提醒</font>',
    ]
    return '\n'.join(lines)


def _notify_fetch_failed(webhook_urls, pm_url, err_text, log_to_stdout=True):
    if not webhook_urls:
        if log_to_stdout:
            print('[version-digest] no webhook configured, skip failure notice', flush=True)
        return {'success': False, 'error': 'no_webhook'}
    notice = _render_auth_fail_notice(pm_url, err_text)
    result = _send_digest_to_webhooks(notice, webhook_urls, quiet=not log_to_stdout)
    if log_to_stdout:
        if result.get('success'):
            print('[version-digest] auth-failure notice sent (all webhooks)', flush=True)
        else:
            print(f"[version-digest] auth-failure notice failed: {result.get('error')}", flush=True)
    return result


def _render_empty_data_notice(pm_url):
    now_str = datetime.now().strftime('%m/%d %H:%M')
    lines = [
        f'## 版本状态数据异常 [{now_str}]',
        '',
        f'- 数据源：`{pm_url}/api/dashboard`',
        '- 结果：接口鉴权通过，但返回 0 条活跃版本',
        '- 处理：本次已跳过正常版本摘要推送，避免误导',
        '',
        '### 行动建议',
        f'1. 核对 PM 实例 `{pm_url}` 当前连接的数据库路径（`backend/data/gamedev_pm.db`）是否为正确环境',
        '2. 直接检查 `/api/versions` 是否也为 0（若为 0，优先排查后端实例数据）',
        '3. 如刚重启/重部署，确认 `backend/.env` 与数据目录未被换到空环境',
        '4. 修复后手动重跑 `py version_digest.py` 验证推送恢复',
        '',
        '<font color="#999999">小秘书提醒</font>',
    ]
    return '\n'.join(lines)


def _notify_empty_data(webhook_urls, pm_url, log_to_stdout=True):
    if not webhook_urls:
        if log_to_stdout:
            print('[version-digest] no webhook configured, skip empty-data notice', flush=True)
        return {'success': False, 'error': 'no_webhook'}
    notice = _render_empty_data_notice(pm_url)
    result = _send_digest_to_webhooks(notice, webhook_urls, quiet=not log_to_stdout)
    if log_to_stdout:
        if result.get('success'):
            print('[version-digest] empty-data notice sent (all webhooks)', flush=True)
        else:
            print(f"[version-digest] empty-data notice failed: {result.get('error')}", flush=True)
    return result


def _fallback_from_json(pm_url):
    """Read pm_data.json directly when API returns empty or fails."""
    pm_data_path = os.path.join(
        os.path.dirname(_DIR), 'pm-system', 'backend', 'data', 'pm_data.json')
    if not os.path.exists(pm_data_path):
        return []
    print(f'[version-digest] fallback: reading {pm_data_path}', flush=True)
    with open(pm_data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    today = date.today()
    versions = data.get('versions', [])
    result = []
    for v in versions:
        phase = v.get('phase', '')
        if phase == 'released':
            continue
        vid = v.get('id', '')
        rd_str = v.get('releaseDate')
        days_remaining = None
        if rd_str:
            try:
                rd = datetime.strptime(rd_str[:10], '%Y-%m-%d').date()
                days_remaining = (rd - today).days
            except ValueError:
                pass
        vf = v.get('features', [])
        def _json_feat_done(f):
            st = (f.get('status') or '').strip()
            return f.get('stage') in ('done', 'released') or st == 'done'

        done = sum(1 for f in vf if _json_feat_done(f))
        blocked = sum(1 for f in vf if f.get('isBlocked') or f.get('stage') == 'blocked')
        in_prog = sum(
            1 for f in vf
            if (not _json_feat_done(f)) and f.get('stage') in ('dev', 'qa', 'testing', 'in_progress')
        )
        not_started = len(vf) - done - blocked - in_prog
        total_cap = v.get('capacity') or 0
        allocated = sum(f.get('estimate') or 0 for f in vf)
        usage_pct = round(allocated / total_cap * 100, 1) if total_cap > 0 else 0.0
        alert = 'critical' if usage_pct > 100 else ('warning' if usage_pct > 80 else 'normal')
        risks = []
        for f in vf:
            if f.get('priority') == 'P0' and (f.get('isBlocked') or f.get('stage') == 'blocked'):
                risks.append(f"P0 Feature '{f.get('name','')}' is blocked")
        entry = {
            'id': vid,
            'name': v.get('name', '?'),
            'phase': phase,
            'releaseDate': rd_str,
            'daysRemaining': days_remaining,
            'featureSummary': {
                'total': len(vf), 'done': done,
                'inProgress': in_prog, 'blocked': blocked,
                'notStarted': not_started,
            },
            'capacitySummary': {'usagePct': usage_pct, 'alertLevel': alert},
            'risks': risks,
            '_pipeline_ddls': v.get('pipelineDdls', {}),
            '_pipeline_status': v.get('pipelineStatus', {}),
            '_pld': v.get('pldUserId', ''),
            '_ple': v.get('pleUserId', ''),
            '_plt_f': v.get('pltFUserId', '') or v.get('pltUserId', ''),
            '_plt_b': v.get('pltBUserId', ''),
            '_plt': v.get('pltFUserId', '') or v.get('pltBUserId', '') or v.get('pltUserId', ''),
        }
        result.append(entry)
    return result


def fetch_version_detail(pm_url, version_id, api_key=None):
    data = _api_get(f'{pm_url}/api/versions/{version_id}', api_key=api_key)
    return data.get('data', {})


def filter_active(versions, limit=None):
    """活跃版本：phase!=released；按 releaseDate 排序。limit 为 None 时不截断。"""
    active = [v for v in versions if v.get('phase') != 'released']
    active.sort(key=lambda v: v.get('releaseDate') or '9999-12-31')
    if limit is None:
        return active
    return active[:limit]


def pick_versions(
    versions: List[dict],
    limit: Optional[int] = 3,
    version_id: Optional[str] = None,
    version_name: Optional[str] = None,
) -> List[dict]:
    """优先按版本ID精确选单版本；否则按名称（全等）；否则走原有活跃版本筛选。"""
    if version_id:
        vid = str(version_id).strip()
        if not vid:
            return []
        for v in versions or []:
            if str(v.get('id') or '').strip() == vid:
                return [v]
        return []
    if version_name:
        name_want = str(version_name).strip()
        if not name_want:
            return []
        for v in versions or []:
            if str(v.get('name') or '').strip() == name_want:
                return [v]
        return []
    return filter_active(versions, limit)


def enrich_pipeline(pm_url, version):
    """拉版本详情，解析管线超期、当前节点、时间进度与「按日程应处于」节点。"""
    vid = version.get('id')
    api_key = version.get('_api_key')
    detail: Dict[str, Any] = {}
    if vid:
        try:
            detail = fetch_version_detail(pm_url, vid, api_key=api_key) or {}
        except Exception as e:
            print(f'[warn] cannot fetch version {vid}: {e}', flush=True)

    ddls = version.get('_pipeline_ddls') or detail.get('pipeline_ddls') or {}
    status = version.get('_pipeline_status') or detail.get('pipeline_status') or {}
    version['_pipeline_ddls'] = ddls
    version['_pipeline_status'] = status
    version.setdefault('_pld', detail.get('pld_user_id') or detail.get('pldUserId', ''))
    version.setdefault('_ple', detail.get('ple_user_id') or detail.get('pleUserId', ''))
    plt_f = detail.get('plt_f_user_id') or detail.get('pltFUserId') or detail.get('plt_user_id') or detail.get('pltUserId', '')
    plt_b = detail.get('plt_b_user_id') or detail.get('pltBUserId', '')
    version.setdefault('_plt_f', plt_f)
    version.setdefault('_plt_b', plt_b)
    version.setdefault('_plt', plt_f or plt_b)

    today = date.today()
    overdue: List[str] = []
    overdue_max_days = 0
    current_node = None

    for stage_id, label in PIPELINE_STAGES:
        if stage_id == 'retro':
            continue
        done = bool(status.get(stage_id, False))
        if done:
            continue
        ddl_str = ddls.get(stage_id)
        if ddl_str:
            try:
                ddl_date = datetime.strptime(str(ddl_str)[:10], '%Y-%m-%d').date()
                if ddl_date < today:
                    days_over = (today - ddl_date).days
                    overdue_max_days = max(overdue_max_days, days_over)
                    overdue.append(f'{label} (超{days_over}天)')
                elif current_node is None:
                    days_until = (ddl_date - today).days
                    current_node = (label, str(ddl_str)[:10], days_until)
            except ValueError:
                pass
        if current_node is None and not done:
            current_node = (label, str(ddl_str)[:10] if ddl_str else '?', None)

    version['_pipeline_overdue'] = overdue
    version['_pipeline_current'] = current_node

    start_d = _parse_iso_date(detail.get('start_date')) or _parse_iso_date(
        version.get('startDate')
    )
    release_d = _parse_iso_date(version.get('releaseDate')) or _parse_iso_date(
        detail.get('release_date')
    )
    if not start_d and release_d:
        start_d = release_d - timedelta(days=90)

    eff: Dict[str, Optional[date]] = {}
    for sid, _label, base, off in STAGE_SCHEDULE_SPEC:
        raw = ddls.get(sid)
        if raw:
            eff[sid] = _parse_iso_date(raw)
        elif base == 'start' and start_d:
            eff[sid] = start_d + timedelta(days=off)
        elif base == 'release' and release_d:
            eff[sid] = release_d + timedelta(days=off)
        else:
            eff[sid] = None

    max_behind = overdue_max_days
    for sid, _label, *_ in STAGE_SCHEDULE_SPEC:
        if bool(status.get(sid, False)):
            continue
        ddl = eff.get(sid)
        if ddl and today > ddl:
            max_behind = max(max_behind, (today - ddl).days)

    expected_label = '—'
    for sid, label, *_ in STAGE_SCHEDULE_SPEC:
        if bool(status.get(sid, False)):
            continue
        ddl = eff.get(sid)
        if ddl is None:
            expected_label = label
            break
        if today <= ddl:
            expected_label = label
            break
    if expected_label == '—':
        for sid, label, *_ in STAGE_SCHEDULE_SPEC:
            if not bool(status.get(sid, False)):
                expected_label = label
                break

    actual_label = '—'
    if current_node:
        actual_label = current_node[0]

    schedule_state = 'ok'
    if max_behind > 0:
        schedule_state = 'behind'
    else:
        if current_node and current_node[2] is not None and current_node[2] >= 14:
            schedule_state = 'ahead'

    version['_schedule_max_behind_days'] = max_behind
    version['_schedule_state'] = schedule_state
    version['_expected_stage_label'] = expected_label
    version['_actual_stage_label'] = actual_label


def _render_version(v, tmpl=None, *, checklist_append=None):
    """按产品约定结构输出：### 状态emoji 版本|剩余天 → #### 建议 → #### 时间进度 → 超期 → 数据快照等。"""
    if tmpl is None:
        tmpl = _load_template()
    show = tmpl.get('show', {})
    limits = tmpl.get('limits', {})

    name = v.get('name', '?')
    days_rem = v.get('daysRemaining')
    ps = v.get('_pipeline_status') or v.get('pipelineStatus') or {}
    release_done = bool(isinstance(ps, dict) and ps.get('release'))
    if days_rem is None:
        sub = '发版日未定'
    elif release_done:
        sub = '发版已完成，待复盘'
    elif days_rem <= 0:
        sub = '已到期或超发版日'
    else:
        sub = f'剩余{days_rem}天'

    pipeline_overdue = v.get('_pipeline_overdue') or []
    cs = v.get('capacitySummary') or {}
    risks_early = v.get('risks') or []
    al_early = cs.get('alertLevel', 'normal')
    fs = v.get('featureSummary') or {}
    tot_e = fs.get('total') or 0
    done_e = fs.get('done') or 0
    max_bd = int(v.get('_schedule_max_behind_days') or 0)

    health_bits: List[str] = []
    if pipeline_overdue:
        health_bits.append('管线超期')
    if al_early == 'critical':
        health_bits.append('容量透支')
    elif al_early == 'warning':
        health_bits.append('容量偏高')
    if risks_early:
        health_bits.append('阻塞或里程碑风险')
    if tot_e > 0 and days_rem is not None and days_rem <= 14 and done_e == 0:
        health_bits.append('Feature 完成度仍低')

    is_red = bool(pipeline_overdue or al_early == 'critical' or risks_early)
    if release_done:
        if pipeline_overdue or max_bd > 0 or is_red:
            v_emoji = '❌'
        elif health_bits:
            v_emoji = '⚠️'
        else:
            v_emoji = '✅'
    elif days_rem is not None and days_rem <= 0:
        v_emoji = '❌'
    elif pipeline_overdue or max_bd > 0 or is_red:
        v_emoji = '❌'
    elif health_bits:
        v_emoji = '⚠️'
    else:
        v_emoji = '✅'

    lines: List[str] = [f'### {v_emoji} {name}|{sub}']

    if is_red:
        action = '优先处理管线超期、解除阻塞与容量透支'
        hcolor = _DT_COLOR_RED
    elif health_bits:
        action = '跟进容量与 Feature 完成度'
        hcolor = _DT_COLOR_AMBER
    else:
        action = '维持节奏，继续按管线推进'
        hcolor = _DT_COLOR_GREEN

    overview = '、'.join(health_bits) if health_bits else '未发现上述预警项'
    lines.append(_dt_heading4(hcolor, f'[{action}]'))
    lines.append(f'{_VD_BULLET}{overview}')

    sched = v.get('_schedule_state', 'ok')
    if release_done:
        sched_title = '发版节点已完成，待复盘安排'
        scolor = _DT_COLOR_GREEN
    elif days_rem is not None and days_rem <= 0:
        sched_title = '发版日已过，请立即评估补救'
        scolor = _DT_COLOR_RED
    elif sched == 'behind' and max_bd > 0:
        sched_title = f'落后时间进度{max_bd}天'
        scolor = _DT_COLOR_RED
    elif pipeline_overdue and max_bd <= 0:
        sched_title = '落后时间进度（管线已超期）'
        scolor = _DT_COLOR_RED
    elif sched == 'ahead':
        sched_title = '高于时间进度'
        scolor = _DT_COLOR_GREEN
    else:
        sched_title = '符合时间进度'
        scolor = _DT_COLOR_BLUE

    lines.append(_dt_heading4(scolor, sched_title))
    exp = v.get('_expected_stage_label') or '—'
    act = v.get('_actual_stage_label') or '—'
    if sched_title != '符合时间进度':
        lines.append(f'{_VD_BULLET}当前应处于 **{exp}**')
        lines.append(f'{_VD_BULLET}系统实际处于 **{act}**')

    if show.get('overdue_nodes', True) and pipeline_overdue:
        max_od = int(limits.get('overdue_nodes', 5) or 5)
        max_od = max(1, min(max_od, 20))
        shown = pipeline_overdue[:max_od]
        lines.append(_dt_heading4(_DT_COLOR_RED, '超期节点'))
        for item in shown:
            lines.append(f'{_VD_BULLET}{item}')
        if len(pipeline_overdue) > max_od:
            lines.append(f'{_VD_BULLET}… 等 {len(pipeline_overdue) - max_od} 项')

    total = fs.get('total', 0)
    done = fs.get('done', 0)
    in_prog = fs.get('inProgress', 0)
    blocked = fs.get('blocked', 0)
    not_started = fs.get('notStarted', 0)
    parts = [f'{total}个']
    if done:
        parts.append(f'{done}完成')
    if in_prog:
        parts.append(f'{in_prog}开发中')
    if blocked:
        parts.append(f'{blocked}阻塞')
    if not_started:
        parts.append(f'{not_started}未开始')
    feat_snap = ' · '.join(parts) if parts else '0个'
    if total > 0:
        feat_snap += f' · 完成 {round(done / total * 100)}%'
    usage = cs.get('usagePct', 0)
    cap_al = cs.get('alertLevel', 'normal')
    alert = ALERT_ICONS.get(cap_al, '')
    cap_part = f'容量 {usage}%{alert}'
    snap_color = (
        _DT_COLOR_RED
        if cap_al == 'critical'
        else (_DT_COLOR_AMBER if cap_al == 'warning' else _DT_COLOR_SNAPSHOT_NAVY)
    )
    lines.append(_dt_heading4(snap_color, '数据快照'))
    lines.append(f'{_VD_BULLET}Feature：**{feat_snap}**')
    lines.append(f'{_VD_BULLET}{cap_part}')

    if show.get('milestone', True):
        ms = v.get('nextMilestone')
        if ms:
            ms_name = ms.get('name', '?')
            ms_date = ms.get('date', '?')
            ms_days = ms.get('daysUntil')
            suf = ''
            if ms_days is not None:
                suf = f'，{ms_days}天后到期' if ms_days > 0 else '，已到期'
            lines.append(f'{_VD_BULLET}下一里程碑：**{ms_name}**（{ms_date}）{suf}')

    if show.get('risks', True) and risks_early:
        max_risks = int(limits.get('risks', 3) or 3)
        lines.append(_dt_heading4(_DT_COLOR_AMBER, '其它风险'))
        for r in risks_early[:max_risks]:
            lines.append(f'{_VD_BULLET}{r}')

    body = '\n\n'.join(lines)
    if checklist_append:
        body = body + '\n\n' + checklist_append
    return body


def render_digest(versions, checklist_by_id=None):
    tmpl = _load_template()
    now_str = datetime.now().strftime('%m/%d %H:%M')
    title = tmpl.get('title', '## 版本状态 [{timestamp}]').format(timestamp=now_str)
    top_sep = tmpl.get('top_separator', '---')
    block_sep = '\n\n' + tmpl.get('separator', '---') + '\n\n'
    footer = '\n\n' + tmpl.get('separator', '---') + '\n\n' + tmpl.get(
        'footer', '###### ※ 小秘书提醒')

    cl = checklist_by_id or {}
    blocks = [
        _render_version(v, tmpl, checklist_append=cl.get(v.get('id')))
        for v in versions
    ] or ['（无活跃版本）']
    return title + '\n\n' + top_sep + '\n\n' + block_sep.join(blocks) + footer


def send_via_webhook(text, webhook_url, *, quiet=False, at_mobiles=None, markdown_title=None):
    title = (markdown_title or '').strip() or '小秘书提醒 · 版本状态'
    if '小秘书提醒' not in title:
        title = f'小秘书提醒 · {title}'
    payload = {
        'msgtype': 'markdown',
        'markdown': {
            'title': title,
            'text': text,
        },
    }
    if at_mobiles:
        payload['at'] = {'atMobiles': list(at_mobiles), 'isAtAll': False}
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=body,
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('errcode') == 0:
                if not quiet:
                    print('[send] webhook OK', flush=True)
                return {'success': True}
            if not quiet:
                print(f'[send] webhook error: {result}', flush=True)
            return {'success': False, 'error': str(result)}
    except Exception as e:
        if not quiet:
            print(f'[send] webhook exception: {e}', flush=True)
        return {'success': False, 'error': str(e)}


def run_version_digest_send(
    *,
    send_webhook=True,
    log_to_stdout=True,
    mark_morning=True,
    persist_state=True,
    version_id: Optional[str] = None,
    version_name: Optional[str] = None,
    audience_override: Optional[str] = None,
    ignore_workday: bool = False,
):
    """拉取活跃版本、渲染摘要；可选发 webhook。供 skill_router 与 CLI 共用。

    audience_override：仅 dry-run 单测某受众正文（pm/pld/group/full/producer），不用于生产多群发送。
    早间且 send_webhook：默认按 PM /api/config/holidays + workdays 判断「非法定假、调休算上班」；非工作日不发送。
    ignore_workday / 环境变量 VERSION_DIGEST_IGNORE_WORKDAY：跳过上述判断（补发调试用）。
    多群分流：digest_config.version_digest_audience_by_key + version_digest_progress_webhook_audience。
    版本快报（group）：多版本早间从各版本 progressNotifyWebhooks POST；不读 webhook_config 的 group 行。

    log_to_stdout=False 时不打印正文（避免 skill_router 线程里 GBK 控制台问题）。
    返回 dict: ok（已配置 webhook 且发送成功时为 True）、versions_count、digest、error（可选）
    """
    config = _load_config()
    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    webhook_urls, wc_keys = _collect_version_digest_targets(config)

    if log_to_stdout:
        print(f'[version-digest] fetching from {pm_url}', flush=True)

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except FetchAuthError as e:
        err = str(e)
        if log_to_stdout:
            print(f'[error] PM API auth failed: {err}', flush=True)
        notice_ok = False
        if send_webhook:
            notice_ret = _notify_fetch_failed(
                webhook_urls, pm_url, err, log_to_stdout=log_to_stdout
            )
            notice_ok = bool(notice_ret and notice_ret.get('success'))
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': f'auth_failed: {err}',
            'sent_failure_notice': notice_ok,
        }
    except Exception as e:
        if log_to_stdout:
            print(f'[error] cannot reach PmSystem: {e}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}
    try:
        import _push_versions_webhook_at_dm as _pvd
    except Exception as e:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}

    if (
        mark_morning
        and send_webhook
        and not ignore_workday
        and not _env_truthy('VERSION_DIGEST_IGNORE_WORKDAY')
    ):
        ranges, work_set, cal_err = _fetch_pm_calendar_for_workday(pm_url, api_key or None)
        today_d = date.today()
        if cal_err:
            if log_to_stdout:
                print(
                    f'[version-digest] calendar fetch failed ({cal_err}); '
                    f'fallback: Mon-Fri only (weekends off)',
                    flush=True,
                )
            is_work = today_d.weekday() < 5
        else:
            is_work = _is_pm_calendar_workday(today_d, ranges, work_set)
        if not is_work:
            if log_to_stdout:
                print(
                    '[version-digest] skip snapshot: non-workday (PM holidays/workdays)',
                    flush=True,
                )
            return {
                'ok': True,
                'versions_count': 0,
                'digest': '',
                'error': None,
                'skipped': True,
                'reason': 'non_workday',
            }

    state_path = _state_path_from_config(config)
    state = _load_state(state_path)
    today_s = date.today().isoformat()
    scoped_state: Dict[str, Any] = {}
    if version_id:
        scoped_state = _get_scoped_state(state, pm_url, str(version_id))
        release_target = _fetch_version_from_data(pm_url, api_key or None, str(version_id))
        if isinstance(release_target, dict):
            phase_now = str(release_target.get('phase') or '').strip()
            node_checks = release_target.get('nodeManualChecks') or {}
            online_ready = _is_release_guidance_complete(node_checks)
            if _should_send_online_notice(scoped_state, online_ready):
                vname = str(release_target.get('name') or str(version_id)).strip()
                detail_url = f"{pm_url.rstrip('/')}/index.html#version={str(version_id).strip()}"
                pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
                pm_mention, pld_mention = resolve_pm_pld_mentions(config, pm_users, release_target)
                digest = _render_online_digest(
                    version_name=vname,
                    detail_url=detail_url,
                    mode='snapshot',
                    pm_mention=pm_mention,
                    pld_mention=pld_mention,
                )
                send_webhook_urls = list(_pvd._resolve_progress_webhooks(release_target))
                if not send_webhook_urls:
                    send_webhook_urls = _collect_version_digest_webhooks(config)
                at_per_url = [[] for _ in send_webhook_urls]
                if persist_state:
                    scoped_state['online_notified_at'] = today_s
                    scoped_state['last_release_guidance_complete'] = True
                    scoped_state['last_phase'] = phase_now
                    scoped_state['latest'] = {'date': today_s, 'hash': _sha256_text(digest), 'digest': digest}
                    if mark_morning:
                        scoped_state['morning'] = {'date': today_s, 'hash': _sha256_text(digest), 'digest': digest}
                    _save_state(state_path, state)
                if not send_webhook:
                    return {'ok': True, 'versions_count': 1, 'digest': digest, 'error': None}
                if not send_webhook_urls:
                    return {'ok': False, 'versions_count': 1, 'digest': digest, 'error': 'no_webhook'}
                result = _send_digest_body_to_webhooks(digest, send_webhook_urls, at_per_url, quiet=not log_to_stdout)
                ok = bool(result and result.get('success'))
                err = None if ok else (result or {}).get('error', 'send failed')
                return {'ok': ok, 'versions_count': 1, 'digest': digest, 'error': err}
            if online_ready and str(scoped_state.get('online_notified_at') or '').strip():
                if persist_state:
                    scoped_state['last_release_guidance_complete'] = True
                    scoped_state['last_phase'] = phase_now
                    _save_state(state_path, state)
                return {
                    'ok': True,
                    'versions_count': 0,
                    'digest': '',
                    'error': None,
                    'skipped': True,
                    'reason': 'online_already_notified',
                }
            if _should_send_release_notice(scoped_state, phase_now):
                vname = str(release_target.get('name') or str(version_id)).strip()
                detail_url = f"{pm_url.rstrip('/')}/index.html#version={str(version_id).strip()}"
                pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
                pm_mention, pld_mention = resolve_pm_pld_mentions(config, pm_users, release_target)
                digest = _render_release_digest(
                    version_name=vname,
                    detail_url=detail_url,
                    mode='snapshot',
                    pm_mention=pm_mention,
                    pld_mention=pld_mention,
                )
                send_webhook_urls = list(_pvd._resolve_progress_webhooks(release_target))
                if not send_webhook_urls:
                    send_webhook_urls = _collect_version_digest_webhooks(config)
                at_per_url = [[] for _ in send_webhook_urls]
                if persist_state:
                    scoped_state['released_notified_at'] = today_s
                    scoped_state['last_phase'] = 'released'
                    scoped_state['latest'] = {'date': today_s, 'hash': _sha256_text(digest), 'digest': digest}
                    if mark_morning:
                        scoped_state['morning'] = {'date': today_s, 'hash': _sha256_text(digest), 'digest': digest}
                    _save_state(state_path, state)
                if not send_webhook:
                    return {'ok': True, 'versions_count': 1, 'digest': digest, 'error': None}
                if not send_webhook_urls:
                    return {'ok': False, 'versions_count': 1, 'digest': digest, 'error': 'no_webhook'}
                result = _send_digest_body_to_webhooks(digest, send_webhook_urls, at_per_url, quiet=not log_to_stdout)
                ok = bool(result and result.get('success'))
                err = None if ok else (result or {}).get('error', 'send failed')
                return {'ok': ok, 'versions_count': 1, 'digest': digest, 'error': err}
            if _is_released_phase(phase_now) and str(scoped_state.get('released_notified_at') or '').strip():
                if persist_state:
                    scoped_state['last_phase'] = 'released'
                    _save_state(state_path, state)
                return {
                    'ok': True,
                    'versions_count': 0,
                    'digest': '',
                    'error': None,
                    'skipped': True,
                    'reason': 'released_already_notified',
                }

    if not all_versions:
        if log_to_stdout:
            print('[error] dashboard returned 0 active versions', flush=True)
        notice_ok = False
        if send_webhook:
            notice_ret = _notify_empty_data(webhook_urls, pm_url, log_to_stdout=log_to_stdout)
            notice_ok = bool(notice_ret and notice_ret.get('success'))
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': 'empty_active_versions',
            'sent_empty_notice': notice_ok,
        }

    versions = pick_versions(
        all_versions, None, version_id=version_id, version_name=version_name,
    )
    if (version_id or version_name) and not versions:
        tag = str(version_id or version_name or '').strip()
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': f'version_not_found:{tag}',
        }
    if log_to_stdout:
        print(f'[version-digest] {len(versions)} active version(s)', flush=True)

    versions_by_id, users_by_id, pm_data_payload = fetch_pm_data_maps(
        pm_url, api_key=api_key or None,
    )
    versions = merge_versions_with_data(versions, versions_by_id)

    version_names = [
        str(v.get('name') or '').strip() for v in versions if str(v.get('name') or '').strip()
    ]

    single_mode = bool((version_id or version_name) and len(versions) == 1)
    target_version = versions[0] if single_mode else None
    detail_url = f'{pm_url.rstrip("/")}/index.html'
    if single_mode and target_version and str(target_version.get('id') or '').strip():
        detail_url = f'{detail_url}#version={str(target_version.get("id") or "").strip()}'
    elif not single_mode:
        detail_url = f'{pm_url.rstrip("/")}/index.html'

    pm_users: List[dict] = []
    if isinstance(pm_data_payload, dict):
        u_raw = pm_data_payload.get('users')
        if isinstance(u_raw, list) and u_raw:
            pm_users = [x for x in u_raw if isinstance(x, dict)]
    if not pm_users:
        pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    send_webhook_urls = list(webhook_urls)
    send_wc_keys = list(wc_keys)
    if single_mode and target_version is not None:
        send_webhook_urls, send_wc_keys = _merge_snapshot_webhooks_single_version(
            config, send_webhook_urls, send_wc_keys, target_version,
        )
    wc_keys_before_strip = list(send_wc_keys)
    send_webhook_urls, send_wc_keys = _strip_group_rows_from_digest_webhook_targets(
        send_webhook_urls,
        send_wc_keys,
        config,
        log_to_stdout=log_to_stdout,
    )

    ao = str(audience_override or '').strip()
    if ao:
        names_ao = _morning_names_from_merged(versions, ao, config)
        digest, at_ms, n_built = _pvd.render_multi_version_digest_markdown(
            pm_url,
            api_key or None,
            names_ao,
            config,
            log_to_stdout=log_to_stdout,
            audience=ao,
            data_all=pm_data_payload,
        )
        if n_built == 0:
            if log_to_stdout:
                print('[error] version digest body: no version rendered', flush=True)
            return {
                'ok': False,
                'versions_count': 0,
                'digest': '',
                'error': 'digest_body_failed',
            }
        if log_to_stdout:
            try:
                print(f'\n{digest}\n', flush=True)
            except UnicodeEncodeError:
                enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
                safe = (digest + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
                print(f'\n{safe}\n', flush=True)
        return {'ok': True, 'versions_count': n_built, 'digest': digest, 'error': None}

    raw_audiences_for_cache = _resolve_version_digest_raw_audiences(
        config,
        wc_keys_before_strip,
        single_mode=False,
    )
    need_raw = set(raw_audiences_for_cache)
    need_raw.add('full')
    if mark_morning:
        need_raw.add('producer')
    digest_cache: Dict[str, str] = {}
    at_ms: List[str] = []
    n_built_max = 0
    for ra in sorted(need_raw):
        names_ra = _morning_names_from_merged(versions, ra, config)
        d, at_ms, n_built = _pvd.render_multi_version_digest_markdown(
            pm_url,
            api_key or None,
            names_ra,
            config,
            log_to_stdout=log_to_stdout,
            audience=ra,
            data_all=pm_data_payload,
        )
        digest_cache[ra] = d
        n_built_max = max(n_built_max, n_built)
    if not any((digest_cache.get(ra) or '').strip() for ra in need_raw):
        if log_to_stdout:
            print('[error] version digest body: no audience produced content', flush=True)
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': 'digest_body_failed',
        }

    names_pld_all = _morning_names_from_merged(versions, 'pld', config)
    names_group_dbg = _morning_names_from_merged(versions, 'group', config)
    if log_to_stdout:
        print(
            f'[version-digest] scope: pld={len(names_pld_all)} {names_pld_all!r} '
            f'group={len(names_group_dbg)} {names_group_dbg!r}',
            flush=True,
        )
        if not names_group_dbg:
            print(
                '[version-digest] hint: group 无纳入版本时不会推送（需发版未完成且规划DDL未远于阈值）。',
                flush=True,
            )
        elif not _group_has_any_data_webhook(versions, names_group_dbg):
            print(
                '[version-digest] hint: 有纳入版本但各版本均未配置 progressNotifyWebhooks，版本快报无法发出。',
                flush=True,
            )

    digest_full = digest_cache['full']
    raw_audiences = _resolve_version_digest_raw_audiences(
        config,
        send_wc_keys,
        single_mode=False,
    )
    digests_per_url = [digest_cache[a] for a in raw_audiences]
    digest = digest_full

    at_per_url = _build_version_digest_at_per_url(
        config, pm_users, send_webhook_urls, send_wc_keys, at_ms,
    )

    if log_to_stdout:
        try:
            print(f'\n{digest_full}\n', flush=True)
            pairs = list(zip(send_wc_keys or [None] * len(send_webhook_urls), send_webhook_urls))
            print(f'[version-digest] webhooks: {pairs}', flush=True)
            print(f'[version-digest] audience per url: {raw_audiences}', flush=True)
            at_map = config.get('version_digest_webhook_at')
            if isinstance(at_map, dict) and at_map:
                print(f'[version-digest] @ 策略: {at_map}', flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = (digest_full + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
            print(f'\n{safe}\n', flush=True)

    metrics_map = _build_metrics_map(
        versions,
        users_by_id=users_by_id,
        default_pm_user_id=str(config.get('default_pipeline_pm_user_id') or '').strip(),
    )

    if persist_state:
        try:
            state_path = _state_path_from_config(config)
            state = _load_state(state_path)
            today_s = date.today().isoformat()
            state['schema_version'] = 1
            state['latest'] = {
                'date': today_s,
                'hash': _sha256_text(digest),
                'digest': digest,
            }
            if mark_morning:
                state['morning'] = {
                    'date': today_s,
                    'hash': _sha256_text(digest),
                    'digest': digest,
                    'metrics': metrics_map,
                }
                mp_body = str(digest_cache.get('producer') or '').strip()
                if mp_body:
                    state['morning_producer'] = {
                        'date': today_s,
                        'hash': _sha256_text(mp_body),
                        'digest': mp_body,
                        'metrics': metrics_map,
                    }
            state['latest_metrics'] = metrics_map
            if not str(state.get('last_changed_date') or '').strip():
                state['last_changed_date'] = today_s
            if single_mode and target_version is not None:
                scoped = _get_scoped_state(
                    state,
                    pm_url,
                    str(target_version.get('id') or ''),
                )
                scoped['latest'] = {
                    'date': today_s,
                    'hash': _sha256_text(digest),
                    'digest': digest,
                }
                if mark_morning:
                    scoped['morning'] = {
                        'date': today_s,
                        'hash': _sha256_text(digest),
                        'digest': digest,
                        'metrics': metrics_map,
                    }
                    mp_body_s = str(digest_cache.get('producer') or '').strip()
                    if mp_body_s:
                        scoped['morning_producer'] = {
                            'date': today_s,
                            'hash': _sha256_text(mp_body_s),
                            'digest': mp_body_s,
                            'metrics': metrics_map,
                        }
                scoped['latest_metrics'] = metrics_map
                if not str(scoped.get('last_changed_date') or '').strip():
                    scoped['last_changed_date'] = today_s
                scoped['last_phase'] = str(target_version.get('phase') or '').strip()
                scoped['last_release_guidance_complete'] = _is_release_guidance_complete(
                    target_version.get('nodeManualChecks') or {}
                )
            _save_state(state_path, state)
        except Exception as e:
            if log_to_stdout:
                print(f'[warn] save snapshot state failed: {e}', flush=True)

    if not send_webhook:
        return {'ok': True, 'versions_count': n_built_max, 'digest': digest, 'error': None}

    if not send_webhook_urls and not _group_has_any_data_webhook(versions, names_group_dbg):
        if log_to_stdout:
            print(
                '[version-digest] no webhook: digest_config 无可用行且版本未配置 progressNotifyWebhooks',
                flush=True,
            )
        return {'ok': False, 'versions_count': n_built_max, 'digest': digest,
                'error': 'no_webhook'}

    quiet = not log_to_stdout
    bodies_out = list(digests_per_url)
    if len(bodies_out) != len(send_webhook_urls):
        bodies_out = [digest_full] * len(send_webhook_urls)
    if not bodies_out:
        bodies_out = [digest_full] * len(send_webhook_urls)
    delay_s = float(config.get('version_digest_send_interval_seconds') or 0)
    titles_out = [
        _dingtalk_markdown_title_for_digest_audience(a)
        for a in raw_audiences
    ]
    send_urls_f: List[str] = []
    bodies_f: List[str] = []
    at_f: List = []
    titles_f: List[str] = []
    for i, a in enumerate(raw_audiences):
        body = bodies_out[i] if i < len(bodies_out) else ''
        url_i = send_webhook_urls[i] if i < len(send_webhook_urls) else ''
        at_i = at_per_url[i] if i < len(at_per_url) else []
        title_i = titles_out[i] if i < len(titles_out) else ''
        if a == 'pld' and len(names_pld_all) > 1:
            for vn in names_pld_all:
                d_single, _at2, _nb = _pvd.render_multi_version_digest_markdown(
                    pm_url,
                    api_key or None,
                    [vn],
                    config,
                    log_to_stdout=log_to_stdout,
                    audience='pld',
                    data_all=pm_data_payload,
                )
                if not (d_single or '').strip():
                    if log_to_stdout:
                        print(f'[version-digest] skip PLD split body empty: {vn!r}', flush=True)
                    continue
                send_urls_f.append(url_i)
                bodies_f.append(d_single)
                at_f.append(at_i)
                titles_f.append(_dingtalk_markdown_title_pld_single_version(vn))
            continue
        if a == 'pld' and not (body or '').strip():
            if log_to_stdout:
                print(f'[version-digest] skip send audience={a}: empty after filter', flush=True)
            continue
        send_urls_f.append(url_i)
        bodies_f.append(body)
        at_f.append(at_i)
        titles_f.append(title_i)

    main_ok = True
    result: Optional[dict] = None
    if send_urls_f:
        result = _send_digest_body_to_webhooks_multi(
            bodies_f,
            send_urls_f,
            at_f,
            quiet=quiet,
            delay_seconds=max(0.0, delay_s),
            markdown_titles=titles_f,
        )
        main_ok = bool(result and result.get('success'))
        if log_to_stdout:
            if main_ok:
                print(f'[version-digest] sent via {len(send_urls_f)} digest_config webhook(s)', flush=True)
            else:
                print('[version-digest] digest_config send failed (one or more webhooks)', flush=True)
    elif log_to_stdout:
        print(
            '[version-digest] no digest_config rows to POST (group uses version progressNotifyWebhooks only)',
            flush=True,
        )

    has_progress_digest_row = any(
        str(x or '').strip() == _PROGRESS_WC_KEY for x in send_wc_keys
    )
    if single_mode and has_progress_digest_row:
        group_ok, group_sent = True, 0
    else:
        group_ok, group_sent = _send_group_digests_from_version_webhooks(
            merged_versions=versions,
            names_group=names_group_dbg,
            pm_url=pm_url,
            api_key=api_key,
            config=config,
            pm_data_payload=pm_data_payload,
            _pvd=_pvd,
            log_to_stdout=log_to_stdout,
            quiet=quiet,
            send_webhook=send_webhook,
            delay_s=delay_s,
        )

    if not send_urls_f and group_sent == 0:
        if log_to_stdout:
            print('[version-digest] no webhooks to send (digest_config 全跳过且无版本快报)', flush=True)
        assistant_notified = False
        if send_webhook:
            assistant_notified = _notify_version_digest_all_skipped(
                pm_url, log_to_stdout=log_to_stdout,
            )
        return {
            'ok': False,
            'versions_count': n_built_max,
            'digest': digest,
            'error': 'all_webhooks_skipped_empty',
            'assistant_notified': assistant_notified,
        }

    ok = main_ok and group_ok
    err: Optional[str] = None
    if not ok:
        if not main_ok:
            err = (result or {}).get('error', 'send failed') if result else 'send failed'
        else:
            err = 'group_webhook_send_failed'
    if log_to_stdout:
        if ok:
            print(
                f'[version-digest] done: digest_config={len(send_urls_f)} '
                f'group_posts={group_sent}',
                flush=True,
            )
        else:
            print(f'[version-digest] partial or failed: {err}', flush=True)
    return {'ok': ok, 'versions_count': n_built_max, 'digest': digest, 'error': err}


def _dingtalk_markdown_title_pmo_evening() -> str:
    t = _load_pmo_evening_template()
    mmdd = datetime.now().strftime('%m/%d')
    return _fmt_pmo_evening(t, 'dingtalk_title', '小秘书提醒 · PMO晚报[{mmdd}]', mmdd=mmdd)


def _pmo_evening_split_vn_prefix(line: str, name_set: set) -> Optional[Tuple[str, str]]:
    """若行首为「某版本名：」且版本名在集合中，返回 (版本名, 余下正文)。"""
    s = str(line or '').strip()
    if '：' not in s:
        return None
    for vn in sorted(name_set, key=len, reverse=True):
        p = f'{vn}：'
        if s.startswith(p):
            return vn, s[len(p) :].strip()
    return None


_RE_AT_PHONE = __import__('re').compile(r'\s*@\d{10,15}')
_RE_AT_MENTION = __import__('re').compile(r'\s*@[A-Za-z\u4e00-\u9fff]+')


def _strip_at_mentions(s: str) -> str:
    """移除正文中的 @手机号 和 @PLD / @张梦君 等标记（给制作人看，不需要 @）。"""
    out = _RE_AT_PHONE.sub('', s)
    out = _RE_AT_MENTION.sub('', out)
    return out.strip()


def _render_pmo_evening_markdown(
    *,
    names_order: List[str],
    change_facts: Dict[str, Any],
    has_baseline: bool,
    quiet: bool,
    calendar_err: Optional[str] = None,
) -> str:
    """PMO 晚报正文：文案见 message_templates.json · pmo_evening。"""
    t = _load_pmo_evening_template()
    mmdd = datetime.now().strftime('%m/%d')
    hhmm = datetime.now().strftime('%H:%M')
    suf_nc = str(t.get('suffix_risk_no_change') or '（没变化项）')
    suf_st = str(t.get('suffix_risk_stale') or '（连续无变化风险）')
    suf_pd = str(t.get('suffix_risk_pending') or '（待跟进）')
    bullet = str(t.get('bullet') or _VD_BULLET)
    sep = str(t.get('separator') or '---')
    vl_tpl = str(t.get('version_label') or '**【{version}】**')
    facts = change_facts or {}
    progress_lines = list(facts.get('progress') or [])
    followup = list(facts.get('followup_stale') or [])
    stale_a = list(facts.get('stale_alert') or [])
    no_change = list(facts.get('no_change') or [])

    names_order = [str(x or '').strip() for x in names_order if str(x or '').strip()]
    name_set = set(names_order)
    multi = len(names_order) > 1

    prog_by: Dict[str, List[str]] = {n: [] for n in names_order}
    extra_prog: List[str] = []
    for line in progress_lines:
        raw = _strip_at_mentions(str(line).strip())
        if not raw:
            continue
        if multi:
            sp = _pmo_evening_split_vn_prefix(raw, name_set)
            if sp:
                vn, rest = sp
                prog_by[vn].append(rest)
                continue
            extra_prog.append(raw)
        else:
            if names_order:
                prog_by[names_order[0]].append(raw)
            else:
                extra_prog.append(raw)

    sec1_lines: List[str] = []
    for vn in names_order:
        parts = [p for p in prog_by.get(vn) or [] if p]
        if parts:
            try:
                sec1_lines.append(vl_tpl.format(version=vn))
            except Exception:
                sec1_lines.append(f'**【{vn}】**')
            for p in parts:
                sec1_lines.append(f'{bullet}{p}')
    for ep in extra_prog:
        sec1_lines.append(f'{bullet}{ep}')

    if quiet:
        sec1_body = str(t.get('body_progress_quiet') or f'{bullet}暂无相对早间的新增可量化进展。')
    elif not sec1_lines:
        if not has_baseline:
            sec1_body = _fmt_pmo_evening(
                t, 'body_progress_first_run', f'{bullet}首次运行已建基线，明日起对比晚间变化。',
                bullet=bullet,
            )
        else:
            sec1_body = str(t.get('body_progress_empty') or f'{bullet}暂无相对早间的新增可量化进展。')
    else:
        sec1_body = '\n\n'.join(sec1_lines)

    risk_by: Dict[str, List[str]] = defaultdict(list)

    def _add_risk(vn_key: str, text: str) -> None:
        tx = _strip_at_mentions(str(text or '').strip())
        if not tx:
            return
        vn_key = str(vn_key or '').strip()
        if vn_key in name_set:
            risk_by[vn_key].append(tx)
        else:
            risk_by['__unmapped__'].append(tx)

    for line in followup:
        s = _strip_at_mentions(str(line).strip())
        if not s:
            continue
        sp = _pmo_evening_split_vn_prefix(s, name_set)
        if sp:
            vn, rest = sp
            _add_risk(vn, f'{rest}{suf_nc}')
        elif '：' in s:
            vn, rest = s.split('：', 1)
            _add_risk(vn.strip(), f'{rest.strip()}{suf_nc}')
        else:
            _add_risk(names_order[0] if names_order else '', f'{s}{suf_nc}')

    for line in stale_a:
        s = _strip_at_mentions(str(line).strip())
        if not s:
            continue
        sp = _pmo_evening_split_vn_prefix(s, name_set)
        if sp:
            vn, rest = sp
            _add_risk(vn, f'{rest}{suf_st}')
        elif '：' in s:
            vn, rest = s.split('：', 1)
            _add_risk(vn.strip(), f'{rest.strip()}{suf_st}')
        else:
            _add_risk(names_order[0] if names_order else '', s)

    for block in no_change:
        blk = _strip_at_mentions(str(block).strip())
        if not blk:
            continue
        first_ln, _, rest_blk = blk.partition('\n')
        if '：' in first_ln:
            vn, lead = first_ln.split('：', 1)
            vn = vn.strip()
            tail = _strip_at_mentions(
                (lead.strip() + (' ' + rest_blk.replace('\n', ' ') if rest_blk else '')).strip()
            )
            _add_risk(vn, f'{tail}{suf_pd}')
        else:
            _add_risk(names_order[0] if names_order else '', f'{blk}{suf_pd}')

    if calendar_err:
        risk_by['__meta__'].append(
            _fmt_pmo_evening(t, 'calendar_err_line', f'{bullet}工作日历读取异常：{{detail}}', detail=str(calendar_err))
        )

    sec2_lines: List[str] = []
    for vn in names_order:
        rs = [x for x in risk_by.get(vn) or [] if x]
        if rs:
            try:
                sec2_lines.append(vl_tpl.format(version=vn))
            except Exception:
                sec2_lines.append(f'**【{vn}】**')
            for r in rs:
                sec2_lines.append(f'{bullet}{r}')
    um = [x for x in risk_by.get('__unmapped__') or [] if x]
    for u in um:
        sec2_lines.append(f'{bullet}{u}')
    meta = [x for x in risk_by.get('__meta__') or [] if x]
    for m in meta:
        sec2_lines.append(m)

    empty_risk = str(t.get('body_risk_empty') or f'{bullet}暂无需要单独预警的「相对早间无变化」项。')
    if sec2_lines:
        sec2_body = '\n\n'.join(sec2_lines)
    else:
        sec2_body = empty_risk

    heading = _fmt_pmo_evening(t, 'heading', '## PMO晚报[{mmdd}]', mmdd=mmdd)
    hdr_p = str(t.get('section_progress_header') or '## <font color="#166534">今日实际进展</font>')
    hdr_r = str(t.get('section_risk_header') or '## <font color="#b45309">风险预警</font>')
    foot = _fmt_pmo_evening(t, 'footer', '###### ※ 小秘书提醒 · {mmdd} {hhmm}', mmdd=mmdd, hhmm=hhmm)

    layout = str(
        t.get('body_layout')
        or '{heading}\n\n{sep}\n\n{hdr_progress}\n\n{sec_progress}\n\n'
           '{sep}\n\n{hdr_risk}\n\n{sec_risk}\n\n'
           '{sep}\n\n{footer}'
    )
    try:
        return layout.format(
            heading=heading,
            sep=sep,
            hdr_progress=hdr_p,
            sec_progress=sec1_body,
            hdr_risk=hdr_r,
            sec_risk=sec2_body,
            footer=foot,
        )
    except Exception:
        return (
            f'{heading}\n\n{sep}\n\n{hdr_p}\n\n{sec1_body}\n\n'
            f'{sep}\n\n{hdr_r}\n\n{sec2_body}\n\n'
            f'{sep}\n\n{foot}'
        )


def _dingtalk_markdown_title_pm_evening() -> str:
    t = _load_pm_evening_template()
    mmdd = datetime.now().strftime('%m/%d')
    return _fmt_pm_evening(t, 'dingtalk_title', '小秘书提醒 · 管线晚报[{mmdd}]', mmdd=mmdd)


def _render_pm_evening_markdown(
    *,
    names_order: List[str],
    change_facts: Dict[str, Any],
    current_metrics: Dict[str, dict],
    has_baseline: bool,
    quiet: bool,
    calendar_err: Optional[str] = None,
) -> str:
    """PM 晚报正文：参照管线快报视觉风格重组 change_facts + current_metrics。"""
    t = _load_pm_evening_template()
    mmdd = datetime.now().strftime('%m/%d')
    hhmm = datetime.now().strftime('%H:%M')
    bullet = str(t.get('bullet') or _VD_BULLET)
    sep = str(t.get('separator') or '---')
    vl_tpl = str(t.get('version_label') or '**【{version}】**')
    vs_tpl = str(t.get('version_summary') or '<font color="#6b7280">距发版{days_remaining}天 · 进度 {done}/{total}</font>')
    vs_nd_tpl = str(t.get('version_summary_no_date') or '<font color="#6b7280">进度 {done}/{total}</font>')
    em_crit = str(t.get('emoji_critical') or '\u274c')
    em_warn = str(t.get('emoji_warning') or '\u26a0\ufe0f')
    em_ok = str(t.get('emoji_ok') or '\u2705')
    c_blocked = str(t.get('color_blocked') or '#dc2626')
    c_unassigned = str(t.get('color_unassigned') or '#b45309')
    c_dor = str(t.get('color_dor') or '#6b7280')

    names_order = [str(x or '').strip() for x in names_order if str(x or '').strip()]
    name_set = set(names_order)
    metrics_by_name: Dict[str, dict] = {}
    for m in (current_metrics or {}).values():
        mn = str(m.get('name') or '').strip()
        if mn:
            metrics_by_name[mn] = m

    # --- Section 1: 需处理事项 ---
    action_lines: List[str] = []
    for vn in names_order:
        m = metrics_by_name.get(vn)
        if not m:
            continue
        items: List[str] = []
        has_blocked = m.get('blocked', 0) > 0
        if has_blocked:
            bnames = m.get('blocked_names') or []
            txt = f'阻塞 {m["blocked"]} 项：{"、".join(bnames[:3])}' if bnames else f'阻塞 {m["blocked"]} 项'
            items.append(f'<font color="{c_blocked}">{txt}</font>')
        if m.get('unassigned', 0) > 0:
            txt = f'未指派负责人 {m["unassigned"]} 项'
            items.append(f'<font color="{c_unassigned}">{txt}</font>')
        if m.get('dor_gap', 0) > 0:
            dnames = m.get('dor_not_ready_names') or []
            txt = f'DoR 未就绪 {m["dor_gap"]} 项：{"、".join(dnames[:3])}' if dnames else f'DoR 未就绪 {m["dor_gap"]} 项'
            items.append(f'<font color="{c_dor}">{txt}</font>')
        if not items:
            continue
        emoji = em_crit if has_blocked else em_warn
        dr = m.get('days_remaining')
        done = m.get('done', 0)
        total = m.get('total', 0)
        try:
            vlabel = vl_tpl.format(version=vn)
        except Exception:
            vlabel = f'**【{vn}】**'
        if dr is not None:
            try:
                vsummary = vs_tpl.format(days_remaining=dr, done=done, total=total)
            except Exception:
                vsummary = f'距发版{dr}天 \u00b7 进度 {done}/{total}'
        else:
            try:
                vsummary = vs_nd_tpl.format(done=done, total=total)
            except Exception:
                vsummary = f'进度 {done}/{total}'
        action_lines.append(f'{emoji} {vlabel} {vsummary}')
        for item in items:
            action_lines.append(f'{bullet}{item}')

    if not action_lines:
        sec1_body = str(t.get('body_action_empty') or f'{em_ok} 当前各版本无阻塞、未指派、DoR 缺口项。')
    else:
        sec1_body = '\n\n'.join(action_lines)

    # --- Section 2: 今日进展 ---
    facts = change_facts or {}
    progress_lines = list(facts.get('progress') or [])
    multi = len(names_order) > 1

    prog_by: Dict[str, List[str]] = {n: [] for n in names_order}
    extra_prog: List[str] = []
    for line in progress_lines:
        raw = _strip_at_mentions(str(line).strip())
        if not raw:
            continue
        if multi:
            sp = _pmo_evening_split_vn_prefix(raw, name_set)
            if sp:
                vn, rest = sp
                prog_by[vn].append(rest)
                continue
            extra_prog.append(raw)
        else:
            if names_order:
                prog_by[names_order[0]].append(raw)
            else:
                extra_prog.append(raw)

    sec2_lines: List[str] = []
    for vn in names_order:
        parts = [p for p in prog_by.get(vn) or [] if p]
        if parts:
            try:
                sec2_lines.append(vl_tpl.format(version=vn))
            except Exception:
                sec2_lines.append(f'**【{vn}】**')
            for p in parts:
                sec2_lines.append(f'{bullet}{p}')
    for ep in extra_prog:
        sec2_lines.append(f'{bullet}{ep}')

    if quiet:
        sec2_body = str(t.get('body_progress_quiet') or f'{bullet}暂无相对早间的新增可量化进展。')
    elif not sec2_lines:
        if not has_baseline:
            sec2_body = _fmt_pm_evening(
                t, 'body_progress_first_run', f'{bullet}首次运行已建基线，明日起对比晚间变化。',
                bullet=bullet,
            )
        else:
            sec2_body = str(t.get('body_progress_empty') or f'{bullet}暂无相对早间的新增可量化进展。')
    else:
        sec2_body = '\n\n'.join(sec2_lines)

    # --- Section 3: 跟进提醒（按版本分组） ---
    followup = list(facts.get('followup_stale') or [])
    stale_a = list(facts.get('stale_alert') or [])
    no_change = list(facts.get('no_change') or [])

    follow_by: Dict[str, List[str]] = defaultdict(list)

    def _parse_follow_line(raw: str) -> None:
        s = _strip_at_mentions(raw.strip())
        if not s:
            return
        sp = _pmo_evening_split_vn_prefix(s, name_set)
        if sp:
            vn, rest = sp
            for part in rest.split('   '):
                p = part.strip().lstrip('- ').strip()
                if p:
                    follow_by[vn].append(p)
            return
        if '\uff1a' in s:
            vn, rest = s.split('\uff1a', 1)
            vn = vn.strip()
            if vn in name_set:
                for part in rest.split('   '):
                    p = part.strip().lstrip('- ').strip()
                    if p:
                        follow_by[vn].append(p)
                return
        follow_by['__other__'].append(s)

    for line in followup:
        _parse_follow_line(str(line))
    for line in stale_a:
        _parse_follow_line(str(line))
    _SKIP_LEADS = {'今日无推进', '无推进'}
    for block in no_change:
        blk = str(block).strip()
        if not blk:
            continue
        first_ln, _, rest_blk = blk.partition('\n')
        first_ln = _strip_at_mentions(first_ln.strip())
        sub_items: List[str] = []
        if rest_blk:
            for sub in rest_blk.split('\n'):
                p = _strip_at_mentions(sub.strip().lstrip('- ').strip())
                if p:
                    sub_items.append(p)
        if '\uff1a' in first_ln:
            vn, lead = first_ln.split('\uff1a', 1)
            vn = vn.strip()
            lead = lead.strip()
            if vn in name_set:
                if sub_items:
                    merged = '\u3001'.join(sub_items)
                    if lead and lead not in _SKIP_LEADS:
                        follow_by[vn].append(f'{lead} \u2014 {merged}')
                    else:
                        follow_by[vn].append(merged)
                elif lead:
                    follow_by[vn].append(lead)
                continue
        if sub_items:
            lead_t = first_ln.strip()
            merged = '\u3001'.join(sub_items)
            if lead_t and lead_t not in _SKIP_LEADS:
                follow_by['__other__'].append(f'{lead_t} \u2014 {merged}')
            else:
                follow_by['__other__'].append(merged)
        elif first_ln.strip():
            _parse_follow_line(first_ln)

    if calendar_err:
        follow_by['__meta__'].append(
            _fmt_pm_evening(t, 'calendar_err_line', f'{bullet}工作日历读取异常：{{detail}}', detail=str(calendar_err))
        )

    sec3_lines: List[str] = []
    for vn in names_order:
        items = [x for x in follow_by.get(vn) or [] if x]
        if items:
            try:
                sec3_lines.append(vl_tpl.format(version=vn))
            except Exception:
                sec3_lines.append(f'**【{vn}】**')
            for item in items:
                sec3_lines.append(f'{bullet}{item}')
    other = [x for x in follow_by.get('__other__') or [] if x]
    for o in other:
        sec3_lines.append(f'{bullet}{o}')
    meta = [x for x in follow_by.get('__meta__') or [] if x]
    for m in meta:
        sec3_lines.append(m)

    if sec3_lines:
        sec3_body = '\n\n'.join(sec3_lines)
    else:
        sec3_body = str(t.get('body_followup_empty') or f'{bullet}暂无需跟进的无变化项。')

    heading = _fmt_pm_evening(t, 'heading', '## 管线晚报[{mmdd}]', mmdd=mmdd)
    hdr_a = str(t.get('section_action_header') or '## <font color="#b45309">需处理事项</font>')
    hdr_p = str(t.get('section_progress_header') or '## <font color="#166534">今日进展</font>')
    hdr_f = str(t.get('section_followup_header') or '## <font color="#1e40af">跟进提醒</font>')
    foot = _fmt_pm_evening(t, 'footer', '###### ※ 小秘书提醒 · {mmdd} {hhmm}', mmdd=mmdd, hhmm=hhmm)

    layout = str(
        t.get('body_layout')
        or '{heading}\n\n{sep}\n\n{hdr_action}\n\n{sec_action}\n\n'
           '{sep}\n\n{hdr_progress}\n\n{sec_progress}\n\n'
           '{sep}\n\n{hdr_followup}\n\n{sec_followup}\n\n'
           '{sep}\n\n{footer}'
    )
    try:
        return layout.format(
            heading=heading,
            sep=sep,
            hdr_action=hdr_a,
            sec_action=sec1_body,
            hdr_progress=hdr_p,
            sec_progress=sec2_body,
            hdr_followup=hdr_f,
            sec_followup=sec3_body,
            footer=foot,
        )
    except Exception:
        return (
            f'{heading}\n\n{sep}\n\n{hdr_a}\n\n{sec1_body}\n\n'
            f'{sep}\n\n{hdr_p}\n\n{sec2_body}\n\n'
            f'{sep}\n\n{hdr_f}\n\n{sec3_body}\n\n'
            f'{sep}\n\n{foot}'
        )


def run_pmo_evening_send(
    *,
    send_webhook: bool = True,
    log_to_stdout: bool = True,
    persist_state: bool = True,
) -> dict:
    """制作人向：与早间 producer 正文同源对比；POST 到 digest_config.version_digest_pmo_evening_webhook_key（默认 version_digest_assistant）。"""
    config = _load_config()
    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    stale_threshold = int(config.get('version_change_stale_days', 3) or 3)
    wc = _load_webhook_config()
    wkey = str(config.get('version_digest_pmo_evening_webhook_key') or 'version_digest_assistant').strip()
    evening_url = str(wc.get(wkey) or '').strip()
    if not evening_url:
        if log_to_stdout:
            print(f'[pmo-evening] webhook_config 缺少 {wkey!r}，无法发送', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'no_evening_webhook'}

    state_path = _state_path_from_config(config)
    state = _load_state(state_path)
    today_s = date.today().isoformat()

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except Exception as e:
        if log_to_stdout:
            print(f'[error] cannot reach PmSystem: {e}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}
    try:
        import _push_versions_webhook_at_dm as _pvd
    except Exception as e:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}

    if not all_versions:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'empty_active_versions'}

    versions = pick_versions(all_versions, None, version_id=None, version_name=None)
    versions_by_id, users_by_id, pm_data_payload = fetch_pm_data_maps(
        pm_url, api_key=api_key or None,
    )
    versions = merge_versions_with_data(versions, versions_by_id)
    names_prod = _morning_names_from_merged(versions, 'producer', config)
    if not names_prod:
        if log_to_stdout:
            print('[pmo-evening] producer 范围无版本，跳过', flush=True)
        return {
            'ok': True,
            'versions_count': 0,
            'digest': '',
            'error': None,
            'skipped': True,
            'reason': 'no_producer_versions',
        }

    current_body, at_ms, n_built = _pvd.render_multi_version_digest_markdown(
        pm_url,
        api_key or None,
        names_prod,
        config,
        log_to_stdout=log_to_stdout,
        audience='producer',
        data_all=pm_data_payload,
    )
    if n_built == 0 or not (current_body or '').strip():
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'digest_body_failed'}

    current_hash = _sha256_text(current_body)
    morning_p = state.get('morning_producer') if isinstance(state.get('morning_producer'), dict) else {}
    morning_f = state.get('morning') if isinstance(state.get('morning'), dict) else {}
    baseline_text = ''
    baseline_metrics: Dict[str, dict] = {}
    if str(morning_p.get('date') or '') == today_s:
        baseline_text = str(morning_p.get('digest') or '')
        if isinstance(morning_p.get('metrics'), dict):
            baseline_metrics = dict(morning_p.get('metrics') or {})
    if not baseline_text and str(morning_f.get('date') or '') == today_s:
        baseline_text = str(morning_f.get('digest') or '')
        if log_to_stdout:
            print(
                '[pmo-evening] 无 morning_producer，回退今日 morning 全量基线（对比口径可能偏宽）',
                flush=True,
            )
        if isinstance(morning_f.get('metrics'), dict):
            baseline_metrics = dict(morning_f.get('metrics') or {})
    if not baseline_text:
        baseline_text = str((state.get('latest') or {}).get('digest') or '')
    latest_m = state.get('latest_metrics') if isinstance(state.get('latest_metrics'), dict) else None
    if not baseline_metrics and latest_m:
        baseline_metrics = dict(latest_m or {})
    has_baseline = bool(baseline_text.strip())
    changed = True
    if has_baseline:
        changed = _sha256_text(baseline_text) != current_hash

    last_changed_s = str(state.get('last_changed_date') or '').strip() or today_s
    if changed:
        last_changed_s = today_s
    stale_days: Optional[int] = None
    holidays: List[str] = []
    workdays: List[str] = []
    calendar_err: Optional[str] = None
    if not changed:
        holidays, workdays, calendar_err = _fetch_workday_calendar(pm_url, api_key or None)
        try:
            start_d = datetime.strptime(last_changed_s[:10], '%Y-%m-%d').date()
            end_d = date.today()
            if calendar_err:
                stale_days = None
            else:
                stale_days = _count_workdays_between(
                    start_d,
                    end_d,
                    set(holidays),
                    set(workdays),
                )
        except Exception:
            stale_days = None
    else:
        stale_days = 0

    current_metrics = _build_metrics_map(
        versions,
        users_by_id=users_by_id,
        default_pm_user_id=str(config.get('default_pipeline_pm_user_id') or '').strip(),
    )
    change_facts = _build_change_facts(
        baseline_map=baseline_metrics,
        current_map=current_metrics,
        stale_days=stale_days,
        stale_threshold=stale_threshold,
        config=config,
    )
    has_stale_content = bool(calendar_err) or bool(change_facts.get('stale_alert')) or (
        stale_days is not None and stale_days >= stale_threshold
    )
    use_quiet_day = (
        has_baseline
        and not change_facts.get('progress')
        and not change_facts.get('no_change')
        and not change_facts.get('followup_stale')
        and not has_stale_content
    )
    pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    digest_kind = 'normal'
    if use_quiet_day:
        already_q = str(state.get('quiet_evening_pmo_sent_date') or '').strip() == today_s
        if already_q:
            if log_to_stdout:
                print('[pmo-evening] 今日已发过 quiet，跳过', flush=True)
            return {
                'ok': True,
                'versions_count': n_built,
                'digest': '',
                'error': None,
                'skipped': True,
                'reason': 'quiet_evening_pmo_already_sent',
            }
        digest_kind = 'quiet'
        if log_to_stdout:
            print('[pmo-evening] 无 delta，发制作人 PMO晚报（quiet）', flush=True)
        digest = _render_pmo_evening_markdown(
            names_order=names_prod,
            change_facts=change_facts,
            has_baseline=has_baseline,
            quiet=True,
            calendar_err=calendar_err,
        )
    else:
        digest = _render_pmo_evening_markdown(
            names_order=names_prod,
            change_facts=change_facts,
            has_baseline=has_baseline,
            quiet=False,
            calendar_err=calendar_err,
        )
    digest = digest.rstrip()

    at_per_url: Dict[str, List[str]] = {}

    if persist_state:
        try:
            state['schema_version'] = 1
            state['latest_producer'] = {
                'date': today_s,
                'hash': current_hash,
                'digest': current_body,
            }
            if digest_kind == 'quiet':
                state['quiet_evening_pmo_sent_date'] = today_s
            else:
                state.pop('quiet_evening_pmo_sent_date', None)
            _save_state(state_path, state)
        except Exception as e:
            if log_to_stdout:
                print(f'[warn] save pmo-evening state failed: {e}', flush=True)

    if log_to_stdout:
        try:
            print(f'\n{digest}\n', flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = (digest + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
            print(f'\n{safe}\n', flush=True)

    if not send_webhook:
        return {'ok': True, 'versions_count': n_built, 'digest': digest, 'error': None}

    quiet = not log_to_stdout
    result = _send_digest_body_to_webhooks(
        digest,
        [evening_url],
        at_per_url,
        quiet=quiet,
        markdown_titles=[_dingtalk_markdown_title_pmo_evening()],
    )
    ok = bool(result and result.get('success'))
    err = None if ok else (result or {}).get('error', 'send failed')
    return {'ok': ok, 'versions_count': n_built, 'digest': digest, 'error': err}


def run_pm_evening_send(
    *,
    send_webhook: bool = True,
    log_to_stdout: bool = True,
    persist_state: bool = True,
) -> dict:
    """PM 晚报：行动视角重组，推 PMO 群，@ PM+APM。"""
    config = _load_config()
    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    stale_threshold = int(config.get('version_change_stale_days', 3) or 3)
    wc = _load_webhook_config()
    wkey = str(config.get('version_digest_pm_evening_webhook_key') or 'version_digest_pmo').strip()
    evening_url = str(wc.get(wkey) or '').strip()
    if not evening_url:
        if log_to_stdout:
            print(f'[pm-evening] webhook_config missing {wkey!r}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'no_pm_evening_webhook'}

    state_path = _state_path_from_config(config)
    state = _load_state(state_path)
    today_s = date.today().isoformat()

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except Exception as e:
        if log_to_stdout:
            print(f'[error] cannot reach PmSystem: {e}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}
    try:
        import _push_versions_webhook_at_dm as _pvd
    except Exception as e:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}

    if not all_versions:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'empty_active_versions'}

    versions = pick_versions(all_versions, None, version_id=None, version_name=None)
    versions_by_id, users_by_id, pm_data_payload = fetch_pm_data_maps(
        pm_url, api_key=api_key or None,
    )
    versions = merge_versions_with_data(versions, versions_by_id)
    names_pm = _morning_names_from_merged(versions, 'pm', config)
    if not names_pm:
        if log_to_stdout:
            print('[pm-evening] pm scope has no versions, skip', flush=True)
        return {'ok': True, 'versions_count': 0, 'digest': '', 'error': None, 'skipped': True}

    current_body, at_ms, n_built = _pvd.render_multi_version_digest_markdown(
        pm_url,
        api_key or None,
        names_pm,
        config,
        log_to_stdout=log_to_stdout,
        audience='pm',
        data_all=pm_data_payload,
    )
    if n_built == 0 or not (current_body or '').strip():
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'digest_body_failed'}

    current_hash = _sha256_text(current_body)
    morning_f = state.get('morning') if isinstance(state.get('morning'), dict) else {}
    baseline_text = ''
    baseline_metrics: Dict[str, dict] = {}
    if str(morning_f.get('date') or '') == today_s:
        baseline_text = str(morning_f.get('digest') or '')
        if isinstance(morning_f.get('metrics'), dict):
            baseline_metrics = dict(morning_f.get('metrics') or {})
    if not baseline_text:
        if log_to_stdout:
            print('[pm-evening] no morning baseline today, falling back to latest', flush=True)
    if not baseline_text:
        baseline_text = str((state.get('latest') or {}).get('digest') or '')
    latest_m = state.get('latest_metrics') if isinstance(state.get('latest_metrics'), dict) else None
    if not baseline_metrics and latest_m:
        baseline_metrics = dict(latest_m or {})
    has_baseline = bool(baseline_text.strip())
    changed = True
    if has_baseline:
        changed = _sha256_text(baseline_text) != current_hash

    last_changed_s = str(state.get('last_changed_date') or '').strip() or today_s
    if changed:
        last_changed_s = today_s
    stale_days: Optional[int] = None
    holidays: List[str] = []
    workdays: List[str] = []
    calendar_err: Optional[str] = None
    if not changed:
        holidays, workdays, calendar_err = _fetch_workday_calendar(pm_url, api_key or None)
        try:
            start_d = datetime.strptime(last_changed_s[:10], '%Y-%m-%d').date()
            end_d = date.today()
            if calendar_err:
                stale_days = None
            else:
                stale_days = _count_workdays_between(start_d, end_d, set(holidays), set(workdays))
        except Exception:
            stale_days = None
    else:
        stale_days = 0

    all_metrics = _build_metrics_map(
        versions,
        users_by_id=users_by_id,
        default_pm_user_id=str(config.get('default_pipeline_pm_user_id') or '').strip(),
    )
    pm_name_set = set(names_pm)
    current_metrics = {
        k: v for k, v in all_metrics.items()
        if str(v.get('name', '')).strip() in pm_name_set
    }
    baseline_metrics = {
        k: v for k, v in baseline_metrics.items()
        if str(v.get('name', '')).strip() in pm_name_set
    }
    change_facts = _build_change_facts(
        baseline_map=baseline_metrics,
        current_map=current_metrics,
        stale_days=stale_days,
        stale_threshold=stale_threshold,
        config=config,
    )

    has_action_items = any(
        (m.get('blocked', 0) > 0 or m.get('unassigned', 0) > 0 or m.get('dor_gap', 0) > 0)
        for m in current_metrics.values()
    )
    use_quiet = (
        has_baseline
        and not change_facts.get('progress')
        and not change_facts.get('followup_stale')
        and not change_facts.get('stale_alert')
        and not has_action_items
    )

    pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    at_mobiles = _at_mobiles_pm_apm(config, pm_users)

    if use_quiet:
        already_q = str(state.get('quiet_evening_pm_sent_date') or '').strip() == today_s
        if already_q:
            if log_to_stdout:
                print('[pm-evening] already sent quiet today, skip', flush=True)
            return {'ok': True, 'versions_count': n_built, 'digest': '', 'skipped': True}
        if log_to_stdout:
            print('[pm-evening] no delta + no action items, sending quiet', flush=True)
        digest = _render_pm_evening_markdown(
            names_order=names_pm,
            change_facts=change_facts,
            current_metrics=current_metrics,
            has_baseline=has_baseline,
            quiet=True,
            calendar_err=calendar_err,
        )
    else:
        digest = _render_pm_evening_markdown(
            names_order=names_pm,
            change_facts=change_facts,
            current_metrics=current_metrics,
            has_baseline=has_baseline,
            quiet=False,
            calendar_err=calendar_err,
        )
    digest = digest.rstrip()

    if persist_state:
        try:
            if use_quiet:
                state['quiet_evening_pm_sent_date'] = today_s
            else:
                state.pop('quiet_evening_pm_sent_date', None)
            _save_state(state_path, state)
        except Exception as e:
            if log_to_stdout:
                print(f'[warn] save pm-evening state failed: {e}', flush=True)

    if log_to_stdout:
        try:
            print(f'\n{digest}\n', flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = (digest + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
            print(f'\n{safe}\n', flush=True)

    if not send_webhook:
        return {'ok': True, 'versions_count': n_built, 'digest': digest, 'error': None}

    quiet_flag = not log_to_stdout
    title = _dingtalk_markdown_title_pm_evening()
    result = send_via_webhook(
        digest, evening_url, quiet=quiet_flag,
        at_mobiles=at_mobiles or None,
        markdown_title=title,
    )
    ok = bool(result and result.get('success'))
    err = None if ok else (result or {}).get('error', 'send failed')
    return {'ok': ok, 'versions_count': n_built, 'digest': digest, 'error': err}


def run_version_change_send(
    *,
    send_webhook=True,
    log_to_stdout=True,
    persist_state=True,
    version_id: Optional[str] = None,
    version_name: Optional[str] = None,
):
    """傍晚推送：输出“今日变化”短消息，不再重复早间全量快照。"""
    config = _load_config()
    pm_url = config.get('pm_system_url', 'http://127.0.0.1:8000').rstrip('/')
    api_key = config.get('pm_system_api_key', '')
    limit = config.get('version_digest_limit', 3)
    webhook_urls, wc_keys = _collect_version_digest_targets(config)
    stale_threshold = int(config.get('version_change_stale_days', 3) or 3)

    if log_to_stdout:
        print(f'[version-change] fetching from {pm_url}', flush=True)

    try:
        all_versions = fetch_dashboard(pm_url, api_key=api_key or None)
    except Exception as e:
        if log_to_stdout:
            print(f'[error] cannot reach PmSystem: {e}', flush=True)
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}
    try:
        import _push_versions_webhook_at_dm as _pvd
    except Exception as e:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': str(e)}

    state_path = _state_path_from_config(config)
    state = _load_state(state_path)
    today_s = date.today().isoformat()
    scoped_state: Dict[str, Any] = {}
    release_target: Optional[dict] = None
    if version_id:
        scoped_state = _get_scoped_state(state, pm_url, str(version_id))
        release_target = _fetch_version_from_data(pm_url, api_key or None, str(version_id))
        if isinstance(release_target, dict):
            phase_now = str(release_target.get('phase') or '').strip()
            node_checks = release_target.get('nodeManualChecks') or {}
            online_ready = _is_release_guidance_complete(node_checks)
            if _should_send_online_notice(scoped_state, online_ready):
                vname = str(release_target.get('name') or str(version_id)).strip()
                detail_url = f"{pm_url.rstrip('/')}/index.html#version={str(version_id).strip()}"
                pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
                pm_mention, pld_mention = resolve_pm_pld_mentions(config, pm_users, release_target)
                digest = _render_online_digest(
                    version_name=vname,
                    detail_url=detail_url,
                    mode='change',
                    pm_mention=pm_mention,
                    pld_mention=pld_mention,
                )
                send_webhook_urls = list(_pvd._resolve_progress_webhooks(release_target))
                if not send_webhook_urls:
                    send_webhook_urls = _collect_version_digest_webhooks(config)
                one_at = list(_pvd._pipeline_at_mobiles(config, pm_users, release_target))
                at_per_url = [one_at for _ in send_webhook_urls]
                if persist_state:
                    scoped_state['online_notified_at'] = today_s
                    scoped_state['last_release_guidance_complete'] = True
                    scoped_state['last_phase'] = phase_now
                    scoped_state['latest'] = {'date': today_s, 'hash': _sha256_text(digest), 'digest': digest}
                    _save_state(state_path, state)
                if not send_webhook:
                    return {'ok': True, 'versions_count': 1, 'digest': digest, 'error': None}
                if not send_webhook_urls:
                    return {'ok': False, 'versions_count': 1, 'digest': digest, 'error': 'no_webhook'}
                result = _send_digest_body_to_webhooks(digest, send_webhook_urls, at_per_url, quiet=not log_to_stdout)
                ok = bool(result and result.get('success'))
                err = None if ok else (result or {}).get('error', 'send failed')
                return {'ok': ok, 'versions_count': 1, 'digest': digest, 'error': err}
            if online_ready and str(scoped_state.get('online_notified_at') or '').strip():
                if persist_state:
                    scoped_state['last_release_guidance_complete'] = True
                    scoped_state['last_phase'] = phase_now
                    _save_state(state_path, state)
                return {
                    'ok': True,
                    'versions_count': 0,
                    'digest': '',
                    'error': None,
                    'skipped': True,
                    'reason': 'online_already_notified',
                }
            if _should_send_release_notice(scoped_state, phase_now):
                vname = str(release_target.get('name') or str(version_id)).strip()
                detail_url = f"{pm_url.rstrip('/')}/index.html#version={str(version_id).strip()}"
                pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
                pm_mention, pld_mention = resolve_pm_pld_mentions(config, pm_users, release_target)
                digest = _render_release_digest(
                    version_name=vname,
                    detail_url=detail_url,
                    mode='change',
                    pm_mention=pm_mention,
                    pld_mention=pld_mention,
                )
                send_webhook_urls = list(_pvd._resolve_progress_webhooks(release_target))
                if not send_webhook_urls:
                    send_webhook_urls = _collect_version_digest_webhooks(config)
                one_at = list(_pvd._pipeline_at_mobiles(config, pm_users, release_target))
                at_per_url = [one_at for _ in send_webhook_urls]
                if persist_state:
                    scoped_state['released_notified_at'] = today_s
                    scoped_state['last_phase'] = 'released'
                    scoped_state['latest'] = {'date': today_s, 'hash': _sha256_text(digest), 'digest': digest}
                    _save_state(state_path, state)
                if not send_webhook:
                    return {'ok': True, 'versions_count': 1, 'digest': digest, 'error': None}
                if not send_webhook_urls:
                    return {'ok': False, 'versions_count': 1, 'digest': digest, 'error': 'no_webhook'}
                result = _send_digest_body_to_webhooks(digest, send_webhook_urls, at_per_url, quiet=not log_to_stdout)
                ok = bool(result and result.get('success'))
                err = None if ok else (result or {}).get('error', 'send failed')
                return {'ok': ok, 'versions_count': 1, 'digest': digest, 'error': err}
            if _is_released_phase(phase_now) and str(scoped_state.get('released_notified_at') or '').strip():
                if persist_state:
                    scoped_state['last_phase'] = 'released'
                    _save_state(state_path, state)
                return {
                    'ok': True,
                    'versions_count': 0,
                    'digest': '',
                    'error': None,
                    'skipped': True,
                    'reason': 'released_already_notified',
                }

    if not all_versions:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'empty_active_versions'}

    versions = pick_versions(
        all_versions, limit, version_id=version_id, version_name=version_name,
    )
    if (version_id or version_name) and not versions:
        tag = str(version_id or version_name or '').strip()
        return {
            'ok': False,
            'versions_count': 0,
            'digest': '',
            'error': f'version_not_found:{tag}',
        }
    single_mode = bool((version_id or version_name) and len(versions) == 1)
    target_version = versions[0] if single_mode else None
    versions_by_id, users_by_id, pm_data_payload = fetch_pm_data_maps(
        pm_url, api_key=api_key or None,
    )
    versions = merge_versions_with_data(versions, versions_by_id)
    if single_mode and versions:
        target_version = versions[0]
    version_names = [
        str(v.get('name') or '').strip() for v in versions if str(v.get('name') or '').strip()
    ]
    current_body, at_ms, n_built = _pvd.render_multi_version_digest_markdown(
        pm_url,
        api_key or None,
        version_names,
        config,
        log_to_stdout=log_to_stdout,
        data_all=pm_data_payload,
    )
    if n_built == 0:
        return {'ok': False, 'versions_count': 0, 'digest': '', 'error': 'digest_body_failed'}

    current_hash = _sha256_text(current_body)
    if single_mode and target_version is not None:
        scoped_state = _get_scoped_state(state, pm_url, str(target_version.get('id') or ''))
    morning = scoped_state.get('morning') if scoped_state else None
    if not isinstance(morning, dict):
        morning = state.get('morning') or {}
    latest = scoped_state.get('latest') if scoped_state else None
    if not isinstance(latest, dict):
        latest = state.get('latest') or {}
    baseline_text = ''
    baseline_metrics: Dict[str, dict] = {}
    if str(morning.get('date') or '') == today_s:
        baseline_text = str(morning.get('digest') or '')
        if isinstance(morning.get('metrics'), dict):
            baseline_metrics = dict(morning.get('metrics') or {})
    if not baseline_text:
        baseline_text = str(latest.get('digest') or '')
    scoped_latest_metrics = scoped_state.get('latest_metrics') if scoped_state else None
    if not baseline_metrics and isinstance(scoped_latest_metrics, dict):
        baseline_metrics = dict(scoped_latest_metrics or {})
    if not baseline_metrics and isinstance(state.get('latest_metrics'), dict):
        baseline_metrics = dict(state.get('latest_metrics') or {})
    has_baseline = bool(baseline_text.strip())
    changed = True
    if has_baseline:
        changed = _sha256_text(baseline_text) != current_hash

    last_changed_s = ''
    if scoped_state:
        last_changed_s = str(scoped_state.get('last_changed_date') or '').strip()
    if not last_changed_s:
        last_changed_s = str(state.get('last_changed_date') or '').strip() or today_s
    if changed:
        last_changed_s = today_s
    stale_days: Optional[int] = None
    holidays: List[str] = []
    workdays: List[str] = []
    calendar_err: Optional[str] = None
    if not changed:
        holidays, workdays, calendar_err = _fetch_workday_calendar(pm_url, api_key or None)
        try:
            start_d = datetime.strptime(last_changed_s[:10], '%Y-%m-%d').date()
            end_d = date.today()
            if calendar_err:
                stale_days = None
            else:
                stale_days = _count_workdays_between(
                    start_d,
                    end_d,
                    set(holidays),
                    set(workdays),
                )
        except Exception:
            stale_days = None
    else:
        stale_days = 0

    current_metrics = _build_metrics_map(
        versions,
        users_by_id=users_by_id,
        default_pm_user_id=str(config.get('default_pipeline_pm_user_id') or '').strip(),
    )
    change_facts = _build_change_facts(
        baseline_map=baseline_metrics,
        current_map=current_metrics,
        stale_days=stale_days,
        stale_threshold=stale_threshold,
        config=config,
    )
    has_stale_content = bool(calendar_err) or bool(change_facts.get('stale_alert')) or (
        stale_days is not None and stale_days >= stale_threshold
    )
    use_quiet_day = (
        has_baseline
        and not change_facts.get('progress')
        and not change_facts.get('no_change')
        and not change_facts.get('followup_stale')
        and not has_stale_content
    )
    pm_users = fetch_pm_users(pm_url, api_key=api_key or None)
    digest_kind = 'normal'
    if use_quiet_day:
        already_quiet = False
        if scoped_state:
            already_quiet = str(scoped_state.get('quiet_evening_sent_date') or '').strip() == today_s
        else:
            already_quiet = str(state.get('quiet_evening_sent_date') or '').strip() == today_s
        if already_quiet:
            if log_to_stdout:
                print(
                    '[version-change] skip send: quiet day PM reminder already sent today',
                    flush=True,
                )
            return {
                'ok': True,
                'versions_count': n_built,
                'digest': '',
                'error': None,
                'skipped': True,
                'reason': 'quiet_day_already_sent',
            }
        digest_kind = 'quiet'
        if log_to_stdout:
            print('[version-change] no delta vs baseline: sending PM follow-up (quiet day)', flush=True)
        if single_mode and target_version is not None:
            vn_title = str(target_version.get('name') or '').strip() or str(
                target_version.get('id') or ''
            ).strip() or '多版本'
        elif version_names:
            vn_title = '、'.join(version_names[:5])
        else:
            vn_title = '多版本'
        pm_m, _ = resolve_pm_pld_mentions(config, pm_users, target_version or {})
        digest = _render_change_digest_quiet_day(
            version_name=vn_title,
            pm_mention=pm_m,
            timestamp=_now_mmdd_hhmm(),
        )
    else:
        digest = _render_change_digest(
            baseline_text=baseline_text,
            current_text=current_body,
            has_baseline=has_baseline,
            changed=changed,
            stale_days=stale_days,
            stale_threshold=stale_threshold,
            calendar_err=calendar_err,
            change_facts=change_facts,
            version_name=str(target_version.get('name') or '').strip() if target_version else '',
        )
    detail_url = f'{pm_url.rstrip("/")}/index.html'
    if target_version and str(target_version.get('id') or '').strip():
        detail_url = f'{detail_url}#version={str(target_version.get("id") or "").strip()}'
    # 晚间推送不追加“查看版本详情”固定引导，避免冗余。
    digest = digest.rstrip()
    send_webhook_urls = list(webhook_urls)
    at_per_url: List[Optional[List[str]]] = []
    if single_mode and target_version is not None:
        send_webhook_urls = list(_pvd._resolve_progress_webhooks(target_version))
        at_per_url = [[] for _ in send_webhook_urls]
    else:
        at_per_url = [[] for _ in send_webhook_urls]

    if persist_state:
        try:
            state['schema_version'] = 1
            state['latest'] = {'date': today_s, 'hash': current_hash, 'digest': current_body}
            state['latest_metrics'] = current_metrics
            state['last_changed_date'] = last_changed_s
            if scoped_state:
                scoped_state['latest'] = {'date': today_s, 'hash': current_hash, 'digest': current_body}
                scoped_state['latest_metrics'] = current_metrics
                scoped_state['last_changed_date'] = last_changed_s
                if target_version is not None:
                    scoped_state['last_phase'] = str(target_version.get('phase') or '').strip()
                    scoped_state['last_release_guidance_complete'] = _is_release_guidance_complete(
                        target_version.get('nodeManualChecks') or {}
                    )
                if digest_kind == 'quiet':
                    scoped_state['quiet_evening_sent_date'] = today_s
                else:
                    scoped_state.pop('quiet_evening_sent_date', None)
            else:
                if digest_kind == 'quiet':
                    state['quiet_evening_sent_date'] = today_s
                else:
                    state.pop('quiet_evening_sent_date', None)
            _save_state(state_path, state)
        except Exception as e:
            if log_to_stdout:
                print(f'[warn] save change state failed: {e}', flush=True)

    if log_to_stdout:
        try:
            print(f'\n{digest}\n', flush=True)
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = (digest + '\n').encode(enc, errors='replace').decode(enc, errors='replace')
            print(f'\n{safe}\n', flush=True)

    if not send_webhook:
        return {'ok': True, 'versions_count': n_built, 'digest': digest, 'error': None}
    if not send_webhook_urls:
        return {'ok': False, 'versions_count': n_built, 'digest': digest, 'error': 'no_webhook'}

    quiet = not log_to_stdout
    result = _send_digest_body_to_webhooks(
        digest, send_webhook_urls, at_per_url, quiet=quiet,
    )
    ok = bool(result and result.get('success'))
    err = None if ok else (result or {}).get('error', 'send failed')
    return {'ok': ok, 'versions_count': n_built, 'digest': digest, 'error': err}


def main():
    parser = argparse.ArgumentParser(description='Version status digest')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print digest without sending')
    parser.add_argument('--output', default=None,
                        help='Save digest to file')
    parser.add_argument(
        '--mode',
        choices=['snapshot', 'change', 'pmo-evening', 'pm-evening'],
        default='snapshot',
        help='snapshot=早间现状，change=傍晚今日变化，pmo-evening=制作人 PMO晚报，pm-evening=PM 晚报（PMO 群 @ PM）',
    )
    parser.add_argument(
        '--version-id',
        default='',
        help='仅推送指定版本ID（如 v1769078382322）；与 --version-name 二选一',
    )
    parser.add_argument(
        '--version-name',
        default='',
        help='按版本名称全等匹配单版本（如 五一版）；与 --version-id 二选一',
    )
    parser.add_argument(
        '--audience',
        default='',
        choices=['', 'full', 'producer', 'pm', 'pld', 'group'],
        help='仅与 --dry-run 联用：只渲染该受众正文（不发、不写 state）',
    )
    parser.add_argument(
        '--assistant-batch',
        action='store_true',
        help='助理通知群连发：活跃前3中取第1、2版各一条 + may_day 两条（digest_config.version_digest_assistant_batch）',
    )
    parser.add_argument(
        '--audience-sweep',
        action='store_true',
        help='助理群连发4条：与早间同一套版本筛选；可用 --version-name 将某版置顶进活跃列表',
    )
    parser.add_argument(
        '--ignore-workday',
        action='store_true',
        help='早间快照忽略 PM 假日/调休日历仍发送（补发）；等价环境变量 VERSION_DIGEST_IGNORE_WORKDAY=1',
    )
    args = parser.parse_args()
    version_id = str(args.version_id or '').strip() or None
    version_name = str(args.version_name or '').strip() or None
    if version_id and version_name:
        print(
            '[version-digest] 同时指定 --version-id 与 --version-name，已使用 --version-id',
            flush=True,
        )
        version_name = None
    ao = str(args.audience or '').strip() or None
    if ao and not args.dry_run:
        print('[version-digest] --audience 仅在与 --dry-run 同用时生效，已忽略', flush=True)
        ao = None

    if args.audience_sweep and args.assistant_batch:
        print('[version-digest] 请勿同时使用 --audience-sweep 与 --assistant-batch', flush=True)
        raise SystemExit(2)

    if args.audience_sweep:
        r = run_version_digest_audience_sweep(
            send_webhook=not args.dry_run,
            log_to_stdout=True,
            version_name=version_name,
        )
        if r.get('error'):
            raise SystemExit(2)
        if not args.dry_run and not r.get('ok', False):
            raise SystemExit(1)
        return

    if args.assistant_batch:
        if version_id or version_name:
            print(
                '[version-digest] --assistant-batch 与单版本参数互斥，已忽略 --version-id / --version-name',
                flush=True,
            )
        r = run_version_digest_assistant_batch(
            send_webhook=not args.dry_run,
            log_to_stdout=True,
        )
        ds = r.get('digests') or []
        if args.output and ds:
            joined = '\n\n---\n\n'.join(ds)
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(joined)
            print(f'[version-digest] saved {len(ds)} block(s) to {args.output}', flush=True)
        digest = r.get('digest') or ''
        if r.get('error'):
            raise SystemExit(2)
        if not args.dry_run and not r.get('ok', False):
            raise SystemExit(1)
        return

    if args.mode == 'pmo-evening':
        r = run_pmo_evening_send(
            send_webhook=not args.dry_run,
            log_to_stdout=True,
            persist_state=not args.dry_run,
        )
    elif args.mode == 'pm-evening':
        r = run_pm_evening_send(
            send_webhook=not args.dry_run,
            log_to_stdout=True,
            persist_state=not args.dry_run,
        )
    elif args.mode == 'change':
        r = run_version_change_send(
            send_webhook=not args.dry_run,
            log_to_stdout=True,
            persist_state=not args.dry_run,
            version_id=version_id,
            version_name=version_name,
        )
    else:
        r = run_version_digest_send(
            send_webhook=not args.dry_run,
            log_to_stdout=True,
            mark_morning=True,
            persist_state=not args.dry_run,
            version_id=version_id,
            version_name=version_name,
            audience_override=ao if args.dry_run else None,
            ignore_workday=bool(args.ignore_workday),
        )

    digest = r.get('digest') or ''
    if args.output and digest:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(digest)
        print(f'[version-digest] saved to {args.output}', flush=True)

    if r.get('error'):
        raise SystemExit(2)
    if not args.dry_run and not r.get('ok', False):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
