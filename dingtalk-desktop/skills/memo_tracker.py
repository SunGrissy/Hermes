# -*- coding: utf-8 -*-
"""
备忘追踪技能

触发条件：助理通知群内收到包含"备忘"或"完成"的文本消息
流程：
  备忘录入: 解析内容 -> 存DB -> 写入TaskReminder -> 群内回复确认
  备忘关闭: 查找对应备忘 -> 更新DB+TaskReminder -> 群内回复
"""
import os
import re
import sys
import json
import time
import urllib.request
from datetime import datetime, timedelta

# [AgentMemo Task] 开始时间: 2026-03-18 19:00
# [AgentMemo Task] 任务目标: MEMO-001 补齐 ct=3100 富文本处理并接入模板链路
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_THIS_DIR, '..')
_TEMPLATE_PATH = os.path.join(_ROOT, 'message_templates.json')

sys.path.insert(0, _ROOT)
from db.store import (
    save_memo_item, get_next_memo_seq, is_memo_processed,
    close_memo_item, delete_memo_item, get_pending_memos, get_memo_by_seq,
)

def _log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[memo_tracker][{ts}] {msg}', flush=True)


_DEFAULT_TEMPLATES = {
    'confirm': 'memo #{seq}: {summary}',
    'close': 'done: memo #{seq} {summary}',
    'delete': 'memo #{seq} deleted: {summary}',
    'already_deleted': 'memo #{seq} already deleted',
    'not_found': 'not found: memo #{seq}',
    'today_focus_title': '**今日关注**（到期/超期）',
    'today_focus_empty': '今天没有到期或超期的备忘。',
    'today_focus_item': '#{seq} {text}（{due}）',
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


def _render_template(key: str, **kwargs) -> str:
    memo_tpl = _load_memo_templates()
    tpl = memo_tpl.get(key) or _DEFAULT_TEMPLATES.get(key, '')
    try:
        return tpl.format(**kwargs)
    except Exception:
        return tpl


# ── HTTP helpers ────────────────────────────────────────────

def _send_webhook(text, config):
    """通过 Webhook 机器人身份发送 markdown 消息。
    - title 字段放 webhook_keyword（机器人关键词校验，不显示在正文）
    - 正文自动追加 footer（※ 小秘书提醒）
    """
    webhook = config.get('webhook_url', '')
    if not webhook:
        _log('no webhook_url, skip reply')
        return None
    tpl = _load_memo_templates()
    keyword = tpl.get('webhook_keyword', '[小秘书提醒]')
    footer  = tpl.get('footer', '###### ※ 小秘书提醒')
    if footer and footer not in text:
        text = text + '\n\n' + footer
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': keyword, 'text': text},
    }).encode('utf-8')
    req = urllib.request.Request(
        webhook, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        _log(f'webhook failed: {e}')
        return None

def _http_get_json(url, timeout=10):
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _http_post_json(url, data, timeout=10):
    payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── 文本解析 ────────────────────────────────────────────────

_WEEKDAY_MAP = {
    '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6,
}

_RELATIVE_DAYS = {
    '今天': 0, '明天': 1, '后天': 2, '大后天': 3,
}

_TIME_OF_DAY = re.compile(r'(?:上午|下午|晚上|早上|中午|傍晚)')


def _parse_chinese_date(text):
    """
    从中文自然语言中提取日期, 返回 (date_str, matched_span) 或 (None, None)。

    支持: 今天/明天/后天/大后天, 周一~周日, 下周一~下周日, 月底, N天, MM-DD
    """
    today = datetime.now()

    for word, delta in _RELATIVE_DAYS.items():
        m = re.search(re.escape(word), text)
        if m:
            d = (today + timedelta(days=delta)).strftime('%Y-%m-%d')
            return d, m.span()

    m = re.search(r'下周([一二三四五六日天])', text)
    if m:
        target_wd = _WEEKDAY_MAP[m.group(1)]
        days_ahead = 7 - today.weekday() + target_wd
        d = (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        return d, m.span()

    m = re.search(r'(?:这?周|(?:这个?)?星期)([一二三四五六日天])', text)
    if m:
        target_wd = _WEEKDAY_MAP[m.group(1)]
        days_ahead = (target_wd - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        d = (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        return d, m.span()

    m = re.search(r'月底', text)
    if m:
        import calendar
        last_day = calendar.monthrange(today.year, today.month)[1]
        d = datetime(today.year, today.month, last_day).strftime('%Y-%m-%d')
        return d, m.span()

    m = re.search(r'(\d+)\s*天(?:后|内|之内)?', text)
    if m:
        days = int(m.group(1))
        d = (today + timedelta(days=days)).strftime('%Y-%m-%d')
        return d, m.span()

    m = re.search(r'(\d{1,2})[-/](\d{1,2})', text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = datetime(today.year, month, day).strftime('%Y-%m-%d')
            return d, m.span()
        except ValueError:
            pass

    return None, None


def _parse_memo_text(text):
    """
    从备忘/提醒文本中提取结构化字段。
    who 始终为 None (由 config default_who 决定)。

    支持:
      周四下午提醒我找涛哥沟通工作计划  -> content="找涛哥沟通工作计划" due=周四
      备忘 下周一跟进版本封版           -> content="跟进版本封版" due=下周一
      备忘 紧急 活动排期需要对齐        -> content="活动排期需要对齐" priority=high
      备忘                             -> content="" (取上文)

    返回: (content, due_date, priority)
    """
    content = re.sub(
        r'[\uff3b【\[]*(?:备忘|提醒我)[\uff3d】\]]*', '', text.strip()).strip()

    due_date = None
    priority = 'medium'

    date_str, span = _parse_chinese_date(content)
    if date_str:
        due_date = date_str
        content = (content[:span[0]] + content[span[1]:]).strip()

    content = _TIME_OF_DAY.sub('', content).strip()

    if re.search(r'紧急|urgent|p0', content, re.IGNORECASE):
        priority = 'high'
        content = re.sub(r'紧急|urgent|p0', '', content, flags=re.IGNORECASE).strip()
    elif re.search(r'重要|important', content, re.IGNORECASE):
        priority = 'high'
        content = re.sub(r'重要|important', '', content, flags=re.IGNORECASE).strip()

    return content.strip(), due_date, priority


def _build_context(messages, memo_ts, max_count=3, time_window_ms=300_000):
    """
    从 /fetch 消息列表中提取备忘消息前最近的上下文。
    memo_ts: 备忘消息的毫秒时间戳
    time_window_ms: 回看窗口(毫秒), 默认 5 分钟
    """
    candidates = []
    for msg in messages:
        msg_ts = msg.get('ts', 0)
        if not msg_ts or msg_ts >= memo_ts:
            continue
        if (memo_ts - msg_ts) > time_window_ms:
            continue
        text = (msg.get('text') or '').strip()
        if not text:
            continue
        sender = msg.get('sender', '') or str(msg.get('uid', ''))
        candidates.append((msg_ts, f'[{sender}] {text}'))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:max_count]]


# ── TaskReminder 集成 ───────────────────────────────────────

def _create_task_in_reminder(memo_seq, content, due_date, priority,
                             context, config):
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'

    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            tasks = []
    except Exception as e:
        _log(f'read TaskReminder failed: {e}')
        tasks = []

    now_ts = int(time.time() * 1000)
    default_who = config.get('default_who', '助理大白')
    default_module = config.get('default_module', '备忘')
    default_due_days = config.get('default_due_days', 7)

    if not due_date:
        due_date = (datetime.now() + timedelta(days=default_due_days)).strftime('%Y-%m-%d')

    # 一条 TR 只对应一条备忘，不写入上下文
    new_task = {
        'id': now_ts,
        'who': default_who,
        'what': content,
        'note': f'memo:#{memo_seq} source:dingtalk',
        'module': default_module,
        'version': '',
        'due': due_date,
        'priority': priority,
        'freq': 3,
        'created': now_ts,
        'lastChecked': 0,
        'status': 'active',
        'processStatus': 'todo',
    }

    tasks.append(new_task)

    try:
        _http_post_json(url, tasks)
        return now_ts
    except Exception as e:
        _log(f'write TaskReminder failed: {e}')
        return None


def _close_task_in_reminder(memo_seq, config):
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'

    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return False
    except Exception as e:
        _log(f'read TaskReminder failed: {e}')
        return False

    marker = f'memo:#{memo_seq}'
    found = False
    for task in tasks:
        if marker in (task.get('note') or ''):
            task['processStatus'] = 'done'
            found = True
            break

    if not found:
        return False

    try:
        _http_post_json(url, tasks)
        return True
    except Exception as e:
        _log(f'update TaskReminder failed: {e}')
        return False


def _delete_task_in_reminder(memo_seq, config):
    """从 TaskReminder 列表中移除对应备忘任务（真正删掉）。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return False
    except Exception as e:
        _log(f'read TaskReminder failed: {e}')
        return False
    marker = f'memo:#{memo_seq}'
    new_tasks = [t for t in tasks if marker not in (t.get('note') or '')]
    if len(new_tasks) == len(tasks):
        return False
    try:
        _http_post_json(url, new_tasks)
        return True
    except Exception as e:
        _log(f'write TaskReminder failed: {e}')
        return False


# ── 公开接口 ────────────────────────────────────────────────

def process_memo(msg_id, text, context_msgs, memo_ts, group_cid, config):
    """
    处理备忘消息。
    返回: True 成功 / None 需重试(TaskReminder 不可用)
    """
    if is_memo_processed(msg_id):
        return True

    content, due_date, priority = _parse_memo_text(text)

    context = _build_context(context_msgs, memo_ts)

    if not content and context:
        content = context[0].split('] ', 1)[-1] if context else ''
    if not content:
        content = text

    memo_seq = get_next_memo_seq()

    tr_id = _create_task_in_reminder(
        memo_seq, content, due_date, priority, context, config)

    if tr_id is None:
        _log(f'TaskReminder unreachable, memo #{memo_seq} deferred')
        return None

    default_who = config.get('default_who', '助理大白')
    save_memo_item(
        memo_seq=memo_seq,
        msg_id=msg_id,
        text=content,
        who=default_who,
        due=due_date,
        priority=priority,
        context=json.dumps(context, ensure_ascii=False) if context else None,
        task_reminder_id=tr_id,
    )

    summary = content[:30] + ('...' if len(content) > 30 else '')
    confirm_text = _render_template('confirm', seq=memo_seq, summary=summary)
    _send_webhook(confirm_text, config)
    _log(f'memo #{memo_seq} -> TaskReminder: {summary}')
    return True


def process_close(msg_id, text, group_cid, config):
    """
    处理完成/关闭消息。
    返回: True 已处理 / False 未匹配
    """
    m = re.search(r'(?:完成|关闭)\s*#?(\d+)', text)
    if not m:
        return False

    seq = int(m.group(1))
    memo = get_memo_by_seq(seq)
    if not memo:
        _log(f'close: memo #{seq} not found')
        not_found_text = _render_template('not_found', seq=seq, summary='')
        _send_webhook(not_found_text, config)
        return True

    if memo['status'] == 'done':
        _log(f'close: memo #{seq} already done')
        return True

    close_memo_item(seq)
    _close_task_in_reminder(seq, config)

    summary = memo['text'][:30] + ('...' if len(memo['text']) > 30 else '')
    close_text = _render_template('close', seq=seq, summary=summary)
    _send_webhook(close_text, config)
    _log(f'memo #{seq} closed: {summary}')
    return True


def process_delete(msg_id, text, group_cid, config):
    """
    处理「删除 memo N」指令。
    返回: True 已处理 / False 未匹配
    """
    text = (text or '').strip()
    m = re.search(r'删除\s*(?:memo|备忘)\s*#?\s*(\d+)', text, re.IGNORECASE)
    if not m:
        return False
    seq = int(m.group(1))
    memo = get_memo_by_seq(seq)
    if not memo:
        _log(f'delete: memo #{seq} not found')
        not_found_text = _render_template('not_found', seq=seq, summary='')
        _send_webhook(not_found_text, config)
        return True
    if memo['status'] == 'deleted':
        _log(f'delete: memo #{seq} already deleted')
        already_text = _render_template('already_deleted', seq=seq, summary='')
        _send_webhook(already_text, config)
        return True
    delete_memo_item(seq)
    tr_removed = _delete_task_in_reminder(seq, config)
    summary = (memo.get('text') or '')[:30] + ('...' if len(memo.get('text') or '') > 30 else '')
    delete_text = _render_template('delete', seq=seq, summary=summary)
    if tr_removed:
        delete_text += '\n（TR 已同步删除）'
    else:
        delete_text += '\n（TR 中未找到对应任务或已删除）'
    _send_webhook(delete_text, config)
    _log(f'memo #{seq} deleted: {summary}, TR removed={tr_removed}')
    return True


def process_today_focus(config):
    """
    列出今天应关注的任务：到期日 <= 今天（含超期、今日到期）。
    通过 webhook 发送可读列表，返回是否发送成功。
    """
    today = datetime.now().strftime('%Y-%m-%d')
    pending = get_pending_memos()
    items = [m for m in pending if m.get('due') and m['due'] <= today]
    items.sort(key=lambda m: m.get('due') or '', reverse=False)
    tpl = _load_memo_templates()
    title = tpl.get('today_focus_title') or _DEFAULT_TEMPLATES.get('today_focus_title', '**今日关注**')
    lines = [title, '']
    if not items:
        empty = tpl.get('today_focus_empty') or _DEFAULT_TEMPLATES.get('today_focus_empty', '今天没有到期或超期的备忘。')
        lines.append(empty)
    else:
        for m in items:
            seq = m.get('memo_seq', '')
            text = (m.get('text') or '')[:60] + ('...' if len(m.get('text') or '') > 60 else '')
            due = m.get('due') or '-'
            if due < today:
                due = f'{due}（超期）'
            item_tpl = tpl.get('today_focus_item') or _DEFAULT_TEMPLATES.get('today_focus_item', '#{seq} {text}（{due}）')
            try:
                line = item_tpl.format(seq=seq, text=text, due=due)
            except Exception:
                line = f'{seq}. {text}（{due}）'
            lines.append(line)
    body = '\n'.join(lines)
    _send_webhook(body, config)
    _log(f'today_focus: {len(items)} items')
    return True
