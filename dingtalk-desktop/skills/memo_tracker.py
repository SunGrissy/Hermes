# -*- coding: utf-8 -*-
"""
备忘追踪技能

触发条件：助理通知群内收到包含"备忘"/"TR"或"完成"的文本消息
流程：
  备忘录入: 解析内容 -> 存DB -> 写入TaskReminder -> 群内回复确认
  备忘关闭: 查找对应备忘 -> 更新DB+TaskReminder -> 群内回复
"""
import os
import re
import sys
import json
import time
import threading
import functools
import urllib.request
from datetime import datetime, timedelta

# [AgentMemo Task] 开始时间: 2026-03-18 19:00
# [AgentMemo Task] 任务目标: MEMO-001 补齐 ct=3100 富文本处理并接入模板链路
# [AgentWish Task] 开始时间: 2026-03-19
# [AgentWish Task] 任务目标: WISH wish 序号/列表/删除 wish N + TaskReminder 愿望单
# [AgentWish Task] 白名单群备忘/关注等与许愿共用 wish_reply_webhook_by_cid，避免回复发到助理群
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_THIS_DIR, '..')
_TEMPLATE_PATH = os.path.join(_ROOT, 'message_templates.json')

sys.path.insert(0, _ROOT)
from db.store import (
    find_active_memo_duplicate_body,
    find_active_wish_duplicate_body,
    save_memo_item,
    get_next_memo_seq,
    is_memo_processed,
    close_memo_item,
    delete_memo_item,
    update_memo_due,
    get_pending_memos,
    get_memo_by_seq,
    get_next_wish_seq,
    is_wish_processed,
    save_wish_item,
    delete_wish_item,
    close_wish_item,
    get_wish_by_seq,
    get_pending_wishes,
)

# 备忘/愿望写入与删除串行化，避免 Frida 双触发或 push+poll 交错导致同一 memo_seq 双插或双删双推
_MEMO_PIPELINE_LOCK = threading.Lock()


def _memo_serialized(fn):
    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        with _MEMO_PIPELINE_LOCK:
            return fn(*args, **kwargs)
    return _wrapped


def _log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[memo_tracker][{ts}] {msg}', flush=True)


_DEFAULT_TEMPLATES = {
    'confirm': '### 备忘已收录\n\nMemo #{seq}\n{summary}\n\n----',
    'close': 'done: memo #{seq} {summary}',
    'delete': 'memo #{seq} deleted: {summary}',
    'already_deleted': 'memo #{seq} already deleted',
    'not_found': 'not found: memo #{seq}',
    'today_focus_title': '**今日关注** {date}（到期/超期）',
    'today_focus_empty': '今天没有到期或超期的备忘。',
    'today_focus_item': '#{seq} {text}{overdue_suffix}',
    'tomorrow_focus_title': '**明日关注** {date}',
    'tomorrow_focus_empty': '明天没有到期的备忘。',
    'week_focus_title': '**本周关注** {date}～{end_date}',
    'week_focus_empty': '本周没有到期或超期的备忘。',
    'wish_confirm': '### 愿望已收录\n\nWish #{seq}\n{summary}\n\n----',
    'wish_list_title': '### **愿望单**（未完成）',
    'wish_list_empty': '当前没有分配给「{assignee}」的未完成任务。',
    'wish_list_item': '**wish #{seq}** {title}',
    'wish_list_item_legacy': '· {title}',
    'wish_delete': 'wish #{seq} 已删除：{summary}',
    'wish_already_deleted': 'wish #{seq} 已是删除状态',
    'wish_not_found': 'not found: wish #{seq}',
    'wish_close': 'done: wish #{seq} {summary}',
    'wish_close_already': 'wish #{seq} 已是完成状态',
    'wish_close_deleted': 'wish #{seq} 已删除，无法完成',
    'memo_close_deleted': 'memo #{seq} 已删除，无法标记完成',
    'defer_title': '### 到期日已调整',
    'defer_line_ok': '- **#{seq}** → {due}（本地备忘 + TR）',
    'defer_line_db_only': '- **#{seq}** → {due}（仅本地备忘，TR 未找到 memo:#{seq}）',
    'defer_line_tr_only': '- **#{seq}** → {due}（仅 TR，本地无进行中备忘）',
    'defer_line_missing': '- **#{seq}** 未找到（本地与 TR 均无 memo:#{seq}）',
    'defer_need_date': '未能从指令里解析目标日期，请写明「推到明天」「延到下周一」等。',
    'memo_duplicate': (
        '#### 备忘未重复收录\n\n已有进行中的 **Memo #{existing_seq}**（内容相同）\n'
        '{summary}\n\n未新建条目。\n\n----'
    ),
    'wish_duplicate': (
        '#### 愿望未重复收录\n\n已有进行中的 **Wish #{existing_seq}**（内容相同）\n'
        '{summary}\n\n未新建条目。\n\n----'
    ),
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

def _wish_webhook_for_cid(config: dict, group_cid) -> str:
    """备忘/许愿等技能对群回复的 Webhook：优先 wish_reply_webhook_by_cid[cid]，否则 webhook_url（助理群机器人）。"""
    gc = str(group_cid or '').strip()
    raw = config.get('wish_reply_webhook_by_cid')
    if isinstance(raw, dict) and gc:
        u = raw.get(gc)
        if u is None:
            u = raw.get(str(gc))
        if u is not None and str(u).strip():
            return str(u).strip()
    return (config.get('webhook_url') or '').strip()


def _send_wish_webhook(text, config, group_cid=None):
    """许愿/愿望单/删除或完成 wish 的群回复，按发言群 CID 选机器人（多群各用各机器人）。"""
    return _send_webhook(text, config, group_cid=group_cid)


def _send_webhook(text, config, group_cid=None):
    """通过 Webhook 机器人身份发送 markdown 消息。
    - 按 group_cid 选 URL（与 wish_reply_webhook_by_cid 一致）；无映射则用 webhook_url
    - title 字段放 webhook_keyword（钉钉自定义关键词校验，与机器人 A/B 一致：小秘书提醒）
    - 正文自动追加 footer（含「小秘书提醒」）；其前插入分割线（模板 footer_separator 或 separator，默认 ---）
    """
    webhook = _wish_webhook_for_cid(config, group_cid)
    if not webhook:
        _log('no webhook_url, skip reply')
        return None
    tpl = _load_memo_templates()
    keyword = tpl.get('webhook_keyword', '小秘书提醒')
    footer  = tpl.get('footer', '###### ※ 小秘书提醒')
    if footer and footer not in text:
        sep = tpl.get('footer_separator')
        if sep is None:
            sep = tpl.get('separator', '---')
        sep = str(sep).strip()
        if sep:
            text = text + '\n\n' + sep + '\n\n' + footer
        else:
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
        r'[\uff3b【\[]*(?:备忘|提醒我|TR)[\uff3d】\]]*', '', text.strip()).strip()

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


def _get_pending_memos_from_tr(config):
    """从 TR 读取未完成备忘，返回 [{memo_seq, text, due}, ...]，与本地展示字段对齐。TR 不可用返回 None。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return None
    except Exception as e:
        _log(f'read TaskReminder failed (focus): {e}')
        return None
    default_module = (config.get('default_module') or '备忘').strip() or '备忘'
    memos = []
    for t in tasks:
        if (t.get('module') or '').strip() != default_module:
            continue
        if (t.get('processStatus') or '').lower() == 'done':
            continue
        note = t.get('note') or ''
        m = re.search(r'memo:#(\d+)', note)
        seq = m.group(1) if m else '?'
        memos.append({
            'memo_seq': seq,
            'text': (t.get('what') or '').strip(),
            'due': (t.get('due') or '').strip(),
        })
    return memos


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


def _wish_assignee(config: dict) -> str:
    return (config.get('wish_assignee') or '愿望单').strip() or '愿望单'


def _parse_wish_text(text: str) -> str:
    """去掉触发词「许愿」及常见括号标记，剩余作为任务标题。"""
    if not text:
        return ''
    t = text.strip()
    t = re.sub(r'[\uff3b【\[]+许愿[\uff3d】\]]+', ' ', t)
    t = re.sub(r'^\s*许愿\s*', '', t)
    t = re.sub(r'\s+许愿\s+', ' ', t)
    t = ' '.join(t.split())
    return (t or text.strip()).strip()


def wish_content_key(text: str) -> str:
    """路由层短时去重：与 _parse_wish_text 一致归一化后截断。"""
    t = _parse_wish_text(text)
    t = ' '.join(t.split())
    return (t[:120] or '').strip()


def _create_wish_task_in_reminder(content: str, config: dict, wish_seq: int):
    """写入一条分配给愿望单负责人的 TaskReminder 任务；note 含 wish:#N 供删除对齐。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            tasks = []
    except Exception as e:
        _log(f'read TaskReminder failed (wish): {e}')
        tasks = []

    now_ts = int(time.time() * 1000)
    wish_who = _wish_assignee(config)
    default_due_days = int(config.get('wish_default_due_days', config.get('default_due_days', 7)))
    due_date = (datetime.now() + timedelta(days=default_due_days)).strftime('%Y-%m-%d')
    mod = (config.get('wish_module') or '愿望单').strip() or '愿望单'

    new_task = {
        'id': now_ts,
        'who': wish_who,
        'what': content,
        'note': f'wish:#{wish_seq} source:dingtalk',
        'module': mod,
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
        _http_post_json(url, tasks)
        return now_ts
    except Exception as e:
        _log(f'write TaskReminder failed (wish): {e}')
        return None


def _fetch_legacy_wish_titles(config: dict) -> list:
    """TR 中旧版 note=wish:dingtalk、无 wish:# 序号的任务标题（兼容升级前数据）。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return []
    except Exception as e:
        _log(f'read TaskReminder failed (wish legacy list): {e}')
        return []

    wish_who = _wish_assignee(config)
    titles = []
    for task in tasks:
        who = (task.get('who') or '').strip()
        if who != wish_who:
            continue
        if (task.get('processStatus') or '').lower() == 'done':
            continue
        note = (task.get('note') or '')
        if re.search(r'wish:#\d+', note):
            continue
        if 'wish:dingtalk' not in note and 'wish:' not in note:
            continue
        w = (task.get('what') or '').strip()
        if w:
            titles.append(w)
    return titles


def _delete_task_in_reminder_wish(wish_seq: int, config: dict) -> bool:
    """从 TaskReminder 移除 note 含 wish:#N 的任务。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return False
    except Exception as e:
        _log(f'read TaskReminder failed (wish delete): {e}')
        return False
    marker = f'wish:#{wish_seq}'
    new_tasks = [t for t in tasks if marker not in (t.get('note') or '')]
    if len(new_tasks) == len(tasks):
        return False
    try:
        _http_post_json(url, new_tasks)
        return True
    except Exception as e:
        _log(f'write TaskReminder failed (wish delete): {e}')
        return False


def _close_task_in_reminder_wish(wish_seq: int, config: dict) -> bool:
    """将 TaskReminder 中 note 含 wish:#N 的任务标为 processStatus=done（与备忘完成一致）。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return False
    except Exception as e:
        _log(f'read TaskReminder failed (wish close): {e}')
        return False
    marker = f'wish:#{wish_seq}'
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
        _log(f'update TaskReminder failed (wish close): {e}')
        return False


@_memo_serialized
def process_wish(msg_id, text, group_cid, config):
    """
    群消息含「许愿」时：分配 wish_seq，写本地库 + TaskReminder（负责人 wish_assignee）。
    返回 True 成功 / None 表示 TaskReminder 不可用需重试。
    """
    if is_wish_processed(msg_id):
        return True

    content = _parse_wish_text(text)
    if not content:
        content = (text or '').strip()

    dup_w = find_active_wish_duplicate_body(content)
    if dup_w:
        es = dup_w.get('wish_seq', '')
        sm = ((dup_w.get('text') or '')[:80] + (
            '...' if len(dup_w.get('text') or '') > 80 else ''))
        body = _render_template('wish_duplicate', existing_seq=es, summary=sm)
        _send_wish_webhook(body, config, group_cid)
        _log(f'wish duplicate body, skip new (existing #{es}): {sm!r}')
        return True

    wish_seq = get_next_wish_seq()
    tr_id = _create_wish_task_in_reminder(content, config, wish_seq)
    if tr_id is None:
        _log(f'TaskReminder unreachable, wish #{wish_seq} deferred msg={msg_id}')
        return None

    save_wish_item(
        wish_seq=wish_seq,
        msg_id=msg_id,
        text=content,
        task_reminder_id=tr_id,
    )

    summary = content[:80] + ('...' if len(content) > 80 else '')
    confirm_text = _render_template('wish_confirm', seq=wish_seq, summary=summary)
    _send_wish_webhook(confirm_text, config, group_cid)
    _log(f'wish #{wish_seq} -> TaskReminder id={tr_id}: {summary}')
    return True


@_memo_serialized
def process_wish_list(config, group_cid=None):
    """
    群消息含「愿望单」时：打印并推送未完成愿望（含 wish #N）；兼容旧版 TR-only 条目。
    group_cid：用于选择该群对应的许愿回复机器人 Webhook。
    """
    assignee = _wish_assignee(config)
    pending = get_pending_wishes()
    # TR 里仅含 wish:dingtalk、无 wish:# 序号的旧数据，避免升级后漏列
    legacy_titles = _fetch_legacy_wish_titles(config)

    total_lines = len(pending) + len(legacy_titles)
    _log(f'愿望单 [{assignee}] 共 {total_lines} 条（编号 {len(pending)} + 旧版 {len(legacy_titles)}），标题如下：')
    for w in pending:
        _log(f'  wish #{w.get("wish_seq")} {w.get("text", "")}')
    for t in legacy_titles:
        _log(f'  （旧）{t}')

    tpl = _load_memo_templates()
    title_tpl = tpl.get('wish_list_title') or _DEFAULT_TEMPLATES.get('wish_list_title', '')
    try:
        title = title_tpl.format(assignee=assignee)
    except Exception:
        title = title_tpl

    lines_out = []
    item_tpl = tpl.get('wish_list_item') or _DEFAULT_TEMPLATES.get('wish_list_item', '')
    legacy_tpl = tpl.get('wish_list_item_legacy') or _DEFAULT_TEMPLATES.get('wish_list_item_legacy', '· {title}')
    for w in pending:
        seq = w.get('wish_seq', '')
        tit = (w.get('text') or '')[:200]
        try:
            lines_out.append(item_tpl.format(seq=seq, title=tit))
        except Exception:
            lines_out.append(f'**wish #{seq}** {tit}')
    for t in legacy_titles:
        try:
            lines_out.append(legacy_tpl.format(title=t))
        except Exception:
            lines_out.append(f'· {t}')

    if not lines_out:
        empty_tpl = tpl.get('wish_list_empty') or _DEFAULT_TEMPLATES.get('wish_list_empty', '')
        try:
            body = title + '\n\n' + empty_tpl.format(assignee=assignee)
        except Exception:
            body = title + '\n\n' + (empty_tpl or '（空）')
    else:
        body = title + '\n\n' + '\n\n'.join(lines_out)
    _send_wish_webhook(body, config, group_cid)
    return True


@_memo_serialized
def process_delete_wish(msg_id, text, group_cid, config):
    """
    处理「删除 wish N」「删除愿望 N」（忽略大小写，wish 与数字间可有空格或 #）。
    """
    m = re.search(r'删除\s*(?:wish|愿望)\s*#?\s*(\d+)', (text or ''), re.IGNORECASE)
    if not m:
        return False

    seq = int(m.group(1))
    row = get_wish_by_seq(seq)
    if not row:
        _log(f'delete wish: #{seq} not found')
        nf = _render_template('wish_not_found', seq=seq, summary='')
        _send_wish_webhook(nf, config, group_cid)
        return True

    delete_wish_item(seq)
    tr_removed = _delete_task_in_reminder_wish(seq, config)
    summary = ((row.get('text') or '')[:30] + ('...' if len(row.get('text') or '') > 30 else ''))
    delete_text = _render_template('wish_delete', seq=seq, summary=summary)
    if tr_removed:
        delete_text += '\n（TR 已同步删除）'
    else:
        delete_text += '\n（TR 中未找到对应任务或已删除）'
    _send_wish_webhook(delete_text, config, group_cid)
    _log(f'wish #{seq} deleted: {summary}, TR removed={tr_removed}')
    return True


@_memo_serialized
def process_close_wish(msg_id, text, group_cid, config):
    """
    处理「完成 wish N」「关闭愿望 N」（忽略大小写）。
    """
    m = re.search(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*(\d+)', (text or ''), re.IGNORECASE)
    if not m:
        return False

    seq = int(m.group(1))
    row = get_wish_by_seq(seq)
    if not row:
        _log(f'close wish: #{seq} not found')
        nf = _render_template('wish_not_found', seq=seq, summary='')
        _send_wish_webhook(nf, config, group_cid)
        return True

    if row.get('status') == 'deleted':
        _log(f'close wish: #{seq} deleted')
        delete_wish_item(seq)
        txt = _render_template('wish_close_deleted', seq=seq, summary='')
        _send_wish_webhook(txt, config, group_cid)
        return True

    if row.get('status') == 'done':
        _log(f'close wish: #{seq} already done')
        txt = _render_template('wish_close_already', seq=seq, summary='')
        _send_wish_webhook(txt, config, group_cid)
        return True

    close_wish_item(seq)
    _close_task_in_reminder_wish(seq, config)

    summary = ((row.get('text') or '')[:30] + ('...' if len(row.get('text') or '') > 30 else ''))
    close_text = _render_template('wish_close', seq=seq, summary=summary)
    _send_wish_webhook(close_text, config, group_cid)
    _log(f'wish #{seq} closed: {summary}')
    return True


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


# ── 备忘延期（推到明天 / 1、9、10 延到下周一）──────────────────

_DEFER_KEYWORDS = (
    '推迟到', '顺延到', '延期到', '推到', '延到', '改到', '挪到', '调到', '延期', '推迟',
)


def _split_defer_memo_text(text: str):
    """从「数字列表 + 延期词 + 日期」中切出 (head, tail)；无法解析返回 None。"""
    t = (text or '').strip()
    if not t:
        return None
    n = len(t)
    best = None  # (index, keyword)
    kws = sorted(set(_DEFER_KEYWORDS), key=len, reverse=True)
    for i in range(n):
        for kw in kws:
            if t.startswith(kw, i):
                if best is None or i < best[0]:
                    best = (i, kw)
                break
    if not best or best[0] == 0:
        return None
    i, kw = best
    head = t[:i].strip()
    tail = t[i + len(kw) :].strip()
    if not head or not tail:
        return None
    return head, tail


def parse_defer_memo_command(text: str):
    """
    解析「1、9、10推到明天」类指令。
    返回 (memo_seq 列表, 目标日期 YYYY-MM-DD)；不是延期指令返回 None。
    """
    sp = _split_defer_memo_text(text)
    if not sp:
        return None
    head, tail = sp
    seqs = [int(x) for x in re.findall(r'\d+', head)]
    if not seqs:
        return None
    due_date, _ = _parse_chinese_date(tail)
    if not due_date:
        due_date, _ = _parse_chinese_date(text)
    return (seqs, due_date)


def _update_tasks_due_for_memo(memo_seq: int, due_date: str, config: dict) -> int:
    """TaskReminder 中所有 note 含 memo:#N 的任务改为 due_date；返回改动条数。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return 0
    except Exception as e:
        _log(f'read TaskReminder failed (defer): {e}')
        return 0
    marker = f'memo:#{memo_seq}'
    changed = 0
    for task in tasks:
        if marker in (task.get('note') or ''):
            task['due'] = due_date
            changed += 1
    if not changed:
        return 0
    try:
        _http_post_json(url, tasks)
        return changed
    except Exception as e:
        _log(f'update TaskReminder due failed (defer): {e}')
        return 0


@_memo_serialized
def process_defer_memo(msg_id, text, group_cid, config):
    """
    处理「#N 推到明天」「1、9、10 延到下周一」等：更新本地 memo_items.due 与 TR 任务 due。
    返回 False 表示非延期指令；True 表示已识别并已回复（含部分失败说明）。
    """
    parsed = parse_defer_memo_command(text)
    if not parsed:
        return False
    seqs, due_date = parsed
    tpl = _load_memo_templates()
    if not due_date:
        hint = tpl.get('defer_need_date') or _DEFAULT_TEMPLATES.get(
            'defer_need_date',
            '未能从指令里解析目标日期，请写明「推到明天」等。',
        )
        _send_webhook(hint, config, group_cid=group_cid)
        _log(f'defer_memo: need date, seqs={seqs}')
        return True
    lines = []
    title = tpl.get('defer_title') or _DEFAULT_TEMPLATES.get('defer_title', '### 到期日已调整')
    line_ok = tpl.get('defer_line_ok') or _DEFAULT_TEMPLATES.get('defer_line_ok', '')
    line_db = tpl.get('defer_line_db_only') or _DEFAULT_TEMPLATES.get('defer_line_db_only', '')
    line_tr = tpl.get('defer_line_tr_only') or _DEFAULT_TEMPLATES.get('defer_line_tr_only', '')
    line_miss = tpl.get('defer_line_missing') or _DEFAULT_TEMPLATES.get('defer_line_missing', '')

    for seq in seqs:
        memo = get_memo_by_seq(seq)
        db_ok = False
        if memo and memo.get('status') == 'active':
            db_ok = update_memo_due(seq, due_date) > 0
        tr_n = _update_tasks_due_for_memo(seq, due_date, config)
        if db_ok and tr_n > 0:
            try:
                lines.append(line_ok.format(seq=seq, due=due_date))
            except Exception:
                lines.append(f'- **#{seq}** → {due_date}（本地备忘 + TR）')
        elif db_ok:
            try:
                lines.append(line_db.format(seq=seq, due=due_date))
            except Exception:
                lines.append(f'- **#{seq}** → {due_date}（仅本地备忘）')
        elif tr_n > 0:
            try:
                lines.append(line_tr.format(seq=seq, due=due_date))
            except Exception:
                lines.append(f'- **#{seq}** → {due_date}（仅 TR）')
        else:
            try:
                lines.append(line_miss.format(seq=seq, due=due_date))
            except Exception:
                lines.append(f'- **#{seq}** 未找到')

    body = title + '\n\n' + '\n'.join(lines)
    _send_webhook(body, config, group_cid=group_cid)
    _log(f'defer_memo: seqs={seqs} -> {due_date}')
    return True


# ── 公开接口 ────────────────────────────────────────────────

@_memo_serialized
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

    dup_m = find_active_memo_duplicate_body(content)
    if dup_m:
        es = dup_m.get('memo_seq', '')
        sm = ((dup_m.get('text') or '')[:80] + (
            '...' if len(dup_m.get('text') or '') > 80 else ''))
        body = _render_template('memo_duplicate', existing_seq=es, summary=sm)
        _send_webhook(body, config, group_cid=group_cid)
        _log(f'memo duplicate body, skip new (existing #{es}): {sm!r}')
        return True

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
    _send_webhook(confirm_text, config, group_cid=group_cid)
    _log(f'memo #{memo_seq} -> TaskReminder: {summary}')
    return True


@_memo_serialized
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
        _send_webhook(not_found_text, config, group_cid=group_cid)
        return True

    if memo.get('status') == 'deleted':
        delete_memo_item(seq)
        _log(f'close: memo #{seq} was deleted (cleaned row)')
        txt = _render_template('memo_close_deleted', seq=seq, summary='')
        _send_webhook(txt, config, group_cid=group_cid)
        return True

    if memo['status'] == 'done':
        _log(f'close: memo #{seq} already done')
        return True

    close_memo_item(seq)
    _close_task_in_reminder(seq, config)

    summary = memo['text'][:30] + ('...' if len(memo['text']) > 30 else '')
    close_text = _render_template('close', seq=seq, summary=summary)
    _send_webhook(close_text, config, group_cid=group_cid)
    _log(f'memo #{seq} closed: {summary}')
    return True


@_memo_serialized
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
        _send_webhook(not_found_text, config, group_cid=group_cid)
        return True
    delete_memo_item(seq)
    tr_removed = _delete_task_in_reminder(seq, config)
    summary = (memo.get('text') or '')[:30] + ('...' if len(memo.get('text') or '') > 30 else '')
    delete_text = _render_template('delete', seq=seq, summary=summary)
    if tr_removed:
        delete_text += '\n（TR 已同步删除）'
    else:
        delete_text += '\n（TR 中未找到对应任务或已删除）'
    _send_webhook(delete_text, config, group_cid=group_cid)
    _log(f'memo #{seq} deleted: {summary}, TR removed={tr_removed}')
    return True


def process_today_focus(config, group_cid=None):
    """
    列出今天应关注的任务：到期日 <= 今天（含超期、今日到期）。
    数据优先从 TR 读取，与定时摘要一致；TR 不可用时回退到本地 SQLite。
    """
    today = datetime.now().strftime('%Y-%m-%d')
    pending = _get_pending_memos_from_tr(config)
    if pending is None:
        pending = get_pending_memos()
    items = [m for m in pending if m.get('due') and m['due'] <= today]
    items.sort(key=lambda m: m.get('due') or '', reverse=False)
    tpl = _load_memo_templates()
    title_tpl = tpl.get('today_focus_title') or _DEFAULT_TEMPLATES.get('today_focus_title', '**今日关注**')
    try:
        title = title_tpl.format(date=today)
    except Exception:
        title = title_tpl
    if not items:
        empty = tpl.get('today_focus_empty') or _DEFAULT_TEMPLATES.get('today_focus_empty', '今天没有到期或超期的备忘。')
        body = title + '\n\n' + empty
    else:
        parts = [title]
        for m in items:
            seq = m.get('memo_seq', '')
            text = (m.get('text') or '')[:60] + ('...' if len(m.get('text') or '') > 60 else '')
            overdue_suffix = '（超期）' if (m.get('due') or '') < today else ''
            item_tpl = tpl.get('today_focus_item') or _DEFAULT_TEMPLATES.get('today_focus_item', '#{seq} {text}')
            try:
                line = item_tpl.format(seq=seq, text=text, overdue_suffix=overdue_suffix)
            except Exception:
                line = f'{seq}. {text}{overdue_suffix}'
            parts.append(line)
        body = '\n\n'.join(parts)
    _send_webhook(body, config, group_cid=group_cid)
    _log(f'today_focus: {len(items)} items')
    return True


def process_tomorrow_focus(config, group_cid=None):
    """
    列出明天到期的任务：到期日 = 明天。
    数据优先从 TR 读取；TR 不可用时回退到本地 SQLite。
    """
    today = datetime.now().date()
    tomorrow_d = today + timedelta(days=1)
    tomorrow = tomorrow_d.strftime('%Y-%m-%d')
    pending = _get_pending_memos_from_tr(config)
    if pending is None:
        pending = get_pending_memos()
    items = [m for m in pending if m.get('due') == tomorrow]
    items.sort(key=lambda m: m.get('due') or '')
    tpl = _load_memo_templates()
    title_tpl = tpl.get('tomorrow_focus_title') or _DEFAULT_TEMPLATES.get('tomorrow_focus_title', '**明日关注** {date}')
    try:
        title = title_tpl.format(date=tomorrow)
    except Exception:
        title = title_tpl
    if not items:
        empty = tpl.get('tomorrow_focus_empty') or _DEFAULT_TEMPLATES.get('tomorrow_focus_empty', '明天没有到期的备忘。')
        body = title + '\n\n' + empty
    else:
        parts = [title]
        for m in items:
            seq = m.get('memo_seq', '')
            text = (m.get('text') or '')[:60] + ('...' if len(m.get('text') or '') > 60 else '')
            item_tpl = tpl.get('today_focus_item') or tpl.get('tomorrow_focus_item') or _DEFAULT_TEMPLATES.get('today_focus_item', '#{seq} {text}{overdue_suffix}')
            try:
                line = item_tpl.format(seq=seq, text=text, overdue_suffix='')
            except Exception:
                line = f'{seq}. {text}'
            parts.append(line)
        body = '\n\n'.join(parts)
    _send_webhook(body, config, group_cid=group_cid)
    _log(f'tomorrow_focus: {len(items)} items')
    return True


def process_week_focus(config, group_cid=None):
    """
    列出本周应关注的任务：到期日在 [今天, 本周日] 之间（含今天、含超期）。
    数据优先从 TR 读取；TR 不可用时回退到本地 SQLite。
    """
    today_d = datetime.now().date()
    today = today_d.strftime('%Y-%m-%d')
    end_week_d = today_d + timedelta(days=(6 - today_d.weekday()))
    end_week = end_week_d.strftime('%Y-%m-%d')
    pending = _get_pending_memos_from_tr(config)
    if pending is None:
        pending = get_pending_memos()
    items = [m for m in pending if m.get('due') and today <= m['due'] <= end_week]
    items.sort(key=lambda m: m.get('due') or '')
    tpl = _load_memo_templates()
    title_tpl = tpl.get('week_focus_title') or _DEFAULT_TEMPLATES.get('week_focus_title', '**本周关注** {date}～{end_date}')
    try:
        title = title_tpl.format(date=today, end_date=end_week)
    except Exception:
        title = title_tpl
    if not items:
        empty = tpl.get('week_focus_empty') or _DEFAULT_TEMPLATES.get('week_focus_empty', '本周没有到期或超期的备忘。')
        body = title + '\n\n' + empty
    else:
        parts = [title]
        for m in items:
            seq = m.get('memo_seq', '')
            text = (m.get('text') or '')[:60] + ('...' if len(m.get('text') or '') > 60 else '')
            due = m.get('due') or '-'
            overdue_suffix = '（超期）' if due < today else ''
            item_tpl = tpl.get('today_focus_item') or tpl.get('week_focus_item') or _DEFAULT_TEMPLATES.get('today_focus_item', '#{seq} {text}{overdue_suffix}')
            try:
                line = item_tpl.format(seq=seq, text=text, overdue_suffix=overdue_suffix)
            except Exception:
                line = f'{seq}. {text}（{due}）{overdue_suffix}'
            parts.append(line)
        body = '\n\n'.join(parts)
    _send_webhook(body, config, group_cid=group_cid)
    _log(f'week_focus: {len(items)} items')
    return True
