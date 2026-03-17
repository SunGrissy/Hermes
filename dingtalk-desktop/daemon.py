# -*- coding: utf-8 -*-
"""
Frida Daemon — 常驻守护进程，为 MCP 工具提供 HTTP API

架构：
  - 单 Frida session 附加到 DingTalk 主进程
  - CEF 脚本：RPC 导出 execJs/loadUrl（消息发送）
  - Monitor 脚本：Native Hook 实时消息监听
  - HTTP API on localhost:19200
  - DingTalk 进程 watchdog

端点：
  POST /send      {cid|name, message}  → 发消息（支持按姓名自动解析 CID）
  POST /fetch     {cid|name, count}    → 获取历史消息
  GET  /search    ?keyword=&limit=     → 搜日志
  GET  /contacts  ?name=               → 查 CID
  GET  /health                         → 状态
  POST /shutdown                       → 停止守护进程
"""
import os
import sys
import json
import time
import signal
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from lib.utils import (
    get_main_pid, get_main_pid_by_mem, js_escape, normalize,
    ADV_SEARCH_URL, DEFAULT_MY_UID, DATA_DIR, DedupTracker,
    deep_decode, fmt_time, CT_NAMES, ContactsDB,
)


APP_VERSION = "1.0.0"
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_server_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
_KEY_FILES = [
    'daemon.py', 'lib/utils.py', 'lib/monitor.py', 'lib/sender.py',
    'SKILL.md', 'report_digest.py',
]

DAEMON_PORT = int(os.environ.get('DINGTALK_DAEMON_PORT', '19200'))
BEACON_PORT = int(os.environ.get('DINGTALK_BEACON_PORT', '18899'))
MY_UID = os.environ.get('DINGTALK_MY_UID', DEFAULT_MY_UID)
LOG_FILE = os.environ.get(
    'DINGTALK_LOG_FILE',
    os.path.join(DATA_DIR, '_msg_log.jsonl'),
)
WATCHDOG_INTERVAL = 30


def _parse_date_param(val, end_of_day=False):
    """Parse date param: 'YYYY-MM-DD [HH:MM:SS]' → ms timestamp, int passthrough, None passthrough"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        val = val.strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(val, fmt)
                if fmt == '%Y-%m-%d' and end_of_day:
                    dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)
                return int(dt.timestamp() * 1000)
            except ValueError:
                continue
        try:
            return int(val)
        except ValueError:
            return None
    return None

# ── CEF Frida 脚本（持久化，RPC 导出）──

_CEF_SCRIPT = r"""
'use strict';

var libcef = null;
Process.enumerateModules().forEach(function(m) {
    if (m.name.toLowerCase() === 'libcef.dll') libcef = m;
});

if (!libcef) {
    send({t: 'error', msg: 'libcef.dll not found'});
} else {
    var ex = {};
    libcef.enumerateExports().forEach(function(e) { ex[e.name] = e.address; });

    var fn_getBrowser = new NativeFunction(
        ex['cef_browser_host_get_browser_by_identifier'], 'pointer', ['int']);
    var fn_strSet = new NativeFunction(
        ex['cef_string_utf16_set'], 'int', ['pointer', 'uint64', 'pointer', 'int']);

    function makeCefStr(text) {
        var s = Memory.alloc(24);
        s.writeU64(0); s.add(8).writeU64(0); s.add(16).writeU64(0);
        var utf16 = Memory.allocUtf16String(text);
        fn_strSet(utf16, text.length, s, 1);
        return s;
    }

    function _execJs(browserId, js) {
        try {
            var b = fn_getBrowser(browserId);
            if (b.isNull()) return 'no_browser';
            var fp = b.add(160).readPointer();
            var fnFrame = new NativeFunction(fp, 'pointer', ['pointer']);
            var f = fnFrame(b);
            if (f.isNull()) return 'no_frame';
            var c = makeCefStr(js);
            var u = makeCefStr('');
            var xp = f.add(152).readPointer();
            var xfn = new NativeFunction(xp, 'void', ['pointer', 'pointer', 'pointer', 'int']);
            xfn(f, c, u, 0);
            return 'ok';
        } catch(e) { return 'err:' + e.message; }
    }

    rpc.exports = {
        execJs: function(browserId, js) { return _execJs(browserId, js); },
        loadUrl: function(browserId, url) {
            try {
                var b = fn_getBrowser(browserId);
                if (b.isNull()) return 'no_browser';
                var fp = b.add(160).readPointer();
                var fnFrame = new NativeFunction(fp, 'pointer', ['pointer']);
                var f = fnFrame(b);
                if (f.isNull()) return 'no_frame';
                var urlStr = makeCefStr(url);
                var luPtr = f.add(144).readPointer();
                var luFn = new NativeFunction(luPtr, 'void', ['pointer', 'pointer']);
                luFn(f, urlStr);
                return 'ok';
            } catch(e) { return 'err:' + e.message; }
        },
        scanBrowsers: function() {
            var ids = [];
            for (var i = 1; i <= 20; i++) {
                try {
                    if (!fn_getBrowser(i).isNull()) ids.push(i);
                } catch(e) {}
            }
            return ids;
        },
        ping: function() { return 'pong'; },
    };

    send({t: 'ready', msg: 'CEF script loaded'});
}
"""

# ── Monitor Frida 脚本 ──

from lib.monitor import _MONITOR_JS, _process_push, _process_send
from skill_router import start_router as _start_skill_router

# ── Beacon 回调服务器（接收 CEF JS 回调）──

class _BeaconServer:
    def __init__(self, port):
        self.port = port
        self.received = []
        self._server = None
        self._thread = None

    def start(self):
        parent = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                parent.received.append(urllib.parse.unquote(self.path))
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'ok')

            def do_POST(self):
                cl = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(cl).decode('utf-8', errors='replace') if cl else ''
                parent.received.append(self.path + '|' + body[:500000])
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'ok')

            def log_message(self, *a):
                pass

        self._server = HTTPServer(('127.0.0.1', self.port), H)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()

    def get_reports(self):
        reports = {}
        for path in self.received:
            parts = path.split('|', 1)
            base = parts[0]
            body = parts[1] if len(parts) > 1 else ''
            if '/r?' not in base and '/b?' not in base:
                continue
            params = urllib.parse.parse_qs(urllib.parse.urlparse(base).query)
            label = params.get('l', ['?'])[0]
            data_raw = params.get('d', [''])[0] or body
            try:
                data = json.loads(data_raw)
            except Exception:
                data = data_raw
            reports[label] = data
        return reports

    def clear(self):
        self.received.clear()


# ── FridaDaemon 核心 ──

class FridaDaemon:
    def __init__(self):
        self._pid = None
        self._session = None
        self._cef_script = None
        self._monitor_script = None
        self._cef_ready = False
        self._monitor_ready = False
        self._beacon = _BeaconServer(BEACON_PORT)
        self._dedup = DedupTracker()
        self._lock = threading.Lock()
        self._fetch_lock = threading.Lock()
        self._watchdog_thread = None
        self._name_resolver_thread = None
        self._name_queue = []
        self._name_queue_lock = threading.Lock()
        self._running = False
        self._attach_time = None
        self._send_count = 0
        self._fetch_count = 0
        self._monitor_count = 0
        self._cached_jsapi_bid = None

    @property
    def is_attached(self):
        return (self._session is not None
                and not self._session.is_detached
                and self._cef_ready)

    def attach(self):
        with self._lock:
            return self._attach_internal()

    def _attach_internal(self):
        import frida

        if self._session and not self._session.is_detached:
            return True

        pid = get_main_pid() or get_main_pid_by_mem()
        if not pid:
            log('DingTalk 进程未找到')
            return False

        try:
            self._session = frida.attach(pid)
            self._pid = pid
            self._attach_time = time.time()

            self._session.on('detached', self._on_detached)

            self._cef_script = self._session.create_script(_CEF_SCRIPT)
            self._cef_script.on('message', self._on_cef_msg)
            self._cef_script.load()
            time.sleep(0.5)

            if self._cef_ready:
                log(f'已附加到 DingTalk PID={pid}, CEF 就绪')
            else:
                log(f'已附加到 DingTalk PID={pid}, 但 CEF 未就绪')

            return self._cef_ready
        except Exception as e:
            log(f'附加失败: {e}')
            self._cleanup()
            return False

    def start_monitor(self):
        with self._lock:
            if self._monitor_script:
                return True
            if not self._session or self._session.is_detached:
                if not self._attach_internal():
                    return False

            try:
                self._monitor_script = self._session.create_script(_MONITOR_JS)
                self._monitor_script.on('message', self._on_monitor_msg)
                self._monitor_script.load()
                log('消息监听器已启动')
                return True
            except Exception as e:
                log(f'监听器启动失败: {e}')
                return False

    def _on_detached(self, reason, crash):
        log(f'Frida session detached: {reason}')
        self._cef_ready = False
        self._monitor_ready = False
        self._session = None
        self._cef_script = None
        self._monitor_script = None
        self._cached_jsapi_bid = None

    def _on_cef_msg(self, msg, data):
        if msg['type'] == 'send':
            p = msg['payload']
            if p.get('t') == 'ready':
                self._cef_ready = True
            elif p.get('t') == 'error':
                log(f'CEF error: {p.get("msg")}')

    def _on_monitor_msg(self, msg, data):
        if msg['type'] != 'send':
            return
        p = msg['payload']
        if p.get('ready'):
            self._monitor_ready = True
            log(f'监听器就绪, {p.get("hooks", 0)} 个 Hook')
            return
        if not data:
            return
        self._monitor_count += 1
        src = p.get('src', 'unknown')
        if src == 'send':
            _process_send(data, p.get('uri', ''),
                          self._dedup, MY_UID, LOG_FILE, False)
        else:
            _process_push(data, src,
                          self._dedup, MY_UID, LOG_FILE, False)
            for cid in ContactsDB.drain_pending_resolve():
                self.queue_name_resolve(cid)

    def _cleanup(self):
        self._cef_ready = False
        self._monitor_ready = False
        if self._cef_script:
            try: self._cef_script.unload()
            except: pass
            self._cef_script = None
        if self._monitor_script:
            try: self._monitor_script.unload()
            except: pass
            self._monitor_script = None
        if self._session:
            try: self._session.detach()
            except: pass
            self._session = None

    def resolve_cid(self, name):
        """按姓名解析 CID，返回 (cid, display_name) 或 (None, None)"""
        entries = self.find_conversation(name)
        if not entries:
            return None, None
        best = entries[0]
        return best['cid'], best.get('sender', name)

    def _find_jsapi_browser(self, force_rescan=False):
        """扫描所有活跃 browser，返回第一个有 listMessage API 的 browser ID。
        结果会缓存，后续调用直接返回缓存值；仅在 force_rescan=True 或缓存失效时重新扫描。
        """
        if not self._cef_script:
            self._cached_jsapi_bid = None
            return None

        if self._cached_jsapi_bid is not None and not force_rescan:
            if self._verify_jsapi_browser(self._cached_jsapi_bid):
                return self._cached_jsapi_bid
            log(f'缓存的 JSAPI browser {self._cached_jsapi_bid} 已失效，重新扫描')
            self._cached_jsapi_bid = None

        try:
            bids = self._cef_script.exports_sync.scan_browsers()
        except Exception as e:
            log(f'scanBrowsers 失败: {e}')
            return None

        if not bids:
            return None

        for bid in bids:
            if self._verify_jsapi_browser(bid):
                log(f'找到 JSAPI browser: ID={bid}')
                self._cached_jsapi_bid = bid
                return bid

        return None

    def _read_browser1_url(self):
        """读取 browser 1 当前 URL，用于 fetch_report_content 的保存/恢复。
        复用 _ensure_b1 同款探测 JS，等待 2 秒收结果。
        失败则返回 ADV_SEARCH_URL 作为安全 fallback。
        """
        try:
            self._beacon.clear()
            read_js = (
                f"(function(){{fetch('http://127.0.0.1:{BEACON_PORT}"
                "/b?l=b1url',{method:'POST',body:JSON.stringify(location.href),"
                "mode:'no-cors'});"
                "})()"
            )
            self._cef_script.exports_sync.exec_js(1, read_js)
            time.sleep(2)
            url = self._beacon.get_reports().get('b1url')
            if isinstance(url, str) and url.startswith('http'):
                return url
        except Exception:
            pass
        return ADV_SEARCH_URL

    def _verify_jsapi_browser(self, bid):
        """验证指定 browser 是否仍有 listMessage API"""
        if not self._cef_script:
            return False
        self._beacon.clear()
        check_js = (
            f"(function(){{fetch('http://127.0.0.1:{BEACON_PORT}"
            "/b?l=chk',{method:'POST',body:JSON.stringify(typeof dingtalk!==\"undefined\""
            "&&!!dingtalk.message"
            "&&typeof dingtalk.message.listMessage===\"function\"),mode:'no-cors'});"
            "})()"
        )
        try:
            self._cef_script.exports_sync.exec_js(bid, check_js)
        except Exception:
            return False
        time.sleep(1)
        reports = self._beacon.get_reports()
        return reports.get('chk', False) is True

    def fetch_history(self, cid, count=20, before=None, after=None, timeout=30):
        """通过 JSAPI dingtalk.message.listMessage 获取历史消息
        
        before: 获取此时间之前的消息（YYYY-MM-DD 或 ms 时间戳），作为 cursor
        after:  过滤掉此时间之前的消息（YYYY-MM-DD 或 ms 时间戳），作为下界
        """
        before_ts = _parse_date_param(before, end_of_day=True)
        after_ts = _parse_date_param(after, end_of_day=False)
        cursor_val = str(before_ts) if before_ts else "Number.MAX_SAFE_INTEGER"

        with self._fetch_lock:
            if not self.is_attached:
                if not self.attach():
                    return {'success': False, 'error': 'Cannot attach to DingTalk'}

            bid = self._find_jsapi_browser()
            if not bid:
                return {'success': False, 'error': '未找到有 listMessage API 的 browser'}

            count = min(count, 50)
            cid_safe = js_escape(cid)
            is_first = before_ts is None

            self._beacon.clear()
            fetch_js = self._build_fetch_js(cid_safe, cursor_val, count, is_first)

            result = self._cef_script.exports_sync.exec_js(bid, fetch_js)
            if result != 'ok':
                bid = self._find_jsapi_browser(force_rescan=True)
                if not bid:
                    return {'success': False, 'error': '未找到有 listMessage API 的 browser'}
                self._beacon.clear()
                result = self._cef_script.exports_sync.exec_js(bid, fetch_js)
                if result != 'ok':
                    return {'success': False, 'error': f'execJS on browser {bid} failed: {result}'}

            msgs_raw = self._wait_for_fetch_beacon(timeout=timeout)
            if msgs_raw is None:
                return {'success': False, 'error': '等待 JSAPI 响应超时'}

            messages = self._format_jsapi_messages(msgs_raw)
            self._fetch_count += 1

            if after_ts:
                messages = [m for m in messages if m.get('ts', 0) >= after_ts]

            resp = {
                'success': True,
                'cid': cid,
                'count': len(messages),
                'messages': messages,
            }
            if before_ts:
                resp['before'] = before_ts
            if after_ts:
                resp['after'] = after_ts
            return resp

    def _format_jsapi_messages(self, msgs_raw):
        """解析 JSAPI dingtalk.message.listMessage 返回的消息列表"""
        if not isinstance(msgs_raw, list):
            return []

        results = []
        for m in msgs_raw:
            ts_val = m.get('ts', 0)
            try:
                ts_int = int(ts_val)
                dt = datetime.fromtimestamp(ts_int / 1000).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                ts_int = 0
                dt = '?'

            uid = str(m.get('uid', ''))
            ct = int(m.get('ct', 0))
            ct_name = CT_NAMES.get(ct, f'type_{ct}')
            text = m.get('text', '')
            raw = m.get('raw', '')
            bf_raw = m.get('bf', '')
            sender_name = m.get('sn', '')

            if ct == 300 and not text:
                if bf_raw:
                    text = self._extract_report_from_bform(bf_raw)
                elif raw:
                    text = self._extract_report_from_raw(raw)

            is_self = uid == MY_UID
            entry = {
                'time': dt,
                'ts': ts_int,
                'sender': '我' if is_self else (sender_name or uid),
                'uid': uid,
                'is_self': is_self,
                'content_type': ct,
                'content_type_name': ct_name,
                'text': text or '',
            }
            if raw:
                entry['raw'] = raw

            action_url = m.get('url', '')
            if action_url:
                entry['action_url'] = action_url
                try:
                    parsed_url = urllib.parse.urlparse(action_url)
                    qs = urllib.parse.parse_qs(parsed_url.query)
                    report_url = qs.get('url', [''])[0]
                    if report_url:
                        entry['report_url'] = report_url
                except Exception:
                    pass

            results.append(entry)

        return results

    @staticmethod
    def _normalize_report_card(m):
        """Extract author name and clean text from ct=2950 report card.

        Supported title formats:
          [日志] 张三的日报
          [日志] 个人日报 · [张三] · [0316]
          [日志] 个人日报 · 张三 · [0316]
          [日志] 个人日报 · 张三
          (同上，周报 / 月报)
        """
        import re
        text = m.get('text', '') or ''
        author = None
        # Pattern 1: [日志] ...张三的日报/周报/月报
        m1 = re.search(r'\[日志\]\s*(.+?)的[日周月]报', text)
        if m1:
            author = m1.group(1).strip()
        if not author:
            # Pattern 2: [日志] 个人日报/周报/月报 · [张三] or · 张三
            m2 = re.search(
                r'\[日志\]\s*个人[日周月]报\s*[··]\s*\[?([^\]·\s][^\]·]*?)\]?'
                r'(?:\s*[··]|$)',
                text,
            )
            if m2:
                author = m2.group(1).strip()
        if not author:
            # Pattern 3: [日志] 个人日报 · 张三  (no trailing separator)
            m3 = re.search(
                r'\[日志\]\s*个人[日周月]报\s*[··]\s*([^\]·\n]+)',
                text,
            )
            if m3:
                candidate = m3.group(1).strip().lstrip('[').rstrip(']').strip()
                # Reject if it looks like a date (e.g. 0316, 2026/3/16)
                if candidate and not re.match(r'^[\d/\-\.]+$', candidate):
                    author = candidate
        if author:
            m['sender'] = author
        parts = text.split('||', 1)
        if len(parts) == 2:
            m['text'] = parts[1].strip()
        elif '|' in text:
            parts2 = text.split('|')
            m['text'] = parts2[-1].strip()
        m['content_type'] = 300
        return m

    @staticmethod
    def _extract_report_from_bform(bf_str):
        """从 b_form 字符串直接提取日报内容"""
        if not bf_str:
            return ''
        try:
            bf = json.loads(bf_str) if isinstance(bf_str, str) else bf_str
        except Exception:
            return bf_str[:500] if isinstance(bf_str, str) else ''
        if isinstance(bf, list):
            parts = []
            for item in bf:
                if isinstance(item, dict):
                    k = item.get('k', '')
                    v = item.get('v', '')
                    if v:
                        parts.append(f'{k}: {v}')
            return ' || '.join(parts) if parts else ''
        return ''

    @staticmethod
    def _extract_report_from_raw(raw_json):
        """从 ct=300 的原始 content JSON 中提取日报内容（fallback）"""
        try:
            ct_obj = json.loads(raw_json)
        except Exception:
            return ''

        attachments = ct_obj.get('attachments', [])
        for att in attachments:
            ext = att.get('extension', {})
            bf_str = ext.get('b_form', '')
            btl = ext.get('b_tl', '日报')
            htl = ext.get('h_tl', '')

            if bf_str:
                try:
                    bf = json.loads(bf_str) if isinstance(bf_str, str) else bf_str
                except Exception:
                    return f'{btl} [{htl}]'

                if isinstance(bf, list):
                    parts = []
                    for item in bf:
                        if isinstance(item, dict):
                            k = item.get('k', '')
                            v = item.get('v', '')
                            if v:
                                parts.append(f'{k}: {v}')
                    if parts:
                        return f'{btl} [{htl}] || ' + ' || '.join(parts)
                    return f'{btl} [{htl}]'

        return ''

    def send_message(self, cid, text):
        if not self.is_attached:
            if not self.attach():
                return {'success': False, 'error': 'Cannot attach to DingTalk'}

        if not self._ensure_b1():
            return {'success': False, 'error': 'B1 (advancedSearch) not available'}

        self._beacon.clear()
        safe = js_escape(text)
        js = (
            f"(function(){{var P={BEACON_PORT};"
                "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
                "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
                "if(typeof dingtalk==='undefined'||!dingtalk.message||!dingtalk.message.sendTextMsg){"
                "r('error','no_api');return;}"
                f"dingtalk.message.sendTextMsg('{cid}','{safe}','',function(res){{r('cb',res);}});"
                "r('sent','ok');"
                "})()"
        )

        result = self._cef_script.exports_sync.exec_js(1, js)
        if result != 'ok':
            if self._ensure_b1():
                result = self._cef_script.exports_sync.exec_js(1, js)

        for _ in range(40):
            time.sleep(0.3)
            reports = self._beacon.get_reports()
            if 'cb' in reports or 'error' in reports:
                break

        reports = self._beacon.get_reports()
        self._send_count += 1
        return {
            'success': 'sent' in reports and 'error' not in reports,
            'cid': cid,
            'callback': reports.get('cb'),
            'error': reports.get('error'),
        }

    def _ensure_b1(self):
        if not self._cef_script:
            return False
        self._beacon.clear()
        check_js = (
            f"(function(){{fetch('http://127.0.0.1:{BEACON_PORT}"
            "/b?l=url',{method:'POST',body:JSON.stringify(location.href),mode:'no-cors'});"
            f"fetch('http://127.0.0.1:{BEACON_PORT}"
            "/b?l=api',{method:'POST',body:JSON.stringify(typeof dingtalk!==\"undefined\""
            "&&!!dingtalk.message&&typeof dingtalk.message.sendTextMsg===\"function\"),mode:'no-cors'});"
            "})()"
        )
        self._cef_script.exports_sync.exec_js(1, check_js)
        time.sleep(1.5)

        reports = self._beacon.get_reports()
        url = reports.get('url', '')
        has_api = reports.get('api', False)

        if isinstance(url, str) and 'advancedSearch' in url and has_api:
            return True

        log('B1 不在 advancedSearch，尝试恢复...')
        self._cef_script.exports_sync.load_url(1, ADV_SEARCH_URL)
        time.sleep(4)

        self._beacon.clear()
        self._cef_script.exports_sync.exec_js(1, check_js)
        time.sleep(1.5)
        reports = self._beacon.get_reports()
        url = reports.get('url', '')
        has_api = reports.get('api', False)
        return isinstance(url, str) and 'advancedSearch' in url and has_api

    def exec_custom_js(self, js, label='exec_result', timeout=10):
        """在 JSAPI browser 中执行任意 JS，通过 beacon 收结果。
        JS 内可用: dingtalk 对象, fetch 到 http://127.0.0.1:{BEACON_PORT}/b?l={label}
        """
        bid = self._find_jsapi_browser()
        if not bid:
            return {'success': False, 'error': 'No JSAPI browser found'}
        self._beacon.clear()
        try:
            self._cef_script.exports_sync.exec_js(bid, js)
        except Exception as e:
            return {'success': False, 'error': f'exec_js failed: {e}'}
        for _ in range(timeout * 4):
            time.sleep(0.25)
            reports = self._beacon.get_reports()
            if label in reports or any(k.startswith(label) for k in reports):
                break
        reports = self._beacon.get_reports()
        matched = {k: v for k, v in reports.items() if k == label or k.startswith(label)}
        return {'success': True, 'results': matched}

    def probe_jsapi(self, timeout=10):
        """探测 JSAPI dingtalk 对象的结构"""
        bid = self._find_jsapi_browser()
        if not bid:
            return {'success': False, 'error': 'No JSAPI browser found'}

        self._beacon.clear()
        probe_js = (
            "(function(){"
            "var P=" + str(BEACON_PORT) + ";"
            "function post(l,d){var b=JSON.stringify(d);"
            "fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:b,mode:'no-cors'}).catch(function(){});}"
            "if(typeof dingtalk==='undefined'){post('probe',{error:'no dingtalk'});return;}"
            "var result={topKeys:Object.keys(dingtalk)};"
            "var topKeys=Object.keys(dingtalk);"
            "for(var i=0;i<topKeys.length;i++){"
            "var k=topKeys[i];"
            "try{var v=dingtalk[k];"
            "if(v&&typeof v==='object'){"
            "var sub=Object.keys(v);"
            "result['sub_'+k]=sub;"
            "for(var j=0;j<sub.length;j++){"
            "try{var vv=v[sub[j]];"
            "if(vv&&typeof vv==='object'&&typeof vv.then!=='function'){"
            "result['sub_'+k+'_'+sub[j]]=Object.keys(vv);"
            "}}catch(e2){}"
            "}"
            "}}catch(e){}}"
            "post('probe',result);"
            "})()"
        )

        try:
            self._cef_script.exports_sync.exec_js(bid, probe_js)
        except Exception as e:
            return {'success': False, 'error': f'exec_js failed: {e}'}

        for _ in range(timeout * 2):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'probe' in reports:
                return {'success': True, 'data': reports['probe']}

        return {'success': False, 'error': 'timeout'}

    def get_conversation_info(self, cid, timeout=10):
        """通过 JSAPI getBaseConversation 获取会话元数据（群名、类型等）"""
        bid = self._find_jsapi_browser()
        if not bid:
            return {'success': False, 'error': 'No JSAPI browser found'}

        self._beacon.clear()
        cid_safe = js_escape(cid)
        conv_js = (
            "(function(){"
            "var P=" + str(BEACON_PORT) + ";"
            "function post(l,d){var b=JSON.stringify(d);"
            "fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:b,mode:'no-cors'}).catch(function(){});}"
            "if(typeof dingtalk==='undefined'||!dingtalk.conversation){"
            "post('conv_error',{error:'no_api'});return;}"
            "var fn=dingtalk.conversation.getBaseConversation||dingtalk.conversation.getConversation;"
            "if(!fn){post('conv_error',{error:'no getBaseConversation'});return;}"
            "fn.call(dingtalk.conversation,'" + cid_safe + "',function(err,data){"
            "if(err){post('conv_error',{error:String(err)});return;}"
            "var r={};"
            "if(data){"
            "try{"
            "var keys=['title','name','icon','memberCount','type','isSingle','conversationType','ownerId'];"
            "for(var i=0;i<keys.length;i++){if(data[keys[i]]!==undefined)r[keys[i]]=data[keys[i]];}"
            "if(!r.title&&!r.name){var ak=Object.keys(data);for(var j=0;j<ak.length;j++){"
            "r['_'+ak[j]]=typeof data[ak[j]]==='object'?JSON.stringify(data[ak[j]]):String(data[ak[j]]);}}"
            "}catch(e){r._raw=String(data);}"
            "}"
            "post('conv_ok',r);"
            "});"
            "})()"
        )

        try:
            self._cef_script.exports_sync.exec_js(bid, conv_js)
        except Exception as e:
            return {'success': False, 'error': f'exec_js failed: {e}'}

        for _ in range(timeout * 2):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'conv_ok' in reports or 'conv_error' in reports:
                break

        reports = self._beacon.get_reports()
        if 'conv_error' in reports:
            return {'success': False, 'error': reports['conv_error']}
        if 'conv_ok' in reports:
            data = reports['conv_ok']
            name = data.get('title') or data.get('name') or ''
            return {'success': True, 'cid': cid, 'name': name, 'data': data}
        return {'success': False, 'error': 'timeout'}

    def queue_name_resolve(self, cid):
        """将 CID 加入名称解析队列"""
        with self._name_queue_lock:
            if cid not in self._name_queue:
                self._name_queue.append(cid)

    def start_name_resolver(self):
        """启动后台名称解析线程"""
        if self._name_resolver_thread and self._name_resolver_thread.is_alive():
            return
        self._name_resolver_thread = threading.Thread(
            target=self._name_resolver_loop, daemon=True)
        self._name_resolver_thread.start()

    def _name_resolver_loop(self):
        """后台循环：从队列取 CID，调 JSAPI 查群名，更新 ContactsDB"""
        while self._running:
            cid = None
            with self._name_queue_lock:
                if self._name_queue:
                    cid = self._name_queue.pop(0)
            if not cid:
                time.sleep(3)
                continue
            if not self.is_attached:
                time.sleep(5)
                continue
            try:
                result = self.get_conversation_info(cid)
                if result.get('success') and result.get('name'):
                    ContactsDB.set_name(cid, result['name'])
                    log(f'[name-resolver] {cid} → {result["name"]}')
                else:
                    log(f'[name-resolver] {cid} 查询失败: {result.get("error", "no name")}')
            except Exception as e:
                log(f'[name-resolver] {cid} 异常: {e}')
            time.sleep(1)

    def enrich_contacts(self):
        """批量补全所有未解析的群聊名称"""
        unresolved = ContactsDB.get_unresolved_groups()
        count = 0
        for cid in unresolved:
            self.queue_name_resolve(cid)
            count += 1
        return {'queued': count, 'total_unresolved': len(unresolved)}

    # ── 自己的日报提取 ──

    MY_REPORT_GROUP_CID = '74401645538'

    def fetch_report_content(self, url, timeout=30):
        """通过 CEF loadUrl 打开报告页面并精准提取报告内容

        始终使用 browser 1（JSAPI browser），先保存当前 URL，抓取完毕后原样恢复，
        保证 DingTalk UI（搜索栏、文档面板等）不受影响。
        优先用 CSS 选择器定位报告正文容器，最终 fallback 到 body.innerText。
        """
        with self._fetch_lock:
            if not self.is_attached:
                if not self.attach():
                    return {'success': False, 'error': 'Cannot attach to DingTalk'}

            # 始终用 browser 1；用完后恢复到 about:blank（中性状态）
            # 不恢复到 advancedSearch.html，否则会触发钉钉搜索栏 UI 弹出
            content_bid = 1

            self._beacon.clear()
            result = self._cef_script.exports_sync.load_url(content_bid, url)
            if result != 'ok':
                return {'success': False, 'error': f'loadUrl failed: {result}'}

            time.sleep(20)

            self._beacon.clear()
            extract_js = (
                "(function(){"
                "var P=" + str(BEACON_PORT) + ";"
                "function post(l,d){fetch('http://127.0.0.1:'+P"
                "+'/r?l='+encodeURIComponent(l),"
                "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"

                "var sels=['.report-detail','.report-content','.detail-content',"
                "'.log-detail','.form-detail','[class*=report]','[class*=detail]',"
                "'article','main','.content','.page-content'];"
                "var el=null,method='body';"
                "for(var i=0;i<sels.length;i++){"
                "var e=document.querySelector(sels[i]);"
                "if(e&&e.innerText&&e.innerText.trim().length>20){"
                "el=e;method=sels[i];break;}}"
                "if(!el)el=document.body;"

                "var text=(el.innerText||'').trim();"
                "var title=document.title||'';"

                "var cs=3000,n=Math.ceil(text.length/cs);"
                "post('rpt_meta',{title:title,len:text.length,parts:n,method:method});"
                "for(var i=0;i<n&&i<100;i++){"
                "post('rpt_c'+i,{d:text.substr(i*cs,cs)});}"
                "})()"
            )

            self._cef_script.exports_sync.exec_js(content_bid, extract_js)

            meta = None
            expected_parts = 1
            for _ in range(timeout * 2):
                time.sleep(0.5)
                reports = self._beacon.get_reports()
                if 'rpt_meta' in reports and meta is None:
                    meta = reports['rpt_meta']
                    expected_parts = meta.get('parts', 1) if isinstance(meta, dict) else 1
                if meta is not None:
                    received = sum(1 for k in reports if k.startswith('rpt_c'))
                    if received >= expected_parts:
                        break

            reports = self._beacon.get_reports()
            # 恢复 browser 1 到 about:blank，不触发搜索栏 UI 弹出
            try:
                self._cef_script.exports_sync.load_url(1, 'about:blank')
            except Exception:
                pass

            if not meta:
                return {'success': False, 'error': 'DOM extraction timed out'}

            full_text = ''
            for i in range(100):
                chunk = reports.get(f'rpt_c{i}')
                if chunk and isinstance(chunk, dict):
                    full_text += chunk.get('d', '')

            return {
                'success': True,
                'title': meta.get('title', ''),
                'text_length': meta.get('len', 0),
                'extraction_method': meta.get('method', 'body'),
                'content': full_text,
            }

    def fetch_my_reports(self, count=5, before=None, after=None,
                         report_type=None, full_content=False):
        """从「我的报」群获取自己的报告（ct=2950 互动卡片），支持 CEF DOM 提取完整内容

        使用独立 JSAPI JS（probe 风格）直接获取消息并提取卡片 URL，
        绕开 fetch_history 的通用处理逻辑。
        """
        before_ts = _parse_date_param(before, end_of_day=True)
        after_ts = _parse_date_param(after, end_of_day=False)
        cursor_val = str(before_ts) if before_ts else "Number.MAX_SAFE_INTEGER"
        fetch_count = min(count * 3, 50)

        with self._fetch_lock:
            if not self.is_attached:
                if not self.attach():
                    return {'success': False, 'error': 'Cannot attach to DingTalk'}

            bid = self._find_jsapi_browser()
            if not bid:
                return {'success': False, 'error': '未找到 JSAPI browser'}

            self._beacon.clear()
            cid_safe = js_escape(self.MY_REPORT_GROUP_CID)

            js = (
                "(function(){"
                "var P=" + str(BEACON_PORT) + ";"
                "function post(l,d){var b=JSON.stringify(d);"
                "fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
                "{method:'POST',body:b,mode:'no-cors'}).catch(function(){});}"
                "function promisify(fn,ctx){"
                "return function(){"
                "var a=Array.prototype.slice.call(arguments);"
                "return new Promise(function(ok,fail){"
                "a.push(function(e,r){e?fail(e):ok(r);});"
                "fn.apply(ctx,a);});};}"
                "if(!dingtalk||!dingtalk.message||!dingtalk.message.listMessage){"
                "post('mr_err',{error:'no_api'});return;}"
                "var lm=promisify(dingtalk.message.listMessage,dingtalk.message);"
                "lm('" + cid_safe + "',String(" + cursor_val + "),"
                + str(fetch_count) + ",false,{isFirstPull:true})"
                ".then(function(msgs){"
                "if(!msgs||!msgs.length){post('mr_meta',{count:0,chunks:0});return;}"
                "var cards=[];"
                "for(var i=0;i<msgs.length;i++){"
                "var m=msgs[i],bm=m.baseMessage||m||{};"
                "var ct=bm.content||{};"
                "if((ct.contentType||0)!==2950)continue;"
                "var ext=bm.extension||{};"
                "if(typeof ext==='string'){try{ext=JSON.parse(ext);}catch(e){}}"
                "var url=ext.biz_custom_action_url||'';"
                "var title=ext.biz_custom_title||'';"
                "var desc=ext.biz_custom_desc||'';"
                "var ts=bm.createdAt||m.createdAt||'0';"
                "cards.push({ts:ts,title:title,desc:desc,url:url});"
                "}"
                "var BS=5,nc=Math.ceil(cards.length/BS);"
                "post('mr_meta',{count:cards.length,chunks:nc});"
                "for(var ci=0;ci<nc;ci++){"
                "post('mr_c'+ci,{cards:cards.slice(ci*BS,(ci+1)*BS)});}"
                "}).catch(function(e){post('mr_err',{error:String(e)});});"
                "})()"
            )

            result = self._cef_script.exports_sync.exec_js(bid, js)
            if result != 'ok':
                return {'success': False, 'error': f'execJS failed: {result}'}

            meta = None
            expected_chunks = 0
            for _ in range(60):
                time.sleep(0.5)
                reports = self._beacon.get_reports()
                if 'mr_err' in reports:
                    break
                if 'mr_meta' in reports and meta is None:
                    meta = reports['mr_meta']
                    expected_chunks = meta.get('chunks', 0) if isinstance(meta, dict) else 0
                if meta is not None:
                    received = sum(1 for k in reports if k.startswith('mr_c'))
                    if received >= expected_chunks:
                        break

            reports = self._beacon.get_reports()

            if 'mr_err' in reports:
                err = reports['mr_err']
                return {'success': False,
                        'error': err.get('error', str(err)) if isinstance(err, dict) else str(err)}

            if not meta:
                return {'success': False, 'error': 'JSAPI 响应超时'}

            raw_cards = []
            for ci in range(expected_chunks):
                chunk = reports.get(f'mr_c{ci}')
                if chunk and isinstance(chunk, dict):
                    raw_cards.extend(chunk.get('cards', []))

        cards = []
        for c in raw_cards:
            ts_val = c.get('ts', 0)
            try:
                ts_int = int(ts_val)
                dt = datetime.fromtimestamp(ts_int / 1000).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                ts_int = 0
                dt = '?'

            if after_ts and ts_int < after_ts:
                continue

            action_url = c.get('url', '')
            report_url = ''
            if action_url:
                try:
                    parsed = urllib.parse.urlparse(action_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    report_url = qs.get('url', [''])[0]
                except Exception:
                    pass

            if not report_url:
                continue

            cards.append({
                'time': dt,
                'ts': ts_int,
                'title': c.get('title', ''),
                'desc': c.get('desc', ''),
                'report_url': report_url,
                'content': '',
            })

        if report_type:
            rt = report_type.strip()
            cards = [c for c in cards if rt in c['title']]

        cards = cards[:count]

        if full_content and cards:
            for card in cards:
                try:
                    cr = self.fetch_report_content(card['report_url'])
                    if cr.get('success'):
                        card['content'] = cr.get('content', '')
                        card['extraction_method'] = cr.get('extraction_method', '')
                except Exception as e:
                    card['content'] = f'[加载失败: {e}]'

        return {
            'success': True,
            'count': len(cards),
            'reports': cards,
        }

    def fetch_reports_paginated(self, count=10, before=None, after=None,
                                author=None, report_type=None, max_pages=20,
                                max_seconds=200, cid=None):
        """daemon 侧分页拉取工作汇报（ct=300），browser 扫描只做一次"""
        target_cid = cid or '316550726:420217003'
        PAGE_SIZE = 50
        before_ts = _parse_date_param(before, end_of_day=True)
        after_ts = _parse_date_param(after, end_of_day=False)
        t_start = time.time()

        with self._fetch_lock:
            if not self.is_attached:
                if not self.attach():
                    return {'success': False, 'error': 'Cannot attach to DingTalk'}

            bid = self._find_jsapi_browser()
            if not bid:
                return {'success': False, 'error': '未找到有 listMessage API 的 browser'}

            all_msgs = []
            seen_ts = set()
            cursor = before_ts
            pages = 0
            timed_out = False

            while len(all_msgs) < count and pages < max_pages:
                elapsed = time.time() - t_start
                if elapsed > max_seconds:
                    log(f'[fetch_reports] 时间预算用尽 ({elapsed:.0f}s > {max_seconds}s)，已获取 {len(all_msgs)} 条')
                    timed_out = True
                    break
                cursor_val = str(cursor) if cursor else "Number.MAX_SAFE_INTEGER"
                is_first = cursor is None

                self._beacon.clear()
                cid_safe = js_escape(target_cid)
                fetch_js = self._build_fetch_js(cid_safe, cursor_val, PAGE_SIZE, is_first)

                try:
                    result = self._cef_script.exports_sync.exec_js(bid, fetch_js)
                except Exception as e:
                    bid = self._find_jsapi_browser(force_rescan=True)
                    if not bid:
                        break
                    try:
                        result = self._cef_script.exports_sync.exec_js(bid, fetch_js)
                    except Exception:
                        break

                if result != 'ok':
                    break

                raw_batch = self._wait_for_fetch_beacon(timeout=30)
                if raw_batch is None:
                    break

                messages = self._format_jsapi_messages(raw_batch)
                if not messages:
                    break

                if after_ts:
                    messages = [m for m in messages if m.get('ts', 0) >= after_ts]

                batch_added = 0
                for m in messages:
                    ct = m.get('content_type')
                    if ct == 2950:
                        txt = m.get('text', '') or ''
                        if '[日志]' not in txt and '日报' not in txt \
                                and '周报' not in txt and '月报' not in txt:
                            continue
                        m = self._normalize_report_card(m)
                    elif ct != 300:
                        continue
                    key = f"{m.get('ts')}_{m.get('sender')}"
                    if key in seen_ts:
                        continue
                    seen_ts.add(key)
                    all_msgs.append(m)
                    batch_added += 1

                pages += 1

                oldest = messages[-1] if messages else None
                if not oldest:
                    break
                new_cursor = oldest.get('ts', 0)
                if not new_cursor or new_cursor == cursor:
                    break
                cursor = new_cursor

                if after_ts and new_cursor < after_ts:
                    break

            self._fetch_count += 1

        msgs = all_msgs
        if report_type:
            rt = report_type.strip()
            msgs = [m for m in msgs if m.get('text', '') and rt in m['text']]
        if author:
            a = author.lower()
            msgs = [m for m in msgs
                    if (m.get('sender', '').lower().find(a) >= 0 or
                        m.get('text', '').lower().find(a) >= 0)]

        msgs = msgs[:count]
        result = {
            'success': True,
            'count': len(msgs),
            'pages': pages,
            'total_reports': len(all_msgs),
            'elapsed_seconds': round(time.time() - t_start, 1),
            'messages': msgs,
        }
        if timed_out:
            result['timed_out'] = True
            result['note'] = f'时间预算 {max_seconds}s 内获取了 {len(msgs)} 条部分结果'
        return result

    def _build_fetch_js(self, cid_safe, cursor_val, count, is_first):
        """构建 listMessage JS 调用代码"""
        return (
            "(function(){"
            "var P=" + str(BEACON_PORT) + ";"
            "function post(l,d){"
            "fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});"
            "}"
            "function promisify(fn,ctx){"
            "return function(){"
            "var a=Array.prototype.slice.call(arguments);"
            "return new Promise(function(ok,fail){"
            "a.push(function(e,r){e?fail(e):ok(r);});"
            "fn.apply(ctx,a);"
            "});"
            "};"
            "}"
            "if(typeof dingtalk==='undefined'||!dingtalk.message||!dingtalk.message.listMessage){"
            "post('fetch_error',{error:'no_api'});return;"
            "}"
            "var lm=promisify(dingtalk.message.listMessage,dingtalk.message);"
            "lm('" + cid_safe + "',String(" + cursor_val + "),"
            + str(count) + ",false,{isFirstPull:" + ("true" if is_first else "false") + "})"
            ".then(function(msgs){"
            "if(!msgs||!msgs.length){post('fetch_meta',{count:0,chunks:0});return;}"
            "var out=[];"
            "for(var i=0;i<msgs.length;i++){"
            "var m=msgs[i],bm=m.baseMessage||m||{};"
            "var ct=bm.content||{};"
            "var text='';"
            "try{"
            "if(ct.textContent&&ct.textContent.text)text=ct.textContent.text;"
            "else if(ct.richTextContent&&ct.richTextContent.text)text=ct.richTextContent.text;"
            "else if(ct.text)text=ct.text;"
            "if(!text&&bm.extension){var ext=bm.extension;"
            "if(ext.origin_text)text=ext.origin_text;"
            "else if(ext.originText)text=ext.originText;}"
            "if(!text&&m.content){"
            "if(typeof m.content==='string')text=m.content;"
            "else if(m.content.text)text=m.content.text;"
            "else if(m.content.textContent&&m.content.textContent.text)text=m.content.textContent.text;}"
            "if(!text&&m.text)text=m.text;"
            "}catch(e){}"
            ""
            "var raw_ct='';"
            "var sender_name='';"
            "var _aurl='';"
            "var _bf_raw='';"
            "try{"
            "var _ct_num=ct.contentType||0;"
            "if(_ct_num===300){"
            "try{raw_ct=JSON.stringify(ct);}catch(ej){}"
            "var att=ct.attachments||[];"
            "if(att.length>0){"
            "var ext2=att[0].extension||{};"
            "var bf=ext2.b_form||'';"
            "var btl=ext2.b_tl||'';"
            "var htl=ext2.h_tl||'';"
            "_bf_raw=bf;"
            "if(bf){"
            "try{var bfa=JSON.parse(bf);"
            "if(bfa&&bfa.length){"
            "var pp=[];"
            "for(var fi=0;fi<bfa.length;fi++){"
            "pp.push(bfa[fi].k+'::'+bfa[fi].v);"
            "}"
            "text=btl+' ['+htl+'] || '+pp.join(' || ');"
            "}}catch(ep){text=btl+' | '+bf;}"
            "}else{text=btl||'[工作汇报]';}"
            "}"
            "if(bm.extension){"
            "if(bm.extension.creatorId)sender_name=bm.extension.creatorId;"
            "}"
            "}else if(_ct_num!==1&&_ct_num!==203){"
            "try{raw_ct=JSON.stringify(ct);}catch(ej){}"
            "}"
            "if(_ct_num===2950){"
            "var _ext=bm.extension||{};"
            "var _lm=_ext.interactiveCardLastMessage||_ext.LastMessageI18n||'';"
            "var _desc=_ext.biz_custom_desc||'';"
            "var _title=_ext.biz_custom_title||'';"
            "var _url=_ext.biz_custom_action_url||'';"
            "_aurl=_url;"
            "if(!text)text=_lm;"
            "if(_desc)text=text+' || '+_desc;"
            "if(_title)text=_title+' | '+text;"
            "try{var _extStr=JSON.stringify(_ext);"
            "if(!raw_ct)raw_ct=_extStr;"
            "}catch(ex3){}"
            "}"
            "}catch(e2){}"
            ""
            "out.push({"
            "ts:bm.createdAt||m.createdAt||'0',"
            "uid:bm.senderOpenId||m.senderOpenId||'',"
            "ct:ct.contentType||0,"
            "text:String(text||''),"
            "raw:raw_ct,"
            "bf:_bf_raw,"
            "sn:sender_name,"
            "url:_aurl"
            "});"
            "}"
            "var BS=3;"
            "var nc=Math.ceil(out.length/BS);"
            "post('fetch_meta',{count:out.length,chunks:nc});"
            "for(var ci=0;ci<nc;ci++){"
            "post('fetch_c'+ci,{msgs:out.slice(ci*BS,(ci+1)*BS)});}"
            "}).catch(function(e){post('fetch_error',{error:String(e)});});"
            "})()"
        )

    def _wait_for_fetch_beacon(self, timeout=30):
        """等待 beacon 回调并收集消息，返回 raw messages list 或 None"""
        meta = None
        expected_chunks = 0
        for _ in range(timeout * 5):
            time.sleep(0.2)
            reports = self._beacon.get_reports()
            if 'fetch_error' in reports:
                err = reports['fetch_error']
                log(f'[fetch] JSAPI error: {err}')
                return None
            if 'fetch_meta' in reports and meta is None:
                meta = reports['fetch_meta']
                expected_chunks = meta.get('chunks', 0) if isinstance(meta, dict) else 0
            if meta is not None:
                received = sum(1 for k in reports if k.startswith('fetch_c'))
                if received >= expected_chunks:
                    break

        reports = self._beacon.get_reports()
        if not meta:
            return None

        msgs_raw = []
        for ci in range(expected_chunks):
            chunk = reports.get(f'fetch_c{ci}')
            if chunk and isinstance(chunk, dict):
                msgs_raw.extend(chunk.get('msgs', []))
        return msgs_raw

    def probe_listmsg_raw(self, cid, count=1, timeout=30):
        """dump listMessage 返回的完整原始对象结构"""
        bid = self._find_jsapi_browser()
        if not bid:
            return {'success': False, 'error': 'No JSAPI browser found'}

        self._beacon.clear()
        cid_safe = js_escape(cid)
        js = (
            "(function(){"
            "var P=" + str(BEACON_PORT) + ";"
            "function post(l,d){var b=JSON.stringify(d);"
            "fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:b,mode:'no-cors'}).catch(function(){});}"
            "function promisify(fn,ctx){"
            "return function(){"
            "var a=Array.prototype.slice.call(arguments);"
            "return new Promise(function(ok,fail){"
            "a.push(function(e,r){e?fail(e):ok(r);});"
            "fn.apply(ctx,a);"
            "});};"
            "}"
            "if(!dingtalk||!dingtalk.message||!dingtalk.message.listMessage){"
            "post('rdump_err',{error:'no_api'});return;}"
            "var lm=promisify(dingtalk.message.listMessage,dingtalk.message);"
            "lm('" + cid_safe + "',String(Number.MAX_SAFE_INTEGER),"
            + str(min(count, 5)) + ",false,{isFirstPull:true})"
            ".then(function(msgs){"
            "if(!msgs||!msgs.length){post('rdump',{count:0});return;}"
            "var m=msgs[0];"
            "post('rdump_keys',{top:Object.keys(m)});"
            "var bm=m.baseMessage;"
            "if(bm)post('rdump_bm_keys',{keys:Object.keys(bm)});"
            "try{var s=JSON.stringify(m);"
            "var cs=4000,n=Math.ceil(s.length/cs);"
            "post('rdump_meta',{len:s.length,parts:n});"
            "for(var i=0;i<n&&i<20;i++){"
            "post('rdump_c'+i,{d:s.substr(i*cs,cs)});}"
            "}catch(e){post('rdump_err',{error:'stringify:'+e});}"
            "}).catch(function(e){post('rdump_err',{error:String(e)});});"
            "})()"
        )

        try:
            self._cef_script.exports_sync.exec_js(bid, js)
        except Exception as e:
            return {'success': False, 'error': f'exec_js failed: {e}'}

        for _ in range(timeout * 2):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if any(k.startswith('rdump') for k in reports):
                break

        reports = self._beacon.get_reports()
        if 'rdump_err' in reports:
            return {'success': False, 'error': reports['rdump_err']}

        result = {
            'success': True,
            'top_keys': reports.get('rdump_keys', {}),
            'base_message_keys': reports.get('rdump_bm_keys', {}),
            'meta': reports.get('rdump_meta', {}),
        }

        full = ''
        for i in range(20):
            chunk = reports.get(f'rdump_c{i}')
            if chunk and isinstance(chunk, dict):
                full += chunk.get('d', '')
        if full:
            try:
                result['raw_object'] = json.loads(full)
            except json.JSONDecodeError:
                result['raw_truncated'] = full[:2000]

        dump_path = os.path.join(DATA_DIR, '_probe_listmsg_result.json')
        try:
            with open(dump_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            result['saved_to'] = dump_path
        except Exception:
            pass

        return result

    def search_log(self, keyword, limit=30):
        if not os.path.exists(LOG_FILE):
            return []
        results = []
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if not keyword or keyword in line:
                    results.append(line.rstrip())
                    if len(results) > limit * 3:
                        results = results[-limit:]
        return results[-limit:]

    def find_conversation(self, name, limit=100):
        from lib.utils import ContactsDB

        cid_map = {}

        for entry in ContactsDB.search(name):
            cid_map[entry['cid']] = {
                'cid': entry['cid'],
                'sender': entry.get('name', '未知'),
                'uid': entry.get('uid', ''),
                'time': entry.get('last_seen', ''),
                'preview': f"[联系人库] {entry.get('type','')}, 消息数: {entry.get('msg_count',0)}",
            }

        lines = self.search_log(name, limit)
        for line in lines:
            try:
                obj = json.loads(line)
                if obj.get('cid') and obj['cid'] not in cid_map:
                    existing = cid_map.get(obj['cid'])
                    if not existing or (obj.get('time', '') > existing.get('time', '')):
                        cid_map[obj['cid']] = {
                            'cid': obj['cid'],
                            'sender': obj.get('sender', '未知'),
                            'time': obj.get('time', ''),
                            'preview': (obj.get('text', '') or '')[:60],
                        }
            except Exception:
                pass

        if not cid_map:
            for entry in self._lookup_contacts_db(name):
                cid_map[entry['cid']] = entry

        return list(cid_map.values())

    @staticmethod
    def _lookup_contacts_db(name):
        """Fallback: search contacts.json for contacts by name"""
        contacts_file = os.path.join(DATA_DIR, 'contacts.json')
        if not os.path.exists(contacts_file):
            return []
        try:
            with open(contacts_file, 'r', encoding='utf-8') as f:
                contacts = json.load(f)
            kw = name.lower()
            results = []
            for section_key in ('p2p', 'group'):
                section = contacts.get(section_key, {})
                if not isinstance(section, dict):
                    continue
                for entry in section.values():
                    entry_name = entry.get('name', '')
                    if kw in entry_name.lower():
                        results.append({
                            'cid': entry['cid'],
                            'sender': entry_name,
                            'time': '',
                            'preview': f'[contacts.json] {section_key}',
                        })
            return results
        except Exception:
            return []

    def health(self):
        dt_running = bool(get_main_pid())
        return {
            'daemon': 'running',
            'port': DAEMON_PORT,
            'pid': os.getpid(),
            'dingtalk_pid': self._pid,
            'dingtalk_running': dt_running,
            'frida_attached': self.is_attached,
            'cef_ready': self._cef_ready,
            'monitor_running': self._monitor_ready,
            'monitor_messages': self._monitor_count,
            'fetch_mode': 'jsapi',
            'fetches': self._fetch_count,
            'sends': self._send_count,
            'uptime_seconds': int(time.time() - self._attach_time) if self._attach_time else 0,
            'log_file': LOG_FILE,
            'log_exists': os.path.exists(LOG_FILE),
        }

    # ── Watchdog ──

    def start_watchdog(self):
        self._running = True
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self):
        while self._running:
            time.sleep(WATCHDOG_INTERVAL)
            if not self._running:
                break
            try:
                pid = get_main_pid()
                if not pid:
                    log('[watchdog] DingTalk 未运行，尝试启动...')
                    self._start_dingtalk()
                    time.sleep(10)
                    pid = get_main_pid()
                    if pid:
                        log(f'[watchdog] DingTalk 已启动 PID={pid}')

                if pid and not self.is_attached:
                    log('[watchdog] Frida session 断开，重新附加...')
                    self.attach()
                    if self._monitor_ready or self._monitor_script:
                        self.start_monitor()
                    self.start_name_resolver()

                if self.is_attached:
                    try:
                        r = self._cef_script.exports_sync.ping()
                        if r != 'pong':
                            raise Exception('ping failed')
                    except Exception:
                        log('[watchdog] CEF ping 失败，重新附加...')
                        self._cleanup()
                        self.attach()
            except Exception as e:
                log(f'[watchdog] 错误: {e}')

    def _start_dingtalk(self):
        import subprocess
        dt_path = os.path.join(
            os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
            'DingDing', 'main', 'current', 'DingTalk.exe',
        )
        if os.path.exists(dt_path):
            try:
                subprocess.Popen([dt_path], creationflags=0x00000008)
                log(f'[watchdog] 已启动 DingTalk: {dt_path}')
            except Exception as e:
                log(f'[watchdog] 启动 DingTalk 失败: {e}')

    def shutdown(self):
        self._running = False
        self._cleanup()
        self._beacon.stop()


# ── HTTP API 服务器 ──

_daemon = FridaDaemon()

class DaemonHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == '/health':
            self._json_response(_daemon.health())

        elif parsed.path == '/api/health':
            self._json_response({
                'status': 'ok',
                'app': 'dingtalk-daemon',
                'version': APP_VERSION,
            })

        elif parsed.path == '/api/version':
            files = {}
            latest = 0.0
            for f in _KEY_FILES:
                try:
                    fpath = os.path.join(_PROJECT_ROOT, f)
                    mtime = os.path.getmtime(fpath)
                    files[f] = datetime.fromtimestamp(mtime).strftime(
                        '%Y-%m-%d %H:%M:%S')
                    latest = max(latest, mtime)
                except OSError:
                    pass
            self._json_response({
                'app_version': APP_VERSION,
                'server_start': _server_start_time,
                'last_update': datetime.fromtimestamp(latest).strftime(
                    '%m/%d %H:%M') if latest else '',
                'last_update_ts': int(latest) if latest else 0,
                'files': files,
            })

        elif parsed.path == '/search':
            keyword = params.get('keyword', [''])[0]
            limit = int(params.get('limit', ['30'])[0])
            lines = _daemon.search_log(keyword, limit)
            if not lines:
                self._json_response({'count': 0, 'results': []})
            else:
                self._json_response({'count': len(lines), 'results': lines})

        elif parsed.path == '/contacts':
            from lib.utils import ContactsDB
            name = params.get('name', [''])[0]
            if name:
                entries = _daemon.find_conversation(name)
            else:
                entries = ContactsDB.get_all()
            self._json_response({'count': len(entries), 'results': entries})

        elif parsed.path == '/debug/scan_browsers':
            if not _daemon._cef_script:
                self._json_response({'error': 'frida not attached'}, 503)
                return
            try:
                bids = _daemon._cef_script.exports_sync.scan_browsers()
                b1_url = _daemon._read_browser1_url()
                self._json_response({
                    'browser_ids': list(bids),
                    'jsapi_bid': _daemon._cached_jsapi_bid or 1,
                    'browser1_url': b1_url,
                })
            except Exception as e:
                self._json_response({'error': str(e)}, 500)

        else:
            self._json_response({'error': 'Not found'}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self._read_body()

        if parsed.path == '/send':
            cid = body.get('cid', '')
            name = body.get('name', '')
            message = body.get('message', '')
            if not message:
                self._json_response({'error': 'message required'}, 400)
                return
            if not cid and name:
                cid, resolved = _daemon.resolve_cid(name)
                if not cid:
                    self._json_response({'error': f'找不到 "{name}" 的会话'}, 404)
                    return
                body['resolved_name'] = resolved
            if not cid:
                self._json_response({'error': 'cid or name required'}, 400)
                return
            result = _daemon.send_message(cid, message)
            if body.get('resolved_name'):
                result['resolved_name'] = body['resolved_name']
                result['resolved_cid'] = cid
            self._json_response(result)

        elif parsed.path == '/fetch':
            cid = body.get('cid', '')
            name = body.get('name', '')
            count = int(body.get('count', 20))
            before = body.get('before')
            after = body.get('after')
            if not cid and name:
                cid, resolved = _daemon.resolve_cid(name)
                if not cid:
                    self._json_response({'error': f'找不到 "{name}" 的会话'}, 404)
                    return
            if not cid:
                self._json_response({'error': 'cid or name required'}, 400)
                return
            result = _daemon.fetch_history(cid, count, before=before, after=after)
            self._json_response(result)

        elif parsed.path == '/monitor/start':
            ok = _daemon.start_monitor()
            self._json_response({'ok': ok})

        elif parsed.path == '/fetch_reports':
            count = int(body.get('count', 10))
            before = body.get('before')
            after = body.get('after')
            author = body.get('author')
            report_type = body.get('report_type')
            max_pages = int(body.get('max_pages', 20))
            cid = body.get('cid')
            result = _daemon.fetch_reports_paginated(
                count=count, before=before, after=after,
                author=author, report_type=report_type, max_pages=max_pages,
                cid=cid)
            self._json_response(result)

        elif parsed.path == '/fetch_my_reports':
            count = int(body.get('count', 5))
            before = body.get('before')
            after = body.get('after')
            report_type = body.get('report_type')
            full_content = body.get('full_content', False)
            result = _daemon.fetch_my_reports(
                count=count, before=before, after=after,
                report_type=report_type, full_content=full_content)
            self._json_response(result)

        elif parsed.path == '/fetch_report_content':
            url = body.get('url', '')
            if not url:
                self._json_response({'error': 'url required'}, 400)
                return
            result = _daemon.fetch_report_content(url)
            self._json_response(result)

        elif parsed.path == '/probe_jsapi':
            result = _daemon.probe_jsapi(timeout=10)
            self._json_response(result)

        elif parsed.path == '/exec_js':
            js = body.get('js', '')
            label = body.get('label', 'exec_result')
            timeout = int(body.get('timeout', 10))
            if not js:
                self._json_response({'error': 'js required'}, 400)
                return
            result = _daemon.exec_custom_js(js, label=label, timeout=timeout)
            self._json_response(result)

        elif parsed.path == '/probe_listmsg':
            cid = body.get('cid', '')
            if not cid:
                self._json_response({'error': 'cid required'}, 400)
                return
            result = _daemon.probe_listmsg_raw(cid, count=int(body.get('count', 1)))
            self._json_response(result)

        elif parsed.path == '/enrich':
            _daemon.start_name_resolver()
            result = _daemon.enrich_contacts()
            self._json_response({'ok': True, **result})

        elif parsed.path == '/reload_contacts':
            result = ContactsDB.reload()
            self._json_response({'ok': True, **result})

        elif parsed.path == '/conv_info':
            cid = body.get('cid', '')
            if not cid:
                self._json_response({'error': 'cid required'}, 400)
                return
            result = _daemon.get_conversation_info(cid)
            self._json_response(result)

        elif parsed.path == '/shutdown':
            self._json_response({'ok': True, 'msg': 'shutting down'})
            threading.Thread(target=_shutdown_server, daemon=True).start()

        else:
            self._json_response({'error': 'Not found'}, 404)

    def _read_body(self):
        cl = int(self.headers.get('Content-Length', 0))
        if cl == 0:
            return {}
        raw = self.rfile.read(cl).decode('utf-8', errors='replace')
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


_http_server = None

def _shutdown_server():
    time.sleep(0.5)
    _daemon.shutdown()
    if _http_server:
        _http_server.shutdown()


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[daemon][{ts}] {msg}', flush=True)


def main():
    global _http_server

    log(f'启动 Frida Daemon on port {DAEMON_PORT}')
    log(f'Beacon port: {BEACON_PORT}')
    log(f'Log file: {LOG_FILE}')

    _daemon._beacon.start()
    log('Beacon 服务器已启动')

    if _daemon.attach():
        log('Frida 已附加，CEF 就绪')
        _daemon.start_monitor()
    else:
        log('初始附加失败，watchdog 将自动重试')

    _daemon.start_watchdog()
    _daemon.start_name_resolver()
    log('Watchdog + NameResolver 已启动')

    _start_skill_router()
    log('SkillRouter 已启动')

    _http_server = HTTPServer(('127.0.0.1', DAEMON_PORT), DaemonHandler)
    log(f'HTTP API 就绪: http://127.0.0.1:{DAEMON_PORT}')
    log('端点: GET /health | POST /send | POST /fetch | GET /search | GET /contacts | POST /shutdown')

    def handle_signal(sig, frame):
        log('收到停止信号')
        from lib.utils import ContactsDB
        ContactsDB.flush()
        _daemon.shutdown()
        _http_server.shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        _http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _daemon.shutdown()
        log('已停止')


if __name__ == '__main__':
    main()
