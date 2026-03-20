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

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_THIS_DIR, '..')
_TEMPLATE_PATH = os.path.join(_ROOT, 'message_templates.json')

sys.path.insert(0, _ROOT)
from db.store import (
    find_active_memo_duplicate_body,
    find_active_wish_duplicate_body,
    find_active_topic_duplicate_body,
    save_memo_item,
    save_topic_item,
    get_next_memo_seq,
    get_next_topic_seq,
    is_memo_processed,
    is_topic_processed,
    close_memo_item,
    close_topic_item,
    delete_memo_item,
    delete_topic_item,
    upsert_topic_from_tr_sync,
    update_memo_due,
    update_memo_text,
    get_pending_memos,
    get_pending_topics,
    get_memo_by_seq,
    get_topic_by_seq,
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

# 改描述/改版本/指派等同一条群消息常经 send Hook 与 push 各入队一次，全文去重避免 webhook 双发
_EDIT_CMD_DEDUP = {}
_EDIT_CMD_TTL_S = 25.0
_EDIT_CMD_DEDUP_LOCK = threading.Lock()


def _dedup_normalize_text(text: str) -> str:
    """与 skill_router._normalize_command_text 对齐，保证 push/poll/双入队 文本键一致。"""
    if not text:
        return ''
    t = text.replace('\u200b', '').replace('\ufeff', '')
    t = t.replace('許願', '许愿')
    return ' '.join(t.strip().split())


def _consume_edit_cmd_dedup(group_cid, text: str) -> bool:
    """若本群近期已处理过完全相同文本，返回 True：调用方应直接 return True 且不再推送。
    查表与写入在同一把锁内完成，避免多线程同时误判「未重复」导致双发 webhook。
    """
    cid = str(group_cid or '').strip()
    norm = _dedup_normalize_text(text or '')
    if not norm:
        return False
    key = f'{cid}|{norm}'
    now = time.time()
    with _EDIT_CMD_DEDUP_LOCK:
        for k in [x for x, ts in _EDIT_CMD_DEDUP.items() if now - ts > _EDIT_CMD_TTL_S]:
            del _EDIT_CMD_DEDUP[k]
        if key in _EDIT_CMD_DEDUP:
            _log('edit cmd dedup skip (send+push duplicate)')
            return True
        _EDIT_CMD_DEDUP[key] = now
        return False


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
    'memo_edit_desc_ok': '已更新 **memo #{seq}** 描述：{summary}',
    'memo_edit_version_ok': '已更新 **memo #{seq}** TR 版本：{version}',
    'memo_assign_ok': '已将 **memo #{seq}** 在 TR 中指派给 **{who}**',
    'topic_pick_confirm': (
        '#### **选题已收录**（{module}）\n\n----\n\n**选题 #{seq}**（TR note: topic:#{seq}）\n{summary}\n\n----'
    ),
    'topic_duplicate': (
        '#### 选题未重复收录\n\n已有进行中的 **选题 #{existing_seq}**（内容相同）\n'
        '{summary}\n\n未新建条目。\n\n----'
    ),
    'topic_library_title': '### **选题库**（TaskReminder，共 {n} 条）\n\n',
    'topic_library_empty': 'TR 中没有带 `topic:#N` 的任务。\n\n',
    'topic_library_item': (
        '**topic #{seq}** [{status}] {what}\n'
        '> 负责人：{who}　到期：{due}　模块：{module}\n\n'
    ),
    'topic_library_trunc': '\n（仅展示前 {n} 条，其余略；完整列表以 TR 为准）\n',
    'topic_library_read_fail': '无法读取 TaskReminder，选题库暂不可用，请稍后重试。\n\n',
    'person_lookup_title': '### **「{keyword}」相关待办**（备忘 + 愿望）\n\n',
    'person_lookup_empty': '没有在进行中的备忘、愿望正文里找到「{keyword}」。\n\n',
    'person_lookup_memo_head': '**备忘**\n',
    'person_lookup_wish_head': '**愿望**\n',
    'person_lookup_memo_line': '- **memo #{seq}** {text}\n',
    'person_lookup_wish_line': '- **wish #{seq}** {text}\n',
    'person_lookup_trunc': '\n（仅展示前 {n} 条，其余略）\n',
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

# 备忘/愿望触发词紧跟的空白与常见标点（半角/全角）
_STRIP_AFTER_TRIGGER = re.compile(
    r'^[\s\u3000，,。、;；:：!！?？.·…\-—（）()\[\]【】]+')


def strip_leading_trigger_punct(s: str) -> str:
    """剥离字符串开头多余空白与标点（用于「备忘：」「许愿，」等）。"""
    if not s:
        return s
    return _STRIP_AFTER_TRIGGER.sub('', s).strip()


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
    content = strip_leading_trigger_punct(content)

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

def _create_task_in_reminder(seq, content, due_date, priority,
                             context, config, who_override=None,
                             module_override=None, note_kind='memo'):
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
    default_who = (who_override or config.get('default_who', '助理大白') or '').strip()
    default_module = (module_override or config.get('default_module', '备忘') or '').strip()
    default_due_days = config.get('default_due_days', 7)

    if not due_date:
        due_date = (datetime.now() + timedelta(days=default_due_days)).strftime('%Y-%m-%d')

    nk = (note_kind or 'memo').strip().lower()
    if nk not in ('memo', 'topic', 'wish'):
        nk = 'memo'
    # 一条 TR 一条本地记录；note 区分 memo / topic / wish
    new_task = {
        'id': now_ts,
        'who': default_who,
        'what': content,
        'note': f'{nk}:#{seq} source:dingtalk',
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


def _strip_trailing_cmd_noise(s: str) -> str:
    if not s:
        return ''
    t = s.strip()
    return re.sub(r'[。！？!?\s]+$', '', t).strip()


# 支持「备忘 39」「备忘39」「memo 12」「memo12」（不用 \\b：中文「版本」前非 ASCII 词界）
_MEMO_NUM_ONE = r'(?:备忘\s*#?\s*|memo\s*#?\s*|memo)(\d+)(?!\d)'

_RE_MEMO_EDIT_DESC = re.compile(
    r'(?:修改|改|更新)\s*' + _MEMO_NUM_ONE
    + r'\s*(?:描述|正文)\s*(?:为|成|是|[:：])\s*(.+)',
    re.IGNORECASE | re.DOTALL,
)
_RE_MEMO_EDIT_VER = re.compile(
    r'(?:修改|改|更新)\s*' + _MEMO_NUM_ONE
    + r'\s*版本\s*(?:为|成|是|[:：])?\s*(.+)',
    re.IGNORECASE | re.DOTALL,
)
_RE_MEMO_ASSIGN = re.compile(
    r'(?:把\s*)?' + _MEMO_NUM_ONE
    + r'\s*(?:指派给|分给|转给|指派|给)\s*(.+)',
    re.IGNORECASE | re.DOTALL,
)


def _parse_memo_edit_desc_command(text: str):
    """解析「改描述」指令，返回 (seq, body) 或 None。
    支持：改备忘39描述为x / 38描述改成：x / memo38改描述：x / #38描述改为x
    """
    t = (text or '').strip()
    m = _RE_MEMO_EDIT_DESC.search(t)
    if m:
        return int(m.group(1)), m.group(2)
    m = re.match(
        r'^\s*#?\s*(\d+)(?!\d)\s*描述\s*(?:改成|改为|变更为|为|成)\s*[:：]?\s*(.+)',
        t,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return int(m.group(1)), m.group(2)
    m = re.match(
        r'^\s*' + _MEMO_NUM_ONE + r'\s*改描述\s*[:：]?\s*(.+)',
        t,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return int(m.group(1)), m.group(2)
    return None


def _find_tr_task_for_memo(tasks, memo_seq: int):
    if not isinstance(tasks, list):
        return None
    marker = f'memo:#{memo_seq}'
    for t in tasks:
        if marker in (t.get('note') or ''):
            return t
    return None


def _update_memo_task_in_tr(memo_seq: int, config: dict, *,
                            what=None, version=None, who=None) -> bool:
    """更新 TR 中带 memo:#N 的任务字段（存在则写回）。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return False
    except Exception as e:
        _log(f'read TaskReminder failed (memo patch): {e}')
        return False
    marker = f'memo:#{memo_seq}'
    found = False
    for task in tasks:
        if marker not in (task.get('note') or ''):
            continue
        found = True
        if what is not None:
            task['what'] = str(what).strip()
        if version is not None:
            task['version'] = str(version).strip()
        if who is not None:
            task['who'] = str(who).strip()
        break
    if not found:
        return False
    try:
        _http_post_json(url, tasks)
        return True
    except Exception as e:
        _log(f'write TaskReminder failed (memo patch): {e}')
        return False


def fetch_tr_tasks_for_sync(config: dict) -> list | None:
    """拉取 TR 任务列表；失败返回 None（与空列表区分）。"""
    base_url = config.get('task_reminder_base', 'http://192.168.20.114:8111')
    url = base_url.rstrip('/') + '/api/storage/task_reminder'
    try:
        tasks = _http_get_json(url)
        if not isinstance(tasks, list):
            return []
        return tasks
    except Exception as e:
        _log(f'sync TR: read failed {e}')
        return None


def _merge_tr_topic_snapshot(tasks: list) -> dict:
    """note 含 topic:#N 的任务合并为 seq -> {done, what, who, due, tr_id, module, priority}。
    同序号多条时优先保留「进行中」，否则取较新 id。
    """
    by_seq: dict[int, tuple[bool, dict]] = {}
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        note = t.get('note') or ''
        mm = re.search(r'topic:#(\d+)', note)
        if not mm:
            continue
        seq = int(mm.group(1))
        done = (t.get('processStatus') or '').lower() == 'done'
        cur = by_seq.get(seq)
        if cur is None:
            by_seq[seq] = (done, t)
            continue
        cur_done, cur_t = cur
        if cur_done and not done:
            by_seq[seq] = (done, t)
        elif cur_done == done:
            if int(t.get('id') or 0) >= int(cur_t.get('id') or 0):
                by_seq[seq] = (done, t)
    out = {}
    for seq, (done, t) in by_seq.items():
        out[seq] = {
            'done': done,
            'what': (t.get('what') or '').strip(),
            'who': (t.get('who') or '').strip(),
            'due': (t.get('due') or '').strip(),
            'tr_id': t.get('id'),
            'module': (t.get('module') or '').strip(),
            'priority': (t.get('priority') or 'medium').strip() or 'medium',
        }
    return out


def apply_tr_sync_to_local_tasks(tasks: list, config: dict) -> dict:
    """在已拉取的 tasks 上执行 memo/wish/topic 与本地对齐（topic 以 TR 字段为真源）。"""
    out = {
        'memo_deleted': 0, 'memo_closed': 0,
        'wish_deleted': 0, 'wish_closed': 0,
        'topic_deleted': 0, 'topic_closed': 0,
        'topic_merged': 0,
    }

    memo_state = {}
    wish_state = {}
    topic_state = {}
    for t in tasks:
        note = t.get('note') or ''
        st = (t.get('processStatus') or '').lower()
        done = st == 'done'
        mm = re.search(r'memo:#(\d+)', note)
        if mm:
            seq = int(mm.group(1))
            if not done:
                memo_state[seq] = 'active'
            elif memo_state.get(seq) != 'active':
                memo_state[seq] = 'done'
        wm = re.search(r'wish:#(\d+)', note)
        if wm:
            seq = int(wm.group(1))
            if not done:
                wish_state[seq] = 'active'
            elif wish_state.get(seq) != 'active':
                wish_state[seq] = 'done'
        tgm = re.search(r'topic:#(\d+)', note)
        if tgm:
            seq = int(tgm.group(1))
            if not done:
                topic_state[seq] = 'active'
            elif topic_state.get(seq) != 'active':
                topic_state[seq] = 'done'

    for m in list(get_pending_memos()):
        seq = int(m['memo_seq'])
        st = memo_state.get(seq)
        if st is None:
            delete_memo_item(seq)
            out['memo_deleted'] += 1
            _log(f'sync: TR 已无 memo #{seq}，已删本地')
        elif st == 'done':
            close_memo_item(seq)
            out['memo_closed'] += 1
            _log(f'sync: TR 已 done memo #{seq}，本地已闭环')

    for w in list(get_pending_wishes()):
        seq = int(w['wish_seq'])
        st = wish_state.get(seq)
        if st is None:
            delete_wish_item(seq)
            out['wish_deleted'] += 1
            _log(f'sync: TR 已无 wish #{seq}，已删本地')
        elif st == 'done':
            close_wish_item(seq)
            out['wish_closed'] += 1
            _log(f'sync: TR 已 done wish #{seq}，本地已闭环')

    topic_snap = _merge_tr_topic_snapshot(tasks)

    for seq, info in topic_snap.items():
        if info['done']:
            row = get_topic_by_seq(seq)
            if row and row.get('status') == 'active':
                close_topic_item(seq)
                out['topic_closed'] += 1
                _log(f'sync: TR 已 done topic #{seq}，本地已闭环')

    def _tr_task_id_eq(a, b) -> bool:
        if a is None and b is None:
            return True
        try:
            return int(a) == int(b)
        except (TypeError, ValueError):
            return str(a or '') == str(b or '')

    def _topic_needs_merge_from_tr(row, inf: dict) -> bool:
        if row is None:
            return True
        if (row.get('status') or '') != 'active':
            return True
        d_loc = (row.get('due') or '') or ''
        d_tr = (inf.get('due') or '') or ''
        return (
            (row.get('text') or '').strip() != (inf.get('what') or '').strip()
            or (row.get('who') or '').strip() != (inf.get('who') or '').strip()
            or d_loc != d_tr
            or (row.get('priority') or 'medium') != (inf.get('priority') or 'medium')
            or not _tr_task_id_eq(row.get('task_reminder_id'), inf.get('tr_id'))
        )

    for seq, info in topic_snap.items():
        if info['done']:
            continue
        row = get_topic_by_seq(seq)
        if not _topic_needs_merge_from_tr(row, info):
            continue
        upsert_topic_from_tr_sync(
            topic_seq=seq,
            text=info['what'],
            who=info['who'],
            due=info['due'] or None,
            priority=info['priority'],
            task_reminder_id=info['tr_id'],
        )
        out['topic_merged'] += 1
        _log(f'sync: topic #{seq} 已与 TR 对齐')

    for m in list(get_pending_topics()):
        seq = int(m['topic_seq'])
        if seq not in topic_snap:
            delete_topic_item(seq)
            out['topic_deleted'] += 1
            _log(f'sync: TR 已无 topic #{seq}，已删本地')

    return out


def sync_tr_state_to_local_memos_wishes(config: dict) -> dict:
    """TR 侧删除/完成/改文案时，对齐本地 memo_items / wish_items / topic_items。"""
    empty = {
        'memo_deleted': 0, 'memo_closed': 0,
        'wish_deleted': 0, 'wish_closed': 0,
        'topic_deleted': 0, 'topic_closed': 0,
        'topic_merged': 0,
    }
    tasks = fetch_tr_tasks_for_sync(config)
    if tasks is None:
        return empty
    return apply_tr_sync_to_local_tasks(tasks, config)


def topic_library_match_text(text: str, config: dict | None = None) -> bool:
    """是否为「选题库」列表指令（整句，避免与「选题xxx」收录冲突）。"""
    t = _dedup_normalize_text(text or '')
    if re.match(r'^\s*选题库\s*$', t):
        return True
    aliases = (config or {}).get('topic_library_aliases') if config else None
    if isinstance(aliases, list):
        for a in aliases:
            s = str(a).strip()
            if s and re.match(rf'^\s*{re.escape(s)}\s*$', t):
                return True
    return False


def _format_topic_library_body(tasks: list, max_items: int = 80) -> str:
    """从 TR tasks 中筛 topic:#N，按序号排序拼 markdown。"""
    snap = _merge_tr_topic_snapshot(tasks)
    rows = []
    for seq in sorted(snap.keys()):
        info = snap[seq]
        st_lbl = '已完成' if info['done'] else '进行中'
        what = info['what'] or '（无标题）'
        if len(what) > 200:
            what = what[:197] + '...'
        line = _render_template(
            'topic_library_item',
            seq=seq,
            status=st_lbl,
            what=what,
            who=info['who'] or '—',
            due=info['due'] or '—',
            module=info['module'] or '—',
        )
        rows.append(line)
    total = len(rows)
    if total == 0:
        return _render_template('topic_library_empty')
    trunc_note = ''
    if total > max_items:
        rows = rows[:max_items]
        trunc_note = _render_template('topic_library_trunc', n=max_items)
    title = _render_template('topic_library_title', n=total)
    return title + ''.join(rows) + trunc_note


def _send_webhook_chunks(text: str, config: dict, group_cid, chunk_size: int = 3200):
    """钉钉 markdown 过长时拆多条（每条仍带 footer）。"""
    text = (text or '').strip()
    if len(text) <= chunk_size:
        _send_webhook(text, config, group_cid=group_cid)
        return
    parts = []
    while text:
        parts.append(text[:chunk_size])
        text = text[chunk_size:]
    n = len(parts)
    for i, chunk in enumerate(parts, start=1):
        header = f'（{i}/{n}）\n\n' if n > 1 else ''
        _send_webhook(header + chunk, config, group_cid=group_cid)


@_memo_serialized
def process_topic_library(config: dict, group_cid=None) -> None:
    """群消息「选题库」：先与 TR 同步选题，再推送 TR 中全部 topic 列表。"""
    tasks = fetch_tr_tasks_for_sync(config)
    if tasks is None:
        _send_webhook(
            _render_template('topic_library_read_fail'),
            config, group_cid=group_cid)
        return
    stats = apply_tr_sync_to_local_tasks(tasks, config)
    if any(stats.values()):
        _log(f'topic_library sync {stats}')
    body = _format_topic_library_body(tasks)
    _send_webhook_chunks(body, config, group_cid)


def _parse_topic_pick_body(text: str) -> tuple:
    """【选题】/ 选题： 开头；可选 提报人：xxx。返回 (展示正文, 提报人或 None)。"""
    if not text:
        return '', None
    t = text.strip()
    t = re.sub(
        r'[\uff3b【\[]+\s*选题\s*[\uff3d】\]]+',
        '',
        t,
    ).strip()
    t = re.sub(r'^\s*选题\s*', '', t).strip()
    t = strip_leading_trigger_punct(t)
    reporter = None
    rm = re.search(r'提报人\s*[:：]\s*(\S+)', t)
    if rm:
        reporter = rm.group(1).strip()
        t = (t[:rm.start()] + t[rm.end():]).strip()
        t = ' '.join(t.split())
    title = t.strip()
    if reporter and title:
        display = f'{title}（提报：{reporter}）'
    elif reporter:
        display = f'（提报：{reporter}）'
    else:
        display = title
    return display, reporter


def _text_triggers_topic_pick(text: str, config: dict | None = None) -> bool:
    if not text:
        return False
    if topic_library_match_text(text, config):
        return False
    if re.search(r'[\uff3b【\[]\s*选题\s*[\uff3d】\]]', text):
        return True
    # 行首「选题」：冒号/逗号、空白+正文，或「选题」后紧跟正文（无标点无空格，如 选题三国赛季）
    return bool(re.match(r'^\s*选题(?:\s*[:：，,]|\s+\S|\S)', text))


@_memo_serialized
def process_memo_edit_description(msg_id, text, group_cid, config) -> bool:
    parsed = _parse_memo_edit_desc_command(text or '')
    if not parsed:
        return False
    if _consume_edit_cmd_dedup(group_cid, text):
        return True
    seq, raw_body = parsed
    body = _strip_trailing_cmd_noise(raw_body)
    if not body:
        _send_webhook('未解析到新描述内容。', config, group_cid=group_cid)
        return True
    memo = get_memo_by_seq(seq)
    if not memo or memo.get('status') != 'active':
        _send_webhook(_render_template('not_found', seq=seq, summary=''), config, group_cid=group_cid)
        return True
    update_memo_text(seq, body)
    ok = _update_memo_task_in_tr(seq, config, what=body)
    msg = _render_template('memo_edit_desc_ok', seq=seq, summary=body[:80])
    if not msg:
        msg = f'已更新 memo #{seq} 描述'
    if not ok:
        msg += f'\n（TR 未找到 memo:#{seq}，仅本地已改）'
    _send_webhook(msg, config, group_cid=group_cid)
    _log(f'memo #{seq} description updated, tr={ok}')
    return True


@_memo_serialized
def process_memo_edit_version(msg_id, text, group_cid, config) -> bool:
    m = _RE_MEMO_EDIT_VER.search((text or '').strip())
    if not m:
        return False
    if _consume_edit_cmd_dedup(group_cid, text):
        return True
    seq = int(m.group(1))
    ver = _strip_trailing_cmd_noise(m.group(2))
    if not ver:
        _send_webhook('未解析到版本号。', config, group_cid=group_cid)
        return True
    memo = get_memo_by_seq(seq)
    if not memo or memo.get('status') != 'active':
        _send_webhook(_render_template('not_found', seq=seq, summary=''), config, group_cid=group_cid)
        return True
    ok = _update_memo_task_in_tr(seq, config, version=ver)
    msg = _render_template('memo_edit_version_ok', seq=seq, version=ver)
    if not msg:
        msg = f'已更新 memo #{seq} 版本 {ver}'
    if not ok:
        msg += f'\n（TR 未找到 memo:#{seq}）'
    _send_webhook(msg, config, group_cid=group_cid)
    _log(f'memo #{seq} version -> {ver}, tr={ok}')
    return True


@_memo_serialized
def process_memo_assign_tr(msg_id, text, group_cid, config) -> bool:
    m = _RE_MEMO_ASSIGN.search((text or '').strip())
    if not m:
        return False
    if _consume_edit_cmd_dedup(group_cid, text):
        return True
    seq = int(m.group(1))
    who = _strip_trailing_cmd_noise(m.group(2))
    who = re.sub(r'^给\s*', '', who).strip()
    if not who:
        _send_webhook('未解析到指派人。', config, group_cid=group_cid)
        return True
    memo = get_memo_by_seq(seq)
    if not memo or memo.get('status') != 'active':
        _send_webhook(_render_template('not_found', seq=seq, summary=''), config, group_cid=group_cid)
        return True
    ok = _update_memo_task_in_tr(seq, config, who=who)
    msg = _render_template('memo_assign_ok', seq=seq, who=who)
    if not msg:
        msg = f'memo #{seq} 已指派 {who}'
    if not ok:
        msg += f'\n（TR 未找到 memo:#{seq}）'
    _send_webhook(msg, config, group_cid=group_cid)
    _log(f'memo #{seq} assign -> {who}, tr={ok}')
    return True


def topic_pick_content_key(text: str) -> str:
    c, _ = _parse_topic_pick_body(text or '')
    t = ' '.join((c or '').split())
    return (t[:80] or '').strip()


@_memo_serialized
def process_topic_pick(msg_id, text, context_msgs, memo_ts, group_cid, config):
    """群选题收录：写入 topic_items（独立 topic_seq）+ TR（note: topic:#N）。"""
    if not _text_triggers_topic_pick(text or '', config):
        return False
    if is_topic_processed(msg_id):
        return True

    content, _rep = _parse_topic_pick_body(text)
    if not (content or '').strip():
        _send_webhook('选题内容为空，请写「选题：标题」或「【选题】标题」，可选「提报人：姓名」。', config, group_cid=group_cid)
        return True

    context = _build_context(context_msgs, memo_ts)
    dup_m = find_active_topic_duplicate_body(content)
    if dup_m:
        es = dup_m.get('topic_seq', '')
        sm = ((dup_m.get('text') or '')[:80] + (
            '...' if len(dup_m.get('text') or '') > 80 else ''))
        body = _render_template('topic_duplicate', existing_seq=es, summary=sm)
        _send_webhook(body, config, group_cid=group_cid)
        return True

    topic_who = (config.get('topic_pick_who') or '选题库').strip() or '选题库'
    topic_mod = (config.get('topic_pick_module') or topic_who).strip() or topic_who

    topic_seq = get_next_topic_seq()
    due_date = (datetime.now() + timedelta(days=int(config.get('default_due_days', 7)))).strftime('%Y-%m-%d')
    tr_id = _create_task_in_reminder(
        topic_seq, content, due_date, 'medium', context, config,
        who_override=topic_who, module_override=topic_mod,
        note_kind='topic',
    )
    if tr_id is None:
        _log(f'TaskReminder unreachable, topic #{topic_seq} deferred')
        return None

    save_topic_item(
        topic_seq=topic_seq,
        msg_id=msg_id,
        text=content,
        who=topic_who,
        due=due_date,
        priority='medium',
        context=json.dumps(context, ensure_ascii=False) if context else None,
        task_reminder_id=tr_id,
    )
    summary = content[:40] + ('...' if len(content) > 40 else '')
    confirm = _render_template('topic_pick_confirm', seq=topic_seq, summary=summary, module=topic_mod)
    _send_webhook(confirm, config, group_cid=group_cid)
    _log(f'topic pick #{topic_seq} -> TR module={topic_mod}')
    return True


def _parse_person_lookup_keyword(text: str, aliases) -> str | None:
    """匹配「洋哥」「找洋哥」等；aliases 来自配置 person_lookup_aliases。"""
    if not text or not aliases:
        return None
    raw = [str(a).strip() for a in aliases if str(a).strip()]
    if not raw:
        return None
    t = re.sub(r'[!！.。…]+$', '', (text or '').strip())
    for a in sorted(set(raw), key=len, reverse=True):
        esc = re.escape(a)
        if t == a or re.match(rf'^找\s*{esc}$', t):
            return a
    return None


def person_lookup_match_keyword(text: str, config: dict) -> str | None:
    """若 text 命中人员筛选指令，返回关键词；供路由层按关键词节流（双通道不同 msg_id）。"""
    aliases = config.get('person_lookup_aliases')
    if not isinstance(aliases, list) or not aliases:
        aliases = ['洋哥', '崔哥']
    return _parse_person_lookup_keyword(text or '', aliases)


def _clip_lookup_line(s: str, n: int = 120) -> str:
    s = ' '.join((s or '').split())
    if len(s) <= n:
        return s
    return s[: n - 1] + '…'


@_memo_serialized
def process_person_lookup(msg_id, text, group_cid, config) -> bool:
    """快捷指令：找洋哥 / 洋哥 — 列出正文中含该关键词的进行中备忘与愿望。"""
    aliases = config.get('person_lookup_aliases')
    if not isinstance(aliases, list) or not aliases:
        aliases = ['洋哥', '崔哥']
    kw = _parse_person_lookup_keyword(text or '', aliases)
    if not kw:
        return False
    if _consume_edit_cmd_dedup(group_cid, text):
        return True
    memos = [m for m in get_pending_memos() if kw in (m.get('text') or '')]
    wishes = [w for w in get_pending_wishes() if kw in (w.get('text') or '')]
    try:
        cap_m = int(config.get('person_lookup_max_memos', 20) or 20)
        cap_w = int(config.get('person_lookup_max_wishes', 20) or 20)
    except (TypeError, ValueError):
        cap_m, cap_w = 20, 20
    cap_m = max(1, min(cap_m, 80))
    cap_w = max(1, min(cap_w, 80))

    title = _render_template('person_lookup_title', keyword=kw)
    if not title:
        title = f'### **「{kw}」相关待办**（备忘 + 愿望）\n\n'
    parts = [title]
    if not memos and not wishes:
        empty = _render_template('person_lookup_empty', keyword=kw)
        parts.append(empty or f'没有在进行中的备忘、愿望正文里找到「{kw}」。\n\n----')
    else:
        if memos:
            head = _render_template('person_lookup_memo_head') or '**备忘**\n'
            parts.append(head)
            n_mem = 0
            for m in memos:
                if n_mem >= cap_m:
                    break
                line = _render_template(
                    'person_lookup_memo_line',
                    seq=m['memo_seq'],
                    text=_clip_lookup_line(m.get('text') or ''),
                )
                parts.append(line or f"- **memo #{m['memo_seq']}** {_clip_lookup_line(m.get('text') or '')}\n")
                n_mem += 1
            if len(memos) > cap_m:
                parts.append(
                    _render_template('person_lookup_trunc', n=cap_m)
                    or f'\n（备忘仅展示前 {cap_m} 条）\n',
                )
        if wishes:
            head = _render_template('person_lookup_wish_head') or '**愿望**\n'
            parts.append(head)
            n_w = 0
            for w in wishes:
                if n_w >= cap_w:
                    break
                line = _render_template(
                    'person_lookup_wish_line',
                    seq=w['wish_seq'],
                    text=_clip_lookup_line(w.get('text') or ''),
                )
                parts.append(line or f"- **wish #{w['wish_seq']}** {_clip_lookup_line(w.get('text') or '')}\n")
                n_w += 1
            if len(wishes) > cap_w:
                parts.append(
                    _render_template('person_lookup_trunc', n=cap_w)
                    or f'\n（愿望仅展示前 {cap_w} 条）\n',
                )
    _send_webhook(''.join(parts), config, group_cid=group_cid)
    _log(f'person lookup kw={kw!r} memos={len(memos)} wishes={len(wishes)}')
    return True


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
    """去掉触发词「许愿」「愿望」「wish」及常见括号；触发词后的标点空格一并去掉。"""
    if not text:
        return ''
    t = text.strip()
    # 【许愿】/【愿望】/【wish】，愿望单不参与
    t = re.sub(
        r'[\uff3b【\[]+(?:许愿|愿望(?!单)|wish)[\uff3d】\]]+',
        ' ', t, flags=re.IGNORECASE)
    t = re.sub(
        r'^\s*(?:许愿|愿望(?!单)|wish)\s*',
        '',
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r'\s+(?:许愿|愿望(?!单)|wish)\s+',
        ' ',
        t,
        flags=re.IGNORECASE,
    )
    t = strip_leading_trigger_punct(t)
    t = ' '.join(t.split())
    return (t or '').strip()


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
    群消息含「许愿」「愿望」或英文 wish（整词）时：分配 wish_seq，写本地库 + TaskReminder（负责人 wish_assignee）。
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
