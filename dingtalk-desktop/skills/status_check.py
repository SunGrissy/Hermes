# -*- coding: utf-8 -*-
"""
MyAgents 工具运行状态与自动就绪

- 检测各服务健康端点；未就绪的尝试自动启动，再重检后通知
- 结果文案从 message_templates.json 的 status_check 读取
- 支持被 skill_router 在「上班啦」触发后调用，并通过指定 webhook 发送（关键词：小秘书提醒）
"""
import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)  # dingtalk-desktop
_WORKSPACE_ROOT = os.path.dirname(_ROOT)  # MyAgents
_TEMPLATES_PATH = os.path.join(_ROOT, 'message_templates.json')

# 检测列表：不含 CCI；md-reader、Palace 独立
SERVICES = [
    {'name': 'PmSystemApp', 'port': 8000, 'path': '/api/health', 'method': 'health'},
    {'name': 'PerformEval', 'port': 8112, 'path': '/api/health', 'method': 'health'},
    {'name': 'md-reader', 'port': 8899, 'path': '/api/health', 'method': 'health'},
    {'name': 'Palace', 'port': 8300, 'path': '/api/health', 'method': 'health'},
    {'name': 'dingtalk-desktop', 'port': 19200, 'path': '/api/health', 'method': 'health'},
]

# 未就绪时自动启动：name -> (cwd 相对 WORKSPACE_ROOT, argv)
_START_COMMANDS = {
    'PmSystemApp': ('pm-system/backend', [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', '8000']),
    'PerformEval': ('performeval', [sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '8112']),
    'md-reader': ('md-reader', [sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', '8899']),
    'Palace': ('palace', [sys.executable, '-m', 'uvicorn', 'palace_web.server:app', '--host', '0.0.0.0', '--port', '8300']),
    # dingtalk-desktop 不自动启动（当前进程即 daemon）
}


def _load_templates():
    try:
        with open(_TEMPLATES_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('status_check', {})
    except Exception:
        return {}


def _check_one(host: str, port: int, path: str, method: str) -> tuple[bool, str]:
    """检测单服务，返回 (是否正常, 描述)。"""
    url = f'http://{host}:{port}{path}'
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            if method == 'health':
                if resp.status != 200:
                    return False, f'HTTP {resp.status}'
                return True, url
            return resp.status == 200, url
    except urllib.error.HTTPError as e:
        return False, f'HTTP {e.code}'
    except urllib.error.URLError as e:
        return False, str(e.reason) if getattr(e, 'reason', None) else str(e)
    except Exception as e:
        return False, str(e)


def run_checks(host: str = '127.0.0.1') -> list[dict]:
    """执行所有服务检测，返回 [{'name','ok','endpoint','reason'}, ...]。"""
    results = []
    for svc in SERVICES:
        ok, detail = _check_one(host, svc['port'], svc['path'], svc['method'])
        endpoint = f"http://{host}:{svc['port']}{svc['path']}"
        results.append({
            'name': svc['name'],
            'ok': ok,
            'endpoint': endpoint,
            'reason': detail if not ok else None,
        })
    return results


def _try_start(name: str) -> bool:
    """尝试启动指定服务（后台、不阻塞）。返回是否已发起启动。"""
    cmd = _START_COMMANDS.get(name)
    if not cmd:
        return False
    cwd_rel, argv = cmd
    cwd = os.path.join(_WORKSPACE_ROOT, cwd_rel.replace('/', os.sep))
    if not os.path.isdir(cwd):
        return False
    try:
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return True
    except Exception:
        return False


def run_checks_and_start(host: str = '127.0.0.1', wait_after_start: int = 6) -> list[dict]:
    """先检测，对未就绪的尝试启动，等待后重检；返回带 status 的结果。"""
    results = run_checks(host=host)
    # 对未就绪的发起启动
    for r in results:
        if not r['ok'] and _try_start(r['name']):
            r['started'] = True
        else:
            r['started'] = False
    if any(r.get('started') for r in results):
        time.sleep(wait_after_start)
        results2 = run_checks(host=host)
        by_name = {r['name']: r for r in results2}
        for r in results:
            if r.get('started'):
                r['ok'] = by_name.get(r['name'], {}).get('ok', False)
    # 统一 status：ok | started_ok | started_fail | fail
    for r in results:
        if r['ok']:
            r['status'] = 'started_ok' if r.get('started') else 'ok'
        else:
            r['status'] = 'started_fail' if r.get('started') else 'fail'
    return results


def _render_markdown(results: list[dict], tpl: dict, timestamp: str) -> str:
    """根据模板生成可读的 Markdown 正文；每项后空一行便于换行显示。"""
    lines = []
    title = (tpl.get('title') or '## 工具状态 [{timestamp}]').format(timestamp=timestamp)
    intro = (tpl.get('intro') or '收到「上班啦」，已检查并确保服务就绪：')
    item_ok = tpl.get('item_ok') or '✅ **{name}** — 已就绪'
    item_started_ok = tpl.get('item_started_ok') or '✅ **{name}** — 已尝试启动，当前已就绪'
    item_started_fail = tpl.get('item_started_fail') or '⚠️ **{name}** — 已尝试启动，请稍后确认'
    item_fail = tpl.get('item_fail') or '❌ **{name}** — 未响应（未配置自动启动）'
    summary_ok = tpl.get('summary_ok') or '**汇总**：{ok_count}/{total} 项已就绪'
    summary_partial = tpl.get('summary_partial') or '**汇总**：{ok_count}/{total} 项已就绪'
    sep = tpl.get('separator') or '---'
    footer = tpl.get('footer') or '###### ※ 小秘书提醒'

    lines.append(title)
    lines.append('')
    lines.append(intro)
    lines.append('')

    ok_count = 0
    for r in results:
        s = r.get('status', 'ok' if r['ok'] else 'fail')
        name = r.get('name', '')
        endpoint = r.get('endpoint', '')
        reason = r.get('reason', '')
        try:
            if s == 'ok':
                ok_count += 1
                lines.append(item_ok.format(name=name, endpoint=endpoint, reason=reason))
            elif s == 'started_ok':
                ok_count += 1
                lines.append(item_started_ok.format(name=name, endpoint=endpoint, reason=reason))
            elif s == 'started_fail':
                lines.append(item_started_fail.format(name=name, endpoint=endpoint, reason=reason))
            else:
                lines.append(item_fail.format(name=name, endpoint=endpoint, reason=reason))
        except KeyError:
            lines.append(item_ok.format(name=name) if s in ('ok', 'started_ok') else item_fail.format(name=name))
        lines.append('')  # 每项后空一行，钉钉 Markdown 换行更清晰

    total = len(results)
    fail_count = total - ok_count
    if total == ok_count:
        lines.append(summary_ok.format(ok_count=ok_count, total=total, fail_count=fail_count))
    else:
        lines.append(summary_partial.format(ok_count=ok_count, total=total, fail_count=fail_count))
    lines.append('')
    lines.append(sep)
    lines.append('')
    lines.append(footer)
    return '\n'.join(lines)


def send_via_webhook(md_text: str, webhook_url: str, keyword: str = '小秘书提醒') -> bool:
    """通过钉钉机器人 webhook 发送 Markdown；title 填关键词以满足校验。"""
    if not webhook_url:
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


def run_and_send(webhook_url: str, host: str = '127.0.0.1') -> bool:
    """检查并确保就绪（未就绪则尝试启动）、按模板生成正文、通过 webhook 发送。"""
    tpl = _load_templates()
    keyword = tpl.get('keyword', '小秘书提醒')
    timestamp = datetime.now().strftime('%m-%d %H:%M')
    results = run_checks_and_start(host=host)
    md_text = _render_markdown(results, tpl, timestamp)
    # 正文过短时不发送，避免钉钉只显示标题「小秘书提醒」
    if not md_text or len(md_text.strip()) < 50:
        return False
    return send_via_webhook(md_text, webhook_url, keyword=keyword)


if __name__ == '__main__':
    # 优先从 webhook_config.json 的 memo_tracker 读取，无则回退 digest_config
    sys.path.insert(0, _ROOT)
    from lib.utils import get_webhook_url
    fallback = ''
    try:
        with open(os.path.join(_ROOT, 'digest_config.json'), 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        fallback = (cfg.get('memo_tracker') or {}).get('webhook_url') or cfg.get('webhook_url', '')
    except Exception:
        pass
    webhook_url = get_webhook_url('memo_tracker', fallback)
    if not webhook_url:
        print('no webhook_url in webhook_config.json (memo_tracker) or digest_config.json', flush=True)
        sys.exit(1)
    ok = run_and_send(webhook_url)
    print('sent' if ok else 'send failed', flush=True)
    sys.exit(0 if ok else 1)
