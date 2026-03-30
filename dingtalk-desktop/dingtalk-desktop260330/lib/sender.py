# -*- coding: utf-8 -*-
"""
钉钉消息发送器 — 通过 Frida + libcef.dll 注入 JS 调用 JSAPI
重构自 dt_jsapi_send.py
"""
import time
import json
import urllib.parse
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from .utils import get_main_pid, js_escape, ADV_SEARCH_URL, DEFAULT_MY_UID

# --------------- Beacon 回调服务器 ---------------

class _BeaconServer:
    """轻量 HTTP beacon，接收 JS 注入的回调结果"""

    def __init__(self, port=18899):
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
                body = (self.rfile.read(cl).decode('utf-8', errors='replace')
                        if cl > 0 else '')
                parent.received.append(self.path + '|' + body)
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'ok')

            def log_message(self, *a):
                pass

        self._server = HTTPServer(('127.0.0.1', self.port), H)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()

    def get_reports(self):
        reports = {}
        for path in self.received:
            base = path.split('|')[0]
            body = path.split('|')[1] if '|' in path else ''
            if '/r?' not in base and '/b?' not in base:
                continue
            params = urllib.parse.parse_qs(urllib.parse.urlparse(base).query)
            label = params.get('l', ['?'])[0]
            data_raw = params.get('d', [''])[0] or body
            try:
                data = json.loads(data_raw)
            except Exception:
                data = data_raw
            if label in reports:
                if not isinstance(reports[label], list):
                    reports[label] = [reports[label]]
                reports[label].append(data)
            else:
                reports[label] = data
        return reports

    def clear(self):
        self.received.clear()

# --------------- Frida CEF 注入模板 ---------------

_FRIDA_INJECT_TEMPLATE = r"""
var libcef = null;
Process.enumerateModules().forEach(function(m) {
    if (m.name.toLowerCase() === 'libcef.dll') libcef = m;
});
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

function execJS(browserId, js) {
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

function loadUrl(browserId, url) {
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
}

__ACTION__
"""

# --------------- DingTalkSender ---------------

class DingTalkSender:
    """钉钉消息发送器 — 纯 JSAPI，无需 UI 自动化"""

    def __init__(self, beacon_port=18899, my_uid=None):
        self._port = beacon_port
        self._beacon = _BeaconServer(beacon_port)
        self._beacon.start()
        self._my_uid = my_uid or DEFAULT_MY_UID
        self._pid = None
        self._b1_verified = False

    def send_text(self, target_uid, text, timeout=12):
        """
        单聊发送文本消息

        Args:
            target_uid: 目标用户 UID
            text: 消息文本
            timeout: 等待超时秒数

        Returns:
            dict: {'success': bool, 'cid': str, ...}
        """
        cid = f'{self._my_uid}:{target_uid}'
        return self._send(cid, text, timeout)

    def send_to_group(self, group_cid, text, timeout=12):
        """
        群聊发送文本消息

        Args:
            group_cid: 群 CID（纯数字字符串）
            text: 消息文本
            timeout: 等待超时秒数

        Returns:
            dict: {'success': bool, 'cid': str, ...}
        """
        return self._send(group_cid, text, timeout)

    def close(self):
        self._beacon.stop()

    # ---------- internal ----------

    def _send(self, cid, text, timeout):
        pid = get_main_pid()
        if not pid:
            return {'success': False, 'error': 'DingTalk not running', 'cid': cid}

        if not self._b1_verified:
            if not self._ensure_b1(pid):
                return {'success': False, 'error': 'B1 restore failed', 'cid': cid}

        self._beacon.clear()
        safe = js_escape(text)
        js = (
            f"(function(){{var P={self._port};"
            "function r(l,d){navigator.sendBeacon('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "JSON.stringify(d));}"
            "if(typeof dingtalk==='undefined'||!dingtalk.message||!dingtalk.message.sendTextMsg){"
            "r('error','no_api');return;}"
            f"dingtalk.message.sendTextMsg('{cid}','{safe}','',function(res){{r('cb',res);}});"
            "r('sent','ok');"
            "setTimeout(function(){r('done','timeout');},8000);"
            "})()"
        )

        result = self._exec_on_b1(pid, js)
        if result != 'ok':
            self._b1_verified = False
            if self._ensure_b1(pid):
                result = self._exec_on_b1(pid, js)

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.3)
            reports = self._beacon.get_reports()
            if 'cb' in reports or 'error' in reports or 'done' in reports:
                break

        reports = self._beacon.get_reports()
        sent = 'sent' in reports
        error = reports.get('error')
        return {
            'success': sent and not error,
            'cid': cid,
            'callback': reports.get('cb'),
            'error': error,
        }

    def _ensure_b1(self, pid):
        """检查 B1 是否在 advancedSearch.html，不在则恢复"""
        self._beacon.clear()
        check_js = (
            f"(function(){{navigator.sendBeacon('http://127.0.0.1:{self._port}"
            "/b?l=url',JSON.stringify(location.href));"
            f"navigator.sendBeacon('http://127.0.0.1:{self._port}"
            "/b?l=api',JSON.stringify(typeof dingtalk!==\"undefined\""
            "&&!!dingtalk.message&&typeof dingtalk.message.sendTextMsg===\"function\"));"
            "})()"
        )
        self._exec_on_b1(pid, check_js)
        time.sleep(2)

        reports = self._beacon.get_reports()
        url = reports.get('url', '')
        has_api = reports.get('api', False)

        if isinstance(url, str) and 'advancedSearch' in url and has_api:
            self._b1_verified = True
            return True

        self._load_url_on_b1(pid, ADV_SEARCH_URL)
        time.sleep(5)

        self._beacon.clear()
        self._exec_on_b1(pid, check_js)
        time.sleep(2)
        reports = self._beacon.get_reports()
        url = reports.get('url', '')
        has_api = reports.get('api', False)

        self._b1_verified = (isinstance(url, str)
                             and 'advancedSearch' in url and has_api)
        return self._b1_verified

    def _exec_on_b1(self, pid, js_code):
        action = f"send({{r: execJS(1, {json.dumps(js_code)})}});"
        return self._run_frida(pid, action)

    def _load_url_on_b1(self, pid, url):
        action = f"send({{r: loadUrl(1, {json.dumps(url)})}});"
        return self._run_frida(pid, action)

    def _run_frida(self, pid, action_code):
        import frida
        frida_src = _FRIDA_INJECT_TEMPLATE.replace('__ACTION__', action_code)
        result = 'unknown'
        try:
            session = frida.attach(pid)

            def on_msg(msg, data):
                nonlocal result
                if msg['type'] == 'send' and 'r' in msg['payload']:
                    result = msg['payload']['r']

            script = session.create_script(frida_src)
            script.on('message', on_msg)
            script.load()
            time.sleep(1)
            script.unload()
            session.detach()
        except Exception as e:
            result = f'frida_err:{e}'
        return result
