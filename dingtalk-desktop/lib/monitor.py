# -*- coding: utf-8 -*-
"""
钉钉消息监听器 — Hook OnRecvRequest + ProcessPush + ProcessRequest 实现收发双向监听
重构自 _msg_monitor.py
"""
import os
import sys
import time
import json

from .utils import (
    get_main_pid, deep_decode, DedupTracker, toast_async,
    fmt_time, CT_NAMES, DATA_DIR, DEFAULT_MY_UID,
    FRIDA_READSTDSTR_JS, FRIDA_FIND_EXPORT_JS,
    ContactsDB,
)

# --------------- Frida Hook 脚本 ---------------

_MONITOR_JS = (
    "'use strict';\n"
    + FRIDA_FIND_EXPORT_JS
    + FRIDA_READSTDSTR_JS
    + r"""
var bodyFn = new NativeFunction(
    findExport("libgaea.dll", "?body@Message@lwp@gaea@@QEAAAEBV"), 'pointer', ['pointer']);

// Hook 1: OnRecvRequest
var addrRecv = findExport("libgaea.dll", "OnRecvRequest@PushListenerBase@lwp@wukong");
Interceptor.attach(addrRecv, {
    onEnter: function(a) {
        try {
            var req = a[1].readPointer();
            if (!req || req.isNull()) return;
            var bs = bodyFn(req);
            if (!bs) return;
            var d = readStdStr(bs);
            if (d && d.byteLength > 5) send({src: 'recv'}, d);
        } catch(e) {}
    }
});

// Hook 2: ProcessPush
var addrPush = findExport("libgaea.dll", "ProcessPush@MessageFilter@lwp@gaea");
if (addrPush) {
    Interceptor.attach(addrPush, {
        onEnter: function(a) {
            try {
                var sp = a[1];
                if (!sp || sp.isNull()) return;
                var msgPtr = sp.readPointer();
                if (!msgPtr || msgPtr.isNull()) return;
                var bs = bodyFn(msgPtr);
                if (!bs) return;
                var d = readStdStr(bs);
                if (d && d.byteLength > 5) send({src: 'push'}, d);
            } catch(e) {}
        }
    });
}

// Hook 3: ProcessRequest (捕获自己发出的请求)
var reqLineFn = new NativeFunction(
    findExport("libgaea.dll", "?request_line@Request@lwp@gaea"), 'pointer', ['pointer']);
var addrReq = findExport("libgaea.dll", "ProcessRequest@MessageFilter@lwp@gaea");
if (addrReq) {
    Interceptor.attach(addrReq, {
        onEnter: function(a) {
            try {
                var sp = a[1];
                if (!sp || sp.isNull()) return;
                var reqPtr = sp.readPointer();
                if (!reqPtr || reqPtr.isNull()) return;
                var rlPtr = reqLineFn(reqPtr);
                var rl = rlPtr ? readStdStr(rlPtr) : null;
                var rlStr = '';
                if (rl) {
                    try { rlStr = new TextDecoder().decode(rl); } catch(e) { rlStr = ''; }
                }
                var bs = bodyFn(reqPtr);
                if (!bs) return;
                var d = readStdStr(bs);
                if (d && d.byteLength > 5) send({src: 'send', uri: rlStr}, d);
            } catch(e) {}
        }
    });
}

var hookCount = 1 + (addrPush ? 1 : 0) + (addrReq ? 1 : 0);
send({ready: true, hooks: hookCount});
""")

# --------------- 消息处理 ---------------

def _display_and_log(cid, sender, ts, msg_id, ct, text, encrypted,
                     source, my_uid, log_path, enable_toast=False,
                     ext_keys=None, md_extra=None, card_ext=None):
    """统一的消息显示和日志记录"""
    from datetime import datetime
    ct_name = CT_NAMES.get(ct, f'type_{ct}')
    is_p2p = ':' in cid and not cid.startswith('cid')
    tag = 'P2P' if is_p2p else '群聊'
    is_self = (sender == my_uid) or (source == 'send')
    direction = '→ 发送' if is_self else '← 接收'
    time_str = fmt_time(ts) if ts else datetime.now().strftime('%H:%M:%S')
    enc_icon = ' 🔒' if encrypted else ''
    self_tag = ' [我]' if is_self else ''

    print(f"  {time_str} [{tag}]{enc_icon} {direction} {sender}{self_tag} ({ct_name})",
          flush=True)
    if text:
        lines = text.split('\n')
        for line in lines[:3]:
            print(f"    {line[:120]}", flush=True)
        if len(lines) > 3:
            print(f"    ...({len(lines)}行)", flush=True)
    elif encrypted:
        print(f"    [加密消息, 无origin_text]", flush=True)
    print(flush=True)

    if enable_toast:
        toast_title = f"{'📤' if is_self else '📩'} {sender}{self_tag} [{tag}]"
        toast_body = text[:150] if text else f"[{ct_name}]"
        toast_async(toast_title, toast_body)

    try:
        resolved = ContactsDB.update(cid, sender, my_uid, is_self)
        if resolved and resolved != sender:
            sender = resolved
    except Exception:
        pass

    record = {
        'time': time_str, 'ts': ts, 'msg_id': msg_id,
        'tag': tag, 'cid': cid, 'sender': sender,
        'is_self': is_self, 'direction': direction,
        'content_type': ct, 'content_type_name': ct_name,
        'encrypted': encrypted, 'text': text[:500] if text else '',
        'ext_keys': ext_keys or [],
        'source': source,
    }
    if md_extra:
        record['md_extra'] = md_extra
    if card_ext:
        record['card_ext'] = card_ext
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')


def _process_push(data, source, dedup, my_uid, log_path, enable_toast, memo_callback=None):
    """处理接收到的推送消息。memo_callback(record) 若提供，则对每条 record 调用（用于助理群秒级技能路由）。"""
    import msgpack
    try:
        unpacker = msgpack.Unpacker(raw=True, strict_map_key=False)
        unpacker.feed(data)
        for raw_obj in unpacker:
            decoded = deep_decode(raw_obj)
            if not isinstance(decoded, dict):
                continue
            outer = decoded.get(1, {})
            if not isinstance(outer, dict):
                continue
            items = outer.get(6, [])
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                cmd = item.get(1, 0)
                payload = item.get(2, {})
                if cmd != 1000 or not isinstance(payload, dict):
                    continue

                md = payload.get(1, {})
                if not isinstance(md, dict):
                    continue

                cid = str(md.get(2, ''))
                sender = str(md.get(24, ''))
                ts = md.get(6, 0)
                msg_id = md.get(4, 0)

                if dedup.is_seen((cid, msg_id, ts)):
                    continue

                co = md.get(7, {})
                ct = co.get(1, 0) if isinstance(co, dict) else 0

                ext = md.get(9, {}) if isinstance(md.get(9), dict) else {}
                origin_text = str(ext.get('origin_text', ''))
                card_text = str(ext.get('interactiveCardLastMessage', ''))

                raw_content = ''
                if isinstance(co, dict):
                    cd = co.get(2, {})
                    if isinstance(cd, dict):
                        raw_content = str(cd.get(1, ''))
                    elif isinstance(cd, str):
                        raw_content = cd

                encrypted = '||' in raw_content
                text = origin_text or card_text or (raw_content if not encrypted else '')

                # ct=3100 富文本：origin_text 常为空，从 raw JSON 的 attachments[].extension.desc 合并
                if ct == 3100 and raw_content and not encrypted:
                    try:
                        rd = json.loads(raw_content) if isinstance(raw_content, str) else None
                        if isinstance(rd, dict):
                            descs = []
                            for att in (rd.get('attachments') or []):
                                extn = att.get('extension') or {}
                                desc = (extn.get('desc') or '').strip()
                                if desc and desc not in descs:
                                    descs.append(desc)
                            if descs:
                                merged = '\n'.join(descs).strip()
                                if not text or len(merged) > len(text):
                                    text = merged
                    except Exception:
                        pass

                if not text and ct == 300 and isinstance(co, dict):
                    try:
                        cards = co.get(7, [])
                        if isinstance(cards, list) and cards:
                            card = cards[0]
                            body = (card.get(6) or card.get('6') or {}) if isinstance(card, dict) else {}
                            if isinstance(body, dict):
                                b_form = body.get('b_form', [])
                                b_tl = body.get('b_tl', '日报')
                                if isinstance(b_form, list) and b_form:
                                    parts = []
                                    for item in b_form:
                                        if isinstance(item, dict):
                                            k = item.get('k', '')
                                            v = item.get('v', '')
                                            if v:
                                                parts.append(f'{k}: {v}')
                                    text = f'{b_tl} | ' + ' | '.join(parts) if parts else b_tl
                    except Exception:
                        pass

                md_keys = sorted([k for k in md.keys() if k not in (2, 4, 6, 7, 9, 24)])
                md_extra = {}
                for mk in md_keys:
                    v = md.get(mk)
                    if isinstance(v, (str, int, float, bool)):
                        md_extra[mk] = v
                    elif isinstance(v, bytes):
                        md_extra[mk] = v.decode('utf-8', errors='replace')[:200]
                    elif isinstance(v, dict):
                        md_extra[mk] = {str(kk): str(vv)[:100] for kk, vv in list(v.items())[:5]}

                ext_data = list(ext.keys()) if ext else []
                card_ext = None
                if ct == 2950 and ext:
                    card_ext = {}
                    for ck in ('biz_custom_desc', 'biz_custom_title',
                               'biz_custom_action_url', 'biz_custom_action_name',
                               'interactiveCardLastMessage', 'cardInstanceId'):
                        cv = ext.get(ck)
                        if cv:
                            card_ext[ck] = str(cv)[:2000]

                _display_and_log(
                    cid, sender, ts, msg_id, ct, text, encrypted,
                    source, my_uid, log_path, enable_toast,
                    ext_data,
                    md_extra=md_extra,
                    card_ext=card_ext,
                )
                if memo_callback and callable(memo_callback):
                    try:
                        # 自己发的消息已由 ProcessRequest(send) 入队；push 回显再入队会触发两遍技能
                        if str(sender).strip() == str(my_uid).strip():
                            pass
                        else:
                            rec = {
                                'cid': cid, 'uid': sender, 'ts': ts, 'msg_id': msg_id,
                                'content_type': ct, 'text': (text or '')[:500], 'raw': '',
                                'md_extra': md_extra,
                            }
                            memo_callback(rec)
                    except Exception:
                        pass
    except Exception as e:
        print(f"  [解码错误] {e}", flush=True)


_RE_ALIDOCS = __import__('re').compile(
    r'https?://alidocs\.dingtalk\.com/i/nodes/[^\s\]>)\u3001\u3002\uff0c"\']*'
)


def _find_alidocs_in_obj(obj, seen=None):
    """递归从 dict/list 中找第一个 alidocs URL 字符串，供文档卡片等无 origin_text 时用。"""
    if seen is None:
        seen = set()
    if id(obj) in seen:
        return None
    if isinstance(obj, str):
        m = _RE_ALIDOCS.search(obj)
        if m:
            return m.group(0)
        if 'alidocs.dingtalk.com' in obj:
            return obj.strip()
        return None
    if isinstance(obj, dict):
        seen.add(id(obj))
        for v in obj.values():
            u = _find_alidocs_in_obj(v, seen)
            if u:
                return u
        return None
    if isinstance(obj, (list, tuple)):
        seen.add(id(obj))
        for v in obj:
            u = _find_alidocs_in_obj(v, seen)
            if u:
                return u
        return None
    return None


def _process_send(data, uri, dedup, my_uid, log_path, enable_toast, memo_callback=None):
    """处理发出的请求消息。若提供 memo_callback，则对助理群内的发送也调用（仅处理「我」在助理群发的指令）。"""
    import msgpack
    import time
    try:
        decoded = deep_decode(
            msgpack.unpackb(data, raw=True, strict_map_key=False))
        if not isinstance(decoded, dict):
            return

        cid = str(decoded.get(2, ''))
        if not cid:
            return

        ext = decoded.get(7, {}) if isinstance(decoded.get(7), dict) else {}
        origin_text = str(ext.get('origin_text', ''))

        sender = str(decoded.get(8, my_uid))
        co = decoded.get(5, {})
        ct = co.get(1, 0) if isinstance(co, dict) else 0

        raw_content = ''
        if isinstance(co, dict):
            cd = co.get(2, {})
            if isinstance(cd, dict):
                raw_content = str(cd.get(1, ''))
            elif isinstance(cd, str):
                raw_content = cd
        encrypted = '||' in raw_content
        # 自己发送的富文本：origin_text 常为空，从 raw 合并 desc（与 ProcessPush 一致）
        if ct == 3100 and raw_content and not encrypted:
            try:
                rd = json.loads(raw_content) if isinstance(raw_content, str) else None
                if isinstance(rd, dict):
                    descs = []
                    for att in (rd.get('attachments') or []):
                        extn = att.get('extension') or {}
                        desc = (extn.get('desc') or '').strip()
                        if desc and desc not in descs:
                            descs.append(desc)
                    if descs:
                        merged = '\n'.join(descs).strip()
                        if not origin_text or len(merged) > len(origin_text):
                            origin_text = merged
            except Exception:
                pass

        # 文档卡片等可能无 origin_text，从整包中提取 alidocs URL 以便预审回溯能找到
        if not origin_text:
            origin_text = _find_alidocs_in_obj(decoded) or ''
        if not origin_text:
            return

        # 归一化后再去重，避免同一句因首尾/中间空格差异被 Hook 触发两次时重复入队
        origin_for_dedup = ' '.join(origin_text.strip().split())[:80]
        if dedup.is_seen(('send', cid, origin_for_dedup)):
            return

        _display_and_log(
            cid, sender, 0, 0, ct, origin_text, False,
            'send', my_uid, log_path, enable_toast,
            list(ext.keys()) if ext else [],
        )
        if memo_callback and callable(memo_callback):
            try:
                ts_ms = int(time.time() * 1000)
                rec = {
                    'cid': cid, 'uid': sender, 'ts': ts_ms,
                    'msg_id': f'{ts_ms}_{sender}',
                    'content_type': ct, 'text': (origin_text or '')[:500], 'raw': '',
                    'md_extra': {},
                }
                memo_callback(rec)
            except Exception:
                pass
    except Exception:
        pass

# --------------- MessageMonitor 类 ---------------

class MessageMonitor:
    """钉钉消息监听器，封装 Frida Hook 的完整生命周期"""

    def __init__(self, my_uid=None, enable_toast=False,
                 log_file=None):
        self._my_uid = my_uid or DEFAULT_MY_UID
        self._enable_toast = enable_toast
        self._log_path = log_file or os.path.join(DATA_DIR, '_msg_log.jsonl')
        self._dedup = DedupTracker()
        self._session = None
        self._script = None

    @property
    def log_path(self):
        return self._log_path

    def start(self, pid=None):
        """
        启动监听。阻塞直到 Ctrl+C。

        Args:
            pid: 钉钉主进程 PID，为 None 则自动检测
        """
        import frida

        if pid is None:
            pid = get_main_pid()
        if not pid:
            print("找不到 DingTalk 主进程!", flush=True)
            sys.exit(1)

        print(f"┌──────────────────────────────────────┐", flush=True)
        print(f"│   DingTalk 消息监听器                │", flush=True)
        print(f"│   PID: {pid:<30}│", flush=True)
        print(f"│   Hook: OnRecvRequest + ProcessPush  │", flush=True)
        print(f"│   收发双向监听 + 自动去重            │", flush=True)
        print(f"│   按 Ctrl+C 停止                     │", flush=True)
        print(f"└──────────────────────────────────────┘", flush=True)
        print(flush=True)

        self._session = frida.attach(pid)
        self._script = self._session.create_script(_MONITOR_JS)

        dedup = self._dedup
        my_uid = self._my_uid
        log_path = self._log_path
        enable_toast = self._enable_toast

        def on_msg(msg, data):
            if msg['type'] == 'send':
                p = msg['payload']
                if p.get('ready'):
                    hooks = p.get('hooks', 1)
                    print(f"  [监听中... {hooks} 个 Hook 已激活]\n", flush=True)
                    return
                if not data:
                    return
                src = p.get('src', 'unknown')
                if src == 'send':
                    _process_send(data, p.get('uri', ''),
                                  dedup, my_uid, log_path, enable_toast)
                else:
                    _process_push(data, src,
                                  dedup, my_uid, log_path, enable_toast)

        self._script.on('message', on_msg)
        self._script.load()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        self.stop()

    def stop(self):
        if self._script:
            try:
                self._script.unload()
            except Exception:
                pass
            self._script = None
        if self._session:
            try:
                self._session.detach()
            except Exception:
                pass
            self._session = None

        if os.path.exists(self._log_path):
            with open(self._log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            print(f"\n  共记录 {len(lines)} 条消息 → {self._log_path}", flush=True)

        print("已停止", flush=True)
