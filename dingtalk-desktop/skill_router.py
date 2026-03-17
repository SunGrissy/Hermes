# -*- coding: utf-8 -*-
"""
技能路由器 — 后台轮询线程

当前支持：
  - 监听招聘群内 ct=502（PDF 文件消息）→ 触发简历 AI 初筛

架构：
  - 启动时由 daemon.py 调用 SkillRouter.start()
  - 每 POLL_INTERVAL 秒向 daemon /fetch 查询各招聘群的新消息
  - ct=502 且未处理过 → 交给 skills/resume_screen.process_resume_message()
  - 通过 DB 的 is_resume_processed() 实现幂等，重启不重复处理
"""
import os
import sys
import json
import time
import threading
import urllib.request
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

from db.store import init_db, is_resume_processed
from skills.resume_screen import process_resume_message

DAEMON_URL    = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
POLL_INTERVAL = int(os.environ.get('SKILL_ROUTER_INTERVAL', '60'))   # 秒
_CONFIG_PATH  = os.path.join(_THIS_DIR, 'digest_config.json')


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[skill_router][{ts}] {msg}', flush=True)


def _load_config() -> dict:
    """从 digest_config.json 读取 recruit_cids 和 notify_target"""
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        recruit_cids = cfg.get('recruit_cids', [])
        cids = [c if isinstance(c, str) else c.get('cid', '') for c in recruit_cids if c]
        notify_cid = cfg.get('notify_target', '')
        return {'recruit_cids': cids, 'notify_cid': notify_cid}
    except Exception as e:
        _log(f'加载配置失败: {e}')
        return {'recruit_cids': [], 'notify_cid': ''}


def _fetch_recent_messages(cid: str, count: int = 20) -> list:
    """调 daemon /fetch 获取群内最近消息"""
    payload = json.dumps({'cid': cid, 'count': count}).encode('utf-8')
    req = urllib.request.Request(
        DAEMON_URL.rstrip('/') + '/fetch',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get('messages', [])
    except Exception as e:
        _log(f'fetch {cid} 失败: {e}')
        return []


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


def _poll_once(cid: str, notify_cid: str, seen_ids: set):
    """轮询一个招聘群，处理所有新的 ct=502 消息。
    结果发到 notify_cid（助理通知群），而非原招聘群。
    """
    messages = _fetch_recent_messages(cid, count=20)
    processed_count = 0

    for msg in messages:
        if msg.get('content_type') != 502:
            continue

        msg_id, file_name, file_path = _extract_file_info(msg)
        if not msg_id:
            continue

        if file_name and not file_name.lower().endswith('.pdf'):
            continue

        if msg_id in seen_ids or is_resume_processed(msg_id):
            continue
        seen_ids.add(msg_id)

        sender_uid = str(msg.get('uid', ''))
        reply_cid = notify_cid or cid
        _log(f'发现新简历: {file_name} (uid={sender_uid}) → 结果发到 {reply_cid}')

        try:
            ok = process_resume_message(
                msg_id=msg_id,
                group_cid=reply_cid,
                sender_uid=sender_uid,
                file_name=file_name,
                file_path=file_path,
            )
            if ok:
                processed_count += 1
                _log(f'处理完成: {file_name}')
        except Exception as e:
            _log(f'处理失败 {file_name}: {e}')

    return processed_count


class SkillRouter:
    def __init__(self):
        self._thread = None
        self._running = False
        self._seen_ids: set = set()   # 内存去重，防止非通过简历被反复调 LLM

    def start(self):
        """启动后台轮询线程（由 daemon.py 调用）"""
        init_db()
        _log('DB 已初始化')

        cfg = _load_config()
        recruit_cids = cfg['recruit_cids']
        notify_cid   = cfg['notify_cid']
        if not recruit_cids:
            _log('digest_config.json 中无 recruit_cids，简历监听未启动')
            return

        _log(f'简历监听启动，监听群: {recruit_cids}，结果发到: {notify_cid or "原群"}，轮询间隔: {POLL_INTERVAL}s')
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, args=(recruit_cids, notify_cid), daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self, recruit_cids: list, notify_cid: str):
        while self._running:
            for cid in recruit_cids:
                try:
                    n = _poll_once(cid, notify_cid, self._seen_ids)
                    if n:
                        _log(f'群 {cid} 本轮处理 {n} 份简历')
                except Exception as e:
                    _log(f'轮询群 {cid} 异常: {e}')
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
