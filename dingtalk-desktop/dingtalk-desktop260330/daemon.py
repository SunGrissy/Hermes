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
  GET  /contacts  ?name=               → 按显示姓名精确查 CID（多条则 409）
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
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from lib.utils import (
    get_main_pid, get_main_pid_by_mem, js_escape, normalize,
    ADV_SEARCH_URL, DEFAULT_MY_UID, DATA_DIR, DedupTracker,
    deep_decode, fmt_time, CT_NAMES, ContactsDB,
)


def _load_skill_config():
    """Load personal config from config.json next to daemon.py."""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

_SKILL_CFG = _load_skill_config()

DAEMON_PORT = int(os.environ.get('DINGTALK_DAEMON_PORT', '19200'))
BEACON_PORT = int(os.environ.get('DINGTALK_BEACON_PORT', '18899'))
MY_UID = os.environ.get('DINGTALK_MY_UID', '') or _SKILL_CFG.get('my_uid', '') or DEFAULT_MY_UID
EVENT_GATEWAY_URL = os.environ.get('DINGTALK_EVENT_GATEWAY', 'http://127.0.0.1:18789/api/events/ingest')
REPORT_CID = os.environ.get('DINGTALK_REPORT_CID', '') or _SKILL_CFG.get('report_cid', '')
MY_REPORT_GROUP_CID = os.environ.get('DINGTALK_MY_REPORT_GROUP_CID', '') or _SKILL_CFG.get('my_report_group_cid', '')
SILENT_DL_DIR = os.environ.get('DINGTALK_SILENT_DL_DIR', '') or _SKILL_CFG.get('silent_download_dir', '') or os.path.join(os.path.expanduser('~'), 'Downloads', 'DingTalkFiles')

LOG_FILE = os.environ.get(
    'DINGTALK_LOG_FILE',
    os.path.join(DATA_DIR, '_msg_log.jsonl'),
)
WATCHDOG_INTERVAL = 30


# ── 多媒体消息解析辅助 ──

def _resolve_image_local_path(url):
    """Decode local file path from DingTalk loc:// URL.
    Format: http://loc.dingtalk.com/<hash><base64>
    The base64 portion decodes to the local image cache path."""
    import base64 as b64mod
    if not url or 'loc.dingtalk.com' not in url:
        return ''
    try:
        raw_path = urllib.parse.urlparse(url).path.lstrip('/')
        if not raw_path:
            return ''
        for prefix_len in (0, 32, 40, 64):
            if prefix_len >= len(raw_path):
                continue
            candidate = raw_path[prefix_len:]
            try:
                padded = candidate + '=' * (-len(candidate) % 4)
                decoded = b64mod.b64decode(padded).decode('utf-8', errors='replace')
                if decoded and ('\\' in decoded or '/' in decoded):
                    if os.path.exists(decoded):
                        return decoded
                    if decoded[1:3] == ':\\' or decoded.startswith('/'):
                        return decoded
            except Exception:
                continue
    except Exception:
        pass
    return ''


def _mediaid_to_cdn_url(mediaid_raw, width=None, height=None, fmt=None):
    """Convert DingTalk mediaId to a public CDN download URL.
    mediaid_raw: raw mediaId string (e.g. '@lQL...' or 'mediaId://@lQL...')
    width/height: image dimensions (required; extracted from MsgPack if not given)
    fmt: image format like 'png', 'jpg' (falls back to 'png')
    Returns URL string or empty string on failure."""
    import base64 as b64mod
    import msgpack
    mid = mediaid_raw
    if mid.startswith('mediaId://'):
        mid = mid[len('mediaId://'):]
    no_prefix = mid.lstrip('@')
    if not no_prefix:
        return ''
    if width and height and fmt:
        return f'https://static.dingtalk.com/media/{no_prefix}_{width}_{height}.{fmt}'
    try:
        b64s = no_prefix.replace('-', '+').replace('_', '/')
        b64s += '=' * (-len(b64s) % 4)
        raw = b64mod.b64decode(b64s)
        arr = msgpack.unpackb(raw, raw=True)
        h = arr[2] if len(arr) > 2 else height
        w = arr[3] if len(arr) > 3 else width
        if w and h:
            ext = fmt or 'png'
            return f'https://static.dingtalk.com/media/{no_prefix}_{w}_{h}.{ext}'
    except Exception:
        pass
    return ''


_IMAGE_CACHE_DIR = os.path.join(DATA_DIR, 'cache', 'images')
os.makedirs(_IMAGE_CACHE_DIR, exist_ok=True)


def _download_cdn_image(cdn_url):
    """Download a CDN image to local cache, return local path.
    Uses URL hash as filename to avoid re-downloading."""
    import hashlib
    if not cdn_url or not cdn_url.startswith('https://'):
        return ''
    url_hash = hashlib.md5(cdn_url.encode()).hexdigest()[:16]
    ext = cdn_url.rsplit('.', 1)[-1] if '.' in cdn_url.rsplit('/', 1)[-1] else 'png'
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'):
        ext = 'png'
    local_path = os.path.join(_IMAGE_CACHE_DIR, f'{url_hash}.{ext}')
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path
    try:
        req = urllib.request.Request(cdn_url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        with open(local_path, 'wb') as f:
            f.write(resp.read())
        return local_path
    except Exception as e:
        log(f'[image-cache] download failed {cdn_url[:60]}: {e}')
        return ''


_FILE_CACHE_DIR = os.path.join(DATA_DIR, 'cache', 'files')
os.makedirs(_FILE_CACHE_DIR, exist_ok=True)

_DT_ACCESS_TOKEN = ''
_DT_TOKEN_EXPIRES = 0


def _get_dingtalk_access_token():
    """Get access token from ultraai.config.json robot credentials."""
    global _DT_ACCESS_TOKEN, _DT_TOKEN_EXPIRES
    import time as _t
    if _DT_ACCESS_TOKEN and _t.time() < _DT_TOKEN_EXPIRES:
        return _DT_ACCESS_TOKEN
    try:
        cfg_path = os.path.join(os.path.dirname(DATA_DIR), 'ultraai.config.json')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.loads(f.read())
        dt_cfg = cfg.get('channels', {}).get('dingtalk', {})
        app_key = dt_cfg.get('appKey', '')
        app_secret = dt_cfg.get('appSecret', '')
        if not app_key or not app_secret:
            return ''
        body = json.dumps({'appKey': app_key, 'appSecret': app_secret}).encode()
        req = urllib.request.Request(
            'https://api.dingtalk.com/v1.0/oauth2/accessToken',
            data=body, headers={'Content-Type': 'application/json'},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        _DT_ACCESS_TOKEN = result.get('accessToken', '')
        _DT_TOKEN_EXPIRES = _t.time() + result.get('expireIn', 7200) - 300
        return _DT_ACCESS_TOKEN
    except Exception as e:
        log(f'[token] 获取 access_token 失败: {e}')
        return ''


def _get_user_union_id(uid):
    """Get unionId for a DingTalk internal UID via oapi."""
    token = _get_dingtalk_access_token()
    if not token:
        return ''
    try:
        url = f'https://oapi.dingtalk.com/topapi/v2/user/get?access_token={token}'
        body = json.dumps({'userid': str(uid)}).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get('result', {}).get('unionid', '')
    except Exception:
        return ''


def _try_download_im_file(f_id, s_id, f_name, f_type):
    """Try to download an IM file using storage API. Returns local path or ''."""
    if not f_id or not s_id:
        return ''
    safe_name = f_name.replace('/', '_').replace('\\', '_').replace(':', '_')
    if not safe_name:
        safe_name = f'{f_id}.{f_type}' if f_type else str(f_id)
    local_path = os.path.join(_FILE_CACHE_DIR, f'{f_id}_{safe_name}')
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    token = _get_dingtalk_access_token()
    if not token:
        log(f'[file-dl] 无 access_token，跳过下载 {f_name}')
        return ''

    # Need a unionId — try current user (MY_UID)
    union_id = _get_user_union_id(MY_UID)
    if not union_id:
        log(f'[file-dl] 无法获取 unionId (uid={MY_UID})，跳过下载 {f_name}')
        return ''

    try:
        url = (
            f'https://api.dingtalk.com/v1.0/storage/spaces/{s_id}'
            f'/dentries/{f_id}/downloadInfos/query?unionId={union_id}'
        )
        req = urllib.request.Request(
            url, data=b'{}',
            headers={
                'Content-Type': 'application/json',
                'x-acs-dingtalk-access-token': token,
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        dl_info = json.loads(resp.read())
        sig_info = dl_info.get('headerSignatureInfo', {})
        dl_urls = sig_info.get('resourceUrls', [])
        dl_headers = sig_info.get('headers', {})
        if not dl_urls:
            log(f'[file-dl] storage API 未返回下载 URL: {dl_info}')
            return ''
        dl_req = urllib.request.Request(dl_urls[0])
        for k, v in dl_headers.items():
            dl_req.add_header(k, v)
        dl_resp = urllib.request.urlopen(dl_req, timeout=60)
        with open(local_path, 'wb') as f:
            f.write(dl_resp.read())
        log(f'[file-dl] 下载成功: {f_name} → {local_path} ({os.path.getsize(local_path)}B)')
        return local_path
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, 'read'):
            try:
                err_msg = e.read().decode('utf-8', errors='replace')
            except Exception:
                pass
        log(f'[file-dl] storage API 下载失败 {f_name}: {err_msg[:200]}')
        return ''


def _extract_markdown_text(raw_json):
    """Extract text from ct=1200 Markdown content JSON.
    DingTalk stores markdown replies in attachments[0].extension.markdown/title."""
    try:
        ct_obj = json.loads(raw_json)
        for key in ('markdownContent', 'richTextContent', 'textContent'):
            sub = ct_obj.get(key)
            if isinstance(sub, dict) and sub.get('text'):
                return sub['text']
        atts = ct_obj.get('attachments') or []
        if atts and isinstance(atts, list):
            ext = (atts[0] if isinstance(atts[0], dict) else {}).get('extension', {})
            md = ext.get('markdown', '')
            title = ext.get('title', '')
            if md:
                return _parse_dingtalk_markdown_reply(md, title)
            if title:
                return title
    except Exception:
        pass
    return ''


def _parse_dingtalk_markdown_reply(md_text, title=''):
    """Parse DingTalk reply markdown format:
    > ###### SenderName
    > QuotedText
    ----
    #### ReplyText
    Returns: '[回复 Sender: "QuotedPreview"] ReplyText'
    """
    lines = md_text.split('\n')
    quote_sender = ''
    quote_lines = []
    reply_lines = []
    in_quote = True
    past_separator = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('---') or stripped.startswith('───'):
            past_separator = True
            in_quote = False
            continue
        if in_quote and stripped.startswith('> '):
            content = stripped[2:].strip()
            if content.startswith('###### '):
                quote_sender = content[7:].strip()
            else:
                quote_lines.append(content)
        elif past_separator:
            content = stripped.lstrip('#').strip()
            if content:
                reply_lines.append(content)

    reply_text = ' '.join(reply_lines) if reply_lines else title or ''
    if quote_sender or quote_lines:
        quote_preview = ' '.join(quote_lines)[:60]
        prefix = f'[回复 {quote_sender}: "{quote_preview}"] ' if quote_sender else f'[回复: "{quote_preview}"] '
        return prefix + reply_text
    return reply_text


def _extract_richtext_text(raw_json, image_urls_out=None):
    """Extract text from ct=3100 rich text content.
    DingTalk stores rich text in attachments[0].extension.payload (JSON items array).
    image_urls_out: optional list to collect image mediaId URLs."""
    try:
        ct_obj = json.loads(raw_json)
        # Legacy format: richTextContent at top level
        rtc = ct_obj.get('richTextContent', {})
        if isinstance(rtc, dict):
            if rtc.get('text'):
                return rtc['text']
            nodes = rtc.get('richTextNodes') or rtc.get('richText') or []
            if isinstance(nodes, list) and nodes:
                return _richtext_nodes_to_text(nodes, image_urls_out)

        # DingTalk actual format: attachments[0].extension.payload
        atts = ct_obj.get('attachments') or []
        if atts and isinstance(atts, list):
            ext = (atts[0] if isinstance(atts[0], dict) else {}).get('extension', {})
            payload_str = ext.get('payload', '')
            if payload_str:
                try:
                    payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
                    items = payload.get('items', [])
                    parts = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        itype = item.get('type', '')
                        val = item.get('value', {})
                        if itype == 'rt' and isinstance(val, dict):
                            for run in val.get('textRuns', []):
                                t = run.get('text', '')
                                if t:
                                    parts.append(t)
                        elif itype in ('img', 'image') and isinstance(val, dict):
                            src = val.get('src', '')
                            w = val.get('width')
                            h = val.get('height')
                            cdn = _mediaid_to_cdn_url(src, w, h) if src else ''
                            parts.append('[图片]')
                            if image_urls_out is not None and (cdn or src):
                                image_urls_out.append(cdn or src)
                    if parts:
                        return ''.join(parts)
                except (json.JSONDecodeError, TypeError):
                    pass
            desc = ext.get('desc', '')
            if desc:
                return desc

        for key in ('textContent', 'markdownContent'):
            sub = ct_obj.get(key)
            if isinstance(sub, dict) and sub.get('text'):
                return sub['text']
    except Exception:
        pass
    return ''


def _richtext_nodes_to_text(nodes, image_urls_out=None):
    """Parse richTextNodes array into text."""
    parts = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        t = node.get('text', '') or node.get('content', '')
        if t:
            parts.append(t)
        elif node.get('type') == 'at' or node.get('userId'):
            name = node.get('name') or node.get('userId') or ''
            parts.append(f'@{name}')
        elif node.get('type') in ('image', 'img'):
            parts.append('[图片]')
            if image_urls_out is not None:
                src = node.get('src', '') or node.get('url', '')
                if src:
                    image_urls_out.append(src)
    return ''.join(parts) if parts else ''


def _parse_quote_msg(ext_s):
    """Parse quoted/replied message info from extension quoteMsg field."""
    if not ext_s:
        return None
    try:
        qm = json.loads(ext_s) if isinstance(ext_s, str) else ext_s
        if isinstance(qm, str):
            qm = json.loads(qm)
        if not isinstance(qm, dict):
            return None

        sender = qm.get('senderNick', '') or qm.get('sender', '') or qm.get('senderOpenId', '')
        text = ''
        content_obj = qm.get('content', {})
        if isinstance(content_obj, dict):
            for key in ('textContent', 'richTextContent', 'markdownContent'):
                sub = content_obj.get(key)
                if isinstance(sub, dict) and sub.get('text'):
                    text = sub['text']
                    break
            if not text:
                text = content_obj.get('text', '')
        elif isinstance(content_obj, str):
            text = content_obj
        if not text:
            text = qm.get('text', '') or qm.get('origin_text', '')

        ts = qm.get('createAt', 0) or qm.get('createdAt', 0)
        ct = 0
        if isinstance(content_obj, dict):
            ct = content_obj.get('contentType', 0)

        return {
            'sender': sender,
            'text': text[:500] if text else '',
            'ts': ts,
            'content_type': ct,
        }
    except Exception:
        return None


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
        getBrowserUrl: function(browserId) {
            try {
                var b = fn_getBrowser(browserId);
                if (b.isNull()) return null;
                var fp = b.add(160).readPointer();
                var fnFrame = new NativeFunction(fp, 'pointer', ['pointer']);
                var f = fnFrame(b);
                if (f.isNull()) return null;
                /* Try multiple offsets for CefFrame::GetURL() */
                var offsets = [200, 192, 208, 176, 184, 216];
                for (var oi = 0; oi < offsets.length; oi++) {
                    try {
                        var off = offsets[oi];
                        var fnPtr = f.add(off).readPointer();
                        if (fnPtr.isNull()) continue;
                        var fn = new NativeFunction(fnPtr, 'pointer', ['pointer']);
                        var result = fn(f);
                        if (result.isNull()) continue;
                        var strPtr = result.readPointer();
                        var strLen = result.add(8).readU64();
                        if (strPtr.isNull() || strLen < 3 || strLen > 2000) continue;
                        var url = strPtr.readUtf16String(strLen);
                        if (url && (url.indexOf('://') > 0 || url.indexOf('about:') === 0)) {
                            return url;
                        }
                    } catch(e2) { /* try next offset */ }
                }
                return 'no_url_found';
            } catch(e) { return 'err:' + e.message; }
        },
        ping: function() { return 'pong'; },
        testExecJs: function(browserId, jsCode, execOffset, loadOffset) {
            try {
                var b = fn_getBrowser(browserId);
                if (b.isNull()) return {error: 'no_browser'};
                var fp = b.add(160).readPointer();
                var fnFrame = new NativeFunction(fp, 'pointer', ['pointer']);
                var f = fnFrame(b);
                if (f.isNull()) return {error: 'no_frame'};

                /* read current URL at offset 200 */
                var getUrlFn = new NativeFunction(f.add(200).readPointer(), 'pointer', ['pointer']);
                var urlBefore = '';
                try {
                    var r = getUrlFn(f);
                    if (!r.isNull()) {
                        var sp = r.readPointer();
                        var sl = r.add(8).readU64();
                        if (!sp.isNull() && sl > 0 && sl < 5000)
                            urlBefore = sp.readUtf16String(sl);
                    }
                } catch(eu) {}

                /* try ExecuteJavaScript at given offset */
                var result = 'not_tried';
                if (execOffset >= 0) {
                    try {
                        var xp = f.add(execOffset).readPointer();
                        var xfn = new NativeFunction(xp, 'void', ['pointer', 'pointer', 'pointer', 'int']);
                        var c = makeCefStr(jsCode);
                        var u = makeCefStr('');
                        xfn(f, c, u, 0);
                        result = 'called_ok';
                    } catch(ex) { result = 'exec_err:' + ex.message; }
                }

                /* try LoadURL at given offset with a safe URL */
                var loadResult = 'not_tried';
                if (loadOffset >= 0) {
                    try {
                        var urlStr = makeCefStr('about:blank');
                        var lp = f.add(loadOffset).readPointer();
                        var lfn = new NativeFunction(lp, 'void', ['pointer', 'pointer']);
                        lfn(f, urlStr);
                        loadResult = 'called_ok';
                    } catch(el) { loadResult = 'load_err:' + el.message; }
                }

                /* wait a bit then read URL again */
                Thread.sleep(0.5);
                var urlAfter = '';
                try {
                    var r2 = getUrlFn(f);
                    if (!r2.isNull()) {
                        var sp2 = r2.readPointer();
                        var sl2 = r2.add(8).readU64();
                        if (!sp2.isNull() && sl2 > 0 && sl2 < 5000)
                            urlAfter = sp2.readUtf16String(sl2);
                    }
                } catch(eu2) {}

                return {
                    urlBefore: urlBefore,
                    urlAfter: urlAfter,
                    urlChanged: urlBefore !== urlAfter,
                    execResult: result,
                    loadResult: loadResult,
                    execOffset: execOffset,
                    loadOffset: loadOffset,
                };
            } catch(e) { return {error: e.message}; }
        },
        probeVtable: function(browserId) {
            try {
                var b = fn_getBrowser(browserId);
                if (b.isNull()) return {error: 'no_browser'};
                var fp = b.add(160).readPointer();
                var fnFrame = new NativeFunction(fp, 'pointer', ['pointer']);
                var f = fnFrame(b);
                if (f.isNull()) return {error: 'no_frame'};
                var results = {};
                for (var off = 0; off <= 320; off += 8) {
                    try {
                        var fnPtr = f.add(off).readPointer();
                        if (fnPtr.isNull()) { results[off] = 'null'; continue; }
                        var fn = new NativeFunction(fnPtr, 'pointer', ['pointer']);
                        var r = fn(f);
                        if (r.isNull()) { results[off] = 'ret_null'; continue; }
                        try {
                            var sp = r.readPointer();
                            var sl = r.add(8).readU64();
                            if (!sp.isNull() && sl >= 3 && sl < 5000) {
                                var s = sp.readUtf16String(sl);
                                if (s) { results[off] = 'STR:' + s.substring(0, 100); continue; }
                            }
                        } catch(es) {}
                        results[off] = 'ptr:' + r.toString();
                    } catch(e) { results[off] = 'err:' + e.message; }
                }
                return results;
            } catch(e) { return {error: e.message}; }
        },
    };

    // ── Hook GetSaveFileNameW for silent createTask downloads ──
    try {
        var comdlg = Process.getModuleByName('comdlg32.dll');
        var pGetSave = comdlg.getExportByName('GetSaveFileNameW');
        Interceptor.replace(pGetSave, new NativeCallback(function(lpofn) {
            try {
                var lpstrFile = lpofn.add(48).readPointer();
                var nMaxFile = lpofn.add(56).readU32();
                var proposed = '';
                if (!lpstrFile.isNull()) {
                    try { proposed = lpstrFile.readUtf16String(); } catch(e) {}
                }
                var safeName = proposed || 'download.bin';
                var saveDir = '""" + SILENT_DL_DIR.replace('\\', '\\\\') + """';
                var savePath = saveDir + '\\' + safeName;
                send({t:'dialog_intercepted', proposed: proposed, savePath: savePath});
                if (!lpstrFile.isNull() && savePath.length < nMaxFile - 1) {
                    lpstrFile.writeUtf16String(savePath);
                }
                return 1;
            } catch(e) {
                send({t:'dialog_error', msg: e.message});
                return 0;
            }
        }, 'int', ['pointer'], 'win64'));
        send({t: 'hook', api: 'GetSaveFileNameW', status: 'replaced'});
    } catch(e) {
        send({t: 'hook', api: 'GetSaveFileNameW', status: 'failed', error: e.message});
    }

    send({t: 'ready', msg: 'CEF script loaded'});
}
"""

# ── Monitor Frida 脚本 ──

from lib.monitor import _MONITOR_JS, _process_push, _process_send, set_event_callback

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


# ── 事件推送 ──

class EventDispatcher:
    """Debounces incoming messages by CID, fetches plaintext history via JSAPI,
    then pushes enriched events to Gateway. All enrichment happens in the daemon
    to eliminate a Gateway→daemon callback round-trip."""

    DEBOUNCE_SECONDS = 3
    IMAGE_DEBOUNCE_SECONDS = 15
    MAX_WAIT_SECONDS = 180
    DEFAULT_FETCH_COUNT = 20

    def __init__(self, daemon, gateway_url, my_uid):
        self._daemon = daemon
        self._url = gateway_url
        self._my_uid = my_uid
        self._pending = {}          # cid -> {'records': [...], 'deadline': float}
        self._lock = threading.Lock()
        self._thread = None
        self._running = False
        self._push_count = 0
        self._fetch_count = 0
        self._error_count = 0
        self._skip_count = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log(f'EventDispatcher started → {self._url} (debounce={self.DEBOUNCE_SECONDS}s)')

    def stop(self):
        self._running = False

    def enqueue(self, record):
        """Called from monitor callback (Frida message thread)."""
        cid = record.get('cid', '')
        if not cid:
            return

        if record.get('is_self', False):
            self._skip_count += 1
            return

        ct = record.get('content_type', 0)
        debounce = self.IMAGE_DEBOUNCE_SECONDS if ct == 203 else self.DEBOUNCE_SECONDS

        with self._lock:
            now = time.time()
            if cid in self._pending:
                self._pending[cid]['records'].append(record)
                new_deadline = now + debounce
                if new_deadline > self._pending[cid]['deadline']:
                    self._pending[cid]['deadline'] = new_deadline
                if ct == 203:
                    self._pending[cid]['has_image'] = True
            else:
                self._pending[cid] = {
                    'records': [record],
                    'deadline': now + debounce,
                    'created_at': now,
                    'has_image': ct == 203,
                }

    def _loop(self):
        while self._running:
            expired = []
            with self._lock:
                now = time.time()
                for cid, info in list(self._pending.items()):
                    if now >= info['deadline']:
                        expired.append((cid, info))
                        del self._pending[cid]

            for cid, info in expired:
                self._process_cid(
                    cid, info['records'],
                    created_at=info.get('created_at', 0),
                    has_image=info.get('has_image', False),
                )

            time.sleep(0.3)

    def _process_cid(self, cid, records, created_at=0, has_image=False):
        """Debounce expired: fetch plaintext history via JSAPI, push enriched event.
        Splits fetched messages into new_messages (matching debounce window) and
        history (older context) using the earliest trigger timestamp as cutoff.
        Only others' messages enter the queue (is_self filtered in enqueue),
        so no additional loop prevention needed here.
        If has_image and ct=203 images are not yet cached locally, re-queues
        the CID for retry (up to MAX_WAIT_SECONDS from created_at)."""

        fetch_count = max(len(records), self.DEFAULT_FETCH_COUNT)
        messages = []

        try:
            result = self._daemon.fetch_history(cid, count=fetch_count)
            if result.get('success'):
                messages = result.get('messages', [])
                self._fetch_count += 1
            else:
                log(f'[event-dispatch] fetch failed for {cid}: {result.get("error", "?")}')
        except Exception as e:
            log(f'[event-dispatch] fetch exception for {cid}: {e}')

        latest = records[-1] if records else {}

        cutoff_ts = min((int(r.get('ts', 0)) for r in records if r.get('ts')), default=0)
        if cutoff_ts > 0 and messages:
            new_messages = []
            history = []
            for m in messages:
                msg_ts = int(m.get('ts', 0) or 0)
                if msg_ts >= cutoff_ts:
                    new_messages.append(m)
                else:
                    history.append(m)
        else:
            new_messages = messages
            history = []

        # Re-queue if ct=203 images not yet downloaded locally
        if has_image and created_at:
            unresolved = any(
                m.get('content_type') == 203 and not m.get('image_local_path')
                for m in new_messages
            )
            elapsed = time.time() - created_at
            if unresolved and elapsed < self.MAX_WAIT_SECONDS:
                log(f'[event-dispatch] ct=203 image not ready for {cid}, '
                    f're-queuing (elapsed={elapsed:.0f}s)')
                with self._lock:
                    if cid not in self._pending:
                        self._pending[cid] = {
                            'records': records,
                            'deadline': time.time() + self.IMAGE_DEBOUNCE_SECONDS,
                            'created_at': created_at,
                            'has_image': True,
                        }
                    else:
                        self._pending[cid]['has_image'] = True
                        self._pending[cid]['created_at'] = min(
                            self._pending[cid].get('created_at', created_at),
                            created_at,
                        )
                return
            elif unresolved:
                log(f'[event-dispatch] ct=203 image timeout for {cid} '
                    f'after {elapsed:.0f}s, proceeding without image')

        last_new = new_messages[0] if new_messages else None
        last_msg = last_new or (messages[0] if messages else None)

        event = {
            'type': 'dingtalk.message.received',
            'source': 'dingtalk-daemon',
            'timestamp': int(latest.get('ts', 0)) or int(time.time() * 1000),
            'payload': {
                'cid': cid,
                'sender': (last_msg or latest).get('sender', ''),
                'text': (last_msg or latest).get('text', ''),
                'trigger_count': len(records),
                'new_messages': new_messages,
                'history': history,
            },
        }

        if not messages:
            event['payload']['raw_triggers'] = [
                {
                    'sender': r.get('sender', ''),
                    'text': r.get('text', ''),
                    'ts': r.get('ts', 0),
                    'encrypted': r.get('encrypted', False),
                }
                for r in records
            ]

        self._push_event(event)

    def _push_event(self, event):
        import urllib.request
        try:
            data = json.dumps(event, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(
                self._url, data=data,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            self._push_count += 1
        except Exception:
            self._error_count += 1

    def stats(self):
        with self._lock:
            pending = len(self._pending)
            image_waiting = sum(
                1 for v in self._pending.values() if v.get('has_image')
            )
        return {
            'gateway_url': self._url,
            'pushed': self._push_count,
            'fetched': self._fetch_count,
            'errors': self._error_count,
            'skipped_self': self._skip_count,
            'pending_debounce': pending,
            'pending_image_wait': image_waiting,
            'running': self._running and self._thread is not None and self._thread.is_alive(),
        }


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

    def list_conversations_by_exact_name(self, name, limit=100):
        """按显示姓名精确匹配：ContactsDB + contacts.json，不扫 _msg_log，不按 CID/UID 模糊搜。"""
        from lib.utils import ContactsDB

        uid_map = {}
        for entry in ContactsDB.search_by_exact_display_name(name):
            cid = entry.get('cid')
            if not cid:
                continue
            uid = entry.get('uid') or cid
            uid_map[uid] = {
                'cid': cid,
                'sender': entry.get('name', '未知'),
                'uid': entry.get('uid', ''),
                'time': entry.get('last_seen', ''),
                'preview': f"[联系人库] 消息数: {entry.get('msg_count', 0)}",
            }

        for entry in self._lookup_contacts_db_exact(name):
            uid = entry.get('uid') or entry['cid']
            if uid not in uid_map:
                uid_map[uid] = entry

        return list(uid_map.values())[:limit]

    def resolve_cid(self, name):
        """按显示姓名精确解析 CID。

        返回 (cid, display_name, err)。err 非空表示失败（未找到或歧义）；cid 仅在 err 为空且唯一命中时有值。
        """
        entries = self.list_conversations_by_exact_name(name)
        if not entries:
            return None, None, None
        if len(entries) > 1:
            parts = [f"{e['cid']} ({e.get('sender', '')})" for e in entries]
            return None, None, (
                f'姓名「{name}」精确匹配到 {len(entries)} 条会话：{"；".join(parts)}，请改用 cid 指定'
            )
        best = entries[0]
        return best['cid'], best.get('sender', name), None

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

            # ct=203: pure image — resolve local cache, then CDN fallback
            if ct == 203:
                img_url = m.get('img', '')
                att_ext = {}
                if not img_url and raw:
                    try:
                        raw_obj = json.loads(raw) if isinstance(raw, str) else raw
                        atts = raw_obj.get('attachments', [])
                        if atts and isinstance(atts, list):
                            img_url = atts[0].get('filePath', '') or atts[0].get('url', '')
                            att_ext = atts[0].get('extension', {}) or {}
                    except Exception:
                        pass
                local_path = _resolve_image_local_path(img_url)
                if local_path and not os.path.isfile(local_path):
                    log(f'[ct=203] local cache miss: {local_path}')
                    local_path = ''
                if not local_path and img_url:
                    cdn = ''
                    if img_url.startswith('https://'):
                        cdn = img_url
                    elif 'loc.dingtalk.com' not in img_url:
                        cdn = _mediaid_to_cdn_url(img_url)
                    if cdn:
                        local_path = _download_cdn_image(cdn)
                if not local_path and att_ext:
                    f_id_203 = att_ext.get('f_id', '')
                    s_id_203 = att_ext.get('s_id', '')
                    f_name_203 = att_ext.get('f_name', '')
                    f_type_203 = att_ext.get('f_type', '')
                    if f_id_203 and s_id_203:
                        local_path = _try_download_im_file(f_id_203, s_id_203, f_name_203, f_type_203)
                if not local_path and raw:
                    try:
                        raw_obj = json.loads(raw) if isinstance(raw, str) else raw
                        for key in ('photoModels', 'photos'):
                            photos = raw_obj.get(key, [])
                            if isinstance(photos, list):
                                for p in photos:
                                    mid = p.get('mediaId', '') or p.get('src', '')
                                    w = p.get('width')
                                    h = p.get('height')
                                    if mid:
                                        cdn = _mediaid_to_cdn_url(mid, w, h)
                                        if cdn:
                                            local_path = _download_cdn_image(cdn)
                                            if local_path:
                                                break
                                if local_path:
                                    break
                    except Exception:
                        pass
                if not local_path:
                    log(f'[ct=203] image not resolved, img_url={img_url[:80] if img_url else "empty"}, att_ext_keys={list(att_ext.keys()) if att_ext else "none"}')
                if local_path:
                    entry['image_local_path'] = local_path
                elif img_url:
                    entry['image_url'] = img_url
                if not entry['text']:
                    entry['text'] = '[图片]'

            # ct=1200: Markdown/Reply — always prefer Python parse for reply context
            if ct == 1200 and raw:
                parsed = _extract_markdown_text(raw)
                if parsed:
                    entry['text'] = parsed

            # ct=3100: Rich text — parse payload for text, download images to local cache
            if ct == 3100 and raw:
                img_urls = []
                parsed = _extract_richtext_text(raw, img_urls)
                if parsed:
                    entry['text'] = parsed
                if img_urls:
                    entry['richtext_images'] = img_urls
                    cdn_urls = [u for u in img_urls if u.startswith('https://')]
                    local_paths = []
                    for cdn in cdn_urls:
                        lp = _download_cdn_image(cdn)
                        if lp:
                            local_paths.append(lp)
                    if local_paths:
                        entry['image_local_path'] = local_paths[0]
                        if len(local_paths) > 1:
                            entry['image_local_paths'] = local_paths
                    elif cdn_urls:
                        entry['image_url'] = cdn_urls[0]
                        if len(cdn_urls) > 1:
                            entry['image_urls'] = cdn_urls

            # ct=501/502/503: File messages — extract metadata from attachments
            if ct in (501, 502, 503) and raw:
                try:
                    raw_obj = json.loads(raw) if isinstance(raw, str) else raw
                    atts = raw_obj.get('attachments', [])
                    if atts:
                        ext_data = atts[0].get('extension', {})
                        f_name = ext_data.get('f_name', '')
                        f_size = ext_data.get('f_size', '0')
                        f_type = ext_data.get('f_type', '')
                        f_id = ext_data.get('f_id', '')
                        s_id = ext_data.get('s_id', '')
                        entry['file_info'] = {
                            'f_id': f_id, 's_id': s_id,
                            'f_name': f_name, 'f_size': f_size,
                            'f_type': f_type,
                        }
                        size_str = f' ({f_size}B)' if f_size and f_size != '0' else ''
                        entry['text'] = f'[文件: {f_name}{size_str}]'
                except Exception as e:
                    log(f'[ct={ct}] 解析 attachments 失败: {e}')
                    if not entry['text']:
                        entry['text'] = '[文件]'

            # Reply/quote — parse from extension quoteMsg
            ext_s = m.get('exts', '')
            if ext_s:
                quote_info = _parse_quote_msg(ext_s)
                if quote_info:
                    entry['reply_to'] = quote_info

            results.append(entry)

        return results

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

    def send_image(self, cid, file_path):
        """Send a local image file via dingtalk.message.sendLocalImage JSAPI."""
        if not self.is_attached:
            if not self.attach():
                return {'success': False, 'error': 'Cannot attach to DingTalk'}

        if not self._ensure_b1():
            return {'success': False, 'error': 'B1 (advancedSearch) not available'}

        if not os.path.isfile(file_path):
            return {'success': False, 'error': f'File not found: {file_path}'}

        self._beacon.clear()
        safe_path = file_path.replace('\\', '\\\\').replace("'", "\\'")
        js = (
            f"(function(){{var P={BEACON_PORT};"
                "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
                "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
                "if(typeof dingtalk==='undefined'||!dingtalk.message){"
                "r('error','no_dingtalk_message');return;}"
                "if(!dingtalk.message.sendLocalImage){"
                "r('error','no_sendLocalImage');return;}"
                f"try{{dingtalk.message.sendLocalImage('{cid}','{safe_path}',function(res){{"
                "r('cb',{code:res&&res.code,data:res&&res.data,str:JSON.stringify(res)});"
                "});"
                "r('sent','ok');"
                "}catch(e){r('error',e.message||String(e));}"
                "})()"
        )

        result = self._cef_script.exports_sync.exec_js(1, js)
        if result != 'ok':
            if self._ensure_b1():
                result = self._cef_script.exports_sync.exec_js(1, js)

        for _ in range(20):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'cb' in reports or 'error' in reports:
                break

        reports = self._beacon.get_reports()
        self._send_count += 1
        cb = reports.get('cb')
        return {
            'success': 'sent' in reports and 'error' not in reports,
            'cid': cid,
            'file_path': file_path,
            'callback': cb,
            'error': reports.get('error'),
        }

    def _auto_accept_save_dialog(self, timeout_sec=15):
        """Background: watch for Windows file save dialog and click Save.
        Returns True if dialog was found and Save button clicked."""
        import ctypes
        import ctypes.wintypes
        import subprocess as _sp

        user32 = ctypes.windll.user32
        GetWindowTextW = user32.GetWindowTextW
        GetClassNameW = user32.GetClassNameW
        EnumWindows = user32.EnumWindows
        EnumChildWindows = user32.EnumChildWindows
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        IsWindowVisible = user32.IsWindowVisible
        GetDlgItem = user32.GetDlgItem
        PostMessageW = user32.PostMessageW

        BM_CLICK = 0x00F5
        IDOK = 1
        ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        # Collect all DingTalk PIDs (main + children own dialogs)
        try:
            out = _sp.check_output(
                'tasklist /fi "imagename eq DingTalk.exe" /fo csv /nh', shell=True
            ).decode('gbk', errors='replace')
            dt_pids = set()
            for line in out.strip().split('\n'):
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    try: dt_pids.add(int(parts[1]))
                    except: pass
        except Exception:
            dt_pids = {self._pid} if self._pid else set()

        self._dialog_accepted = False

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(0.3)
            found_dialogs = []

            @ENUM_PROC
            def enum_cb(hwnd, lp):
                pid = ctypes.wintypes.DWORD()
                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in dt_pids:
                    return True
                if not IsWindowVisible(hwnd):
                    return True
                cls = ctypes.create_unicode_buffer(256)
                GetClassNameW(hwnd, cls, 256)
                if cls.value == '#32770':
                    title = ctypes.create_unicode_buffer(256)
                    GetWindowTextW(hwnd, title, 256)
                    if '另存' in title.value or '保存' in title.value or 'Save' in title.value:
                        found_dialogs.append(hwnd)
                return True

            try:
                EnumWindows(enum_cb, 0)
            except Exception:
                continue

            for dlg_hwnd in found_dialogs:
                btn = GetDlgItem(dlg_hwnd, IDOK)
                if btn:
                    PostMessageW(btn, BM_CLICK, 0, 0)
                    log(f'[dialog-auto] Clicked Save button on dialog')
                    self._dialog_accepted = True
                    return True
        return False

    def _find_task_file(self, dentry_id, timeout=8):
        """Query listAllTask to find downloaded file path for given dentry_id."""
        self._beacon.clear()
        js = (
            f"(function(){{var P={BEACON_PORT};"
            "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
            "dingtalk.fileTask.listAllTask(function(err,tasks){"
            "if(err){r('result',{error:err.message});return;}"
            "var found=null;"
            "for(var i=0;i<tasks.length;i++){"
            f"if(tasks[i].url&&tasks[i].url.indexOf('{dentry_id}')>=0&&tasks[i].status===1){{"
            "found={taskId:tasks[i].taskId,filePath:tasks[i].filePath,fileName:tasks[i].fileName};"
            "break;}}"
            "}"
            "r('result',found||{notFound:true});"
            "});"
            "})()"
        )
        try:
            self._cef_script.exports_sync.exec_js(1, js)
            for _ in range(timeout * 2):
                time.sleep(0.5)
                reports = self._beacon.get_reports()
                if 'result' in reports:
                    r = reports['result']
                    if isinstance(r, dict) and r.get('filePath'):
                        return r['filePath']
                    return None
        except Exception as e:
            log(f'[file-dl] listAllTask query failed: {e}')
        return None

    def download_im_file(self, space_id, dentry_id, file_name='', timeout=20):
        """Download an IM file via JSAPI createTask + native dialog hook.

        GetSaveFileNameW is hooked in the CEF script to auto-fill the save
        path and return TRUE, so no dialog appears. The native download
        manager then decrypts the file and writes plaintext to disk.

        Strategy:
          1. Check local cache
          2. Check listAllTask for previously-downloaded file
          3. createTask (dialog silently intercepted) → check save dir + listAllTask
          4. Fallback: storage API
        """
        safe_name = (file_name or str(dentry_id)).replace('/', '_').replace('\\', '_').replace(':', '_')
        local_path = os.path.join(_FILE_CACHE_DIR, f'{dentry_id}_{safe_name}')
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return {'success': True, 'path': local_path, 'cached': True}

        if not self.is_attached or not self._ensure_b1():
            local = _try_download_im_file(dentry_id, space_id, file_name, '')
            if local:
                return {'success': True, 'path': local, 'method': 'storage_api'}
            return {'success': False, 'error': 'DingTalk not attached'}

        # Step 1: check listAllTask for existing download
        existing = self._find_task_file(dentry_id)
        if existing and os.path.isfile(existing):
            log(f'[file-dl] Found in listAllTask: {existing}')
            return {'success': True, 'path': existing, 'method': 'listAllTask'}

        # Step 2: createTask — dialog is silently handled by GetSaveFileNameW hook
        _SILENT_DL_DIR = SILENT_DL_DIR
        os.makedirs(_SILENT_DL_DIR, exist_ok=True)
        url = f'https://space.dingtalk.com/auth/download?spaceId={space_id}&path={dentry_id}'

        self._beacon.clear()
        safe_fname = js_escape(file_name or safe_name)
        dl_js = (
            f"(function(){{var P={BEACON_PORT};"
            "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
            f"dingtalk.download.createTask('{url}',"
            f"{{fileName:'{safe_fname}',spaceId:'{space_id}',fileId:'{dentry_id}',"
            "messageId:'0',conversationId:'',isFolder:false},"
            "function(err,taskId){"
            "if(err){r('result',{error:err.message||JSON.stringify(err),code:err.code});}"
            "else{r('result',{taskId:taskId});}"
            "});"
            "})()"
        )
        try:
            self._cef_script.exports_sync.exec_js(1, dl_js)
        except Exception as e:
            log(f'[file-dl] createTask exec failed: {e}')

        # Wait for createTask callback
        result = {}
        for _ in range(timeout * 2):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'result' in reports:
                result = reports.get('result', {})
                break

        log(f'[file-dl] createTask result: {json.dumps(result, default=str)[:300]}')

        if isinstance(result, dict) and result.get('taskId'):
            # createTask succeeded — check the hook save dir first, then listAllTask
            time.sleep(2)
            hook_path = os.path.join(_SILENT_DL_DIR, file_name or safe_name)
            if os.path.isfile(hook_path) and os.path.getsize(hook_path) > 0:
                log(f'[file-dl] Downloaded to hook dir: {hook_path}')
                return {'success': True, 'path': hook_path, 'method': 'createTask'}

            actual_path = self._find_task_file(dentry_id)
            if actual_path and os.path.isfile(actual_path):
                log(f'[file-dl] Downloaded to: {actual_path}')
                return {'success': True, 'path': actual_path, 'method': 'createTask'}
            for _ in range(min(timeout, 15)):
                time.sleep(1)
                if os.path.isfile(hook_path) and os.path.getsize(hook_path) > 0:
                    log(f'[file-dl] Downloaded to hook dir: {hook_path}')
                    return {'success': True, 'path': hook_path, 'method': 'createTask'}
                actual_path = self._find_task_file(dentry_id)
                if actual_path and os.path.isfile(actual_path):
                    log(f'[file-dl] Downloaded to: {actual_path}')
                    return {'success': True, 'path': actual_path, 'method': 'createTask'}
            return {
                'success': True,
                'path': hook_path if os.path.isfile(hook_path) else (actual_path or ''),
                'method': 'createTask',
                'taskId': result['taskId'],
                'downloading': True,
            }

        # Fallback: storage API
        local = _try_download_im_file(dentry_id, space_id, file_name, '')
        if local:
            return {'success': True, 'path': local, 'method': 'storage_api'}

        return {
            'success': False,
            'error': f'createTask failed: {json.dumps(result, default=str)[:200]}',
            'file_info': {'s_id': space_id, 'f_id': dentry_id, 'f_name': file_name},
        }

    def probe_image_apis(self, timeout=10):
        """Probe all image-related JSAPI methods."""
        bid = self._find_jsapi_browser()
        if not bid:
            if not self._ensure_b1():
                return {'success': False, 'error': 'No JSAPI browser'}
            bid = 1

        self._beacon.clear()
        js = (
            f"(function(){{var P={BEACON_PORT};"
            "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
            "var result={};"
            "if(typeof dingtalk!=='undefined'){"
            "var m=dingtalk.message||{};"
            "var rt=dingtalk.richText||{};"
            "result.message_methods=Object.keys(m).filter(function(k){"
            "return k.toLowerCase().indexOf('image')>=0||k.toLowerCase().indexOf('photo')>=0"
            "||k.toLowerCase().indexOf('media')>=0||k.toLowerCase().indexOf('rich')>=0"
            "||k.toLowerCase().indexOf('local')>=0||k.toLowerCase().indexOf('file')>=0;});"
            "result.richText_methods=Object.keys(rt);"
            "['sendLocalImage','sendRichTextMsg','shareImageToChatWithMediaId',"
            "'sendLocalFile','sendImageMsg'].forEach(function(fn){"
            "result['has_'+fn]=typeof m[fn]==='function';});"
            "['uploadLocalImage','uploadLocalImageV2','getImageLocalURL',"
            "'getRichTextPayload'].forEach(function(fn){"
            "result['has_rt_'+fn]=typeof rt[fn]==='function';});"
            "}"
            "r('probe',result);"
            "})()"
        )
        self._cef_script.exports_sync.exec_js(bid, js)
        for _ in range(20):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'probe' in reports:
                return {'success': True, **reports['probe']}
        return {'success': False, 'error': 'timeout'}

    def upload_local_image(self, file_path, timeout=15):
        """Upload local image via dingtalk.richText.uploadLocalImage, returns mediaId."""
        if not self.is_attached:
            if not self.attach():
                return {'success': False, 'error': 'Cannot attach to DingTalk'}

        if not self._ensure_b1():
            return {'success': False, 'error': 'B1 (advancedSearch) not available'}

        if not os.path.isfile(file_path):
            return {'success': False, 'error': f'File not found: {file_path}'}

        self._beacon.clear()
        safe_path = file_path.replace('\\', '\\\\').replace("'", "\\'")
        js = (
            f"(function(){{var P={BEACON_PORT};"
                "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
                "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
                "if(typeof dingtalk==='undefined'||!dingtalk.richText||!dingtalk.richText.uploadLocalImage){"
                "r('error','no_uploadLocalImage');return;}"
                f"try{{dingtalk.richText.uploadLocalImage('{safe_path}',function(res){{"
                "r('cb',{code:res?res.code:null,data:res?res.data:null,str:JSON.stringify(res)});"
                f"}});"
                "r('sent','ok');"
                f"}}catch(e){{r('error',e.message||String(e));}}"
                "})()"
        )
        result = self._cef_script.exports_sync.exec_js(1, js)
        if result != 'ok':
            log(f'upload_local_image exec_js returned: {result}')
            if self._ensure_b1():
                result = self._cef_script.exports_sync.exec_js(1, js)

        for _ in range(int(timeout * 2)):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'cb' in reports or 'error' in reports:
                break

        reports = self._beacon.get_reports()
        return {
            'success': 'sent' in reports and 'error' not in reports,
            'file_path': file_path,
            'callback': reports.get('cb'),
            'sent': reports.get('sent'),
            'error': reports.get('error'),
        }

    def get_image_local_url(self, media_id, timeout=10):
        """Get local URL for a mediaId via dingtalk.richText.getImageLocalURL."""
        if not self.is_attached:
            if not self.attach():
                return {'success': False, 'error': 'Cannot attach to DingTalk'}

        if not self._ensure_b1():
            return {'success': False, 'error': 'B1 (advancedSearch) not available'}

        self._beacon.clear()
        safe_mid = media_id.replace("'", "\\'").replace('\\', '\\\\')
        js = (
            f"(function(){{var P={BEACON_PORT};"
                "function r(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
                "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
                "if(typeof dingtalk==='undefined'||!dingtalk.richText||!dingtalk.richText.getImageLocalURL){"
                "r('error','no_getImageLocalURL');return;}"
                f"try{{dingtalk.richText.getImageLocalURL('{safe_mid}',function(res){{"
                "r('cb',{code:res?res.code:null,data:res?res.data:null,str:JSON.stringify(res)});"
                f"}});r('sent','ok');}}"
                f"catch(e){{r('error',e.message||String(e));}}"
                "})()"
        )
        result = self._cef_script.exports_sync.exec_js(1, js)
        if result != 'ok':
            if self._ensure_b1():
                result = self._cef_script.exports_sync.exec_js(1, js)

        for _ in range(int(timeout * 2)):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'cb' in reports or 'error' in reports:
                break

        reports = self._beacon.get_reports()
        return {
            'success': 'cb' in reports and 'error' not in reports,
            'media_id': media_id,
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

    def exec_js_raw(self, js_code, timeout=15, bid=None):
        """Execute arbitrary JS in specified or JSAPI browser, return beacon results."""
        if bid is None:
            bid = self._find_jsapi_browser()
            if not bid:
                if not self._ensure_b1():
                    return {'success': False, 'error': 'No JSAPI browser'}
                bid = 1

        self._beacon.clear()
        wrapped = (
            "(function(){var P=" + str(BEACON_PORT) + ";"
            "function post(l,d){fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
            "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
            + js_code +
            "})()"
        )
        try:
            self._cef_script.exports_sync.exec_js(bid, wrapped)
        except Exception as e:
            return {'success': False, 'error': f'exec_js failed: {e}'}

        for _ in range(timeout * 2):
            time.sleep(0.5)
            reports = self._beacon.get_reports()
            if 'result' in reports:
                return {'success': True, 'data': reports['result']}
        return {'success': False, 'error': 'timeout'}

    def exec_js_hash(self, js_code, timeout=10, bid=1):
        """Execute JS in a CEF browser using location.hash for result delivery.
        Works on app:// protocol pages where fetch-based beacon fails.
        The user JS should call __done(data) to signal completion."""
        if not self._cef_script:
            return {'success': False, 'error': 'No CEF script'}

        marker = '__HASH_R_'
        wrapped = (
            "(function(){"
            "function __done(d){try{location.hash='" + marker + "'+btoa(unescape(encodeURIComponent(JSON.stringify(d))));}catch(e){location.hash='" + marker + "'+btoa('err:'+e.message);}}"
            + js_code +
            "})()"
        )
        try:
            result = self._cef_script.exports_sync.exec_js(bid, wrapped)
            if result != 'ok':
                return {'success': False, 'error': f'exec_js returned: {result}'}
        except Exception as e:
            return {'success': False, 'error': f'exec_js failed: {e}'}

        import base64
        for _ in range(timeout * 4):
            time.sleep(0.25)
            try:
                url = self._cef_script.exports_sync.get_browser_url(bid)
                if url and marker in url:
                    b64 = url.split(marker, 1)[1]
                    decoded = base64.b64decode(b64).decode('utf-8')
                    try:
                        data = json.loads(decoded)
                    except Exception:
                        data = decoded
                    # Restore original hash
                    self._cef_script.exports_sync.exec_js(bid,
                        "(function(){location.hash='#/MultiSearch';})()")
                    return {'success': True, 'data': data}
            except Exception:
                pass
        return {'success': False, 'error': 'timeout'}

    def scan_all_browsers(self, timeout=15):
        """Scan all CEF browsers using native Frida RPC to get URLs."""
        if not self._cef_script:
            return {'success': False, 'error': 'No CEF script'}
        try:
            bids = self._cef_script.exports_sync.scan_browsers()
        except Exception as e:
            return {'success': False, 'error': f'scan failed: {e}'}

        results = []
        for bid in bids:
            try:
                url = self._cef_script.exports_sync.get_browser_url(bid)
                results.append({'bid': bid, 'url': url or '(null)'})
            except Exception as e:
                results.append({'bid': bid, 'url': f'error: {e}'})
        return {'success': True, 'browsers': results}

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

    def fetch_report_content(self, url, timeout=30, wait=20, selectors=None, custom_js=None):
        """通过 CEF loadUrl 打开页面并提取正文内容

        优先用 CSS 选择器定位正文容器，避免提取导航栏、侧栏等噪音。
        多选择器逐级 fallback，最终 fallback 到 body.innerText。

        Args:
            url: 要加载的页面 URL
            timeout: 等待 beacon 响应的超时秒数
            wait: 页面加载后等待渲染的秒数（默认20，alidocs建议35+）
            selectors: 自定义 CSS 选择器列表（默认使用报告页选择器）
            custom_js: 自定义提取 JS（可用 post(label, data) 发送数据）
        """
        if selectors is None:
            selectors = ['.report-detail','.report-content','.detail-content',
                         '.log-detail','.form-detail','[class*=report]','[class*=detail]',
                         'article','main','.content','.page-content']
        with self._fetch_lock:
            if not self.is_attached:
                if not self.attach():
                    return {'success': False, 'error': 'Cannot attach to DingTalk'}

            self._beacon.clear()
            result = self._cef_script.exports_sync.load_url(1, url)
            if result != 'ok':
                return {'success': False, 'error': f'loadUrl failed: {result}'}

            time.sleep(wait)

            self._beacon.clear()
            beacon_prefix = (
                "(function(){"
                "var P=" + str(BEACON_PORT) + ";"
                "function post(l,d){fetch('http://127.0.0.1:'+P"
                "+'/r?l='+encodeURIComponent(l),"
                "{method:'POST',body:JSON.stringify(d),mode:'no-cors'}).catch(function(){});}"
            )
            if custom_js:
                extract_js = beacon_prefix + custom_js + "})()"
            else:
                sels_js = ','.join(f"'{s}'" for s in selectors)
                extract_js = (
                    beacon_prefix +

                    "var sels=[" + sels_js + "];"
                    "var el=null,method='body';"
                    "for(var i=0;i<sels.length;i++){"
                    "var e=document.querySelector(sels[i]);"
                    "if(e&&e.innerText&&e.innerText.trim().length>20){"
                    "el=e;method=sels[i];break;}}"
                    "if(!el){"
                    "var iframes=document.querySelectorAll('iframe');"
                    "for(var fi=0;fi<iframes.length;fi++){"
                    "try{var fb=iframes[fi].contentDocument.body;"
                    "if(fb&&fb.innerText&&fb.innerText.trim().length>50){"
                    "el=fb;method='iframe['+fi+']';break;}"
                    "}catch(e){}}"
                    "}"
                    "if(!el)el=document.body;"

                    "var text=(el.innerText||'').trim();"
                    "var title=document.title||'';"

                    "var ifInfo=[];"
                    "var ifs=document.querySelectorAll('iframe');"
                    "for(var j=0;j<ifs.length;j++){"
                    "var s=ifs[j].src||'';var bl=0;"
                    "try{bl=(ifs[j].contentDocument.body.innerText||'').length;}catch(e){bl=-1;}"
                    "ifInfo.push({src:s.substring(0,200),bodyLen:bl});}"

                    "var cs=3000,n=Math.ceil(text.length/cs);"
                    "post('rpt_meta',{title:title,len:text.length,parts:n,method:method,url:window.location.href,iframes:ifInfo});"
                    "for(var i=0;i<n&&i<100;i++){"
                    "post('rpt_c'+i,{d:text.substr(i*cs,cs)});}"
                    "})()"
                )

            self._cef_script.exports_sync.exec_js(1, extract_js)

            if custom_js:
                # Custom JS mode: collect all beacon reports
                for _ in range(timeout * 2):
                    time.sleep(0.5)
                    reports = self._beacon.get_reports()
                    if reports:
                        break
                reports = self._beacon.get_reports()
                self._ensure_b1()
                if not reports:
                    return {'success': False, 'error': 'Custom JS produced no beacon output'}
                return {'success': True, 'reports': reports}
            else:
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
                self._ensure_b1()

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
                    'page_url': meta.get('url', ''),
                    'iframes': meta.get('iframes', []),
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

            if not MY_REPORT_GROUP_CID:
                return {'success': False, 'error': 'my_report_group_cid not configured in config.json'}

            self._beacon.clear()
            cid_safe = js_escape(MY_REPORT_GROUP_CID)

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
                                max_seconds=200):
        """daemon 侧分页拉取工作汇报（ct=300），browser 扫描只做一次"""
        if not REPORT_CID:
            return {'success': False, 'error': 'report_cid not configured in config.json'}
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
                cid_safe = js_escape(REPORT_CID)
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
                    if m.get('content_type') != 300:
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
            'total_ct300': len(all_msgs),
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
            "else if(ct.markdownContent&&ct.markdownContent.text)text=ct.markdownContent.text;"
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
            "if(!text){"
            "try{"
            "var _ctn=ct.contentType||0;"
            "var _atts=ct.attachments||[];"
            "if(_atts.length>0){"
            "var _aext=_atts[0].extension||{};"
            "if(_ctn===1200){text=_aext.title||'';}"
            "else if(_ctn===3100){text=_aext.desc||'';}"
            "}"
            "}catch(ea){}"
            "}"
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
            "}else if(_ct_num!==1){"
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
            "var _ext_s='',_img_url='';"
            "try{"
            "var _eo=bm.extension||{};"
            "if(typeof _eo==='string'){try{_eo=JSON.parse(_eo);}catch(ee){}}"
            "var _qm=_eo.quoteMsg||_eo.quotedMsg||_eo.quote_msg||null;"
            "if(_qm){_ext_s=typeof _qm==='string'?_qm:JSON.stringify(_qm);}"
            "}catch(e5){}"
            "if(_ct_num===203){"
            "try{"
            "var _mc=ct.mediaContent||ct.imageContent||{};"
            "if(typeof _mc==='object')_img_url=_mc.mediaCopyUrl||_mc.imageUrl||_mc.url||_mc.filePath||'';"
            "if(!_img_url&&ct.mediaCopyUrl)_img_url=ct.mediaCopyUrl;"
            "if(!_img_url){"
            "var _a203=ct.attachments||[];"
            "if(_a203.length>0)_img_url=_a203[0].filePath||_a203[0].url||'';"
            "}"
            "}catch(e6){}"
            "}"
            ""
            "out.push({"
            "ts:bm.createdAt||m.createdAt||'0',"
            "uid:bm.senderOpenId||m.senderOpenId||'',"
            "ct:ct.contentType||0,"
            "text:String(text||''),"
            "raw:raw_ct,"
            "bf:_bf_raw,"
            "sn:sender_name,"
            "url:_aurl,"
            "exts:_ext_s,"
            "img:_img_url"
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
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if not keyword or keyword in line:
                    results.append(line.rstrip())
                    if len(results) > limit * 3:
                        results = results[-limit:]
        return results[-limit:]

    @staticmethod
    def _lookup_contacts_db_exact(name):
        """contacts.json 中显示姓名与 name（strip）完全一致"""
        contacts_file = os.path.join(DATA_DIR, 'contacts.json')
        if not os.path.exists(contacts_file):
            return []
        q = (name or '').strip()
        if not q:
            return []
        try:
            with open(contacts_file, 'r', encoding='utf-8') as f:
                contacts = json.load(f)
            results = []
            for section_key in ('p2p', 'group'):
                section = contacts.get(section_key, {})
                if not isinstance(section, dict):
                    continue
                for entry in section.values():
                    entry_name = (entry.get('name') or '').strip()
                    if entry_name == q:
                        results.append({
                            'cid': entry['cid'],
                            'sender': entry_name,
                            'uid': entry.get('uid', ''),
                            'time': '',
                            'preview': f'[contacts.json] {section_key}',
                        })
            return results
        except Exception:
            return []

    def health(self):
        dt_running = bool(get_main_pid())
        result = {
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
        if hasattr(self, '_event_dispatcher') and self._event_dispatcher:
            result['event_dispatcher'] = self._event_dispatcher.stats()
        return result

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
                    if self.is_attached:
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
            name = (params.get('name', [''])[0] or '').strip()
            if name:
                entries = _daemon.list_conversations_by_exact_name(name)
                if len(entries) > 1:
                    self._json_response({
                        'error': (
                            f'姓名「{name}」精确匹配到 {len(entries)} 条会话，请使用 cid 或消歧后重试'
                        ),
                        'candidates': entries,
                    }, 409)
                    return
                self._json_response({'count': len(entries), 'results': entries})
            else:
                entries = ContactsDB.get_all()
                self._json_response({'count': len(entries), 'results': entries})

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
                cid, resolved, rerr = _daemon.resolve_cid(name)
                if rerr:
                    self._json_response({'error': rerr}, 409)
                    return
                if not cid:
                    self._json_response({
                        'error': (
                            f'找不到显示名为「{name}」的会话（需与联系人库/contacts.json 中姓名完全一致），'
                            '请核对或直接使用 cid'
                        ),
                    }, 404)
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

        elif parsed.path == '/send-image':
            cid = body.get('cid', '')
            name = body.get('name', '')
            file_path = body.get('file_path', '')
            if not file_path:
                self._json_response({'error': 'file_path required'}, 400)
                return
            if not cid and name:
                cid, resolved, rerr = _daemon.resolve_cid(name)
                if rerr:
                    self._json_response({'error': rerr}, 409)
                    return
                if not cid:
                    self._json_response({
                        'error': f'找不到显示名为「{name}」的会话',
                    }, 404)
                    return
                body['resolved_name'] = resolved
            if not cid:
                self._json_response({'error': 'cid or name required'}, 400)
                return
            result = _daemon.send_image(cid, file_path)
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
                cid, resolved, rerr = _daemon.resolve_cid(name)
                if rerr:
                    self._json_response({'error': rerr}, 409)
                    return
                if not cid:
                    self._json_response({
                        'error': (
                            f'找不到显示名为「{name}」的会话（需与联系人库/contacts.json 中姓名完全一致），'
                            '请核对或直接使用 cid'
                        ),
                    }, 404)
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
            result = _daemon.fetch_reports_paginated(
                count=count, before=before, after=after,
                author=author, report_type=report_type, max_pages=max_pages)
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
            wait = int(body.get('wait', 20))
            timeout = int(body.get('timeout', 30))
            selectors = body.get('selectors', None)
            custom_js = body.get('custom_js', None)
            result = _daemon.fetch_report_content(url, timeout=timeout, wait=wait, selectors=selectors, custom_js=custom_js)
            self._json_response(result)

        elif parsed.path == '/load_url':
            url = body.get('url', '')
            bid = int(body.get('bid', 1))
            if not url:
                self._json_response({'error': 'url required'}, 400)
                return
            try:
                result = _daemon._cef_script.exports_sync.load_url(bid, url)
                self._json_response({'success': result == 'ok', 'result': result})
            except Exception as e:
                self._json_response({'success': False, 'error': str(e)})

        elif parsed.path == '/download_file':
            s_id = body.get('s_id', '')
            f_id = body.get('f_id', '')
            f_name = body.get('f_name', '')
            if not s_id or not f_id:
                self._json_response({'error': 's_id and f_id required'}, 400)
                return
            result = _daemon.download_im_file(s_id, f_id, f_name, timeout=20)
            self._json_response(result)

        elif parsed.path == '/probe_jsapi':
            result = _daemon.probe_jsapi(timeout=10)
            self._json_response(result)

        elif parsed.path == '/scan_browsers':
            result = _daemon.scan_all_browsers(timeout=20)
            self._json_response(result)

        elif parsed.path == '/exec_js':
            js_code = body.get('js', '')
            if not js_code:
                self._json_response({'error': 'js required'}, 400)
                return
            timeout = body.get('timeout', 15)
            bid = body.get('bid', None)
            result = _daemon.exec_js_raw(js_code, timeout=timeout, bid=bid)
            self._json_response(result)

        elif parsed.path == '/exec_js_hash':
            js_code = body.get('js', '')
            if not js_code:
                self._json_response({'error': 'js required'}, 400)
                return
            timeout = body.get('timeout', 10)
            bid = body.get('bid', 1)
            result = _daemon.exec_js_hash(js_code, timeout=timeout, bid=bid)
            self._json_response(result)

        elif parsed.path == '/probe_vtable':
            bid = body.get('bid', 1)
            try:
                result = _daemon._cef_script.exports_sync.probe_vtable(bid)
                self._json_response({'success': True, 'vtable': result})
            except Exception as e:
                self._json_response({'success': False, 'error': str(e)})

        elif parsed.path == '/test_exec':
            bid = body.get('bid', 1)
            js = body.get('js', "location.hash='#TEST_EXEC_OK'")
            exec_off = body.get('exec_offset', -1)
            load_off = body.get('load_offset', -1)
            try:
                result = _daemon._cef_script.exports_sync.test_exec_js(
                    bid, js, exec_off, load_off)
                self._json_response({'success': True, 'result': result})
            except Exception as e:
                self._json_response({'success': False, 'error': str(e)})

        elif parsed.path == '/probe_image_apis':
            result = _daemon.probe_image_apis(timeout=10)
            self._json_response(result)

        elif parsed.path == '/upload_image':
            file_path = body.get('file_path', '')
            if not file_path:
                self._json_response({'error': 'file_path required'}, 400)
                return
            result = _daemon.upload_local_image(file_path, timeout=15)
            self._json_response(result)

        elif parsed.path == '/get_image_url':
            media_id = body.get('media_id', '')
            if not media_id:
                self._json_response({'error': 'media_id required'}, 400)
                return
            result = _daemon.get_image_local_url(media_id, timeout=10)
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

    _event_dispatcher = EventDispatcher(_daemon, EVENT_GATEWAY_URL, MY_UID)
    _event_dispatcher.start()
    set_event_callback(_event_dispatcher.enqueue)
    _daemon._event_dispatcher = _event_dispatcher

    if _daemon.attach():
        log('Frida 已附加，CEF 就绪')
        _daemon.start_monitor()
    else:
        log('初始附加失败，watchdog 将自动重试')

    _daemon.start_watchdog()
    _daemon.start_name_resolver()
    log('Watchdog + NameResolver 已启动')

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
