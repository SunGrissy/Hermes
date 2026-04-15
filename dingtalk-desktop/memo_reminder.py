# -*- coding: utf-8 -*-
"""
备忘定时提醒

独立脚本, 由 Windows Task Scheduler 在工作日 08:50、17:30 各调用一次。
从 TaskReminder (KV storage) 读取备忘类任务, 统计待跟进数, 发汇总到助理通知群。
工作日判定与 PmSystem「假日与调休」一致：优先请求 digest_config.json 中 pm_system_url 的 /api/pm-calendar，
失败则尝试读取仓库内 pm-system/backend/data/gamedev_pm_data.json；均不可用时本次不推送。

规则：发给助理通知群（自己看的）时，分配给 default_who（如助理大白）的任务不显示分配人。

拓展备忘（未实现）：
- 若任务分配给「助理大白」以外的人，到期时自动触发 TaskReminder 里的提醒按钮（推给责任人）。
"""
import os
import sys
import json
import urllib.request
from datetime import date, datetime, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _THIS_DIR)
# [AgentMemo Task] memo 提醒：仅 PM 工作日推送；计划任务 08:50 / 17:30
from lib.utils import get_webhook_url
from pm_work_calendar import fetch_pm_calendar_http, is_pm_workday, try_load_pm_calendar

_CONFIG_PATH = os.path.join(_THIS_DIR, 'digest_config.json')
_TEMPLATE_PATH = os.path.join(_THIS_DIR, 'message_templates.json')

def _log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[memo_reminder][{ts}] {msg}', flush=True)


def _load_digest_root() -> dict:
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _load_config():
    cfg = _load_digest_root()
    memo_cfg = cfg.get('memo_tracker', {})
    if not memo_cfg.get('group_cid'):
        memo_cfg['group_cid'] = cfg.get('notify_target', '')
    # webhook 优先从 webhook_config.json 的 memo_tracker 读取
    memo_cfg['webhook_url'] = get_webhook_url(
        'memo_tracker', memo_cfg.get('webhook_url') or cfg.get('webhook_url', '')
    )
    return memo_cfg


def _load_pm_holidays_workdays():
    """
    返回 (holidays, workdays)，与 PM 前端 isWorkday 同源。
    不可用时返回 None（调用方应跳过推送，避免法定假误推）。
    """
    cfg = _load_digest_root()
    base = (cfg.get('pm_system_url') or '').strip()
    timeout = int(cfg.get('pm_calendar_timeout_sec') or 15)
    if base:
        url = base.rstrip('/') + '/api/pm-calendar'
        loaded = fetch_pm_calendar_http(url, timeout_sec=max(3, timeout))
        if loaded:
            h, w, _ = loaded
            return h, w
    tried = try_load_pm_calendar('pm-system/backend/data/gamedev_pm_data.json', _ROOT)
    if tried:
        h, w, _ = tried
        return h, w
    return None


_DEFAULT_TEMPLATES = {
    'task_due_digest_title': '## 任务到期与待关注 [{date}]',
    'reminder_subtitle': '**待跟进 {count} 项**',
    'section_urgent': '### 紧急 / 超期（{count}）',
    'section_due_soon': '### 本周到期（{count}）',
    'section_other': '### 其他（{count}）',
    'item_line': '> **#{seq}** {who} {text}',
    'item_due_tag': '> {due_info}',
    'due_overdue': '已超期 {days} 天',
    'due_today': '今日到期',
    'due_normal': '还剩 {days} 天',
    'separator': '---',
    'footer': '###### ※ 小秘书提醒',
}


def _load_memo_templates():
    try:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        memo_tpl = data.get('memo_tracker', {})
        if isinstance(memo_tpl, dict):
            return memo_tpl
    except Exception as e:
        _log(f'load memo template failed: {e}')
    return {}


def _render_template(key, **kwargs):
    memo_tpl = _load_memo_templates()
    tpl = memo_tpl.get(key) or _DEFAULT_TEMPLATES.get(key, '')
    try:
        return tpl.format(**kwargs)
    except Exception:
        return tpl


def _http_get_json(url, timeout=10):
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _send_webhook(webhook_url, text):
    keyword = _load_memo_templates().get('keyword', '小秘书提醒')
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': f'小秘书提醒 · 任务到期与待关注', 'text': text},
    }).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _get_pending_memos(config):
    """从 TaskReminder 读取未完成的备忘任务"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'

    tasks = _http_get_json(url)
    if not isinstance(tasks, list):
        return []

    default_module = config.get('default_module', '备忘')
    memos = []
    for t in tasks:
        if t.get('module') != default_module:
            continue
        if t.get('processStatus') in ('done',):
            continue
        memos.append(t)
    return memos


def _categorize(memos):
    """按紧急/本周到期/其他 分类，due_info 用中文模板渲染"""
    today = datetime.now().date()
    week_end = today + timedelta(days=7)
    re = __import__('re')

    urgent, due_soon, other = [], [], []

    for m in memos:
        note = m.get('note', '')
        seq_match = re.search(r'memo:#(\d+)', note)
        seq = seq_match.group(1) if seq_match else '?'

        due_str = m.get('due', '')
        who = m.get('who', '')
        what = m.get('what', '')[:40]

        due_info = ''
        overdue = False
        if due_str:
            try:
                due_date = datetime.strptime(due_str, '%Y-%m-%d').date()
                delta = (due_date - today).days
                if delta < 0:
                    due_info = _render_template('due_overdue', days=-delta)
                    overdue = True
                elif delta == 0:
                    due_info = _render_template('due_today')
                    overdue = True
                else:
                    due_info = _render_template('due_normal', days=delta)
            except ValueError:
                due_info = due_str

        item = {'seq': seq, 'who': who, 'what': what, 'due_info': due_info}

        if m.get('priority') == 'high' or overdue:
            urgent.append(item)
        elif due_str and due_info and not overdue:
            try:
                due_date = datetime.strptime(due_str, '%Y-%m-%d').date()
                if due_date <= week_end:
                    due_soon.append(item)
                else:
                    other.append(item)
            except ValueError:
                other.append(item)
        else:
            other.append(item)

    return urgent, due_soon, other


def _build_message(memos, config=None):
    """构造汇总消息：每条任务用 blockquote 卡片式排版。
    发给助理通知群（自己看的）：分配给 default_who（如助理大白）的任务不显示分配人。
    """
    total = len(memos)
    if total == 0:
        return None

    config = config or _load_config()
    hide_who_name = config.get('default_who', '助理大白')  # 该分配人的任务不显示分配人

    urgent, due_soon, other = _categorize(memos)
    today_str = datetime.now().strftime('%m/%d')
    sep = _render_template('separator')

    lines = [
        _render_template('task_due_digest_title', date=today_str),
        '',
        _render_template('reminder_subtitle', count=total),
    ]

    def _add_section(section_key, items):
        if not items:
            return
        lines.append('')
        lines.append(sep)
        lines.append('')
        lines.append(_render_template(section_key, count=len(items)))
        lines.append('')
        for it in items:
            # 分配给 助理大白 的不显示分配人（发给自己的提醒）
            if it['who'] and it['who'] == hide_who_name:
                who = ''
            else:
                who = (f'@{it["who"]}') if it['who'] else ''
            lines.append(_render_template('item_line',
                                          seq=it['seq'], who=who,
                                          text=it['what']))
            if it['due_info']:
                lines.append(_render_template('item_due_tag',
                                              due_info=it['due_info']))
            lines.append('')

    _add_section('section_urgent', urgent)
    _add_section('section_due_soon', due_soon)
    _add_section('section_other', other)

    lines.append(sep)
    lines.append(_render_template('footer'))
    return '\n'.join(lines)


def main():
    _log('starting memo reminder...')

    cal = _load_pm_holidays_workdays()
    if cal is None:
        _log('pm calendar unavailable, skip (no push)')
        return
    h, w = cal
    today = date.today()
    if not is_pm_workday(today, h, w):
        _log(f'today {today.isoformat()} is not a PM workday, skip')
        return

    config = _load_config()
    webhook_url = config.get('webhook_url', '')
    if not webhook_url:
        _log('no webhook_url configured, exit')
        return

    try:
        memos = _get_pending_memos(config)
    except Exception as e:
        _log(f'failed to read TaskReminder: {e}')
        return

    _log(f'found {len(memos)} pending memos')

    msg = _build_message(memos, config)
    if not msg:
        _log('no pending memos, skip')
        return

    try:
        result = _send_webhook(webhook_url, msg)
        _log(f'sent: {result}')
    except Exception as e:
        _log(f'send failed: {e}')


if __name__ == '__main__':
    main()
