# -*- coding: utf-8 -*-
"""
MyAgents 服务巡检与「上班啦」拉起

# [AgentStat Task] 2026-03-26 上班啦拉起+查岗巡检；口令始终推摘要；daemon /health 深度检查

- 从 digest_config.json memo_tracker.services_status_check 读取巡检项；留空则用内置列表
- 「上班啦」：检测 + 对挂了的有 start 配置则尝试后台拉起，再复检；**口令触达时始终推钉钉**（便于确认已尝试拉起与当前状态）
- 「查岗」：只检测不启动；**用户口令触达时始终推钉钉**（含全绿摘要）。「全绿不推」仅适用于未实现的定时静默巡检，不用于群内「查岗」回复。
- 「修复」：同上班啦尝试拉起，复检后**始终推送摘要**；钉钉大门仍异常时**分离子进程**跑 daemon_health_notify（避免在本进程里 restart 把自己杀掉）
- 易读 Markdown 经 webhook 发送（关键词见 message_templates status_check）
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
_WORKSPACE_ROOT = os.path.dirname(_ROOT)
_DIGEST_PATH = os.path.join(_ROOT, 'digest_config.json')
_TEMPLATES_PATH = os.path.join(_ROOT, 'message_templates.json')
# 仅 headless 自动拉起时持有日志句柄，避免被 GC 关掉
_AUTOSTART_LOG_HANDLES: list = []


def _load_templates() -> dict:
    try:
        with open(_TEMPLATES_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('status_check', {}) or {}
    except Exception:
        return {}


def _load_services_from_digest() -> list[dict] | None:
    """返回非空 list 表示完全替换内置；None 表示用内置。"""
    try:
        with open(_DIGEST_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        mt = cfg.get('memo_tracker') or {}
        raw = mt.get('services_status_check')
        if isinstance(raw, list) and len(raw) > 0:
            return [_normalize_service_entry(x) for x in raw if isinstance(x, dict)]
    except Exception:
        pass
    return None


def _normalize_service_entry(x: dict) -> dict:
    sid = str(x.get('id') or x.get('name') or 'svc').strip()
    name = str(x.get('name') or sid).strip()
    port = int(x['port'])
    host = str(x.get('host') or '127.0.0.1').strip() or '127.0.0.1'
    path = str(x.get('path') or '/').strip() or '/'
    method = str(x.get('method') or 'health').strip().lower()
    start = x.get('start')
    if start is not None and not isinstance(start, dict):
        start = None
    return {
        'id': sid,
        'name': name,
        'host': host,
        'port': port,
        'path': path,
        'method': method,
        'start': start,
    }


def _default_services() -> list[dict]:
    """内置默认：与本机常见军团端口对齐（同一端口不要配两项）。"""
    py = sys.executable
    return [
        {
            'id': 'dingtalk_daemon',
            'name': '钉钉桌面通道（大门）',
            'host': '127.0.0.1',
            'port': 19200,
            'path': '/health',
            'method': 'daemon_full',
            'start': None,
        },
        {
            'id': 'web_8000',
            'name': '端口 8000（任务提醒等）',
            'host': '127.0.0.1',
            'port': 8000,
            'path': '/',
            'method': 'http_any',
            'start': {
                'cwd': 'task_reminder',
                'argv': [py, 'server.py'],
            },
        },
        {
            'id': 'pm_frontend',
            'name': 'PM 系统前端',
            'host': '127.0.0.1',
            'port': 3005,
            'path': '/',
            'method': 'http_any',
            'start': {
                'cwd': 'pm-system',
                'argv': [py, '-m', 'http.server', '3005'],
            },
        },
        {
            'id': 'performeval',
            'name': '绩效系统 PerformEval',
            'host': '127.0.0.1',
            'port': 8112,
            'path': '/api/health',
            'method': 'health',
            'start': {
                'cwd': 'performeval',
                'argv': [py, '-m', 'uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '8112'],
            },
        },
        {
            'id': 'md_reader',
            'name': 'MD 阅读器',
            'host': '127.0.0.1',
            'port': 8899,
            'path': '/api/health',
            'method': 'health',
            'start': {
                'cwd': 'md-reader',
                'argv': [py, '-m', 'uvicorn', 'server:app', '--host', '0.0.0.0', '--port', '8899'],
                'env_extra': {'MD_READER_ROOT': os.path.abspath(_WORKSPACE_ROOT)},
            },
        },
        {
            'id': 'palace',
            'name': 'Palace 预审前台',
            'host': '127.0.0.1',
            'port': 8300,
            'path': '/api/health',
            'method': 'health',
            'start': {
                'cwd': 'palace',
                'argv': [py, '-m', 'uvicorn', 'palace_web.server:app', '--host', '0.0.0.0', '--port', '8300'],
            },
        },
    ]


def load_services() -> list[dict]:
    custom = _load_services_from_digest()
    if custom is not None:
        return custom
    return _default_services()


def _check_tcp(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True, '端口在监听'
    except OSError as e:
        return False, str(e)[:120]


def _check_http(
    host: str, port: int, path: str, method: str,
) -> tuple[bool, str]:
    url = 'http://%s:%s%s' % (host, port, path if path.startswith('/') else '/' + path)
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=6) as resp:
            if method == 'health':
                if resp.status != 200:
                    return False, 'HTTP %s' % resp.status
                return True, '健康检查通过'
            if method == 'http_any':
                return resp.status == 200, 'HTTP %s' % resp.status
    except urllib.error.HTTPError as e:
        return False, 'HTTP %s' % e.code
    except urllib.error.URLError as e:
        return False, str(e.reason or e)[:120]
    except Exception as e:
        return False, str(e)[:120]
    return False, '未知'


def _check_daemon_full(host: str, port: int, path: str) -> tuple[bool, str]:
    url = 'http://%s:%s%s' % (host, port, path if path.startswith('/') else '/' + path)
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
        data = json.loads(raw)
    except urllib.error.URLError as e:
        return False, '本机 :%s 连不上（大门没起？）— %s' % (port, str(e.reason or e)[:80])
    except Exception as e:
        return False, '解析异常：%s' % str(e)[:100]

    if data.get('daemon') != 'running':
        return False, '进程在但状态异常'
    problems = []
    if not data.get('frida_attached'):
        problems.append('Frida 未挂上钉钉')
    if not data.get('cef_ready'):
        problems.append('CEF 未就绪')
    if not data.get('dingtalk_running'):
        problems.append('钉钉主程序未在跑')
    if 'monitor_running' in data and data.get('monitor_running') is False:
        problems.append('消息监控未就绪')
    if problems:
        return False, '；'.join(problems)
    return True, 'Frida / CEF / 钉钉 / 监控均正常'


def check_one(svc: dict) -> dict:
    host, port, path = svc['host'], svc['port'], svc['path']
    method = svc['method']
    endpoint = 'http://%s:%s%s' % (host, port, path)

    if method == 'tcp':
        ok, reason = _check_tcp(host, port)
    elif method == 'daemon_full':
        ok, reason = _check_daemon_full(host, port, path)
    elif method in ('health', 'http_any'):
        ok, reason = _check_http(host, port, path, method)
    else:
        ok, reason = False, '未知 method：%s' % method

    return {
        'id': svc['id'],
        'name': svc['name'],
        'ok': ok,
        'reason': reason,
        'endpoint': endpoint,
        'start': svc.get('start'),
    }


def run_checks(host: str | None = None) -> list[dict]:
    host = host or '127.0.0.1'
    services = load_services()
    out = []
    for svc in services:
        s = dict(svc)
        s['host'] = host
        out.append(check_one(s))
    return out


def _argv_looks_like_daemon(argv: list[str]) -> bool:
    """命令行是否在启动 dingtalk daemon（避免上班啦再拉起第二个大门）。"""
    for a in argv:
        s = str(a).replace('\\', '/').lower()
        if s.endswith('daemon.py') or '/daemon.py' in s or s == 'daemon.py':
            return True
    return False


def _daemon_listen_port() -> int:
    try:
        return int(os.environ.get('DINGTALK_DAEMON_PORT', '19200'))
    except ValueError:
        return 19200


def _try_start(svc: dict, host: str = '127.0.0.1') -> bool:
    st = svc.get('start')
    if not st or not isinstance(st, dict):
        return False
    cwd_rel = str(st.get('cwd') or '').strip()
    argv = st.get('argv')
    if not cwd_rel or not isinstance(argv, list) or not argv:
        return False
    cwd = os.path.join(_WORKSPACE_ROOT, cwd_rel.replace('/', os.sep))
    if not os.path.isdir(cwd):
        return False
    argv = [str(x) for x in argv]
    force_busy = os.environ.get('STATUS_CHECK_ALLOW_START_ON_BUSY_PORT', '').strip() in (
        '1', 'true', 'yes',
    )
    if _argv_looks_like_daemon(argv):
        if _check_tcp(host, _daemon_listen_port())[0]:
            return False
    elif not force_busy and svc.get('port') is not None:
        if _check_tcp(host, int(svc['port']))[0]:
            return False
    try:
        headless_win = (
            sys.platform == 'win32'
            and os.environ.get('STATUS_CHECK_START_HEADLESS', '').strip().lower() in (
                '1', 'true', 'yes',
            )
        )
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = (
                getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                if headless_win
                else getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10)
            )
        env = os.environ.copy()
        extra = st.get('env_extra') or {}
        if isinstance(extra, dict):
            for k, v in extra.items():
                env[str(k)] = str(v)
        if headless_win:
            log_dir = os.path.join(_ROOT, 'logs')
            os.makedirs(log_dir, exist_ok=True)
            sid = str(svc.get('id') or 'svc').replace(os.sep, '_')[:48] or 'svc'
            log_path = os.path.join(log_dir, 'autostart_%s.log' % sid)
            lf = open(log_path, 'a', encoding='utf-8', errors='replace')
            _AUTOSTART_LOG_HANDLES.append(lf)
            subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=lf,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                close_fds=False,
            )
        else:
            subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        return True
    except Exception:
        return False


def run_checks_and_start(
    host: str = '127.0.0.1',
    wait_after_start: int = 8,
) -> list[dict]:
    services = load_services()
    svc_by_id = {x['id']: x for x in services}
    results = []
    for svc in services:
        s = dict(svc)
        s['host'] = host
        results.append(check_one(s))

    for r in results:
        base = svc_by_id.get(r['id'], {})
        r['started'] = False
        if not r['ok'] and _try_start(base, host=host):
            r['started'] = True

    if any(r.get('started') for r in results):
        time.sleep(wait_after_start)
        fresh = {
            x['id']: check_one({**svc_by_id[x['id']], 'host': host})
            for x in results if x['id'] in svc_by_id
        }
        for r in results:
            if r.get('started'):
                nr = fresh.get(r['id'])
                if nr:
                    r['ok'] = nr['ok']
                    r['reason'] = nr['reason']

    for r in results:
        if r['ok']:
            r['status'] = 'started_ok' if r.get('started') else 'ok'
        else:
            r['status'] = 'started_fail' if r.get('started') else 'fail'
    return results


def _all_ok(results: list[dict]) -> bool:
    return all(r.get('ok') for r in results)


def _started_recovered_markdown_lines(results: list[dict]) -> list[str]:
    """上班啦：本次执行里触发过启动且复检已正常的项。"""
    out: list[str] = []
    for r in results:
        if r.get('status') != 'started_ok':
            continue
        name = r.get('name', r.get('id', '?'))
        out.append('- **%s** 已尝试拉起，复检正常' % name)
    return out


def _bad_item_markdown_lines(results: list[dict]) -> list[str]:
    """异常项：列表 + emoji，便于钉钉 Markdown 阅读。"""
    out: list[str] = []
    for r in results:
        if r.get('ok'):
            continue
        st = r.get('status', 'fail')
        if st == 'started_fail':
            emoji, tag = '🔴', '已尝试启动仍异常'
        else:
            emoji, tag = '⚠️', '未就绪'
        name = r.get('name', r.get('id', '?'))
        reason = (r.get('reason') or '无详情').replace('\n', ' ').strip()
        out.append('- %s **%s**' % (emoji, name))
        out.append('  - %s（*%s*）' % (reason, tag))
    return out


def _render_human_markdown(
    results: list[dict],
    mode: str,
    timestamp: str,
    tpl: dict,
) -> str:
    """mode: morning | inspection"""
    if mode == 'inspection':
        in_ok = _all_ok(results)
        if in_ok:
            title = (tpl.get('title_inspection_all_ok') or '').strip() or '## 查岗结果 · 全部正常'
            intro = (tpl.get('intro_inspection_all_ok') or '').strip() or (
                '刚按你的 **查岗** 扫了一遍，**当前全部正常**，无需处理。'
            )
        else:
            title = tpl.get('title_inspection') or '## 查岗结果 · 有需要你瞄一眼的'
            intro = tpl.get('intro_inspection') or (
                '刚按你的 **查岗** 把各服务扫了一遍。**下面列出来的都是不正常的**；'
                '没出现在列表里的就是当前探测正常。'
            )
    else:
        in_ok = _all_ok(results)
        any_started = any(r.get('started') for r in results)
        if in_ok:
            title = (tpl.get('title_morning_all_ok') or '').strip() or '## 上班啦 · 已全部就绪'
            if any_started:
                intro = (tpl.get('intro_morning_all_ok') or '').strip() or (
                    '已按 **上班啦** 对未就绪项尝试拉起并完成复检，**当前全部正常**。'
                )
            else:
                intro = (tpl.get('intro_morning_all_ok_idle') or '').strip() or (
                    '已按 **上班啦** 巡检：各服务**已在运行**，未触发自动拉起。'
                )
        else:
            title = tpl.get('title_morning') or '## 上班啦 · 仍有异常需关注'
            intro = tpl.get('intro_morning') or (
                '已按 **上班啦** 执行：**能自动拉起的已试着拉起**，并复检了一遍。'
                '下面仍标出的，需要你本机看一下（端口占用、脚本报错等）。'
            )

    lines = [
        title,
        '',
        '**时间** %s' % timestamp,
        '',
        intro,
        '',
    ]

    if mode == 'morning':
        rec_lines = _started_recovered_markdown_lines(results)
        if rec_lines:
            lines.append('**本次拉起已恢复**')
            lines.extend(rec_lines)
            lines.append('')

    bad_lines = _bad_item_markdown_lines(results)
    if bad_lines:
        lines.append('**需关注**')
        lines.extend(bad_lines)
        lines.append('')

    ok_n = sum(1 for r in results if r.get('ok'))
    total = len(results)
    lines.append(
        '**小结** 共巡检 **%d** 项，其中 **%d** 项正常、**%d** 项需要处理。'
        % (total, ok_n, total - ok_n)
    )
    sep = tpl.get('separator') or '---'
    footer = tpl.get('footer') or '###### ※ 小秘书提醒'
    lines.extend(['', sep, '', footer])
    return '\n'.join(lines)


def _render_repair_markdown(
    results: list[dict],
    timestamp: str,
    tpl: dict,
    *,
    gate_repair_spawned: bool,
) -> str:
    title = tpl.get('title_repair') or '## 修复结果 · 复检摘要'
    intro_ok = tpl.get('intro_repair_all_ok') or (
        '已按 **修复** 尝试拉起各服务并复检。**当前全部正常**。'
    )
    intro_partial = tpl.get('intro_repair_partial') or (
        '已按 **修复** 尝试拉起各服务并复检。下面仍为异常的项需要你本机再看（配置端口、依赖未装等）。'
    )
    lines = [
        title,
        '',
        '**时间** %s' % timestamp,
        '',
    ]
    if _all_ok(results):
        lines.append(intro_ok)
    else:
        lines.append(intro_partial)
        lines.append('')
        bl = _bad_item_markdown_lines(results)
        if bl:
            lines.append('**仍异常**')
            lines.extend(bl)
            lines.append('')
    ok_n = sum(1 for r in results if r.get('ok'))
    total = len(results)
    lines.append(
        '**小结** 共 **%d** 项，**%d** 项正常、**%d** 项待处理。'
        % (total, ok_n, total - ok_n)
    )
    if gate_repair_spawned:
        lines.append('')
        lines.append(
            '> **钉钉大门**：已另起**后台进程**做通道自检（与 **查岗** 大门判定一致，含 **monitor_running**），必要时会自动重启；'
            '约半分钟内还会收到一条 **「通道自检」** 推送（与本次摘要可能分两条发）。'
        )
    sep = tpl.get('separator') or '---'
    footer = tpl.get('footer') or '###### ※ 小秘书提醒'
    lines.extend(['', sep, '', footer])
    return '\n'.join(lines)


def _gate_repair_webhook_key() -> str:
    k = (os.environ.get('STATUS_CHECK_GATE_REPAIR_WEBHOOK_KEY') or '').strip()
    return k or 'default'


def _spawn_daemon_health_notify_detached(webhook_key: str) -> None:
    """分离子进程跑 daemon_health_notify，避免在 daemon 线程内 restart 导致当前进程被关。"""
    py = sys.executable
    script = os.path.join(_ROOT, 'daemon_health_notify.py')
    argv = [py, script, '--webhook-key', webhook_key or 'default']
    kw: dict = {}
    if sys.platform == 'win32':
        kw['creationflags'] = (
            getattr(subprocess, 'DETACHED_PROCESS', 0x8)
            | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200)
        )
    subprocess.Popen(
        argv,
        cwd=_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **kw,
    )


def send_via_webhook(md_text: str, webhook_url: str, keyword: str = '小秘书提醒') -> bool:
    if not webhook_url or not (md_text or '').strip():
        return False
    payload = json.dumps({
        'msgtype': 'markdown',
        'markdown': {'title': keyword, 'text': md_text},
    }).encode('utf-8')
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception:
        return False


def run_morning_flow(webhook_url: str, host: str = '127.0.0.1') -> dict:
    """上班啦：拉起 + 复检；**始终推送**摘要（含「已在跑未拉起」「已拉起恢复」「仍异常」）。"""
    tpl = _load_templates()
    keyword = tpl.get('keyword', '小秘书提醒')
    ts = datetime.now().strftime('%m-%d %H:%M')
    results = run_checks_and_start(host=host)
    all_ok = _all_ok(results)
    md = _render_human_markdown(results, 'morning', ts, tpl)
    ok_send = send_via_webhook(md, webhook_url, keyword=keyword)
    return {
        'success': ok_send,
        'notified': ok_send,
        'all_ok': all_ok,
        'results': results,
    }


def run_inspection_flow(webhook_url: str, host: str = '127.0.0.1') -> dict:
    """查岗：只巡检；**始终推送**摘要（全绿也推，便于确认口令已执行）。"""
    tpl = _load_templates()
    keyword = tpl.get('keyword', '小秘书提醒')
    ts = datetime.now().strftime('%m-%d %H:%M')
    results = run_checks(host=host)
    for r in results:
        r['status'] = 'ok' if r['ok'] else 'fail'
        r['started'] = False
    all_ok = _all_ok(results)
    md = _render_human_markdown(results, 'inspection', ts, tpl)
    ok_send = send_via_webhook(md, webhook_url, keyword=keyword)
    return {
        'success': ok_send,
        'notified': ok_send,
        'all_ok': all_ok,
        'results': results,
    }


def run_repair_flow(webhook_url: str, host: str = '127.0.0.1') -> dict:
    """修复：先推「已收到」；再同上班啦拉起并复检并推摘要；大门仍异常则分离子进程跑 daemon_health_notify。"""
    tpl = _load_templates()
    keyword = tpl.get('keyword', '小秘书提醒')
    ts = datetime.now().strftime('%m-%d %H:%M')
    sep = tpl.get('separator') or '---'
    foot = tpl.get('footer') or '###### ※ 小秘书提醒'
    ack_body = (tpl.get('repair_ack') or '').strip() or (
        '### 修复 · **指令已收到**\n\n'
        '已开始按 **修复** 巡检并尝试拉起各服务；**几秒后**会再推一条 **复检摘要**。\n\n'
        '若 **钉钉大门** 仍异常，之后还会再推一条 **通道自检**（与查岗同一套健康标准，含消息监控）。'
    )
    ack_md = '%s\n\n**时间** %s\n\n%s\n\n%s' % (ack_body, ts, sep, foot)
    ack_ok = send_via_webhook(ack_md, webhook_url, keyword=keyword)

    results = run_checks_and_start(host=host)
    gate_bad = any(
        r.get('id') == 'dingtalk_daemon' and not r.get('ok')
        for r in results
    )
    md = _render_repair_markdown(
        results, ts, tpl, gate_repair_spawned=gate_bad,
    )
    ok_send = send_via_webhook(md, webhook_url, keyword=keyword)
    if gate_bad:
        _spawn_daemon_health_notify_detached(_gate_repair_webhook_key())
    return {
        'success': ok_send,
        'notified': ok_send,
        'ack_notified': bool(ack_ok),
        'all_ok': _all_ok(results),
        'results': results,
        'gate_repair_spawned': bool(gate_bad),
    }


def run_and_send(webhook_url: str, host: str = '127.0.0.1') -> bool:
    """兼容旧调用：等价于上班啦流程；成功指 webhook 发送成功。"""
    r = run_morning_flow(webhook_url, host=host)
    return bool(r.get('success'))


if __name__ == '__main__':
    sys.path.insert(0, _ROOT)
    from lib.utils import get_webhook_url

    fallback = ''
    try:
        with open(_DIGEST_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        fallback = (cfg.get('memo_tracker') or {}).get('webhook_url') or cfg.get('webhook_url', '')
    except Exception:
        pass
    webhook_url = get_webhook_url('memo_tracker', fallback)
    if not webhook_url:
        print('no webhook_url', flush=True)
        sys.exit(1)
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'morning').lower()
    if mode == 'inspect':
        out = run_inspection_flow(webhook_url)
    elif mode in ('repair', 'fix'):
        out = run_repair_flow(webhook_url)
    else:
        out = run_morning_flow(webhook_url)
    print(
        'notified=%s all_ok=%s' % (out.get('notified'), out.get('all_ok')),
        flush=True,
    )
    sys.exit(0 if out.get('success') else 1)
