# -*- coding: utf-8 -*-
"""
技能路由器 — 后台轮询线程

当前支持：
  - 监听招聘群内 ct=502（PDF 文件消息）→ 触发简历 AI 初筛
  - 监听助理通知群文本消息 → 备忘录入 / 关闭

架构：
  - 启动时由 daemon.py 调用 SkillRouter.start()
  - 每 POLL_INTERVAL 秒向 daemon /fetch 查询各群的新消息
  - ct=502 且未处理过 → 交给 skills/resume_screen
  - 文本含"备忘"/"完成" → 交给 skills/memo_tracker
  - 通过 DB + 内存 seen_ids 实现幂等
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
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

from db.store import init_db, is_resume_processed, is_memo_processed, is_doc_review_processed
from skills.resume_screen import process_resume_message
from skills.memo_tracker import process_memo, process_close
from skills.doc_review import extract_doc_url, process_doc_review

DAEMON_URL    = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
POLL_INTERVAL = int(os.environ.get('SKILL_ROUTER_INTERVAL', '60'))   # 秒
_CONFIG_PATH  = os.path.join(_THIS_DIR, 'digest_config.json')
_LOG_FILE     = os.path.join(_THIS_DIR, 'data', 'dingtalk', '_msg_log.jsonl')


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
        if not doc_review_cfg.get('webhook_url'):
            doc_review_cfg['webhook_url'] = cfg.get('webhook_url', '')

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


def _fetch_recent_messages(cid: str, count: int = 20, timeout: int = 30) -> list:
    """调 daemon /fetch 获取群内最近消息"""
    payload = json.dumps({'cid': cid, 'count': count}).encode('utf-8')
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

        uid = m.get('uid') or ''
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
    messages = _fetch_recent_messages(cid, count=20, timeout=5)
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
    messages = _fetch_recent_messages(cid, count=20)
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
    return f'{ts}_{uid}' if (ts and uid) else None


def _extract_message_text(msg: dict) -> str:
    """统一提取消息文本，兼容纯文本(ct=1)与富文本(ct=3100)。"""
    ct = int(msg.get('content_type') or 0)
    if ct == 1:
        return (msg.get('text') or '').strip()
    if ct != 3100:
        return ''

    # 优先使用 daemon 已解析好的 text 字段
    text = (msg.get('text') or '').strip()

    # 兜底：从 raw.attachments[].extension.desc 合并富文本内容
    raw = msg.get('raw', '')
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


_RE_MEMO = re.compile(r'[\uff3b【\[]*(?:备忘|提醒我)[\uff3d】\]]*')
_RE_CLOSE = re.compile(r'(?:完成|关闭)\s*#?\d+')
_RE_PRECHECK = re.compile(r'^\s*预审[!！。.\s]*$')

_MEMO_MAX_AGE_MS       = 24 * 3600 * 1000   # 处理 24 小时内的备忘（beacon 日志兜底，seen_ids 保幂等）
_DOC_REVIEW_MAX_AGE_MS = 30 * 60 * 1000    # 预审指令保持 30 分钟窗口（避免误触发历史链接）


def _poll_memo_once(group_cid: str, memo_cfg: dict, seen_ids: set):
    """轮询助理通知群, 处理备忘/完成指令（JSAPI 不可用时自动降级到 beacon 日志）"""
    messages = _fetch_memo_messages(group_cid, max_age_ms=_MEMO_MAX_AGE_MS)
    now_ms = int(time.time() * 1000)

    for msg in messages:
        ct = int(msg.get('content_type') or 0)
        if ct not in (1, 3100):
            continue
        text = _extract_message_text(msg)
        if not text:
            continue

        msg_ts = msg.get('ts', 0)
        if msg_ts and (now_ms - msg_ts) > _MEMO_MAX_AGE_MS:
            continue

        msg_id = _make_msg_id(msg)
        if not msg_id or msg_id in seen_ids:
            continue

        if _RE_CLOSE.search(text):
            try:
                process_close(msg_id=msg_id, text=text,
                              group_cid=group_cid, config=memo_cfg)
                seen_ids.add(msg_id)
            except Exception as e:
                _log(f'close error: {e}')
            continue

        if _RE_MEMO.search(text):
            if is_memo_processed(msg_id):
                seen_ids.add(msg_id)
                continue
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


def _poll_doc_review_once(group_cid: str, doc_cfg: dict, seen_ids: set):
    """轮询助理通知群，检测'预审'指令，回溯找最近的文档链接后启动预审。

    触发条件：用户先发文档链接（消息A），再发'预审'（消息B）。
    以消息B的 msg_id 做去重 key。
    """
    messages = _fetch_memo_messages(group_cid, max_age_ms=_DOC_REVIEW_MAX_AGE_MS)
    now_ms = int(time.time() * 1000)
    webhook_url = doc_cfg.get('webhook_url', '')

    msgs_by_ts = sorted(messages, key=lambda m: int(m.get('ts', 0)))

    for i, msg in enumerate(msgs_by_ts):
        ct = int(msg.get('content_type') or 0)
        if ct not in (1, 3100):
            continue
        text = _extract_message_text(msg)
        if not text:
            continue

        msg_ts = int(msg.get('ts', 0))
        if msg_ts and (now_ms - msg_ts) > _DOC_REVIEW_MAX_AGE_MS:
            continue

        if not _RE_PRECHECK.match(text):
            continue

        msg_id = _make_msg_id(msg)
        if not msg_id or msg_id in seen_ids:
            continue
        if is_doc_review_processed(msg_id):
            seen_ids.add(msg_id)
            continue

        doc_url = None
        for j in range(i - 1, -1, -1):
            prev_msg = msgs_by_ts[j]
            prev_ct = int(prev_msg.get('content_type') or 0)
            if prev_ct not in (1, 3100):
                continue
            prev_text = _extract_message_text(prev_msg)
            if prev_text:
                url = extract_doc_url(prev_text)
                if url:
                    doc_url = url
                    break

        if not doc_url:
            _log('收到预审指令，但未找到前序文档链接')
            _send_notify(
                '小秘书提醒 收到预审指令，但未找到最近的文档链接。'
                '请先发送文档链接，再发送"预审"。',
                webhook_url,
            )
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
        # 本次启动时刻（毫秒），用于过滤"daemon 启动前已存在的消息"
        self._start_ts: int = int(time.time() * 1000)

    def start(self):
        """启动后台轮询线程（由 daemon.py 调用）"""
        init_db()
        _log('DB initialized')

        cfg = _load_config()
        recruit_cids = cfg['recruit_cids']
        cid_names    = cfg.get('cid_names', {})
        notify_cid   = cfg['notify_cid']
        memo_cfg     = cfg.get('memo_tracker', {})

        doc_review_cfg = cfg.get('doc_review', {})

        has_resume     = bool(recruit_cids)
        has_memo       = bool(memo_cfg.get('group_cid'))
        has_doc_review = bool(doc_review_cfg.get('group_cid'))

        if has_resume:
            _log(f'resume watch: {recruit_cids}, notify: {notify_cid or "source group"}')
        if has_memo:
            _log(f'memo watch: {memo_cfg["group_cid"]}')
        if has_doc_review:
            _log(f'doc_review watch: {doc_review_cfg["group_cid"]}')
        if not has_resume and not has_memo and not has_doc_review:
            _log('no skills configured, router idle')
            return

        _log(f'poll interval: {POLL_INTERVAL}s')
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(recruit_cids, cid_names, notify_cid, memo_cfg, doc_review_cfg),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._running = False

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

            if memo_cfg.get('group_cid'):
                try:
                    _poll_memo_once(memo_cfg['group_cid'], memo_cfg,
                                    self._memo_seen_ids)
                except Exception as e:
                    _log(f'memo poll error: {e}')

            if doc_review_cfg and doc_review_cfg.get('group_cid'):
                try:
                    _poll_doc_review_once(doc_review_cfg['group_cid'],
                                          doc_review_cfg, self._doc_seen_ids)
                except Exception as e:
                    _log(f'doc_review poll error: {e}')

            time.sleep(POLL_INTERVAL)


# 单例
_router = SkillRouter()


def start_router():
    """供 daemon.py 调用的入口"""
    _router.start()


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
