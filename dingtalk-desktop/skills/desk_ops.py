# -*- coding: utf-8 -*-
"""
桌面运维快捷指令（助理群 / 白名单群）：检查大门、重启大门、拉日报。
与 memo_tracker 共用 webhook；长任务不占 memo 串行锁。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

from skills.memo_tracker import (
    _consume_edit_cmd_dedup,
    _send_webhook,
    _wish_webhook_for_cid,
)

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, '..'))


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


def _parse_desk_ops_command(text: str):
    t = (text or '').strip()
    if re.match(r'^\s*(?:检查大门|大门检查)\s*$', t):
        return 'check_gate', None
    if re.match(r'^\s*(?:重启大门|大门重启)\s*$', t):
        return 'restart_gate', None
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


def _run_subprocess_capture(argv: list, cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(
            argv,
            cwd=cwd,
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
    op, payload = _parse_desk_ops_command(text or '')
    if not op:
        return False
    if _consume_edit_cmd_dedup(group_cid, text):
        return True

    if config.get('desk_ops_enabled') is False:
        return True

    wh = _wish_webhook_for_cid(config, group_cid)

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

    return False
