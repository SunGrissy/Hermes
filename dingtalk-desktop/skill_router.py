# -*- coding: utf-8 -*-
"""
技能路由器 — 后台轮询线程

当前支持：
  - 监听招聘群内 ct=502（PDF 文件消息）→ 触发简历 AI 初筛
  - 监听助理群 + memo_tracker.colleague_skill_cids 白名单群（及可选 topic_skill_group_cid 选题群）→ 备忘 / 许愿 / 完成 等（他人仅白名单群入队）
  - 助理通知主群 memo_tracker.group_cid：仅 memo_tracker.assistant_group_skill_uids 中的钉钉 UID 可触发技能（缺省该字段时用 DINGTALK_MY_UID / DEFAULT_MY_UID）；设为 [] 则群内所有人可触发。白名单群不受此限。
  - 手机发指令依赖桌面 /fetch：备忘轮询 JSAPI 超时默认约 95s（SKILL_MEMO_FETCH_TIMEOUT_S），须盖住 daemon _fetch_lock 排队 + beacon；POST body 带 timeout 与 fetch_history 对齐。发送者身份用 uid / is_self / sender 综合解析。
  - 文本含「许愿」「愿望」或英文 wish（整词）→ 写入 TaskReminder，负责人为配置项 wish_assignee（默认「愿望单」）
  - 文本含「愿望单」→ 列出未完成愿望（wish #N + 旧版 TR 条目）（日志 + webhook）；优先于「愿望」单独触发
  - 文本含「删除 wish N」「删除愿望 N」→ 删本地 wish 记录并移除 TR 中 wish:#N
  - 文本含「完成 wish N」「关闭愿望 N」→ 本地标 done，TR 中 wish:#N 标 processStatus=done
  - 助理通知群发送「上班啦」/「上班」→ 执行 MyAgents 工具状态检查，结果经 webhook（小秘书提醒）推送
  - 助理群发送「版本咋样了」/「版本怎么样了」→ 触发 version_digest，向 version_digest_webhook 推送版本状态摘要
  - 备忘快捷：改描述/改版本/TR 指派（例：改备忘39描述为…、备忘39版本v1、备忘39分给张三）；选题收录（【选题】/选题：→ topic_items + TR note topic:#N）；选题改描述/删除 topic（与备忘同类指令，支持多编号顿号分隔）；「选题库」从 TR 列出全部 topic:#N 并先做一次本地同步；人员筛选（配置 person_lookup_aliases，如「洋哥」「找洋哥」→ 列出含关键词的备忘+愿望）；桌面运维（检查大门/重启大门/拉今天|昨天|YYMMDD|N天日报，开始+完成 webhook）；轮询周期对齐 TR 与本地 memo/wish/topic（选题以 TR 文案/删改/完成为准）；选题专用群 cid 可由 topic_skill_group_name 在 report_cids 中按群名解析
  - 助理群「预审」：推送路径下优先用本进程缓存的「上一条钉钉文档链接」（与备忘同源 send 事件），避免依赖 /fetch 回溯

架构：
  - 启动时由 daemon.py 调用 SkillRouter.start()
  - 每 POLL_INTERVAL 秒向 daemon /fetch 查询各群的新消息
  - ct=502 且未处理过 → 交给 skills/resume_screen
  - 文本含"备忘"/"TR"/"完成"/「许愿」/「愿望」/wish/「愿望单」/「N、M推到明天」类延期 → 交给 skills/memo_tracker；触发词后可跟标点空格，解析时会剥离
  - 通过 DB + 内存 seen_ids 实现幂等
  - 备忘/wish/预审轮询与推送：仅处理 skill_router.start() 之后的消息（ts），重启不追溯历史
  - Frida 备忘推送队列开启时仍执行 _poll_memo_once：否则手机发的消息不会入队、永远无法触发技能
"""
import os
import re
import sys
import json
import time
import threading
import urllib.request
from datetime import datetime

# [AgentMemo Task] 开始时间: 2026-03-18 19:00
# [AgentMemo Task] 任务目标: MEMO-001 补齐 ct=3100 富文本处理并接入模板链路
# [AgentWish Task] 开始时间: 2026-03-19
# [AgentWish Task] 任务目标: WISH-001 群消息「许愿」/「愿望单」路由
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

from db.store import init_db, is_resume_processed, is_memo_processed, is_doc_review_processed
from skills.resume_screen import process_resume_message
from version_digest import run_version_digest_send
from skills.memo_tracker import (
    process_memo,
    process_close,
    process_close_wish,
    process_delete,
    process_delete_topic,
    process_delete_wish,
    process_defer_memo,
    parse_defer_memo_command,
    parse_delete_memo_seqs,
    parse_delete_topic_seqs,
    process_today_focus,
    process_tomorrow_focus,
    process_week_focus,
    process_wish,
    process_wish_list,
    wish_content_key,
    strip_leading_trigger_punct,
    process_memo_edit_description,
    process_memo_edit_version,
    process_memo_assign_tr,
    process_topic_edit_description,
    process_topic_pick,
    topic_pick_content_key,
    _text_triggers_topic_pick,
    topic_library_match_text,
    process_topic_library,
    process_person_lookup,
    person_lookup_match_keyword,
    sync_tr_state_to_local_memos_wishes,
)
from skills.desk_ops import process_desk_ops
from skills.doc_review import (
    extract_doc_url,
    extract_doc_url_from_message,
    process_doc_review,
    get_doc_review_no_link_message,
    try_user_stop_doc_review,
    send_no_active_doc_review_stop_reply,
)
from skills.status_check import run_and_send as run_status_check_and_send
from lib.utils import get_webhook_url, DATA_DIR, DEFAULT_MY_UID, ContactsDB

DAEMON_URL    = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
POLL_INTERVAL = int(os.environ.get('SKILL_ROUTER_INTERVAL', '20'))   # 秒（推送未接入时兜底；可设 SKILL_ROUTER_INTERVAL=60 恢复）
_last_tr_sync_ms = 0
_TR_SYNC_INTERVAL_MS = int(os.environ.get('SKILL_TR_SYNC_INTERVAL_MS', '120000'))  # TR↔本地对齐周期（毫秒）
_CONFIG_PATH  = os.path.join(_THIS_DIR, 'digest_config.json')
# 与 daemon 写入的日志路径一致，否则预审回溯时读不到「刚发的文档链接」
_LOG_FILE     = os.path.join(DATA_DIR, '_msg_log.jsonl')

# region agent log
_AGENT_DEBUG_LOG = os.path.normpath(os.path.join(_THIS_DIR, '..', 'debug-5a049e.log'))


def _agent_dbg(hypothesis_id: str, location: str, message: str, **data):
    try:
        rec = {
            'sessionId': '5a049e',
            'hypothesisId': hypothesis_id,
            'location': location,
            'message': message,
            'timestamp': int(time.time() * 1000),
            'data': data,
        }
        with open(_AGENT_DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
# endregion


def _memo_allowed_cids(memo_cfg: dict) -> set:
    """技能路由处理的群：助理群 group_cid + colleague_skill_cids（同事指令白名单）。"""
    s = set()
    g = str(memo_cfg.get('group_cid') or '').strip()
    if g:
        s.add(g)
    for x in (memo_cfg.get('colleague_skill_cids') or []):
        xs = str(x).strip()
        if xs:
            s.add(xs)
    return s


# 备忘轮询优先走 JSAPI；须 >= daemon 侧 _fetch_lock 排队 + JSAPI 等待；过短则客户端先断连 → daemon 写响应 WinError 10053
_MEMO_FETCH_JSAPI_TIMEOUT_S = int(os.environ.get('SKILL_MEMO_FETCH_TIMEOUT_S', '95'))


def _message_sender_identity(msg: dict) -> str:
    """供助理群白名单比对：优先 uid；JSAPI 标 is_self 或 sender='?'（本人）时映射为我的数字 UID；否则用 sender（常为手机端 sn）。"""
    u = str(msg.get('uid') or '').strip()
    if u:
        return u
    if msg.get('is_self') is True:
        return str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()
    s = str(msg.get('sender') or '').strip()
    if s == '?':
        return str(os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)).strip()
    return s


def _normalize_person_display(s: str) -> str:
    """群聊 /fetch 有时把发送者放在 uid 字段里且为「张三」或「张三（备注）」；取主名做比对。"""
    t = (s or '').strip()
    if not t:
        return ''
    for sep in ('（', '('):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
    return t


def _assistant_group_allowed_sender_labels(memo_cfg: dict, allowed_ids: set) -> set:
    """数字 UID + 配置的别名 + 通讯录里这些 UID 对应的显示名（群消息里可能是名而不是数字）。"""
    lab = set(allowed_ids)
    raw = memo_cfg.get('assistant_group_skill_aliases')
    if raw is None:
        extra = []
    elif isinstance(raw, list):
        extra = raw
    else:
        extra = [raw]
    for x in extra:
        xs = str(x).strip()
        if not xs:
            continue
        lab.add(xs)
        lab.add(_normalize_person_display(xs))
    for uid in allowed_ids:
        if not uid.isdigit():
            continue
        try:
            nm = ContactsDB._resolve_name(uid)
            if nm:
                lab.add(nm)
                lab.add(_normalize_person_display(nm))
        except Exception:
            pass
        try:
            for ent in ContactsDB.get_all():
                eu = str(ent.get('uid') or '')
                if eu == uid and ent.get('name'):
                    lab.add(ent['name'])
                    lab.add(_normalize_person_display(ent['name']))
        except Exception:
            pass
    lab.discard('')
    return lab


def _sender_matches_assistant_labels(sender: str, labels: set) -> bool:
    s = (sender or '').strip()
    if not s:
        return False
    if s in labels:
        return True
    sn = _normalize_person_display(s)
    if sn and sn in labels:
        return True
    for L in labels:
        if not L:
            continue
        if s == L:
            return True
        ln = _normalize_person_display(L)
        if sn and ln and sn == ln:
            return True
    return False


def _assistant_group_skill_sender_allowed(memo_cfg: dict, msg_cid: str, sender_uid: str) -> bool:
    """仅助理通知主群 memo_tracker.group_cid 校验发送者；白名单 colleague 群、选题群始终放行。

    - assistant_group_skill_uids 为 []：不限制（兼容旧行为）。
    - 缺省该字段：仅允许 DINGTALK_MY_UID（未设则用 DEFAULT_MY_UID）。
    - 群聊 /fetch 可能把发送者标成显示名（如「孙懿」）而非数字 UID：用 assistant_group_skill_aliases +
      通讯录反查数字 UID 的姓名，与主名归一化后比对。
    - 发送者 uid 为空时放行：Frida 推送记录常不带 uid；环境变量 DINGTALK_ASSISTANT_DENY_EMPTY_UID=1 可拒绝。
    """
    g = str(memo_cfg.get('group_cid') or '').strip()
    if not g or str(msg_cid).strip() != g:
        return True
    raw = memo_cfg.get('assistant_group_skill_uids')
    if isinstance(raw, list) and len(raw) == 0:
        return True
    if raw is None:
        uids = [os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)]
    elif not isinstance(raw, list):
        uids = [raw]
    else:
        uids = raw
    allowed = {str(x).strip() for x in uids if str(x).strip()}
    if not allowed:
        return True
    labels = _assistant_group_allowed_sender_labels(memo_cfg, allowed)
    su = str(sender_uid or '').strip()
    if not su:
        if os.environ.get('DINGTALK_ASSISTANT_DENY_EMPTY_UID', '').strip().lower() in (
                '1', 'true', 'yes', 'on'):
            _log('助理群指令已忽略：发送者 uid 为空（Frida 推送常缺 uid；勿与钉钉机器人关键词混淆）')
            return False
        return True
    ok = _sender_matches_assistant_labels(su, labels)
    if not ok:
        _log(
            '助理群指令已忽略：发送者标识=%r 不在白名单（数字 UID + assistant_group_skill_aliases + 通讯录姓名）'
            % (su,)
        )
    return ok


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[skill_router][{ts}] {msg}', flush=True)


def _load_config() -> dict:
    """从 digest_config.json 读取所有路由配置"""
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        recruit_cids = cfg.get('recruit_cids', [])
        cids = []
        cid_names = {}
        for c in recruit_cids:
            if not c:
                continue
            if isinstance(c, str):
                cids.append(c)
            else:
                cid = c.get('cid', '')
                name = c.get('name', '')
                if cid:
                    cids.append(cid)
                    if name:
                        cid_names[cid] = name
        notify_cid = cfg.get('notify_target', '')

        memo_cfg = cfg.get('memo_tracker', {})
        if not memo_cfg.get('group_cid'):
            memo_cfg['group_cid'] = notify_cid

        doc_review_cfg = cfg.get('doc_review', {})
        if not doc_review_cfg.get('group_cid'):
            doc_review_cfg['group_cid'] = notify_cid
        # webhook 优先从 webhook_config.json 按 key 读取
        memo_cfg['webhook_url'] = get_webhook_url(
            'memo_tracker', memo_cfg.get('webhook_url') or cfg.get('webhook_url', '')
        )
        doc_review_cfg['webhook_url'] = get_webhook_url(
            'doc_review', doc_review_cfg.get('webhook_url') or cfg.get('webhook_url', '')
        )
        # 白名单群 CID 列表（字符串），缺省为空 = 他人发言不入队
        _col = memo_cfg.get('colleague_skill_cids')
        if _col is None:
            memo_cfg['colleague_skill_cids'] = []
        elif not isinstance(_col, list):
            memo_cfg['colleague_skill_cids'] = [str(_col).strip()] if str(_col).strip() else []

        # 选题 / 选题库专用群：cid 优先；否则按 topic_skill_group_name 在 report_cids 中匹配群名
        tgc = str(memo_cfg.get('topic_skill_group_cid') or '').strip()
        tname = str(memo_cfg.get('topic_skill_group_name') or '').strip()
        if not tgc and tname:
            for c in cfg.get('report_cids', []):
                if not isinstance(c, dict):
                    continue
                nm = (c.get('name') or '').strip()
                cid = str(c.get('cid') or '').strip()
                if not cid or not nm:
                    continue
                if nm == tname or tname in nm:
                    tgc = cid
                    break
        if tgc:
            memo_cfg['topic_skill_group_cid'] = tgc
        tkey = str(memo_cfg.get('topic_skill_webhook_key') or '').strip()
        raw_tw = str(memo_cfg.get('topic_skill_webhook_url') or '').strip()
        tw = (get_webhook_url(tkey, raw_tw) if tkey else raw_tw).strip()
        if tgc:
            cols = memo_cfg['colleague_skill_cids']
            if tgc not in cols:
                cols.append(tgc)
            if tw:
                br = memo_cfg.get('wish_reply_webhook_by_cid')
                if not isinstance(br, dict):
                    br = {}
                    memo_cfg['wish_reply_webhook_by_cid'] = br
                br[tgc] = tw

        return {
            'recruit_cids': cids,
            'cid_names': cid_names,
            'notify_cid': notify_cid,
            'memo_tracker': memo_cfg,
            'doc_review': doc_review_cfg,
        }
    except Exception as e:
        _log(f'load config failed: {e}')
        return {'recruit_cids': [], 'cid_names': {}, 'notify_cid': '',
                'memo_tracker': {}}


def _fetch_recent_messages(cid: str, count: int = 20, timeout: int = 75) -> list:
    """调 daemon /fetch 获取群内最近消息（timeout 与 daemon fetch_history 内 beacon 等待一致，需随 POST 传入）。"""
    payload = json.dumps({
        'cid': cid, 'count': count,
        'timeout': int(timeout),
    }).encode('utf-8')
    req = urllib.request.Request(
        DAEMON_URL.rstrip('/') + '/fetch',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data.get('messages', [])
    except Exception as e:
        _log(f'fetch {cid} 失败: {e}')
        return []


# 手机/轻量 ProcessPush 常不带 origin_text（见 _msg_log ext_keys 仅 openConversationId 等），需用 JSAPI 补正文
_HYDRATE_FETCH_MAX_DELTA_MS = 120_000
# daemon 侧 _fetch_lock 串行 + JSAPI 重扫/等待 beacon 可达数十秒，客户端过短会先断开并触发 ConnectionAbortedError
_HYDRATE_FETCH_TIMEOUT_S = 75


def _try_hydrate_push_message_from_fetch(msg: dict) -> None:
    """push 记录 text 为空时，调 /fetch 按时间戳对齐最近一条有正文的群消息。"""
    t0 = int(time.time() * 1000)
    cid = str(msg.get('cid') or '').strip()
    push_ts = int(msg.get('ts') or 0)
    if not cid or push_ts <= 0:
        return
    rows = []
    for attempt in range(2):
        rows = _fetch_recent_messages(cid, count=35, timeout=_HYDRATE_FETCH_TIMEOUT_S)
        if rows:
            break
        if attempt == 0:
            time.sleep(2.5)
    if not rows:
        return
    best = None
    best_d = None
    for m in rows:
        t = (m.get('text') or '').strip()
        if not t:
            continue
        mts = int(m.get('ts') or 0)
        if mts <= 0:
            continue
        d = abs(mts - push_ts)
        if d > _HYDRATE_FETCH_MAX_DELTA_MS:
            continue
        if best_d is None or d < best_d:
            best_d = d
            best = m
    if not best or best_d is None:
        return
    msg['text'] = best.get('text') or ''
    rw = best.get('raw')
    if rw:
        msg['raw'] = rw
    try:
        msg['content_type'] = int(best.get('content_type') or msg.get('content_type') or 1)
    except (TypeError, ValueError):
        pass
    _log(f'push: 已用 /fetch 补全正文 (delta_ms={best_d})')


def _read_log_messages(cid: str, max_count: int = 50,
                       max_age_ms: int = 86400 * 1000) -> list:
    """从 beacon 监控日志读取指定 CID 的近期消息（JSAPI 不可用时的备选通道）。

    日志按追加顺序写入（最新在末尾），倒序扫描以快速获取最近消息。
    uid 字段可能为 null，从 md_extra.3.1 补全，确保 msg_id 能正确构造。
    返回格式与 /fetch 消息兼容（chronological 顺序）。
    """
    if not os.path.exists(_LOG_FILE):
        return []

    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - max_age_ms
    results = []

    try:
        with open(_LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        _log(f'read log failed: {e}')
        return []

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue

        ts = int(m.get('ts', 0))
        if ts and ts < cutoff_ms:
            break  # 日志按时序追加，遇到过期条目即可停止

        if str(m.get('cid', '')) != str(cid):
            continue

        uid = m.get('uid') or m.get('sender') or ''
        if not uid:
            try:
                uid = (m.get('md_extra') or {}).get('3', {}).get('1', '') or ''
            except Exception:
                uid = ''

        results.append({
            'cid': m.get('cid', ''),
            'uid': uid,
            'ts': ts,
            'content_type': m.get('content_type', 0),
            'text': m.get('text', '') or '',
            'raw': m.get('raw', '') or '',
            '_from_log': True,
        })

        if len(results) >= max_count:
            break

    results.reverse()
    return results


def _fetch_memo_messages(cid: str, max_age_ms: int) -> list:
    """备忘/文档指令专用拉取：优先 JSAPI，不可用时自动降级到 beacon 日志。"""
    messages = _fetch_recent_messages(cid, count=20, timeout=_MEMO_FETCH_JSAPI_TIMEOUT_S)
    if messages:
        return messages
    msgs = _read_log_messages(cid, max_count=50, max_age_ms=max_age_ms)
    if msgs:
        _log(f'memo fetch: JSAPI 不可用，已切换到 beacon 日志 ({len(msgs)} 条)')
    return msgs


def _extract_file_info(msg: dict) -> tuple:
    """
    从 fetch 返回的消息中提取 (msg_id, file_name, file_path)。
    ct=502 的 raw 字段包含 content JSON，attachment.extension 有 f_name 和 path。
    """
    raw_str = msg.get('raw', '')
    if not raw_str:
        return None, None, None

    try:
        content = json.loads(raw_str)
    except Exception:
        return None, None, None

    attachments = content.get('attachments', [])
    if not attachments:
        return None, None, None

    att = attachments[0]
    ext = att.get('extension', {})

    file_name = ext.get('f_name', '') or att.get('filePath', '').split('/')[-1]
    file_path = att.get('filePath', '') or ext.get('path', '')

    # msg_id 不在 fetch 返回里，用 ts + uid 拼一个稳定 key
    ts  = str(msg.get('ts', ''))
    uid = str(msg.get('uid', ''))
    msg_id = f'{ts}_{uid}' if (ts and uid) else None

    return msg_id, file_name, file_path


_RESUME_WINDOW_MS = 48 * 3600 * 1000   # 只处理 48 小时内的简历消息


def _poll_once(cid: str, notify_cid: str, seen_ids: set,
               source_name: str = '', start_ts: int = 0):
    """轮询一个招聘群/私信，处理所有新的 ct=502 消息。
    结果发到 notify_cid（助理通知群），而非原来源。
    source_name: 来源的显示名（用于推送消息中告知来源）
    start_ts: daemon 本次启动时刻（毫秒），早于此时刻的消息跳过
    """
    # 与 _HYDRATE_FETCH_TIMEOUT_S 一致：daemon /fetch 串行锁 + JSAPI 慢时 30s 易误判超时
    messages = _fetch_recent_messages(
        cid, count=20, timeout=_HYDRATE_FETCH_TIMEOUT_S)
    processed_count = 0
    now_ms = int(time.time() * 1000)
    # 截止时间 = max(启动时刻, 48小时前)，两个条件都满足才处理
    cutoff_ms = max(start_ts, now_ms - _RESUME_WINDOW_MS)

    for msg in messages:
        if msg.get('content_type') != 502:
            continue

        # ── 时间门禁：消息发送时间必须晚于截止时间 ──────────────
        msg_ts = int(msg.get('ts') or 0)
        if msg_ts and msg_ts < cutoff_ms:
            continue

        msg_id, file_name, file_path = _extract_file_info(msg)
        if not msg_id:
            continue

        if file_name and not file_name.lower().endswith('.pdf'):
            continue

        if msg_id in seen_ids or is_resume_processed(msg_id):
            continue

        sender_uid = str(msg.get('uid', ''))
        reply_cid = notify_cid or cid
        _log(f'发现新简历: {file_name} (uid={sender_uid}, 来源={source_name or cid}) → 结果发到 {reply_cid}')

        try:
            result = process_resume_message(
                msg_id=msg_id,
                group_cid=reply_cid,
                sender_uid=sender_uid,
                file_name=file_name,
                file_path=file_path,
                source_name=source_name,
            )
            if result is None:
                # 文件未下载，不加 seen_ids，下次 poll 继续重试
                _log(f'等待下载: {file_name}')
            elif result is True:
                processed_count += 1
                seen_ids.add(msg_id)
                _log(f'处理完成: {file_name}')
            else:
                # False: 结论为待定/不通过，已发通知，加 seen_ids 避免重复调 LLM
                seen_ids.add(msg_id)
                _log(f'已通知（非通过）: {file_name}')
        except Exception as e:
            _log(f'处理失败 {file_name}: {e}')

    return processed_count


def _make_msg_id(msg: dict) -> str | None:
    ts = str(msg.get('ts', ''))
    uid = str(msg.get('uid', ''))
    if ts and uid:
        return f'{ts}_{uid}'
    dm = msg.get('ding_mid')
    if dm is not None and str(dm).strip() not in ('', '0'):
        sdm = str(dm).strip()
        if ts:
            return f'{ts}_mid{sdm}'
        return f'mid_{sdm}'
    if ts:
        return f'{ts}_nouid'
    return None


def _extract_message_text(msg: dict) -> str:
    """统一提取消息文本：纯文本、富文本(3100)，以及带 text 字段的 Markdown 等类型。"""
    ct = int(msg.get('content_type') or 0)
    if ct == 1:
        return (msg.get('text') or '').strip()

    if ct == 3100:
        text = (msg.get('text') or '').strip()
        raw = msg.get('raw', '') or ''
        if raw:
            try:
                raw_data = json.loads(raw) if isinstance(raw, str) else raw
                descs = []
                for att in (raw_data.get('attachments') or []):
                    ext = att.get('extension') or {}
                    desc = (ext.get('desc') or '').strip()
                    if desc and desc not in descs:
                        descs.append(desc)
                if descs:
                    merged = '\n'.join(descs).strip()
                    if not text or len(merged) > len(text):
                        text = merged
            except Exception:
                pass
        return text

    return (msg.get('text') or '').strip()


def _normalize_command_text(text: str) -> str:
    """指令关键词归一：零宽字符、繁体「許願」等。"""
    if not text:
        return text
    t = text.replace('\u200b', '').replace('\ufeff', '')
    t = t.replace('許願', '许愿')
    return t


_RE_MEMO   = re.compile(r'[\uff3b【\[]*(?:备忘|提醒我|TR)[\uff3d】\]]*')
_RE_CLOSE  = re.compile(r'(?:完成|关闭)\s*#?\d+')
_RE_CLOSE_WISH = re.compile(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*\d+', re.IGNORECASE)
_RE_DELETE_WISH = re.compile(r'删除\s*(?:wish|愿望)\s*#?\s*\d+', re.IGNORECASE)
_RE_TODAY_FOCUS = re.compile(
    r'今天\s*(?:我要?)?\s*关注\s*啥|今天\s*有啥\s*(?:要做的|要关注)|今天\s*关注\s*啥'
)
_RE_TOMORROW_FOCUS = re.compile(
    r'明天\s*(?:我\s*)?(?:要\s*)?\s*关注\s*啥|明天\s*有啥'
)
_RE_WEEK_FOCUS = re.compile(
    r'本周\s*(?:我要?)?\s*关注\s*啥|本周\s*有啥|本周\s*关注\s*啥'
)
_RE_PRECHECK = re.compile(r'^\s*预审[!！。.\s]*$')
# 同一文档在 doc_review_window 内被去重后，发下列句式可跳过时间窗再跑一轮
_RE_PRECHECK_FORCE_PREFIX = re.compile(
    r'^\s*(?:强制|再|重跑|坚持|必须|再来|依旧|还要)\s*预审[!！。.\s]*$'
)
_RE_PRECHECK_FORCE_SUFFIX = re.compile(
    r'^\s*预审\s*(?:再来|重试|重跑)(?:[!！。.\s]*)?$'
)
# 停止 Palace 子进程：停止预审 / 中断预审 / 叫停预审 / 预审停止 …
_RE_PRECHECK_STOP = re.compile(
    r'^\s*(?:(?:停止|中断|叫停)\s*预审|预审\s*(?:停止|中断|叫停))(?:[!！。.,，\s]*)?$'
)
# 支持「上班啦」「上班」「上班啦！」等，整条以上班啦/上班开头且无其它实质内容即可
_RE_MORNING = re.compile(r'^\s*(?:上班啦|上班)\s*[!！。.~\s]*$')
# 版本状态摘要（与 py version_digest.py 同源，发向 digest 里 version_digest_webhook）
_RE_VERSION_DIGEST = re.compile(
    r'^\s*版本\s*(?:咋样|怎么样)了\s*[!！。.?？~\s]*$')


def _precheck_command_flags(text: str) -> tuple:
    """预审指令：(是否匹配, 是否跳过同一文档的短时去重窗口)。"""
    if not text:
        return (False, False)
    if _RE_PRECHECK_FORCE_PREFIX.match(text) or _RE_PRECHECK_FORCE_SUFFIX.match(text):
        return (True, True)
    if _RE_PRECHECK.match(text):
        return (True, False)
    return (False, False)

_MEMO_MAX_AGE_MS       = 24 * 3600 * 1000   # 处理 24 小时内的备忘（beacon 日志兜底，seen_ids 保幂等）
_DOC_REVIEW_MAX_AGE_MS = 30 * 60 * 1000    # 预审：回溯文档链接时只看近 30 分钟消息
# 推送链路上缓存助理群最近一条文档 URL（send Hook 先到、免等 JSAPI /fetch）
_doc_push_url_lock = threading.Lock()
_last_push_doc_url_by_cid: dict = {}


def _remember_push_doc_url_if_any(msg_cid: str, msg: dict, doc_group_cid: str) -> None:
    """本人/群内任一条发送里若带钉钉文档链接，写入缓存，供下一条「预审」免 fetch。"""
    if not doc_group_cid or str(msg_cid) != str(doc_group_cid).strip():
        return
    u = extract_doc_url_from_message(msg)
    if not u:
        return
    now_ms = int(time.time() * 1000)
    with _doc_push_url_lock:
        _last_push_doc_url_by_cid[str(msg_cid)] = (u, now_ms)


def _cached_push_doc_url(msg_cid: str, doc_group_cid: str, now_ms: int, max_age_ms: int):
    """返回推送缓存中仍有效的文档链接；过期或未命中返回 None。"""
    if not doc_group_cid or str(msg_cid) != str(doc_group_cid).strip():
        return None
    with _doc_push_url_lock:
        t = _last_push_doc_url_by_cid.get(str(msg_cid))
    if not t:
        return None
    url, ts_ms = t
    if not url or (now_ms - int(ts_ms or 0)) > max_age_ms:
        return None
    return url


# 即时类指令：仅当消息带有效 ts 且在下列时间窗内才执行（钉钉/ daemon 重启后轮询到历史消息时不误触发）
_MORNING_CMD_MAX_AGE_MS = int(os.environ.get('SKILL_MORNING_MAX_AGE_MS', str(15 * 60 * 1000)))   # 默认 15 分钟
_PRECHECK_CMD_MAX_AGE_MS = int(os.environ.get('SKILL_PRECHECK_MAX_AGE_MS', str(30 * 60 * 1000)))  # 默认 30 分钟
_RECENT_CMD_MS = 15000   # 同一指令 15 秒内只响应一次，避免重复推送
# 今日/明日/本周关注：Hook 推送与 /fetch 轮询对同一条消息可能生成不同 msg_id，15s 挡不住「下一轮 poll」；窗口须盖住 POLL_INTERVAL
_RECENT_FOCUS_CMD_MS = max(
    _RECENT_CMD_MS,
    int(os.environ.get('SKILL_FOCUS_THROTTLE_MS', str(POLL_INTERVAL * 1000 + 5000))),
)
_recent_cmd_ts = {}      # (group_cid, cmd_key) -> last_run_ts_ms
_recent_memo_ts = {}     # (group_cid, content_key) -> last_run_ts_ms，备忘按内容短时去重
# 人员筛选等 throttle 的读改写与 push/poll 并发时加锁，避免双线程同时通过 15s 窗
_MEMO_THROTTLE_LOCK = threading.Lock()
# 备忘「内容键 + 短时窗」登记与 push/poll 并发时加锁，避免双线程同时通过去重导致双收录
_MEMO_INGEST_LOCK = threading.Lock()
# msg_id 去重需要原子“查+写”，否则并发 push 可能同一 msg_id 双处理
_MEMO_SEEN_LOCK = threading.Lock()


def _reserve_msg_id_once(seen_set: set, msg_id: str) -> bool:
    """原子预占 msg_id。True=本次首次占用，可继续处理；False=已处理过。"""
    with _MEMO_SEEN_LOCK:
        if msg_id in seen_set:
            return False
        seen_set.add(msg_id)
        return True


def _is_stale_command_msg(msg: dict, now_ms: int, max_age_ms: int) -> bool:
    """即时类指令（上班啦、预审等）：True 表示消息过旧或时间戳不可靠，应忽略。

    - ts<=0：常见于 beacon 日志兜底写入的发送记录，无真实消息时间，轮询时不应触发。
    - now_ms - ts > max_age_ms：历史消息（如重启后 JSAPI 拉回群历史）。
    """
    ts = int(msg.get('ts') or 0)
    if ts <= 0:
        return True
    return (now_ms - ts) > max_age_ms


def _skip_msg_before_router_start(msg: dict, router_start_ms: int) -> bool:
    """True：本条消息早于 skill_router 本次 start()，应跳过（重启后不追溯）。

    router_start_ms<=0 时不启用。ts<=0 且无 ding_mid 时视为不可靠；有 ding_mid 的实时 push 仍处理（手机端常见）。
    """
    if not router_start_ms or router_start_ms <= 0:
        return False
    ts = int(msg.get('ts') or 0)
    if ts <= 0:
        return msg.get('ding_mid') is None
    return ts < router_start_ms


def _memo_content_key(text: str) -> str:
    """备忘内容归一化，用于短时去重（同一条备忘不重复收录）。"""
    if not text:
        return ''
    t = re.sub(r'[\uff3b【\[]*(?:备忘|提醒我|TR)[\uff3d】\]]*', '', text).strip()
    t = strip_leading_trigger_punct(t)
    t = ' '.join(t.split())  # 合并中间空白，避免同一句因空格差异被处理两次
    return (t[:80] or '').strip()


def _text_triggers_new_wish(text: str, memo_cfg: dict | None = None) -> bool:
    """与「许愿」等效的新愿望触发：含愿望单时只走列表，不收录。"""
    if not text:
        return False
    # 选题优先：标题里常带「愿望/wish」等词，勿误进愿望单
    if _text_triggers_topic_pick(text, memo_cfg):
        return False
    if '愿望单' in text:
        return False
    if '许愿' in text:
        return True
    if re.search(r'愿望(?!单)', text):
        return True
    if re.search(r'(?i)\bwish\b', text):
        return True
    return False


def _normalize_push_record(record: dict) -> dict:
    """把 monitor 推送的 record 转成与 _read_log_messages 一致的 msg 结构（含 uid）。"""
    uid = record.get('uid', '') or ''
    if not uid:
        try:
            me = record.get('md_extra') or {}
            inner = me.get(3) or me.get('3') or {}
            uid = str(inner.get(1) or inner.get('1') or '')
        except Exception:
            uid = ''
    dm = record.get('msg_id')
    ding_mid = None
    if dm is not None and str(dm).strip() not in ('', '0'):
        ding_mid = dm
    return {
        'cid': record.get('cid', ''),
        'uid': uid,
        'ts': record.get('ts', 0),
        'content_type': record.get('content_type', 0),
        'text': record.get('text', '') or '',
        'raw': '',
        'ding_mid': ding_mid,
    }


def _dispatch_one_message(record: dict, memo_cfg: dict,
                          memo_seen_ids: set, doc_review_cfg: dict = None,
                          doc_seen_ids: set = None, router_start_ms: int = 0):
    """推送到达时立刻处理单条：消息 cid 须在 memo 助理群或 colleague_skill_cids 白名单内。

    router_start_ms：本次 router 启动时刻（毫秒）；早于该时刻的记录不处理（与轮询一致）。
    """
    msg = _normalize_push_record(record)
    if _skip_msg_before_router_start(msg, router_start_ms):
        return
    msg_cid = str(msg.get('cid', '') or '')
    if msg_cid not in _memo_allowed_cids(memo_cfg):
        return
    _sender_uid = _message_sender_identity(msg)
    if not _assistant_group_skill_sender_allowed(memo_cfg, msg_cid, _sender_uid):
        return
    _doc_g = str((doc_review_cfg or {}).get('group_cid') or '').strip()
    if _doc_g:
        _remember_push_doc_url_if_any(msg_cid, msg, _doc_g)

    try:
        _ct_h = int(msg.get('content_type') or 0)
    except (TypeError, ValueError):
        _ct_h = 0
    # 仅文本类 push 补水；文件/卡片等空正文不应误配邻近文字
    if _ct_h == 1 and not (msg.get('text') or '').strip():
        _try_hydrate_push_message_from_fetch(msg)

    text = _normalize_command_text(_extract_message_text(msg))
    if not text:
        return
    msg_id = _make_msg_id(msg)
    if not msg_id:
        return

    # 预审所在群：用户叫停（终止 Palace + 停进度推送）
    if (
        doc_review_cfg
        and str(doc_review_cfg.get('group_cid') or '').strip()
        and msg_cid == str(doc_review_cfg.get('group_cid')).strip()
        and _RE_PRECHECK_STOP.match(text)
    ):
        wh = doc_review_cfg.get('webhook_url', '')
        if try_user_stop_doc_review(wh):
            _log('push: 预审已按用户指令叫停')
        else:
            send_no_active_doc_review_stop_reply(wh)
        if doc_seen_ids is not None:
            doc_seen_ids.add(msg_id)
        return

    # 预审：即时拉取近期消息、回溯文档链接后执行（推送即刚发生，不做时间窗判断；轮询侧再做过期过滤）
    _is_precheck, _force_precheck = _precheck_command_flags(text)
    if _is_precheck and doc_review_cfg and doc_review_cfg.get('group_cid') and msg_cid == str(doc_review_cfg.get('group_cid')):
        if doc_seen_ids is not None and msg_id in doc_seen_ids:
            return
        try:
            now_precheck = int(time.time() * 1000)
            doc_url = _cached_push_doc_url(
                msg_cid, _doc_g, now_precheck, _DOC_REVIEW_MAX_AGE_MS,
            )
            if doc_url:
                _log('push: 预审 -> 使用前序 send 缓存的文档链接（不调用 fetch）')

            if not doc_url:
                messages = list(_fetch_memo_messages(msg_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS))
                # 当前这条「预审」可能尚未出现在 fetch 结果中，并入列表以便正确回溯前序文档
                messages.append(msg)
                msgs_by_ts = sorted(messages, key=lambda m: int(m.get('ts', 0)))
                for i, m in enumerate(msgs_by_ts):
                    if _make_msg_id(m) != msg_id:
                        continue
                    for j in range(i - 1, -1, -1):
                        u = extract_doc_url_from_message(msgs_by_ts[j])
                        if u:
                            doc_url = u
                            break
                    break
                # 首次未找到时延迟 2 秒再拉一次（刚发的文档链接可能尚未入历史）
                if not doc_url and messages:
                    time.sleep(2)
                    messages2 = list(_fetch_memo_messages(msg_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS))
                    messages2.append(msg)
                    msgs_by_ts = sorted(messages2, key=lambda m: int(m.get('ts', 0)))
                    for i, m in enumerate(msgs_by_ts):
                        if _make_msg_id(m) != msg_id:
                            continue
                        for j in range(i - 1, -1, -1):
                            u = extract_doc_url_from_message(msgs_by_ts[j])
                            if u:
                                doc_url = u
                                break
                        break
            if doc_url:
                sender_uid = str(msg.get('uid', ''))
                result = process_doc_review(
                    msg_id=msg_id, url=doc_url, sender_uid=sender_uid,
                    msg_text=text, config=doc_review_cfg,
                    force_bypass_recent_window=_force_precheck,
                )
                if doc_seen_ids is not None:
                    doc_seen_ids.add(msg_id)
                _log('push: 预审 -> 已触发')
            else:
                _send_notify(get_doc_review_no_link_message(), doc_review_cfg.get('webhook_url', ''))
                if doc_seen_ids is not None:
                    doc_seen_ids.add(msg_id)
                _log('push: 预审 -> 未找到前序文档链接')
        except Exception as e:
            _log(f'push doc_review error: {e}')
        return

    reserved = _reserve_msg_id_once(memo_seen_ids, msg_id)
    _agent_dbg(
        'H2', 'skill_router._dispatch', 'after_reserve',
        reserved=reserved, msg_id=msg_id, cid=msg_cid,
        text_preview=(text or '')[:120],
    )
    if not reserved:
        return

    now_ms = int(time.time() * 1000)

    if _RE_MORNING.match(text):
        key = (msg_cid, 'morning')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            webhook_url = memo_cfg.get('webhook_url', '')
            if webhook_url and run_status_check_and_send(webhook_url):
                _log('push: 上班啦 -> 已执行状态检查并推送')
            else:
                _log('push: 上班啦 -> webhook 未配置或发送失败')
            memo_seen_ids.add(msg_id)
        except Exception as e:
            _log(f'morning status_check error: {e}')
        return

    if _RE_VERSION_DIGEST.match(text):
        key = (msg_cid, 'version_digest')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            r = run_version_digest_send(send_webhook=True, log_to_stdout=False)
            memo_seen_ids.add(msg_id)
            if r.get('ok'):
                _log('push: 版本咋样了 -> version_digest 已推送')
            else:
                _log(f'push: 版本咋样了 -> 未成功 ({r.get("error")})')
        except Exception as e:
            memo_seen_ids.add(msg_id)
            _log(f'version_digest error: {e}')
        return

    if _RE_TODAY_FOCUS.search(text):
        key = (msg_cid, 'today_focus')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_today_focus(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 今日关注已回复')
        except Exception as e:
            _log(f'today_focus error: {e}')
        return

    if _RE_TOMORROW_FOCUS.search(text):
        key = (msg_cid, 'tomorrow_focus')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_tomorrow_focus(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 明日关注已回复')
        except Exception as e:
            _log(f'tomorrow_focus error: {e}')
        return

    if _RE_WEEK_FOCUS.search(text):
        key = (msg_cid, 'week_focus')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_week_focus(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 本周关注已回复')
        except Exception as e:
            _log(f'week_focus error: {e}')
        return

    pdef = parse_defer_memo_command(text)
    if pdef is not None:
        seqs, due_d = pdef
        defer_dedup_id = f'def:{msg_cid}:{due_d or "nodate"}:{"|".join(sorted(map(str, seqs)))}'
        if defer_dedup_id in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(defer_dedup_id)
        key = (msg_cid, 'defer', tuple(seqs), due_d or '')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_defer_memo(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            memo_seen_ids.add(msg_id)
            _log('push: 备忘延期已处理')
        except Exception as e:
            _log(f'defer_memo error: {e}')
        return

    for _edit_fn in (
        process_topic_edit_description,
        process_memo_edit_description,
        process_memo_edit_version,
        process_memo_assign_tr,
    ):
        try:
            if _edit_fn(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 备忘/选题快捷指令已处理')
                return
        except Exception as e:
            _log(f'memo quick-edit {_edit_fn.__name__} error: {e}')

    try:
        if process_desk_ops(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
            memo_seen_ids.add(msg_id)
            _log('push: 桌面运维指令')
            return
    except Exception as e:
        _log(f'desk_ops error: {e}')

    with _MEMO_THROTTLE_LOCK:
        kw_pl = person_lookup_match_keyword(text, memo_cfg)
        if kw_pl is not None:
            pl_key = (str(msg_cid).strip(), 'person_lookup', kw_pl)
            if now_ms - _recent_cmd_ts.get(pl_key, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
            _recent_cmd_ts[pl_key] = now_ms
    try:
        if process_person_lookup(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
            memo_seen_ids.add(msg_id)
            _log('push: 人员关键词筛选（备忘+愿望）')
            return
    except Exception as e:
        _log(f'person_lookup error: {e}')

    if _RE_DELETE_WISH.search(text):
        m_seq = re.search(r'删除\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
        if m_seq:
            seq = m_seq.group(1)
            delete_dedup_id = f'delwish:{msg_cid}:{seq}'
            if delete_dedup_id in memo_seen_ids:
                memo_seen_ids.add(msg_id)
                return
            memo_seen_ids.add(delete_dedup_id)
            key = (msg_cid, 'delete_wish', seq)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
            _recent_cmd_ts[key] = now_ms
        try:
            if process_delete_wish(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 删除 wish 指令已处理')
        except Exception as e:
            _log(f'delete_wish error: {e}')
        return

        pk_topic = parse_delete_topic_seqs(text)
        if pk_topic is not None:
            _agent_dbg(
                'H4', 'skill_router.push', 'delete_topic_branch',
                msg_id=msg_id, cid=msg_cid, seqs=pk_topic, text_preview=(text or '')[:80],
            )
            seq_key = '|'.join(sorted(map(str, pk_topic))) if pk_topic else ''
        delete_dedup_id = f'deltopic:{msg_cid}:{seq_key}'
        if delete_dedup_id in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(delete_dedup_id)
        key = (msg_cid, 'delete_topic', seq_key)
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            if process_delete_topic(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 删除选题指令已处理')
        except Exception as e:
            _log(f'delete_topic error: {e}')
        return

    pk_memo = parse_delete_memo_seqs(text)
    if pk_memo is not None:
        _agent_dbg(
            'H4', 'skill_router.push', 'delete_memo_branch',
            msg_id=msg_id, cid=msg_cid, seqs=pk_memo, text_preview=(text or '')[:80],
        )
        seq_key = '|'.join(sorted(map(str, pk_memo))) if pk_memo else ''
        delete_dedup_id = f'del:{msg_cid}:{seq_key}'
        if delete_dedup_id in memo_seen_ids:
            memo_seen_ids.add(msg_id)
            return
        memo_seen_ids.add(delete_dedup_id)
        key = (msg_cid, 'delete', seq_key)
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            if process_delete(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 删除备忘指令已处理')
        except Exception as e:
            _log(f'delete error: {e}')
        return

    if _RE_CLOSE_WISH.search(text):
        m_seq = re.search(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
        if m_seq:
            seq = m_seq.group(1)
            dedup = f'closewish:{msg_cid}:{seq}'
            if dedup in memo_seen_ids:
                memo_seen_ids.add(msg_id)
                return
            memo_seen_ids.add(dedup)
            key = (msg_cid, 'close_wish', seq)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
            _recent_cmd_ts[key] = now_ms
        try:
            if process_close_wish(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg):
                memo_seen_ids.add(msg_id)
                _log('push: 完成 wish 指令已处理')
        except Exception as e:
            _log(f'close_wish error: {e}')
        return

    if _RE_CLOSE.search(text):
        try:
            process_close(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            memo_seen_ids.add(msg_id)
            _log('push: 完成指令已处理')
        except Exception as e:
            _log(f'close error: {e}')
        return

    # 「愿望单」优先于「愿望」单字触发，避免误收录
    if '愿望单' in text:
        key = (msg_cid, 'wish_list')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_wish_list(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 愿望单列表已打印并推送')
        except Exception as e:
            _log(f'wish_list error: {e}')
        return

    if _text_triggers_new_wish(text, memo_cfg):
        ck = wish_content_key(text)
        if ck:
            wish_dedup = 'wish_c:' + ck
            if wish_dedup in memo_seen_ids:
                memo_seen_ids.add(msg_id)
                return
            wkey = (msg_cid, ck)
            if now_ms - _recent_memo_ts.get(wkey, 0) < _RECENT_CMD_MS:
                memo_seen_ids.add(msg_id)
                return
        try:
            result = process_wish(msg_id=msg_id, text=text, group_cid=msg_cid, config=memo_cfg)
            if result is not None:
                memo_seen_ids.add(msg_id)
                if ck:
                    memo_seen_ids.add('wish_c:' + ck)
                    _recent_memo_ts[(msg_cid, ck)] = now_ms
                _log('push: 愿望已收录 TaskReminder')
        except Exception as e:
            _log(f'wish error: {e}')
        return

    if topic_library_match_text(text, memo_cfg):
        key = (msg_cid, 'topic_library')
        if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
            memo_seen_ids.add(msg_id)
            return
        _recent_cmd_ts[key] = now_ms
        try:
            process_topic_library(memo_cfg, group_cid=msg_cid)
            memo_seen_ids.add(msg_id)
            _log('push: 选题库已推送')
        except Exception as e:
            _log(f'topic_library error: {e}')
        return

    try:
        if _text_triggers_topic_pick(text, memo_cfg):
            _tck_dbg = topic_pick_content_key(text)
            _tid_dbg = ('topic_c:' + _tck_dbg) if _tck_dbg else ''
            _agent_dbg(
                'H1', 'skill_router.push', 'before_process_topic_pick',
                msg_id=msg_id, cid=msg_cid, tck=_tck_dbg,
                topic_c_in_seen=(_tid_dbg in memo_seen_ids) if _tid_dbg else None,
            )
        memo_ts_push = int(msg.get('ts', 0) or 0)
        tp = process_topic_pick(
            msg_id=msg_id, text=text, context_msgs=[msg],
            memo_ts=memo_ts_push, group_cid=msg_cid, config=memo_cfg)
        if tp is not False:
            if tp is None:
                _log('push: 选题收录 TR 暂不可写')
            else:
                tck = topic_pick_content_key(text)
                if tck:
                    tid = 'topic_c:' + tck
                    if tid in memo_seen_ids:
                        memo_seen_ids.add(msg_id)
                        return
                    memo_seen_ids.add(tid)
                    _recent_memo_ts[(msg_cid, tck)] = now_ms
                memo_seen_ids.add(msg_id)
                _log('push: 选题已收录')
            return
    except Exception as e:
        _log(f'topic_pick error: {e}')

    if _RE_MEMO.search(text):
        if is_memo_processed(msg_id):
            memo_seen_ids.add(msg_id)
            return
        with _MEMO_INGEST_LOCK:
            content_key = _memo_content_key(text)
            if content_key:
                # 按内容去重：同一条备忘若被 Hook/轮询各触发一次（不同 msg_id），只处理一次
                content_dedup_id = 'memo_c:' + content_key
                if content_dedup_id in memo_seen_ids:
                    memo_seen_ids.add(msg_id)
                    return
                memo_seen_ids.add(content_dedup_id)
                key = (msg_cid, content_key)
                if now_ms - _recent_memo_ts.get(key, 0) < _RECENT_CMD_MS:
                    memo_seen_ids.add(msg_id)
                    return
                _recent_memo_ts[key] = now_ms
        try:
            memo_ts = int(msg.get('ts', 0))
            result = process_memo(
                msg_id=msg_id, text=text,
                context_msgs=[msg], memo_ts=memo_ts,
                group_cid=msg_cid, config=memo_cfg,
            )
            if result is not None:
                memo_seen_ids.add(msg_id)
                _log('push: 备忘已收录')
        except Exception as e:
            _log(f'memo error: {e}')


def _poll_memo_once(group_cid: str, memo_cfg: dict, seen_ids: set,
                    router_start_ms: int = 0):
    """轮询助理通知群, 处理备忘/完成指令（JSAPI 不可用时自动降级到 beacon 日志）。

    router_start_ms：仅处理不早于本次 router 启动的消息（重启后不追溯）。
    """
    messages = _fetch_memo_messages(group_cid, max_age_ms=_MEMO_MAX_AGE_MS)
    if os.environ.get('SKILL_ROUTER_MEMO_POLL_TRACE', '').strip() == '1':
        _log(f'memo poll trace cid={group_cid} fetched_messages={len(messages)}')
    now_ms = int(time.time() * 1000)

    for msg in messages:
        text = _normalize_command_text(_extract_message_text(msg))
        if not text:
            continue

        msg_ts = int(msg.get('ts') or 0)
        if _skip_msg_before_router_start(msg, router_start_ms):
            continue
        if msg_ts and (now_ms - msg_ts) > _MEMO_MAX_AGE_MS:
            continue

        msg_id = _make_msg_id(msg)
        if not msg_id or msg_id in seen_ids:
            continue

        if not _assistant_group_skill_sender_allowed(memo_cfg, group_cid, _message_sender_identity(msg)):
            seen_ids.add(msg_id)
            continue

        if _RE_MORNING.match(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 上班啦 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            try:
                webhook_url = memo_cfg.get('webhook_url', '')
                if webhook_url and run_status_check_and_send(webhook_url):
                    _log('poll: 上班啦 -> 已执行状态检查并推送')
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'morning status_check error: {e}')
            continue

        if _RE_VERSION_DIGEST.match(text):
            if _is_stale_command_msg(msg, now_ms, _MORNING_CMD_MAX_AGE_MS):
                seen_ids.add(msg_id)
                _log('poll: 版本咋样了 -> 跳过（超出有效时间窗或时间戳无效）')
                continue
            key = (str(group_cid), 'version_digest')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                r = run_version_digest_send(send_webhook=True, log_to_stdout=False)
                seen_ids.add(msg_id)
                if r.get('ok'):
                    _log('poll: 版本咋样了 -> version_digest 已推送')
                else:
                    _log(f'poll: 版本咋样了 -> 未成功 ({r.get("error")})')
            except Exception as e:
                seen_ids.add(msg_id)
                _log(f'version_digest error: {e}')
            continue

        if _RE_DELETE_WISH.search(text):
            m_seq = re.search(r'删除\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
            if m_seq:
                seq = m_seq.group(1)
                delete_dedup_id = f'delwish:{str(group_cid).strip()}:{seq}'
                if delete_dedup_id in seen_ids:
                    seen_ids.add(msg_id)
                    continue
                seen_ids.add(delete_dedup_id)
                key = (str(group_cid), 'delete_wish', seq)
                if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_cmd_ts[key] = now_ms
            try:
                if process_delete_wish(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'delete_wish error: {e}')
            continue

        pk_topic = parse_delete_topic_seqs(text)
        if pk_topic is not None:
            _agent_dbg(
                'H4', 'skill_router.poll', 'delete_topic_branch',
                msg_id=msg_id, cid=str(group_cid), seqs=pk_topic, text_preview=(text or '')[:80],
            )
            gc = str(group_cid).strip()
            seq_key = '|'.join(sorted(map(str, pk_topic))) if pk_topic else ''
            delete_dedup_id = f'deltopic:{gc}:{seq_key}'
            if delete_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(delete_dedup_id)
            key = (gc, 'delete_topic', seq_key)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                if process_delete_topic(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'delete_topic error: {e}')
            continue

        pk_memo = parse_delete_memo_seqs(text)
        if pk_memo is not None:
            _agent_dbg(
                'H4', 'skill_router.poll', 'delete_memo_branch',
                msg_id=msg_id, cid=str(group_cid), seqs=pk_memo, text_preview=(text or '')[:80],
            )
            gc = str(group_cid).strip()
            seq_key = '|'.join(sorted(map(str, pk_memo))) if pk_memo else ''
            delete_dedup_id = f'del:{gc}:{seq_key}'
            if delete_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(delete_dedup_id)
            key = (gc, 'delete', seq_key)
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                if process_delete(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'delete error: {e}')
            continue

        if _RE_TODAY_FOCUS.search(text):
            gc = str(group_cid).strip()
            key = (gc, 'today_focus')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_today_focus(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'today_focus error: {e}')
            continue

        if _RE_TOMORROW_FOCUS.search(text):
            gc = str(group_cid).strip()
            key = (gc, 'tomorrow_focus')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_tomorrow_focus(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'tomorrow_focus error: {e}')
            continue

        if _RE_WEEK_FOCUS.search(text):
            gc = str(group_cid).strip()
            key = (gc, 'week_focus')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_FOCUS_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_week_focus(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'week_focus error: {e}')
            continue

        pdef = parse_defer_memo_command(text)
        if pdef is not None:
            seqs, due_d = pdef
            defer_dedup_id = f'def:{str(group_cid).strip()}:{due_d or "nodate"}:{"|".join(sorted(map(str, seqs)))}'
            if defer_dedup_id in seen_ids:
                seen_ids.add(msg_id)
                continue
            seen_ids.add(defer_dedup_id)
            key = (str(group_cid), 'defer', tuple(seqs), due_d or '')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_defer_memo(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'defer_memo error: {e}')
            continue

        _poll_edit_handled = False
        for _edit_fn in (
            process_topic_edit_description,
            process_memo_edit_description,
            process_memo_edit_version,
            process_memo_assign_tr,
        ):
            try:
                if _edit_fn(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
                    _log('poll: 备忘/选题快捷指令已处理')
                    _poll_edit_handled = True
                    break
            except Exception as e:
                _log(f'memo quick-edit {_edit_fn.__name__} error: {e}')
        if _poll_edit_handled:
            continue

        try:
            if process_desk_ops(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                seen_ids.add(msg_id)
                _log('poll: 桌面运维指令')
                continue
        except Exception as e:
            _log(f'desk_ops error: {e}')

        with _MEMO_THROTTLE_LOCK:
            kw_pl = person_lookup_match_keyword(text, memo_cfg)
            if kw_pl is not None:
                pl_key = (str(group_cid).strip(), 'person_lookup', kw_pl)
                if now_ms - _recent_cmd_ts.get(pl_key, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_cmd_ts[pl_key] = now_ms
        try:
            if process_person_lookup(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                seen_ids.add(msg_id)
                _log('poll: 人员关键词筛选（备忘+愿望）')
                continue
        except Exception as e:
            _log(f'person_lookup error: {e}')

        if _RE_CLOSE_WISH.search(text):
            m_seq = re.search(r'(?:完成|关闭)\s*(?:wish|愿望)\s*#?\s*(\d+)', text, re.IGNORECASE)
            if m_seq:
                key = (str(group_cid), 'close_wish', m_seq.group(1))
                if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_cmd_ts[key] = now_ms
            try:
                if process_close_wish(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg):
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'close_wish error: {e}')
            continue

        if _RE_CLOSE.search(text):
            try:
                process_close(msg_id=msg_id, text=text,
                              group_cid=group_cid, config=memo_cfg)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'close error: {e}')
            continue

        if '愿望单' in text:
            key = (str(group_cid), 'wish_list')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_wish_list(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'wish_list error: {e}')
            continue

        if _text_triggers_new_wish(text, memo_cfg):
            ck = wish_content_key(text)
            if ck:
                wish_dedup = 'wish_c:' + ck
                if wish_dedup in seen_ids:
                    seen_ids.add(msg_id)
                    continue
                seen_ids.add(wish_dedup)
                wkey = (str(group_cid), ck)
                if now_ms - _recent_memo_ts.get(wkey, 0) < _RECENT_CMD_MS:
                    seen_ids.add(msg_id)
                    continue
                _recent_memo_ts[wkey] = now_ms
            try:
                result = process_wish(msg_id=msg_id, text=text, group_cid=group_cid, config=memo_cfg)
                if result is not None:
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'wish error: {e}')
            continue

        if topic_library_match_text(text, memo_cfg):
            key = (str(group_cid), 'topic_library')
            if now_ms - _recent_cmd_ts.get(key, 0) < _RECENT_CMD_MS:
                seen_ids.add(msg_id)
                continue
            _recent_cmd_ts[key] = now_ms
            try:
                process_topic_library(memo_cfg, group_cid=group_cid)
                seen_ids.add(msg_id)
                _log('poll: 选题库已推送')
            except Exception as e:
                _log(f'topic_library error: {e}')
            continue

        try:
            if _text_triggers_topic_pick(text, memo_cfg):
                _tck_p = topic_pick_content_key(text)
                _tid_p = ('topic_c:' + _tck_p) if _tck_p else ''
                _agent_dbg(
                    'H1', 'skill_router.poll', 'before_process_topic_pick',
                    msg_id=msg_id, cid=str(group_cid), tck=_tck_p,
                    topic_c_in_seen=(_tid_p in seen_ids) if _tid_p else None,
                )
            memo_ts_poll = int(msg.get('ts', 0) or 0)
            tp = process_topic_pick(
                msg_id=msg_id, text=text, context_msgs=messages,
                memo_ts=memo_ts_poll, group_cid=group_cid, config=memo_cfg)
            if tp is not False:
                if tp is None:
                    _log('poll: 选题收录 TR 暂不可写')
                else:
                    tck = topic_pick_content_key(text)
                    if tck:
                        tid = 'topic_c:' + tck
                        if tid in seen_ids:
                            seen_ids.add(msg_id)
                            continue
                        seen_ids.add(tid)
                        _recent_memo_ts[(str(group_cid), tck)] = now_ms
                    seen_ids.add(msg_id)
                    _log('poll: 选题已收录')
                continue
        except Exception as e:
            _log(f'topic_pick error: {e}')

        if _RE_MEMO.search(text):
            if is_memo_processed(msg_id):
                seen_ids.add(msg_id)
                continue
            with _MEMO_INGEST_LOCK:
                content_key = _memo_content_key(text)
                if content_key:
                    content_dedup_id = 'memo_c:' + content_key
                    if content_dedup_id in seen_ids:
                        seen_ids.add(msg_id)
                        continue
                    seen_ids.add(content_dedup_id)
                    key = (str(group_cid), content_key)
                    if now_ms - _recent_memo_ts.get(key, 0) < _RECENT_CMD_MS:
                        seen_ids.add(msg_id)
                        continue
                    _recent_memo_ts[key] = now_ms
            try:
                memo_ts = int(msg.get('ts', 0))
                result = process_memo(
                    msg_id=msg_id, text=text,
                    context_msgs=messages, memo_ts=memo_ts,
                    group_cid=group_cid, config=memo_cfg,
                )
                if result is not None:
                    seen_ids.add(msg_id)
            except Exception as e:
                _log(f'memo error: {e}')
            continue


def _maybe_sync_tr_local(memo_cfg: dict) -> None:
    global _last_tr_sync_ms
    if not (memo_cfg or {}).get('task_reminder_base', '').strip():
        return
    now_ms = int(time.time() * 1000)
    if now_ms - _last_tr_sync_ms < _TR_SYNC_INTERVAL_MS:
        return
    _last_tr_sync_ms = now_ms
    try:
        stats = sync_tr_state_to_local_memos_wishes(memo_cfg)
        n = sum(stats.values())
        if n:
            _log(f'TR<->local sync {stats}')
    except Exception as e:
        _log(f'TR sync error: {e}')


def _send_notify(text: str, webhook_url: str):
    """轻量 webhook 通知（用于路由层的边界情况提示）"""
    if not webhook_url:
        return
    payload = json.dumps({
        'msgtype': 'text',
        'text': {'content': text},
    }).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception as e:
        _log(f'notify webhook failed: {e}')


def _poll_doc_review_once(group_cid: str, doc_cfg: dict, seen_ids: set,
                          router_start_ms: int = 0, memo_cfg: dict = None):
    """轮询助理通知群，检测'预审'指令，回溯找最近的文档链接后启动预审。

    触发条件：用户先发文档链接（消息A），再发'预审'（消息B）。
    以消息B的 msg_id 做去重 key。
    router_start_ms：仅处理不早于本次 router 启动的预审指令（重启后不追溯）。
    """
    messages = _fetch_memo_messages(group_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS)
    now_ms = int(time.time() * 1000)
    webhook_url = doc_cfg.get('webhook_url', '')

    msgs_by_ts = sorted(messages, key=lambda m: int(m.get('ts', 0)))

    for i, msg in enumerate(msgs_by_ts):
        text = _normalize_command_text(_extract_message_text(msg))
        if not text:
            continue

        if _skip_msg_before_router_start(msg, router_start_ms):
            continue

        if _is_stale_command_msg(msg, now_ms, _PRECHECK_CMD_MAX_AGE_MS):
            continue

        msg_id = _make_msg_id(msg)
        if not msg_id or msg_id in seen_ids:
            continue

        _mc = memo_cfg if memo_cfg is not None else {}
        if not _assistant_group_skill_sender_allowed(_mc, group_cid, _message_sender_identity(msg)):
            seen_ids.add(msg_id)
            continue

        if _RE_PRECHECK_STOP.match(text):
            if try_user_stop_doc_review(webhook_url):
                _log('poll: 预审已按用户指令叫停')
            else:
                send_no_active_doc_review_stop_reply(webhook_url)
            seen_ids.add(msg_id)
            continue

        _poll_is_precheck, _poll_force_precheck = _precheck_command_flags(text)
        if not _poll_is_precheck:
            continue

        if is_doc_review_processed(msg_id):
            seen_ids.add(msg_id)
            continue

        doc_url = None
        for j in range(i - 1, -1, -1):
            prev_msg = msgs_by_ts[j]
            url = extract_doc_url_from_message(prev_msg)
            if url:
                doc_url = url
                break

        if not doc_url:
            _log('收到预审指令，但未找到前序文档链接')
            _send_notify(get_doc_review_no_link_message(), webhook_url)
            seen_ids.add(msg_id)
            continue

        sender_uid = str(msg.get('uid', ''))
        _log(f'预审指令触发: {doc_url[:60]}... (uid={sender_uid})')

        try:
            result = process_doc_review(
                msg_id=msg_id,
                url=doc_url,
                sender_uid=sender_uid,
                msg_text=text,
                config=doc_cfg,
                force_bypass_recent_window=_poll_force_precheck,
            )
            seen_ids.add(msg_id)
            if result:
                _log(f'文档预审完成: {doc_url[:40]}...')
            else:
                _log(f'文档预审失败，已通知: {doc_url[:40]}...')
        except Exception as e:
            _log(f'doc_review error: {e}')
            seen_ids.add(msg_id)


class SkillRouter:
    def __init__(self):
        self._thread = None
        self._running = False
        self._seen_ids: set = set()
        self._memo_seen_ids: set = set()
        self._doc_seen_ids: set = set()
        # 在 start() 首行赋值；轮询与推送均不处理早于此时刻的消息
        self._start_ts: int = 0
        self._memo_poll_heartbeat_ms: int = 0

    def start(self, memo_event_queue=None):
        """启动后台轮询线程（由 daemon.py 调用）。

        memo_event_queue 非空时额外消费 Frida 推送（桌面会话内消息可立刻处理）。
        手机发的消息通常不会进该队列，仍依赖下方周期性的 _poll_memo_once(/fetch)，故**有队列时也继续轮询**。
        """
        self._start_ts = int(time.time() * 1000)
        init_db()
        _log('DB initialized')

        cfg = _load_config()
        recruit_cids = cfg['recruit_cids']
        cid_names    = cfg.get('cid_names', {})
        notify_cid   = cfg['notify_cid']
        memo_cfg     = cfg.get('memo_tracker', {})
        doc_review_cfg = cfg.get('doc_review', {})

        has_resume     = bool(recruit_cids)
        _allowed = _memo_allowed_cids(memo_cfg)
        has_memo       = bool(_allowed)
        has_doc_review = bool(doc_review_cfg.get('group_cid'))

        if has_resume:
            _log(f'resume watch: {recruit_cids}, notify: {notify_cid or "source group"}')
        if has_memo:
            _col = [x for x in (memo_cfg.get('colleague_skill_cids') or []) if str(x).strip()]
            _log(
                f'memo watch: assistant={memo_cfg.get("group_cid") or "?"} '
                f'colleague_whitelist={_col or "(empty)"}'
                + (' (push+poll)' if memo_event_queue else '')
            )
            _log(
                '说明: daemon 里「群聊←/→接收」是 Monitor 日志；备忘是否处理要看本线程每 '
                f'{POLL_INTERVAL}s 的 POST /fetch，无新指令时通常不再打日志。'
            )
            _log(
                '可选: 环境变量 SKILL_ROUTER_MEMO_POLL_TRACE=1 每次备忘拉取后打一行条数。'
            )
        if has_doc_review:
            _log(f'doc_review watch: {doc_review_cfg["group_cid"]}')
        if not has_resume and not has_memo and not has_doc_review:
            _log('no skills configured, router idle')
            return

        _log(f'poll interval: {POLL_INTERVAL}s')
        self._running = True
        self._memo_queue = memo_event_queue

        self._thread = threading.Thread(
            target=self._loop,
            args=(recruit_cids, cid_names, notify_cid, memo_cfg, doc_review_cfg),
            daemon=True,
        )
        self._thread.start()

        if memo_event_queue and _allowed:
            push_thread = threading.Thread(
                target=self._memo_push_loop,
                args=(memo_cfg, doc_review_cfg),
                daemon=True,
            )
            push_thread.start()
            _log('memo push consumer started')

    def stop(self):
        self._running = False

    def _memo_push_loop(self, memo_cfg: dict, doc_review_cfg: dict = None):
        """消费 daemon 推送的消息；cid 须在助理群或 colleague_skill_cids 白名单内。"""
        import queue as queue_module
        q = getattr(self, '_memo_queue', None)
        if not q:
            return
        while self._running:
            try:
                record = q.get(timeout=1.0)
            except queue_module.Empty:
                continue
            except Exception:
                break
            try:
                _dispatch_one_message(
                    record, memo_cfg, self._memo_seen_ids,
                    doc_review_cfg=doc_review_cfg, doc_seen_ids=self._doc_seen_ids,
                    router_start_ms=self._start_ts,
                )
            except Exception as e:
                _log(f'memo push dispatch error: {e}')

    def _loop(self, recruit_cids: list, cid_names: dict,
              notify_cid: str, memo_cfg: dict, doc_review_cfg: dict = None):
        while self._running:
            for cid in recruit_cids:
                source_name = cid_names.get(cid, '')
                try:
                    n = _poll_once(cid, notify_cid, self._seen_ids,
                                   source_name=source_name,
                                   start_ts=self._start_ts)
                    if n:
                        _log(f'[{source_name or cid}] processed {n} resumes')
                except Exception as e:
                    _log(f'resume poll [{source_name or cid}] error: {e}')

            # 有 Frida 推送队列时也必须轮询：手机/其他端发的消息往往只经 JSAPI 历史出现，不会入队
            _memo_cids = sorted(_memo_allowed_cids(memo_cfg))
            for _poll_cid in _memo_cids:
                try:
                    _poll_memo_once(
                        _poll_cid, memo_cfg, self._memo_seen_ids,
                        router_start_ms=self._start_ts,
                    )
                except Exception as e:
                    _log(f'memo poll [{_poll_cid}] error: {e}')
            if _memo_cids:
                try:
                    _hb_ms = int(os.environ.get('SKILL_ROUTER_POLL_HEARTBEAT_MS', '45000'))
                except ValueError:
                    _hb_ms = 45000
                if _hb_ms > 0:
                    _now_ms = int(time.time() * 1000)
                    if _now_ms - self._memo_poll_heartbeat_ms >= _hb_ms:
                        self._memo_poll_heartbeat_ms = _now_ms
                        _log(
                            'memo /fetch poll alive: cids=%s (每 %ds 一轮；'
                            '仅心跳日志；设 SKILL_ROUTER_POLL_HEARTBEAT_MS=0 可关闭)'
                            % (_memo_cids, POLL_INTERVAL)
                        )
            if _memo_cids:
                _maybe_sync_tr_local(memo_cfg)

            if doc_review_cfg and doc_review_cfg.get('group_cid'):
                try:
                    _poll_doc_review_once(
                        doc_review_cfg['group_cid'],
                        doc_review_cfg, self._doc_seen_ids,
                        router_start_ms=self._start_ts,
                        memo_cfg=memo_cfg,
                    )
                except Exception as e:
                    _log(f'doc_review poll error: {e}')

            time.sleep(POLL_INTERVAL)


# 单例
_router = SkillRouter()


def start_router(memo_event_queue=None):
    """供 daemon.py 调用的入口。memo_event_queue 非空时增加推送消费；备忘仍周期 /fetch 轮询（含手机消息）。"""
    _router.start(memo_event_queue)


if __name__ == '__main__':
    # 直接运行做单次测试
    init_db()
    recruit_cids = _load_recruit_cids()
    print('招聘群:', recruit_cids)
    seen: set = set()
    notify_cid = _load_config().get('notify_cid', '')
    for cid in recruit_cids:
        n = _poll_once(cid, notify_cid, seen)
        print(f'群 {cid} 处理 {n} 份')
