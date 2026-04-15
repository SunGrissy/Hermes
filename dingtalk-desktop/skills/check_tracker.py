# -*- coding: utf-8 -*-
"""
check_tracker — 引用回复 TR 标注转跟进任务

触发条件：
  1. 消息发送方是本人（is_self=True）
  2. 消息文本格式：[回复 发件人: "被引用内容"] TR[附加说明]
  3. 所在会话 CID 在 check_tracker.allowed_cids 白名单中

处理流程：
  1. 解析引用消息原文 (quoted_text) 与 TR 后的附加说明 (reply_body)
  2. 从两者中提取 DDL（reply_body 优先），无则默认 +7 天
  3. 确定任务标题：reply_body 去掉日期后有内容则用之，否则用 quoted_text
  4. 写入 TaskReminder（note: check:#N source:dingtalk）
  5. 本地 DB 存 check_items
  6. 助理通知群 Webhook 发确认消息
"""
import os
import re
import sys
import json
import time
import threading
import urllib.request
from datetime import datetime, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_THIS_DIR, '..')
sys.path.insert(0, _ROOT)

from db.store import (
    get_next_check_seq,
    is_check_processed,
    save_check_item,
)

_CHECK_PIPELINE_LOCK = threading.Lock()


def _log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[check_tracker][{ts}] {msg}', flush=True)


# ── 日期解析 ─────────────────────────────────────────────────

_WEEKDAY_MAP = {
    '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6,
}
_RELATIVE_DAYS = {
    '今天': 0, '明天': 1, '后天': 2, '大后天': 3,
}


def _parse_date(text: str):
    """从文本中提取第一个中文日期，返回 (date_str, span) 或 (None, None)。"""
    if not text:
        return None, None
    today = datetime.now()

    for word, delta in _RELATIVE_DAYS.items():
        m = re.search(re.escape(word), text)
        if m:
            return (today + timedelta(days=delta)).strftime('%Y-%m-%d'), m.span()

    m = re.search(r'下周([一二三四五六日天])', text)
    if m:
        target_wd = _WEEKDAY_MAP[m.group(1)]
        days_ahead = 7 - today.weekday() + target_wd
        return (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), m.span()

    m = re.search(r'(?:这?周|(?:这个?)?星期)([一二三四五六日天])', text)
    if m:
        target_wd = _WEEKDAY_MAP[m.group(1)]
        curr = today.weekday()
        delta = (target_wd - curr) % 7
        if delta == 0:
            delta = 7
        return (today + timedelta(days=delta)).strftime('%Y-%m-%d'), m.span()

    m = re.search(r'(\d{1,2})月(\d{1,2})(?:号|日)', text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = today.year
        try:
            candidate = datetime(year, month, day)
            if candidate.date() < today.date():
                candidate = datetime(year + 1, month, day)
            return candidate.strftime('%Y-%m-%d'), m.span()
        except ValueError:
            pass

    m = re.search(r'(\d+)\s*天(?:后|以后)', text)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime('%Y-%m-%d'), m.span()

    m = re.search(r'月底', text)
    if m:
        next_month = (today.month % 12) + 1
        year = today.year + (1 if today.month == 12 else 0)
        last_day = datetime(year, next_month, 1) - timedelta(days=1)
        return last_day.strftime('%Y-%m-%d'), m.span()

    return None, None


def _strip_date(text: str, span) -> str:
    """从 text 中删掉 span 对应的日期片段，返回清理后内容。"""
    if not text or not span:
        return text or ''
    start, end = span
    return (text[:start] + text[end:]).strip()


# ── 引用回复解析 ─────────────────────────────────────────────

# 匹配钉钉引用回复格式：[回复 发件人: "被引用内容"] 回复正文
# 兼容中英文引号和全半角冒号
_RE_QUOTED = re.compile(
    r'^\[回复\s+[^:：\]]+[：:]\s*["\u201c\u300c]([^"\u201d\u300d]*)["\u201d\u300d]\]\s*(.*)',
    re.DOTALL,
)
_RE_TR_PREFIX = re.compile(r'^TR\s*', re.IGNORECASE)


def parse_check_trigger(text: str):
    """
    解析引用回复 TR 消息。
    返回 (quoted_text, reply_body) 或 None（不匹配则 None）。
    - quoted_text: 被引用消息的原文
    - reply_body: "TR" 关键词之后的内容（可能为空字符串）
    """
    if not text:
        return None
    m = _RE_QUOTED.match(text)
    if not m:
        return None
    quoted_text = m.group(1).strip()
    after_quote = m.group(2).strip()
    if not _RE_TR_PREFIX.match(after_quote):
        return None
    reply_body = _RE_TR_PREFIX.sub('', after_quote).strip()
    return quoted_text, reply_body


def _extract_title_and_due(quoted_text: str, reply_body: str):
    """
    返回 (title, due_date_str)。

    DDL 提取顺序：reply_body → quoted_text → +7天
    标题确定规则：
      - reply_body 去掉日期后仍有实质内容 → 用 reply_body 的非日期部分
      - 否则 → 用 quoted_text 完整原文
    """
    # Step 1: 从 reply_body 提取日期（reply_body 优先承担 DDL）
    ddl, span = _parse_date(reply_body)
    if ddl:
        # reply_body 含日期：标题取 reply_body 去掉日期后的剩余部分
        title_candidate = _strip_date(reply_body, span).strip()
    else:
        # Step 2: reply_body 无日期 → 从 quoted_text 找日期
        ddl, _ = _parse_date(quoted_text)
        # 此时 reply_body 是有意义的任务说明（不含日期），优先作为标题
        title_candidate = reply_body.strip()

    # Step 3: 兜底 DDL
    if not ddl:
        ddl = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')

    # Step 4: 确定标题：优先 title_candidate，否则用 quoted_text
    title = title_candidate if title_candidate else (quoted_text or reply_body or '').strip()
    if not title:
        title = '(无内容)'

    return title, ddl


# ── TaskReminder 写入 ────────────────────────────────────────

def _create_check_in_reminder(check_seq, title, due_date, source_text, config):
    """写入 TaskReminder，返回 task id（时间戳）或 None（失败）。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'

    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=10) as resp:
            tasks = json.loads(resp.read())
        if not isinstance(tasks, list):
            tasks = []
    except Exception as e:
        _log(f'read TaskReminder failed: {e}')
        return None

    now_ts = int(time.time() * 1000)
    default_who = config.get('default_who', '助理大白')
    new_task = {
        'id': now_ts,
        'who': default_who,
        'what': title,
        'note': f'check:#{check_seq} source:dingtalk',
        'module': '跟进',
        'version': '',
        'due': due_date,
        'priority': 'medium',
        'freq': 3,
        'created': now_ts,
        'lastChecked': 0,
        'status': 'active',
        'processStatus': 'todo',
    }
    tasks.append(new_task)

    try:
        payload = json.dumps(tasks, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            url, data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return now_ts
    except Exception as e:
        _log(f'write TaskReminder failed: {e}')
        return None


# ── Webhook 确认消息 ─────────────────────────────────────────

def _send_confirm_webhook(check_seq, title, due_date, source_name, config):
    """向助理通知群发 check 已创建确认消息。"""
    webhook = (config.get('webhook_url') or '').strip()
    if not webhook:
        _log('no webhook_url, skip confirm')
        return

    tpl_path = os.path.join(_ROOT, 'message_templates.json')
    keyword = '小秘书提醒'
    footer = '###### ※ 小秘书提醒'
    try:
        with open(tpl_path, encoding='utf-8') as f:
            tpl_data = json.load(f)
        memo_tpl = tpl_data.get('memo_tracker', {})
        keyword = memo_tpl.get('webhook_keyword', keyword)
        footer = memo_tpl.get('footer', footer)
    except Exception:
        pass

    text = (
        f'#### check#{check_seq} 已创建\n\n'
        f'**{title}**\n\n'
        f'- DDL：{due_date}\n'
        f'- 来源：{source_name}\n'
        f'- Assignee：助理大白\n\n'
        f'---\n\n{footer}'
    )
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
            resp.read()
    except Exception as e:
        _log(f'confirm webhook failed: {e}')


# ── 主入口 ───────────────────────────────────────────────────

def process_check(msg_id, text, group_cid, config):
    """
    处理 check 引用回复 TR 消息。
    返回 True（已处理/已忽略）或 None（TaskReminder 不可用，可重试）。
    """
    with _CHECK_PIPELINE_LOCK:
        return _process_check_inner(msg_id, text, group_cid, config)


def _process_check_inner(msg_id, text, group_cid, config):
    if is_check_processed(msg_id):
        return True

    parsed = parse_check_trigger(text)
    if parsed is None:
        return True  # 不是 check 格式，忽略

    quoted_text, reply_body = parsed
    title, due_date = _extract_title_and_due(quoted_text, reply_body)
    source_text = f'[被引用] {quoted_text}\n[TR回复] {reply_body or "(空)"}'

    check_seq = get_next_check_seq()
    tr_id = _create_check_in_reminder(check_seq, title, due_date, source_text, config)
    if tr_id is None:
        _log(f'TaskReminder unreachable, check #{check_seq} deferred')
        return None

    # 来源名称：从 check_tracker.cid_names 查群名，兜底用 cid
    cfg_check = config.get('check_tracker', {})
    cid_names = cfg_check.get('cid_names', {})
    source_name = cid_names.get(str(group_cid), str(group_cid))

    save_check_item(
        check_seq=check_seq,
        msg_id=msg_id,
        title=title,
        due=due_date,
        source_text=source_text,
        group_cid=str(group_cid or ''),
        task_reminder_id=tr_id,
    )

    _send_confirm_webhook(check_seq, title, due_date, source_name, config)
    _log(f'check #{check_seq} -> TaskReminder: {title[:50]}')
    return True
