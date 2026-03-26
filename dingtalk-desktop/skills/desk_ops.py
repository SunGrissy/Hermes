# -*- coding: utf-8 -*-
"""
桌面运维快捷指令（助理群 / 白名单群）：检查大门、重启大门、拉日报、启动 PM 栈等。
与 memo_tracker 共用 webhook；长任务不占 memo 串行锁。
"""
from __future__ import annotations

import os
import re
import json
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta

from skills.memo_tracker import (
    _consume_edit_cmd_dedup,
    _send_webhook,
    _send_webhook_chunks,
    _wish_webhook_for_cid,
)
from lib.utils import DATA_DIR

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, '..'))
_DIGEST_CONFIG = os.path.join(_ROOT, 'digest_config.json')
_WORKSPACE = os.path.normpath(os.path.join(_ROOT, '..'))
_PROC_MGR = os.path.join(_WORKSPACE, 'proc_manager.py')
_PROC_STATE = os.path.join(DATA_DIR, 'proc_manager_session.json')
_PM_SYSTEM_DIR = os.path.join(_WORKSPACE, 'pm-system')
_PM_HEADLESS_BAT = os.path.join(_PM_SYSTEM_DIR, 'quick_start_headless.bat')
_PM_TITLE_FILTERS = (
    'PM_System_Backend*',
    'PM_System_Frontend*',
    'MD_Reader*',
    'MD Reader*',
    'Palace_Web*',
)


def _kw_title(suffix: str) -> str:
    return f'小秘书提醒 · 运维 · {suffix}'


def _parse_compact_date_yymmdd(compact: str) -> str | None:
    s = (compact or '').strip()
    if len(s) == 8 and s.isdigit():
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    elif len(s) == 6 and s.isdigit():
        y, m, d = 2000 + int(s[:2]), int(s[2:4]), int(s[4:6])
    else:
        return None
    try:
        datetime(y, m, d)
    except ValueError:
        return None
    return f'{y:04d}-{m:02d}-{d:02d}'


def _load_digest_group_labels() -> dict:
    try:
        with open(_DIGEST_CONFIG, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        labels = cfg.get('digest_group_labels') or {}
        return {str(k): str(v) for k, v in labels.items() if str(k).strip() and str(v).strip()}
    except Exception:
        return {}


def _parse_date_spec_fragment(fragment: str):
    s = (fragment or '').strip()
    if not s:
        return ('rel', '今天')
    if s in ('今天', '昨天'):
        return ('rel', s)
    if re.match(r'^(\d{6}|\d{8})$', s):
        iso = _parse_compact_date_yymmdd(s)
        if iso:
            return ('one', iso)
        return None
    m = re.match(r'^([1-9]\d?)天$', s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 31:
            return ('days', n)
    return None


def _parse_group_digest_command(text: str):
    t = (text or '').strip()
    m = re.match(r'^\s*拉(.+?)日报\s*$', t)
    if not m:
        return None
    body = m.group(1).strip()
    if body in ('今天', '昨天'):
        return None
    if re.match(r'^(\d{6}|\d{8})$', body) or re.match(r'^[1-9]\d?天$', body):
        return None

    labels = _load_digest_group_labels()
    if not labels:
        return None

    pairs = sorted(labels.items(), key=lambda x: len(x[1]), reverse=True)
    for gid, label in pairs:
        if not body.startswith(label):
            continue
        suffix = body[len(label):].strip()
        spec = _parse_date_spec_fragment(suffix)
        if spec is None:
            return None
        return {'group_id': gid, 'group_label': label, 'date_spec': spec}
    return None


def _parse_indices_proc(s: str) -> list[int]:
    if not (s or '').strip():
        return []
    parts = re.split(r'[,，、\s]+', str(s).strip())
    out = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            out.append(int(p))
    return out


def _parse_desk_ops_command(text: str):
    t = (text or '').strip()
    if re.match(r'^\s*查看进程\s*[!！。.~\s]*$', t):
        return 'proc_list', None
    m = re.match(r'^\s*关进程\s*([0-9,\s、，]+)\s*$', t)
    if m:
        return 'proc_kill', m.group(1).strip()
    # 启动PM / 启动 PM / 启动  pm 等（启动与 PM 之间可有任意空白）
    if re.match(r'^\s*启动\s*pm\s*[!！。.~\s]*$', t, re.IGNORECASE):
        return 'pm_restart', None
    if re.match(r'^\s*(?:检查大门|大门检查)\s*$', t):
        return 'check_gate', None
    if re.match(r'^\s*(?:重启大门|大门重启)\s*$', t):
        return 'restart_gate', None
    group_req = _parse_group_digest_command(t)
    if group_req:
        return 'report_digest_group', group_req
    m = re.match(r'^\s*拉(今天|昨天)日报\s*$', t)
    if m:
        return 'report_digest', ('rel', m.group(1))
    m = re.match(r'^\s*拉(\d{6}|\d{8})日报\s*$', t)
    if m:
        iso = _parse_compact_date_yymmdd(m.group(1))
        if iso:
            return 'report_digest', ('one', iso)
    m = re.match(r'^\s*拉([1-9]\d?)天日报\s*$', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 31:
            return 'report_digest', ('days', n)
    return None, None


def _report_dates_from_spec(spec) -> list[str]:
    kind, payload = spec
    today = datetime.now().date()
    if kind == 'rel':
        if payload == '今天':
            d0 = today
        else:
            d0 = today - timedelta(days=1)
        return [d0.strftime('%Y-%m-%d')]
    if kind == 'one':
        return [payload]
    if kind == 'days':
        n = int(payload)
        out = []
        for i in range(n - 1, -1, -1):
            d = today - timedelta(days=i)
            out.append(d.strftime('%Y-%m-%d'))
        return out
    return []


def _truncate(s: str, n: int = 3500) -> str:
    s = s or ''
    if len(s) <= n:
        return s
    return s[: n - 1] + '…'


def _run_subprocess_capture(
    argv: list, cwd: str, env=None,
) -> tuple[int, str]:
    try:
        r = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=None,
        )
        out = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
        return r.returncode, out
    except OSError as e:
        return 1, str(e)


def _pm_kill_quick_start_windows() -> str:
    """与 quick_start.bat 首段一致：按控制台窗口标题结束 PM 栈相关进程树。"""
    chunks: list[str] = []
    for pat in _PM_TITLE_FILTERS:
        r = subprocess.run(
            ['taskkill', '/F', '/FI', f'WINDOWTITLE eq {pat}', '/T'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        merged = ((r.stdout or '') + (r.stderr or '')).strip()
        if merged:
            skip_sub = (
                '没有运行的任务匹配指定标准',
                '没有此任务的实例',
                'INFO: No tasks',
                'not found',
            )
            if any(s in merged for s in skip_sub):
                continue
            chunks.append(_truncate(merged, 500))
    if not chunks:
        return '（无匹配窗口，或窗口已关闭）'
    return '\n'.join(chunks[:12])


def _pm_port_open(port: int, timeout: float = 2.5) -> bool:
    try:
        s = socket.create_connection(('127.0.0.1', int(port)), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def _pm_http_status_line(url: str, timeout: float = 5.0) -> str:
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 'OK HTTP %s' % resp.status
    except Exception as e:
        return '失败 %s' % (_truncate(str(e), 100))


def _pm_probe_services_markdown() -> tuple:
    """headless 脚本结束后再等 8s，探活常用端口。返回 (markdown表格, 后端是否健康)。"""
    time.sleep(8)
    h8000 = _pm_http_status_line('http://127.0.0.1:8000/api/health')
    ok_core = h8000.startswith('OK HTTP')
    lines = [
        '| 端口 | 说明 | 结果 |',
        '| :-: | --- | --- |',
        '| 8000 | PM 后端 `/api/health` | %s |' % h8000,
        '| 3005 | PM 前端 `http.server` | %s |'
        % ('端口可达' if _pm_port_open(3005) else '端口未监听'),
        '| 8899 | MD Reader | %s |'
        % ('端口可达' if _pm_port_open(8899) else '端口未监听'),
        '| 8300 | Palace Web | %s |'
        % ('端口可达' if _pm_port_open(8300) else '端口未监听'),
    ]
    return '\n'.join(lines), ok_core


def _spawn_restart_detached(webhook_url: str) -> None:
    py = sys.executable
    script = os.path.join(_ROOT, 'desk_ops_restart.py')
    argv = [py, script, '--webhook', webhook_url or '']
    kw = {}
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


def process_desk_ops(msg_id, text, group_cid, config) -> bool:
    # [AgentDgst Task] 开始时间: 2026-03-25 00:00
    # [AgentDgst Task] 任务目标: DIGEST-001 分组拉取与顺序编排
    op, payload = _parse_desk_ops_command(text or '')
    if not op:
        return False
    if _consume_edit_cmd_dedup(group_cid, text):
        return True

    if config.get('desk_ops_enabled') is False:
        return True

    wh = _wish_webhook_for_cid(config, group_cid)

    # [AgentProc Task] 2026-03-25 助理通知群：查看进程 / 关进程 N（仓库根 proc_manager.py）
    if op == 'proc_list':
        _send_webhook(
            '### **开始：查看进程**\n\n'
            '正在采集本机 Python 进程（`proc_manager.py --markdown-list`）…\n\n----',
            config,
            group_cid=group_cid,
        )
        exe = sys.executable
        if not os.path.isfile(_PROC_MGR):
            _send_webhook(
                '### **查看进程失败**\n\n'
                '未找到 `proc_manager.py`：\n\n`%s`\n\n----' % _PROC_MGR,
                config,
                group_cid=group_cid,
            )
            return True
        _penv = os.environ.copy()
        _penv['PYTHONIOENCODING'] = 'utf-8'
        _penv['PYTHONUTF8'] = '1'
        rc, out = _run_subprocess_capture(
            [exe, _PROC_MGR, '--markdown-list', '--state-file', _PROC_STATE],
            _WORKSPACE,
            env=_penv,
        )
        body = (out or '').strip() or '(无输出)'
        if rc != 0:
            body = '进程退出码 **%s**\n\n```\n%s\n```' % (rc, _truncate(body, 3000))
        else:
            body = _truncate(body, 12000)
        _send_webhook_chunks(
            '### **查看进程完成**\n\n' + body + '\n\n----',
            config,
            group_cid=group_cid,
            chunk_size=3200,
        )
        return True

    if op == 'proc_kill':
        indices = _parse_indices_proc(payload or '')
        if not indices:
            _send_webhook(
                '### **关进程**\n\n'
                '未能解析序号。示例：`关进程 2` 或 `关进程 1,3`\n\n----',
                config,
                group_cid=group_cid,
            )
            return True
        if not os.path.isfile(_PROC_MGR):
            _send_webhook(
                '### **关进程失败**\n\n未找到 `proc_manager.py`。\n\n----',
                config,
                group_cid=group_cid,
            )
            return True
        exe = sys.executable
        idx_arg = ','.join(str(i) for i in indices)
        _penv = os.environ.copy()
        _penv['PYTHONIOENCODING'] = 'utf-8'
        _penv['PYTHONUTF8'] = '1'
        rc, out = _run_subprocess_capture(
            [
                exe,
                _PROC_MGR,
                '--kill-indices',
                idx_arg,
                '--state-file',
                _PROC_STATE,
            ],
            _WORKSPACE,
            env=_penv,
        )
        body = (out or '').strip() or '(无输出)'
        tail = '' if rc == 0 else '\n\n（子进程退出码 **%s**）' % rc
        _send_webhook(
            _truncate(body + tail, 3500),
            config,
            group_cid=group_cid,
        )
        return True

    # [AgentPM Task] 2026-03-25 助理群「启动PM」：结束 quick_start 标题窗口 + quick_start_headless
    if op == 'pm_restart':
        _send_webhook(
            '### **开始：启动 PM**\n\n'
            '1. 按 `quick_start.bat` 规则 `taskkill` 窗口标题\n'
            '2. 执行 `pm-system/quick_start_headless.bat` 拉起后端/前端/MD Reader/Palace\n\n----',
            config,
            group_cid=group_cid,
        )
        if not os.path.isfile(_PM_HEADLESS_BAT):
            _send_webhook(
                '### **启动 PM 失败**\n\n'
                '未找到 `quick_start_headless.bat`：\n\n`%s`\n\n----' % _PM_HEADLESS_BAT,
                config,
                group_cid=group_cid,
            )
            return True
        kill_log = _pm_kill_quick_start_windows()
        time.sleep(2)
        rc, bat_out = _run_subprocess_capture(
            ['cmd', '/c', _PM_HEADLESS_BAT],
            _PM_SYSTEM_DIR,
        )
        bat_body = _truncate((bat_out or '').strip() or '(脚本无标准输出)', 2400)
        probe, ok_core = _pm_probe_services_markdown()
        summary = '**整体**：PM 后端探活 **正常**' if ok_core else '**整体**：PM 后端探活 **异常或未就绪**（可再等几秒或看 PM_System_Backend 窗口日志）'
        tail_rc = '' if rc == 0 else '\n\n`quick_start_headless.bat` 退出码 **%s**' % rc
        _send_webhook(
            _truncate(
                '### **启动 PM 完成**\n\n'
                '%s\n\n'
                '**taskkill 摘要**\n\n```\n%s\n```\n\n'
                '**headless 脚本输出**\n\n```\n%s\n```\n'
                '%s\n\n'
                '**约 8s 后探活**\n\n%s\n\n'
                '前端：<http://127.0.0.1:3005>\n\n----'
                % (summary, kill_log, bat_body, tail_rc, probe),
                7000,
            ),
            config,
            group_cid=group_cid,
        )
        return True

    if op == 'check_gate':
        _send_webhook(
            '### **开始执行：检查大门**\n\n'
            '`py daemon_health_notify.py`（含不健康时自动重启）\n\n----',
            config,
            group_cid=group_cid,
        )
        exe = sys.executable
        script = os.path.join(_ROOT, 'daemon_health_notify.py')
        rc, out = _run_subprocess_capture(
            [exe, script, '--no-webhook'],
            _ROOT,
        )
        body = _truncate(out.strip() or '(no output)', 3200)
        tail = '自检流程结束。' if rc == 0 else f'进程退出码 {rc}。'
        _send_webhook(
            f'### **执行完成：检查大门**\n\n{tail}\n\n```\n{body}\n```\n\n----',
            config,
            group_cid=group_cid,
        )
        return True

    if op == 'restart_gate':
        _send_webhook(
            '### **开始执行：重启大门**\n\n'
            '已启动独立进程：`desk_ops_restart.py`（shutdown -> `py daemon.py`）。\n'
            '本进程即将退出，**完成**消息由子进程在 healthy 后推送。\n\n----',
            config,
            group_cid=group_cid,
        )
        _spawn_restart_detached(wh or '')
        return True

    if op == 'report_digest':
        dates = _report_dates_from_spec(payload)
        if not dates:
            _send_webhook('### **拉日报**\n\n未能解析日期。\n\n----', config, group_cid=group_cid)
            return True
        ds = '、'.join(dates)
        _send_webhook(
            f'### **开始执行：拉日报**\n\n'
            f'共 **{len(dates)}** 个日期：{ds}\n'
            f'`py report_digest.py --date … --full-content --notify-default`\n'
            f'（过程通知走 webhook_config.json 的 **default** 机器人）\n\n----',
            config,
            group_cid=group_cid,
        )
        exe = sys.executable
        script = os.path.join(_ROOT, 'report_digest.py')
        chunks: list[str] = []
        worst_rc = 0
        for d in dates:
            rc, out = _run_subprocess_capture(
                [exe, script, '--date', d, '--full-content', '--notify-default'],
                _ROOT,
            )
            if rc != 0:
                worst_rc = rc
            chunks.append(f'=== {d} exit={rc} ===\n{_truncate(out.strip(), 2800)}')
        merged = '\n\n'.join(chunks)
        merged = _truncate(merged, 7000)
        tail = '全部日期已跑完。' if worst_rc == 0 else f'存在非零退出码（{worst_rc}），请查日志。'
        _send_webhook(
            f'### **执行完成：拉日报**\n\n{tail}\n\n```\n{merged}\n```\n\n----',
            config,
            group_cid=group_cid,
        )
        return True

    if op == 'report_digest_group':
        group_id = payload.get('group_id', '')
        group_label = payload.get('group_label', group_id)
        dates = _report_dates_from_spec(payload.get('date_spec', ('rel', '今天')))
        if not dates or not group_id:
            _send_webhook('### **拉分组日报**\n\n未能解析参数。\n\n----', config, group_cid=group_cid)
            return True
        ds = '、'.join(dates)
        _send_webhook(
            f'### **开始执行：拉{group_label}日报**\n\n'
            f'分组 **{group_label}**（`{group_id}`）\n'
            f'共 **{len(dates)}** 个日期：{ds}\n'
            f'`py report_digest.py --date … --full-content --notify-default --digest-group {group_id}`\n'
            f'（过程通知走 webhook_config.json 的 **default** 机器人）\n\n----',
            config,
            group_cid=group_cid,
        )
        exe = sys.executable
        script = os.path.join(_ROOT, 'report_digest.py')
        chunks: list[str] = []
        worst_rc = 0
        for d in dates:
            rc, out = _run_subprocess_capture(
                [exe, script, '--date', d, '--full-content', '--notify-default', '--digest-group', group_id],
                _ROOT,
            )
            if rc != 0:
                worst_rc = rc
            chunks.append(f'=== {d} group={group_id} exit={rc} ===\n{_truncate(out.strip(), 2800)}')
        merged = '\n\n'.join(chunks)
        merged = _truncate(merged, 7000)
        tail = '全部日期已跑完。' if worst_rc == 0 else f'存在非零退出码（{worst_rc}），请查日志。'
        _send_webhook(
            f'### **执行完成：拉{group_label}日报**\n\n{tail}\n\n```\n{merged}\n```\n\n----',
            config,
            group_cid=group_cid,
        )
        return True

    return False
