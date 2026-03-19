# -*- coding: utf-8 -*-
"""
文档预审技能

触发条件：用户在助理通知群先发文档链接，再发「预审」指令（两条独立消息）。
         skill_router 检测到指令后回溯找最近的文档链接，调用本模块。
         同一文档在 doc_review_window_seconds 内已尝试过（含失败）会跳过；若仍要重跑，请发
         「再预审」「强制预审」「预审再来」等，将跳过该时间窗去重。

流程：
  1. 通过助理大白通知"预审已启动"
  2. 调 daemon /fetch_report_content 打开文档（AliDocs 自动 wait_extra=15s）
  3. 调 Palace CLI 跑多角色预审
  4. 通过助理大白回复预审结果（成功/失败均通知）

  拉取文档与 Palace 预审耗时较长时，按 digest `doc_review_progress_interval_seconds`（默认 30s，0 关闭）
  经 webhook 推送阶段性进度（阶段名 + 已等待秒数）。
  
所有通知使用 Markdown，title/footer 含「小秘书提醒」以满足钉钉机器人自定义关键词（与助理群其它机器人一致）。
"""
import os
import re
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
_TEMPLATE_PATH = os.path.join(_ROOT, 'message_templates.json')
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from db.store import save_doc_review_result, was_doc_attempted_recently


def _load_doc_review_templates() -> dict:
    try:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('doc_review', {}) or {}
    except Exception:
        return {}


def get_doc_review_no_link_message() -> str:
    """供 skill_router 使用：未找到文档链接时的提示文案。"""
    t = _load_doc_review_templates()
    return t.get('no_link', 'PM助理 收到预审指令，但未找到最近的文档链接。请先发送文档链接，再发送「预审」。')


def normalize_doc_url(url: str) -> str:
    """钉钉文档 URL 规范化：去掉 query、fragment 和尾部斜杠，同一文档得到同一 key。"""
    if not url or not isinstance(url, str):
        return ''
    url = url.strip()
    try:
        p = urllib.parse.urlparse(url)
        path = (p.path or '').rstrip('/')
        return f'{p.scheme or "https"}://{p.netloc or ""}{path}'
    except Exception:
        return url

DAEMON_URL  = os.environ.get('DINGTALK_DAEMON_URL', 'http://127.0.0.1:19200')
PALACE_URL  = os.environ.get('PALACE_URL', 'http://127.0.0.1:8300')
PALACE_ROOT = os.environ.get('PALACE_ROOT', str(Path(__file__).resolve().parent.parent.parent / 'palace'))

_RE_ALIDOCS = re.compile(
    r'https?://alidocs\.dingtalk\.com/i/nodes/[^\s\]>)\u3001\u3002\uff0c"\']*'
)

_VERDICT_LABEL = {
    'pass':    'PASS',
    'concern': 'CONCERN',
    'block':   'BLOCK',
    'error':   'ERROR',
}
_VERDICT_EMOJI = {
    'pass':    '(PASS)',
    'concern': '(!)',
    'block':   '(X)',
    'error':   '(?)',
}
# 摘要卡片用（钉钉 Markdown 正文）
_VERDICT_BADGE = {
    'pass':    '✅',
    'concern': '🟡',
    'block':   '🔴',
    'error':   '⚠️',
}


def _strip_for_md_bold(s: str) -> str:
    """避免标题里出现 ** 破坏 Markdown。"""
    return (s or '').replace('**', '').strip()


def _one_line(s: str) -> str:
    return ' '.join((s or '').split())


def _truncate(s: str, max_len: int) -> str:
    s = s or ''
    if max_len <= 0 or len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + '…'


def _markdown_link(label: str, url: str) -> str:
    lab = (label or '链接').replace(']', '')
    u = (url or '').strip()
    if not u:
        return lab
    return f'[{lab}]({u})'


def _palace_report_link_label(report_url: str) -> str:
    u = (report_url or '').lower()
    if '127.0.0.1' in u or 'localhost' in u:
        return 'Palace 报告（本机/内网打开）'
    return 'Palace 完整报告'


def _log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[doc_review][{ts}] {msg}', flush=True)


def extract_doc_url(text: str) -> str | None:
    """从消息文本里提取第一个 AliDocs URL"""
    if not (text or isinstance(text, str)):
        return None
    m = _RE_ALIDOCS.search(text)
    return m.group(0) if m else None


def _find_alidocs_in_obj(obj, seen=None):
    """递归扫描任意 JSON 结构，返回第一个匹配 alidocs 的 URL 字符串。"""
    if seen is None:
        seen = set()
    if id(obj) in seen:
        return None
    if isinstance(obj, str):
        m = _RE_ALIDOCS.search(obj)
        if m:
            return m.group(0)
        try:
            decoded = urllib.parse.unquote(obj)
            if decoded != obj:
                m = _RE_ALIDOCS.search(decoded)
                if m:
                    return m.group(0)
        except Exception:
            pass
        if 'alidocs.dingtalk.com' in obj:
            return obj.strip()
        return None
    if isinstance(obj, dict):
        seen.add(id(obj))
        for k, v in obj.items():
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


def extract_doc_url_from_message(msg: dict) -> str | None:
    """从单条消息中提取钉钉文档链接。支持：纯文本、action_url/report_url、文档卡片 attachments[].extension、raw 内任意层级。"""
    if not msg:
        return None
    # 1) 显式 URL 字段
    for key in ('action_url', 'report_url', 'url'):
        val = msg.get(key)
        if not val:
            continue
        s = str(val).strip()
        if 'alidocs.dingtalk.com' in s or '/doc/' in s:
            m = _RE_ALIDOCS.search(s)
            if m:
                return m.group(0)
            return s.split('?')[0] if '?' in s else s
    # 2) 从文本内容提取
    text = (msg.get('text') or '').strip()
    u = extract_doc_url(text)
    if u:
        return u
    # 3) 文档卡片：raw.attachments[].extension 中的 link_url / doc_url / url
    raw = msg.get('raw')
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            for att in (data.get('attachments') or []):
                if not isinstance(att, dict):
                    continue
                ext = att.get('extension') or {}
                if not isinstance(ext, dict):
                    continue
                for key in ('link_url', 'doc_url', 'url', 'action_url', 'report_url'):
                    val = ext.get(key)
                    if not val:
                        continue
                    s = str(val).strip()
                    if 'alidocs.dingtalk.com' in s or '/doc/' in s:
                        m = _RE_ALIDOCS.search(s)
                        if m:
                            return m.group(0)
                        return s.split('?')[0] if '?' in s else s
            u = _find_alidocs_in_obj(data)
            if u:
                return u
        except Exception:
            pass
    # 4) 整条消息递归扫描，兜底非常规字段里的链接
    u = _find_alidocs_in_obj(msg)
    if u:
        return u
    return None


def _post(url: str, data: dict, timeout: int = 90) -> dict:
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'_error': str(e)}


# 与 message_templates.json doc_review.keyword 一致；title 带关键词以满足钉钉「自定义关键词」校验
_DOC_WEBHOOK_KEYWORD = '小秘书提醒'
_DOC_WEBHOOK_FOOTER = '\n\n###### ※ 小秘书提醒'


def _parse_dingtalk_webhook_response(raw: bytes) -> tuple[bool, str]:
    """钉钉常返回 HTTP 200 但 JSON errcode!=0（关键词未命中等），须解析后再判成功。"""
    if not raw:
        return True, ''
    try:
        data = json.loads(raw.decode('utf-8'))
    except Exception:
        return True, ''
    code = data.get('errcode')
    if code == 0:
        return True, ''
    return False, f"errcode={code} errmsg={data.get('errmsg', data)}"


def _send_webhook(text: str, webhook_url: str) -> bool:
    """预审通知统一走 Markdown：title 填关键词，避免 text 类型被机器人拒收仍返回 200。"""
    if not webhook_url:
        return False
    md_text = (text or '').strip() + _DOC_WEBHOOK_FOOTER
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {
            'title': _DOC_WEBHOOK_KEYWORD,
            'text': md_text,
        },
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        ok, detail = _parse_dingtalk_webhook_response(raw)
        if not ok:
            _log(f'webhook dingtalk rejected: {detail}')
        return ok
    except Exception as e:
        _log(f'webhook failed: {e}')
        return False


def _spawn_doc_review_progress(webhook_url: str, tpl: dict, interval_sec: int):
    """
    预审长耗时阶段后台进度：每隔 interval_sec 秒推送一条（含阶段与已等待秒数）。
    返回 handle dict（含 stop、state、thread）；interval<=0 或无 webhook 时返回 None。
    """
    if not webhook_url or interval_sec <= 0:
        return None
    stop = threading.Event()
    state = {
        'phase': '拉取文档内容',
        'doc_title': '',
        't0': time.time(),
    }

    def _worker():
        while not stop.wait(timeout=interval_sec):
            elapsed = int(time.time() - state['t0'])
            phase = state.get('phase') or '处理中'
            doc_title = (state.get('doc_title') or '').strip() or '（识别中）'
            raw = (tpl.get('progress_update') or '').strip()
            if not raw:
                raw = (
                    'PM助理 **预审进行中**\n'
                    '- **阶段**：{phase}\n'
                    '- **已等待**：约 {elapsed} 秒\n'
                    '- **文档**：{doc_title}\n\n'
                    '多角色预审可能需数分钟，无需重复发送指令。'
                )
            try:
                msg = raw.format(phase=phase, elapsed=elapsed, doc_title=doc_title)
            except Exception:
                msg = raw
            _send_webhook(msg, webhook_url)

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    return {'stop': stop, 'state': state, 'thread': th}


def _stop_doc_review_progress(handle) -> None:
    if not handle:
        return
    handle['stop'].set()
    try:
        handle['thread'].join(timeout=2.0)
    except Exception:
        pass


def _send_webhook_markdown(title: str, md_text: str, webhook_url: str) -> bool:
    """发送 Markdown 格式的钉钉消息（解析 errcode）。"""
    if not webhook_url:
        return False
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': title, 'text': md_text},
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        ok, detail = _parse_dingtalk_webhook_response(raw)
        if not ok:
            _log(f'webhook markdown dingtalk rejected: {detail}')
        return ok
    except Exception as e:
        _log(f'webhook markdown failed: {e}')
        return False


def _run_palace_cli(content: str, title: str, palace_root: str,
                    palace_base: str, provider: str = '',
                    palace_timeout: int = 600) -> dict:
    """用子进程调 Palace run.py CLI 执行预审，返回解析后的结果 dict"""
    run_py = os.path.join(palace_root, 'run.py')
    if not os.path.isfile(run_py):
        return {'_error': f'Palace run.py not found at {run_py}'}

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.md', encoding='utf-8', delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        cmd = [
            'py', run_py,
            '--scenario', 'what_precheck',
            '--input-file', tmp_path,
            '--title', title,
            '--doc-layer', 'WHAT',
            '--format', 'json',
            '--publish',
            '--publish-url', palace_base,
        ]
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        if provider:
            env['PALACE_PROVIDER'] = provider

        _log(f'subprocess: {" ".join(cmd[:6])}...')
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8',
            timeout=palace_timeout, cwd=palace_root, env=env,
        )

        if result.returncode != 0:
            _log(f'Palace CLI stderr: {result.stderr[:300]}')
            return {'_error': f'exit code {result.returncode}: {result.stderr[:200]}'}

        stdout = result.stdout.strip()
        # run.py --format json 输出 JSON 到 stdout，--publish 会额外输出一行 "Published to ..."
        # 找 JSON 部分（从第一个 { 到最后一个 }）
        json_start = stdout.find('{')
        json_end = stdout.rfind('}')
        if json_start < 0 or json_end < 0:
            return {'_error': f'No JSON in output: {stdout[:200]}'}

        data = json.loads(stdout[json_start:json_end + 1])

        # 从 --publish 输出行提取 report_id
        report_id = None
        for line in stdout.split('\n'):
            if 'Published to Palace Web:' in line and '/report/' in line:
                report_id = line.split('/report/')[-1].strip()
                break

        return {
            'success': True,
            'verdict': data.get('overall_verdict', 'error'),
            'blocker_count': data.get('blocker_count', 0),
            'concern_count': data.get('concern_count', 0),
            'report_id': report_id,
            'data': data,
        }
    except subprocess.TimeoutExpired:
        return {'_error': f'Palace CLI timed out ({palace_timeout}s)'}
    except Exception as e:
        return {'_error': str(e)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _build_summary(palace_resp: dict, title: str, url: str,
                   report_id: str | None, text_length: int,
                   palace_base: str = '', tpl: dict = None) -> str:
    """从 Palace 预审结果构建钉钉推送的摘要文本；tpl 为 doc_review 模板，缺省则自动加载。"""
    if tpl is None:
        tpl = _load_doc_review_templates()

    def _line(key: str, **kwargs) -> str:
        s = (tpl.get(key) or '').strip()
        if not s:
            return ''
        try:
            return s.format(**kwargs)
        except Exception:
            return s

    verdict = palace_resp.get('verdict', 'error')
    blocker = int(palace_resp.get('blocker_count') or 0)
    concern = int(palace_resp.get('concern_count') or 0)
    v_text = _VERDICT_LABEL.get(verdict, str(verdict))
    badge = _VERDICT_BADGE.get(verdict, '⚠️')
    data = palace_resp.get('data', {}) or {}
    issues = data.get('issues', []) if isinstance(data, dict) else []
    if not isinstance(issues, list):
        issues = []

    p0_items = [
        i for i in issues
        if isinstance(i, dict) and (i.get('severity') or '').upper() == 'P0'
    ]
    p1_items = [
        i for i in issues
        if isinstance(i, dict) and (i.get('severity') or '').upper() == 'P1'
    ]

    # 清单数字与下方列表一致：有分项时以列表为准，避免「汇总 1 项 / 列出 5 项」错位
    n_p0 = len(p0_items) if p0_items else blocker
    n_p1 = len(p1_items) if p1_items else concern

    _msi = tpl.get('summary_max_issues_per_severity')
    max_show = int(_msi) if _msi is not None else 6
    if max_show < 1:
        max_show = 6
    _mgc = tpl.get('summary_max_gap_chars')
    max_gap = int(_mgc) if _mgc is not None else 100
    if max_gap < 20:
        max_gap = 100

    doc_title = _strip_for_md_bold(title) or '（无标题）'
    lines = [
        _line('summary_header') or '### PM助理 · 文档预审完成',
        '',
        _line('summary_doc', title=doc_title) or f'**《{doc_title}》**',
        '',
        _line('summary_verdict', verdict_badge=badge, verdict_label=v_text)
        or f'**结论** {badge} **{v_text}**',
        '',
    ]

    stats_parts = []
    if n_p0 > 0:
        stats_parts.append(
            _line('summary_stat_p0', count=n_p0) or f'🔴 P0 **{n_p0}** 项'
        )
    if n_p1 > 0:
        stats_parts.append(
            _line('summary_stat_p1', count=n_p1) or f'🟡 P1 **{n_p1}** 项'
        )
    if stats_parts:
        head = (_line('summary_stats_prefix') or '**问题清单**').rstrip()
        lines.append(f'{head} · ' + ' · '.join(stats_parts))
    else:
        lines.append(_line('summary_no_issues') or '**问题清单**：未返回 P0/P1 分项，请打开完整报告查看。')
    lines.append('')
    lines.append(_line('summary_separator_major') or '---')
    lines.append('')

    def _append_issue_block(sev: str, items: list, section_key: str, more_key: str):
        if not items:
            return
        lines.append(
            _line(section_key, count=len(items))
            or (
                f'#### 🔴 P0 阻断（共 {len(items)} 项）'
                if sev == 'P0'
                else f'#### 🟡 P1 关注（共 {len(items)} 项）'
            )
        )
        lines.append('')
        shown = items[:max_show]
        for idx, item in enumerate(shown, 1):
            t = _strip_for_md_bold(item.get('title', '') or '') or '（未命名）'
            gap = _one_line(item.get('gap_description') or '')
            gap = _truncate(gap, max_gap)
            lines.append(f'{idx}. **{t}**')
            if gap:
                lines.append(f'　{gap}')
            lines.append('')
        if len(items) > max_show:
            lines.append(
                _line(more_key, shown=max_show, total=len(items))
                or f'… 共 {len(items)} 项，此处仅列前 {max_show} 项，其余见 Palace 报告。'
            )
            lines.append('')

    _append_issue_block('P0', p0_items, 'summary_section_p0', 'summary_more_p0')
    _append_issue_block('P1', p1_items, 'summary_section_p1', 'summary_more_p1')

    # 引擎汇总有计数但 issues 未带 severity 时，提示看报告
    if blocker > 0 and not p0_items:
        lines.append(
            _line('summary_p0_fallback', count=blocker)
            or f'🔴 引擎汇总 P0 **{blocker}** 项（明细未在推送中展开，请打开完整报告）。'
        )
        lines.append('')
    if concern > 0 and not p1_items:
        lines.append(
            _line('summary_p1_fallback', count=concern)
            or f'🟡 引擎汇总 P1 **{concern}** 项（明细未在推送中展开，请打开完整报告）。'
        )
        lines.append('')

    lines.append(_line('summary_separator_major') or '---')
    lines.append('')
    lines.append(_line('summary_chars', text_length=text_length) or f'**提取字数** {text_length}')
    if report_id:
        base = palace_base or PALACE_URL
        report_url = f'{base.rstrip("/")}/report/{report_id}'
        rlab = _palace_report_link_label(report_url)
        lines.append(
            _line('summary_report', report_url=report_url, report_link_label=rlab)
            or f'**完整报告** {_markdown_link(rlab, report_url)}'
        )
    lines.append(
        _line('summary_original', url=url)
        or f'**原文** {_markdown_link("打开钉钉文档", url)}'
    )
    return '\n'.join(lines)


def _save_failed(msg_id, url, title='', doc_url_normalized=''):
    try:
        save_doc_review_result(
            msg_id=msg_id, doc_url=url, doc_title=title, verdict='error',
            doc_url_normalized=doc_url_normalized,
        )
    except Exception:
        pass


def process_doc_review(msg_id: str, url: str, sender_uid: str,
                        msg_text: str, config: dict,
                        force_bypass_recent_window: bool = False) -> bool:
    """
    完整预审流程。
    返回 True = 处理完成；False = 失败但已通知；None = 暂时跳过

    force_bypass_recent_window：为 True 时忽略「同一文档近期已尝试」去重（用户发再预审/强制预审等）。
    """
    webhook_url = config.get('webhook_url', '')
    tpl = _load_doc_review_templates()
    normalized_url = normalize_doc_url(url)
    window_seconds = int(config.get('doc_review_window_seconds', 3600))

    # 同一文档在时间窗口内只尝试一次（成功/失败/超时都算已尝试）；用户可发「再预审」等强制再跑
    if normalized_url and was_doc_attempted_recently(normalized_url, window_seconds):
        if force_bypass_recent_window:
            _log(
                f'强制预审：忽略 {window_seconds}s 内去重，重新执行: {normalized_url[:50]}...'
            )
        else:
            minutes = max(1, window_seconds // 60)
            msg = (tpl.get('recently_attempted') or 'PM助理 该文档在近期已尝试过预审，请 {minutes} 分钟后再试。').format(minutes=minutes)
            _send_webhook(msg, webhook_url)
            try:
                save_doc_review_result(
                    msg_id=msg_id, doc_url=url, doc_title='', verdict='skipped',
                    doc_url_normalized=normalized_url,
                )
            except Exception:
                pass
            _log(f'文档在 {window_seconds}s 内已尝试过，跳过: {normalized_url[:50]}...')
            return False

    _log(f'开始预审: {url[:60]}...')
    # ── Step 1: 拉取文档内容 ──────────────────────────────────
    _send_webhook(tpl.get('started', 'PM助理 收到文档链接，正在读取并预审，请稍候（约 1-2 分钟）...'),
                  webhook_url)

    progress_interval = int(config.get('doc_review_progress_interval_seconds', 30))
    prog = _spawn_doc_review_progress(webhook_url, tpl, progress_interval)
    try:
        fetch_result = _post(DAEMON_URL.rstrip('/') + '/fetch_report_content', {
            'url': url,
            'wait_extra': 15,
        }, timeout=120)

        if fetch_result.get('_error') or not fetch_result.get('success'):
            err = fetch_result.get('error') or fetch_result.get('_error') or 'unknown'
            _log(f'fetch failed: {err}')
            msg = (tpl.get('fetch_fail') or 'PM助理 文档读取失败: {error}').format(error=err)
            _send_webhook(msg, webhook_url)
            _save_failed(msg_id, url, doc_url_normalized=normalized_url)
            return False

        title   = fetch_result.get('title', '')
        content = (fetch_result.get('content') or '').strip()
        method  = fetch_result.get('extraction_method', 'body')
        length  = fetch_result.get('text_length', 0)

        # 清理 title 中的零宽字符
        title = re.sub(r'[\u200b\u200c\u200d\u2060\ufeff\u2061-\u2069]+', '', title)
        # 提取 "xxx · 钉钉文档" 中的实际标题
        if ' · ' in title:
            title = title.split(' · ')[0].strip()

        _log(f'fetch done: title={title!r}, length={length}, method={method}')

        if prog:
            prog['state']['doc_title'] = title
            prog['state']['phase'] = 'Palace 多角色预审'

        if not content or length < 50:
            _log('content too short, SPA may not have rendered')
            msg = (tpl.get('content_too_short') or 'PM助理 文档《{title}》内容过少（{length} 字），可能页面未完全渲染。\n{url}').format(title=title, length=length, url=url)
            _send_webhook(msg, webhook_url)
            _save_failed(msg_id, url, title, doc_url_normalized=normalized_url)
            return False

        # ── Step 2: 调 Palace CLI 预审 ──────────────────────────────
        palace_root = config.get('palace_root', '') or PALACE_ROOT
        palace_base = config.get('palace_url', '') or PALACE_URL
        _log(f'calling Palace CLI (root={palace_root}) ...')

        provider = config.get('palace_provider', '')
        palace_timeout = int(config.get('doc_review_palace_timeout_seconds', 600))
        palace_resp = _run_palace_cli(content, title, palace_root, palace_base,
                                       provider=provider, palace_timeout=palace_timeout)

        if not palace_resp or palace_resp.get('_error'):
            err = (palace_resp or {}).get('_error', 'Palace precheck failed')
            _log(f'Palace error: {err}')
            msg = (tpl.get('palace_fail') or 'PM助理 文档预审引擎异常: {error}\n文档: {title}\n{url}').format(error=err, title=title, url=url)
            _send_webhook(msg, webhook_url)
            _save_failed(msg_id, url, title, doc_url_normalized=normalized_url)
            return False

        report_id = palace_resp.get('report_id')
        _log(f'Palace done: verdict={palace_resp.get("verdict")}, '
             f'report_id={report_id}')

        # ── Step 3: 推送预审摘要到群 ──────────────────────────────
        summary = _build_summary(palace_resp, title, url, report_id, length,
                                 palace_base=palace_base, tpl=tpl)
        _send_webhook(summary, webhook_url)

        # ── Step 4: 持久化到 DB，防止重启后重复处理 ─────────────
        try:
            save_doc_review_result(
                msg_id=msg_id, doc_url=url, doc_title=title,
                verdict=palace_resp.get('verdict', ''),
                report_id=report_id or '',
                doc_url_normalized=normalized_url,
            )
        except Exception as e:
            _log(f'save_doc_review_result failed: {e}')

        _log(f'预审完成，已通知群')
        return True
    finally:
        _stop_doc_review_progress(prog)
