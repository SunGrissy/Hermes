# -*- coding: utf-8 -*-
"""
杀掉本机 dingtalk-desktop 旧 daemon（大门）进程。

1) POST http://127.0.0.1:19200/shutdown（与 desk_ops「重启大门」第一步一致）
2) Windows 下再按命令行匹配，Force 结束仍占端口的 python/py（仅含 dingtalk-desktop 且 daemon.py）

用法（在 dingtalk-desktop 目录）:
  py kill_old_daemon.py

环境变量 DINGTALK_DAEMON_URL 可覆盖默认 http://127.0.0.1:19200
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    from daemon_health_notify import _DAEMON_URL, _post_shutdown

    print("[kill_old_daemon] POST /shutdown ->", _DAEMON_URL, flush=True)
    _post_shutdown(_DAEMON_URL)
    time.sleep(2)

    if sys.platform != "win32":
        print("[kill_old_daemon] non-Windows: skip process scan", flush=True)
        return 0

    # 只杀「路径/命令行里带 dingtalk-desktop」且「daemon.py」的 py/python，避免误伤其他 daemon.py
    ps = r"""
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  ($_.Name -eq 'python.exe' -or $_.Name -eq 'py.exe') -and
  $_.CommandLine -and
  ($_.CommandLine -like '*dingtalk-desktop*daemon.py*' -or
   $_.CommandLine -like '*dingtalk-desktop\\daemon.py*' -or
   $_.CommandLine -like '*dingtalk-desktop/daemon.py*')
}
foreach ($p in $procs) {
  $line = $p.CommandLine
  if ($line.Length -gt 140) { $line = $line.Substring(0, 140) + '...' }
  Write-Output ('STOP pid=' + $p.ProcessId + ' :: ' + $line)
  Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if (-not $procs) { Write-Output 'NONE' }
"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "").strip()
    if out == "NONE":
        print("[kill_old_daemon] no matching python/py process", flush=True)
    else:
        print(out, flush=True)
    err = (r.stderr or "").strip()
    if err:
        print("[kill_old_daemon] stderr:", err, flush=True)

    # 命令行常不带目录（仅 py.exe daemon.py），再按本服务端口清理监听进程
    port = 19200
    ps2 = rf"""
$conns = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue
$procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $procIds) {{
  Write-Output ('STOP_LISTEN pid=' + $procId + ' port={port}')
  Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}}
if (-not $procIds) {{ Write-Output 'NO_LISTENER' }}
"""
    r2 = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out2 = (r2.stdout or "").strip()
    if out2 and out2 != "NO_LISTENER":
        print(out2, flush=True)
    elif out2 == "NO_LISTENER":
        print(f"[kill_old_daemon] no listener on :{port}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
