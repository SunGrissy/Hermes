# -*- coding: utf-8 -*-
"""
dingtalk-desktop 共享工具模块
提取自 dt_jsapi_send.py / _msg_monitor.py / _inject_v4.py 的公共逻辑
"""
import os
import sys
import subprocess
import re
import json
import threading
from datetime import datetime
from collections import OrderedDict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# --------------- 路径 / 配置 ---------------

def _find_data_dir():
    """从环境变量或项目结构推断 data/dingtalk 路径"""
    env = os.environ.get('DINGTALK_DATA_DIR')
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(here, 'data', 'dingtalk')
        if os.path.isdir(os.path.join(here, 'src')):
            return candidate
        here = os.path.dirname(here)
    return os.path.join(os.getcwd(), 'data', 'dingtalk')

DATA_DIR = _find_data_dir()
os.makedirs(DATA_DIR, exist_ok=True)

# dingtalk-desktop 项目根目录（lib 的上一级）
_DINGTALK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBHOOK_CONFIG_PATH = os.path.join(_DINGTALK_ROOT, 'webhook_config.json')


def get_webhook_url(key: str, fallback: str = '') -> str:
    """从 webhook_config.json 按 key 读取机器人 webhook URL；无则返回 fallback。
    key 与 webhook_config.json 的键一致，如 memo_tracker / doc_review / resume_notify / default。
    """
    if not key:
        return fallback
    if not os.path.isfile(WEBHOOK_CONFIG_PATH):
        return fallback
    try:
        with open(WEBHOOK_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return (cfg.get(key) or '').strip() or fallback
    except Exception:
        return fallback


DEFAULT_MY_UID = os.environ.get('DINGTALK_MY_UID', '316550726')

# 单聊新建联系人时：部分 Push 把对端 sender 误标为本账号显示名，不可写入为对方昵称
_P2P_IGNORE_DISPLAY = frozenset({'孙懿（猫姐）', '孙懿'})

ADV_SEARCH_URL = (
    'app://desktop.dingtalk.com/web_content/advancedSearch.html'
    '?hideInput=true&uid=31'
)

CT_NAMES = {
    1: '文本', 101: '图文', 203: '图片', 300: '工作汇报',
    302: '语音', 305: '视频', 1200: 'Markdown',
    501: '大文件', 502: '文件', 503: '文件夹',
    2001: '文件', 2950: '互动卡片', 3100: '富文本/@',
}

# --------------- 进程查找 ---------------

_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW

def get_main_pid():
    """找到钉钉主进程 PID（排除 --type= 子进程）。
    优先用 psutil（可靠），fallback 到 wmic（Win11 可能不可用）。
    """
    # 方案1：psutil（最可靠，过滤掉 --type= 子进程）
    try:
        import psutil
        candidates = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'dingtalk' in proc.info['name'].lower():
                    cmdline = proc.info['cmdline'] or []
                    cmdline_str = ' '.join(cmdline)
                    if '--type=' not in cmdline_str:
                        candidates.append((proc.info['pid'], proc.memory_info().rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
    except Exception:
        pass

    # 方案2：wmic（Win10 可用，Win11 可能已废弃）
    try:
        r = subprocess.run(
            ['wmic', 'process', 'where', "name='DingTalk.exe'", 'get',
             'ProcessId,CommandLine', '/format:list'],
            capture_output=True, text=True, encoding='gbk', errors='replace',
            timeout=10, creationflags=_NO_WINDOW,
        )
        for block in r.stdout.split('CommandLine='):
            if 'DingTalk.exe' in block and '--type=' not in block:
                for line in block.split('\n'):
                    if line.strip().startswith('ProcessId='):
                        try:
                            return int(line.strip().split('=')[1])
                        except ValueError:
                            pass
    except Exception:
        pass

    return None


def get_main_pid_by_mem():
    """通过 tasklist 按最大内存找钉钉主进程（备选方案）"""
    try:
        r = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq DingTalk.exe', '/FO', 'CSV'],
            capture_output=True, text=True, encoding='gbk', errors='replace',
            timeout=10, creationflags=_NO_WINDOW,
        )
    except Exception:
        return None
    max_mem, main_pid = 0, None
    for line in r.stdout.strip().split('\n')[1:]:
        parts = line.strip('"').split('","')
        if len(parts) >= 5:
            try:
                pid = int(parts[1])
                mem = int(parts[4].replace(',', '').replace(' K', '')
                          .replace('K', '').strip())
            except (ValueError, IndexError):
                continue
            if mem > max_mem:
                max_mem, main_pid = mem, pid
    return main_pid

# --------------- MsgPack 解码 ---------------

def deep_decode(obj, depth=0):
    """递归解码 msgpack raw bytes → utf-8 字符串 / 嵌套 msgpack"""
    import msgpack
    if depth > 8:
        return str(obj)
    if isinstance(obj, bytes):
        try:
            s = obj.decode('utf-8')
            if s.isprintable() or re.search(r'[\u4e00-\u9fff]', s):
                return s
        except Exception:
            pass
        try:
            inner = msgpack.unpackb(obj, raw=True, strict_map_key=False)
            if isinstance(inner, (dict, list)):
                return deep_decode(inner, depth + 1)
        except Exception:
            pass
        if len(obj) <= 64:
            return f'<hex:{obj.hex()}>'
        return f'<bin:{len(obj)}B>'
    elif isinstance(obj, dict):
        return {deep_decode(k, depth + 1): deep_decode(v, depth + 1)
                for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_decode(v, depth + 1) for v in obj]
    return obj


def normalize(obj, depth=0):
    """简化版解码：bytes→str/hex，不尝试嵌套 msgpack"""
    if depth > 10:
        return str(obj)
    if isinstance(obj, dict):
        return {
            (k.decode('utf-8', errors='replace') if isinstance(k, bytes) else k):
            normalize(v, depth + 1)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [normalize(v, depth + 1) for v in obj]
    elif isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except Exception:
            return obj.hex()
    return obj

# --------------- JS 转义 ---------------

def js_escape(text):
    """将文本转为纯 ASCII 的 JS Unicode 转义（用于 Frida JS 注入）"""
    parts = []
    for ch in text:
        cp = ord(ch)
        # BMP 外（如 emoji U+1F916）不能写 \\uXXXX（只吞 4 位 hex，余字会落到正文里变乱码）
        if cp > 0xFFFF:
            parts.append(f'\\u{{{cp:x}}}')
        elif cp > 127:
            parts.append(f'\\u{cp:04x}')
        elif ch == '\\':
            parts.append('\\\\')
        elif ch == "'":
            parts.append("\\'")
        elif ch == '\n':
            parts.append('\\n')
        elif ch == '\r':
            parts.append('\\r')
        else:
            parts.append(ch)
    return ''.join(parts)


def _parse_dingtalk_markdown_reply(md_text: str, title: str = '') -> str:
    """解析钉钉「引用回复」式 Markdown（> 引用块 + --- + 正文）；否则返回空串由调用方回退为整段 md。"""
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

    reply_text = ' '.join(reply_lines) if reply_lines else ''
    if quote_sender or quote_lines:
        quote_preview = ' '.join(quote_lines)[:60]
        prefix = (
            f'[回复 {quote_sender}: "{quote_preview}"] '
            if quote_sender
            else f'[回复: "{quote_preview}"] '
        )
        return prefix + (reply_text or title or '')

    return ''


def _looks_like_reply_thread_markdown(md: str) -> bool:
    s = (md or '').lstrip()
    return s.startswith('>') or '\n>' in md


def extract_markdown_body_from_ct1200_raw(raw_json) -> str:
    """ct=1200 Webhook/机器人 Markdown：listMessage 的 text 常只有标题，完整正文在 raw JSON。"""
    if not raw_json:
        return ''
    try:
        ct_obj = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except Exception:
        return ''

    for key in ('markdownContent', 'richTextContent', 'textContent'):
        sub = ct_obj.get(key)
        if isinstance(sub, dict):
            t = (sub.get('text') or '').strip()
            if t:
                return t

    atts = ct_obj.get('attachments') or []
    if not isinstance(atts, list) or not atts:
        return ''
    ext = (atts[0] if isinstance(atts[0], dict) else {}).get('extension', {}) or {}
    title = (ext.get('title') or '').strip()
    md = (ext.get('markdown') or '').strip()
    if not md:
        return title
    if _looks_like_reply_thread_markdown(md):
        parsed = _parse_dingtalk_markdown_reply(md, title)
        if parsed:
            return parsed
        return md.strip()
    parts = []
    if title:
        parts.append(title)
    parts.append(md)
    return '\n'.join(parts).strip()


# --------------- 去重追踪器 ---------------

class DedupTracker:
    """基于 OrderedDict 的滑动窗口去重"""

    def __init__(self, max_size=2000):
        self._seen = OrderedDict()
        self._max = max_size

    def is_seen(self, key):
        if key in self._seen:
            return True
        self._seen[key] = True
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return False

    def clear(self):
        self._seen.clear()

# --------------- 桌面通知 ---------------

def toast_async(title, body):
    """Windows 桌面通知（异步，失败静默）"""
    def _show():
        try:
            from winotify import Notification
            n = Notification(
                app_id='DingTalk Monitor',
                title=title[:60],
                msg=body[:150].replace('\n', ' '),
                duration='short',
            )
            n.show()
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()

# --------------- 时间格式 ---------------

def fmt_time(ts_ms):
    if not ts_ms:
        return ''
    return datetime.fromtimestamp(ts_ms / 1000).strftime('%H:%M:%S')

# --------------- Frida JS 公共片段 ---------------

CONTACTS_FILE = os.path.join(DATA_DIR, 'contacts.json')


class ContactsDB:
    """持续维护的联系人库，daemon 每收到消息自动更新"""

    _lock = threading.Lock()
    _cache = None
    _dirty = False
    _pending_resolve = []

    @classmethod
    def _is_p2p(cls, cid):
        return ':' in cid and not cid.startswith('cid')

    @classmethod
    def _section(cls, cid):
        return 'p2p' if cls._is_p2p(cid) else 'group'

    @classmethod
    def _load(cls):
        if cls._cache is not None:
            return cls._cache
        if os.path.exists(CONTACTS_FILE):
            try:
                with open(CONTACTS_FILE, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                if 'p2p' in raw and 'group' in raw:
                    cls._cache = raw
                else:
                    cls._cache = cls._migrate(raw)
                    cls._dirty = True
            except Exception:
                cls._cache = {'p2p': {}, 'group': {}}
        else:
            cls._cache = {'p2p': {}, 'group': {}}
        return cls._cache

    @classmethod
    def _migrate(cls, old_flat):
        """旧的扁平格式 {cid: entry} → 新的 {p2p: {...}, group: {...}}"""
        new = {'p2p': {}, 'group': {}}
        for cid, entry in old_flat.items():
            section = 'p2p' if entry.get('type') == 'p2p' else cls._section(cid)
            clean = {k: v for k, v in entry.items() if k != 'type'}
            new[section][cid] = clean
        return new

    @classmethod
    def _save(cls):
        if not cls._dirty:
            return
        try:
            os.makedirs(os.path.dirname(CONTACTS_FILE), exist_ok=True)
            tmp = CONTACTS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cls._cache, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONTACTS_FILE)
            cls._dirty = False
        except Exception:
            pass

    @classmethod
    def _get(cls, cid):
        db = cls._load()
        section = cls._section(cid)
        return db[section].get(cid)

    @classmethod
    def _iter_all(cls):
        db = cls._load()
        yield from db.get('p2p', {}).items()
        yield from db.get('group', {}).items()

    @classmethod
    def _resolve_name(cls, uid):
        """从 contacts.json 解析 UID → 姓名"""
        try:
            db = cls._load()
            for cid, entry in db.get('p2p', {}).items():
                if entry.get('uid') == uid and entry.get('name'):
                    return entry['name']
            return None
        except Exception:
            return None

    @classmethod
    def update(cls, cid, sender_uid, my_uid, is_self=False):
        """消息到达时调用，自动维护联系人。返回解析后的姓名（可能是 UID）"""
        if not cid or is_self:
            return sender_uid

        with cls._lock:
            db = cls._load()
            section = cls._section(cid)
            entry = db[section].get(cid)
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if entry:
                entry['last_seen'] = now
                entry['msg_count'] = entry.get('msg_count', 0) + 1
                cls._dirty = True
                if entry.get('msg_count', 0) % 20 == 0:
                    cls._save()
                return entry.get('name') or sender_uid

            is_p2p = section == 'p2p'
            other_uid = ''
            if is_p2p:
                parts = cid.split(':')
                other_uid = parts[1] if parts[0] == my_uid else parts[0]

            name = None
            if other_uid:
                name = cls._resolve_name(other_uid)
            if not name and sender_uid and sender_uid != my_uid and is_p2p:
                name = cls._resolve_name(sender_uid)
            if name in _P2P_IGNORE_DISPLAY:
                name = None

            if is_p2p:
                peer_name = name or sender_uid or ''
                if peer_name in _P2P_IGNORE_DISPLAY:
                    peer_name = ''
                if not peer_name and other_uid:
                    peer_name = f'单聊·{other_uid}'
                if not peer_name:
                    peer_name = str(sender_uid or '')
                entry = {
                    'cid': cid,
                    'uid': other_uid or sender_uid,
                    'name': peer_name,
                    'first_seen': now,
                    'last_seen': now,
                    'msg_count': 1,
                    'name_resolved': name is not None,
                }
            else:
                entry = {
                    'cid': cid,
                    'name': name or '',
                    'first_seen': now,
                    'last_seen': now,
                    'msg_count': 1,
                    'name_resolved': name is not None,
                }

            db[section][cid] = entry
            cls._dirty = True
            cls._save()
            if not is_p2p and not name:
                cls._pending_resolve.append(cid)
            return entry['name'] or sender_uid

    @classmethod
    def search(cls, keyword):
        """按姓名/CID/UID 模糊搜索联系人"""
        with cls._lock:
            db = cls._load()
        results = []
        kw = keyword.lower()
        for cid, entry in cls._iter_all():
            if (kw in (entry.get('name') or '').lower()
                    or kw in cid.lower()
                    or kw in (entry.get('uid') or '').lower()):
                results.append(entry)
        return results

    @classmethod
    def get_all(cls):
        with cls._lock:
            db = cls._load()
        return list(e for _, e in cls._iter_all())

    @classmethod
    def drain_pending_resolve(cls):
        """取出并清空待解析的 CID 列表（线程安全）"""
        with cls._lock:
            pending = cls._pending_resolve[:]
            cls._pending_resolve.clear()
        return pending

    @classmethod
    def set_name(cls, cid, name):
        """设置会话名称（如通过 JSAPI 获取的群名），返回是否更新成功"""
        if not cid or not name:
            return False
        with cls._lock:
            db = cls._load()
            section = cls._section(cid)
            entry = db[section].get(cid)
            if not entry:
                return False
            if entry.get('name') and entry.get('name_resolved'):
                return False
            entry['name'] = name
            entry['name_resolved'] = True
            cls._dirty = True
            cls._save()
            return True

    @classmethod
    def get_unresolved_groups(cls):
        """返回所有未解析名称的群聊 CID 列表"""
        with cls._lock:
            db = cls._load()
        return [
            cid for cid, e in db.get('group', {}).items()
            if not e.get('name_resolved')
        ]

    @classmethod
    def flush(cls):
        """强制写盘"""
        with cls._lock:
            cls._save()

    @classmethod
    def reload(cls):
        """强制从磁盘重新加载（用于外部修改了 contacts.json 后同步）"""
        with cls._lock:
            cls._cache = None
            cls._dirty = False
            cls._load()
        return {'p2p': len(cls._cache.get('p2p', {})),
                'group': len(cls._cache.get('group', {}))}


FRIDA_READSTDSTR_JS = r"""
function readStdStr(p) {
    try {
        var len = p.add(16).readU32(), cap = p.add(24).readU32();
        if (!len || len > 2000000 || cap < len) return null;
        var dp = (cap <= 15) ? p : p.readPointer();
        return (dp && !dp.isNull()) ? dp.readByteArray(len) : null;
    } catch(e) { return null; }
}
"""

FRIDA_FIND_EXPORT_JS = r"""
function findExport(mod, sub) {
    var m = Process.getModuleByName(mod);
    var e = m.enumerateExports();
    for (var i = 0; i < e.length; i++)
        if (e[i].name.indexOf(sub) >= 0 && e[i].type === 'function') return e[i].address;
    return null;
}
"""
