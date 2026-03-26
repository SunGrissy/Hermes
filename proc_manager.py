"""Python 进程管理工具 -- 查看运行中的服务并支持关闭指定进程"""

import argparse
import json
import subprocess
import re
import sys
import os
import time

# --- 已知服务映射 ---

PORT_SERVICE = {
    "3005":  "PmSystem 前端",
    "8000":  "TaskReminderApp",
    "8010":  "PerformEval 后端(旧?)",
    "8112":  "PerformEval 后端",
    "8300":  "Palace Web",
    "8501":  "CCI-ScoreSystem (Streamlit)",
    "8899":  "未知 uvicorn",
    "19200": "DingTalk Daemon",
}

CMD_PATTERNS = [
    ("daemon.py",       "DingTalk Daemon"),
    ("palace_web",      "Palace Web"),
    ("http.server",     "PmSystem 静态服务"),
    ("server:app",      "uvicorn server"),
    ("main:app",        "uvicorn main"),
    ("streamlit",       "Streamlit"),
    ("multiprocessing", "(worker 子进程)"),
]

SESSION_SCHEMA_VERSION = 1
SESSION_MAX_AGE_SEC = int(os.environ.get("PROC_MANAGER_SESSION_MAX_AGE", "7200"))


def get_listening_ports():
    """netstat -> {pid: [(proto, port), ...]}"""
    out = subprocess.check_output(
        ["netstat", "-ano"], text=True, errors="replace"
    )
    pid_ports = {}
    for line in out.splitlines():
        m = re.match(
            r"\s+(TCP|UDP)\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)", line
        )
        if m:
            proto, port, pid = m.group(1), m.group(2), m.group(3)
            pid_ports.setdefault(pid, []).append((proto, port))
    return pid_ports


def get_python_processes():
    """WMI 查询所有 python/py 进程, 返回列表[{pid, name, cmdline, created}]"""
    ps_cmd = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { $_.Name -match 'python|py\\.exe' } "
        "| Select-Object ProcessId, Name, CommandLine, CreationDate "
        "| ForEach-Object { "
        "  $d = if($_.CreationDate){$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss')}else{''}; "
        "  \"$($_.ProcessId)|$($_.Name)|$d|$($_.CommandLine)\" }"
    )
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        text=True, errors="replace",
    )
    procs = []
    for line in out.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        pid, name, created, cmdline = parts
        if not cmdline.strip():
            continue
        procs.append({
            "pid": pid.strip(),
            "name": name.strip(),
            "created": created.strip(),
            "cmdline": cmdline.strip(),
        })
    return procs


def identify_service(cmdline, ports):
    """根据端口和命令行推断服务名称"""
    seen = set()
    labels = []
    for proto, port in ports:
        if port in seen:
            continue
        seen.add(port)
        svc = PORT_SERVICE.get(port)
        if svc:
            labels.append(f"{svc} :{port}")
        else:
            labels.append(f":{port}")
    if labels:
        return " / ".join(labels)

    for pattern, svc_name in CMD_PATTERNS:
        if pattern in cmdline:
            return svc_name
    return "-"


def _normalize_args(cmdline):
    """去掉可执行路径, 只保留参数部分用于去重"""
    s = re.sub(r'^"[^"]*"\s*', '', cmdline).strip()
    s = re.sub(r'^\S*?(?:python\d*|py)(?:\.exe)?\s+', '', s).strip()
    return " ".join(s.split())


def collect_display_rows():
    """返回排序后的展示行列表（每项含 pid / port_str / service / created / cmdline）。"""
    procs = get_python_processes()
    pid_ports = get_listening_ports()

    port_proc_args = set()
    for p in procs:
        if pid_ports.get(p["pid"]):
            port_proc_args.add(_normalize_args(p["cmdline"]))

    seen_args = set()
    display = []
    for p in procs:
        if "multiprocessing" in p["cmdline"]:
            continue

        ports = pid_ports.get(p["pid"], [])
        args = _normalize_args(p["cmdline"])

        if not ports and args in port_proc_args:
            continue
        if not ports:
            if args in seen_args:
                continue
            seen_args.add(args)

        service = identify_service(p["cmdline"], ports)
        unique_ports = list(dict.fromkeys(pt for _, pt in ports))
        port_str = ", ".join(f":{pt}" for pt in unique_ports) if unique_ports else "-"
        display.append({
            **p,
            "service": service,
            "port_str": port_str,
        })

    display.sort(key=lambda x: (x["port_str"] == "-", x["port_str"]))
    return display


def _md_cell(s: str) -> str:
    t = (s or "").replace("|", "/").replace("\n", " ").strip()
    if len(t) > 42:
        t = t[:39] + "..."
    return t


def format_markdown_table(display) -> str:
    """钉钉 Markdown 表格（可读性）。"""
    if not display:
        return "### **Python 进程**\n\n当前无已识别的 Python 服务进程。\n"

    lines = [
        "### **Python 进程一览**\n",
        "共 **%d** 条（含本机 py/python 去重后）。\n" % len(display),
        "\n",
        "| # | PID | 端口 | 服务 | 启动 |\n",
        "|:-:|:-:|:---:|---|:-:|\n",
    ]
    for idx, d in enumerate(display, 1):
        cmd_short = d["cmdline"]
        if len(cmd_short) > 55:
            cmd_short = cmd_short[:52] + "..."
        t = d["created"][5:] if d.get("created") else "-"
        lines.append(
            "| %s | %s | %s | %s | %s |\n"
            % (
                idx,
                _md_cell(d["pid"]),
                _md_cell(d["port_str"]),
                _md_cell(d["service"]),
                _md_cell(t),
            )
        )
    lines.append("\n**说明**：`命令行` 列已省略，需要时在终端执行 `py proc_manager.py` 看完整。\n")
    lines.append("\n**关进程**：回复 `关进程 序号` 或 `关进程 1,2`（基于上表序号，**2 小时内**有效）。\n")
    return "".join(lines)


def write_session_file(display, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    rows = []
    for idx, d in enumerate(display, 1):
        cmd_short = d["cmdline"]
        if len(cmd_short) > 80:
            cmd_short = cmd_short[:77] + "..."
        rows.append({
            "index": idx,
            "pid": str(d["pid"]),
            "port_str": d["port_str"],
            "service": d["service"],
            "cmd_short": cmd_short,
        })
    payload = {
        "schema": SESSION_SCHEMA_VERSION,
        "generated_at": int(time.time()),
        "rows": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run_kill_from_session(state_path: str, indices: list[int]) -> tuple[int, str]:
    """按上次快照序号杀进程。返回 (exit_code, markdown正文)。"""
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        return 1, "### **关进程失败**\n\n找不到会话文件，请先发送 **查看进程**。\n\n`%s`\n" % e

    gen = int(data.get("generated_at") or 0)
    if gen <= 0 or (time.time() - gen) > SESSION_MAX_AGE_SEC:
        return 1, (
            "### **关进程已拒绝**\n\n"
            "上次 **查看进程** 已超过 **%d** 分钟，为避免误杀请先重新 **查看进程**。\n"
            % (SESSION_MAX_AGE_SEC // 60)
        )

    rows = data.get("rows") or []
    by_idx = {int(r["index"]): r for r in rows if r.get("index") is not None}

    lines = ["### **关进程结果**\n\n"]
    bad = []
    ok = []
    for i in indices:
        if i not in by_idx:
            bad.append(str(i))
            continue
        r = by_idx[i]
        pid = str(r.get("pid") or "").strip()
        if not pid.isdigit():
            bad.append(str(i))
            continue
        try:
            cp = subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            svc = r.get("service") or "-"
            if cp.returncode == 0:
                ok.append("- **#%s** PID `%s` %s → 已终止\n" % (i, pid, _md_cell(svc)))
            else:
                err = (cp.stderr or cp.stdout or "").strip() or "taskkill 非零退出"
                ok.append(
                    "- **#%s** PID `%s` %s → **失败** `%s`\n"
                    % (i, pid, _md_cell(svc), _md_cell(err)[:120])
                )
        except OSError as e:
            ok.append("- **#%s** PID `%s` → **异常** `%s`\n" % (i, pid, e))

    if bad:
        lines.append("无效或过期序号：**%s**（请对照最近一次列表）\n\n" % "、".join(bad))
    if ok:
        lines.extend(ok)
    if not ok and not bad:
        lines.append("未解析到有效序号。\n")
    lines.append("\n如需继续关闭，请再发 **查看进程** 刷新列表。\n")
    rc = 0
    if bad or not ok:
        rc = 1
    for x in ok:
        if "失败" in x or "异常" in x:
            rc = 1
            break
    return rc, "".join(lines)


def print_table(rows):
    """简单对齐输出（交互终端）"""
    if not rows:
        print("  (无运行中的 Python 进程)")
        return
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    for i, row in enumerate(rows):
        line = "  ".join(str(cell).ljust(w) for cell, w in zip(row, widths))
        print(line)
        if i == 0:
            print("-" * sum(widths) + "-" * (len(widths) * 2))


def _console_utf8():
    if sys.platform == "win32":
        if sys.stdin.isatty():
            os.system("chcp 65001 >nul 2>&1")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main_interactive():
    _console_utf8()
    print("\n== Python 进程管理工具 ==\n")

    display = collect_display_rows()
    if not display:
        print("  (无运行中的 Python 进程)")
        return

    header = ["#", "PID", "端口", "服务/功能", "启动时间", "命令行(摘要)"]
    rows = [header]
    for idx, d in enumerate(display, 1):
        cmd_short = d["cmdline"]
        if len(cmd_short) > 60:
            cmd_short = cmd_short[:57] + "..."
        rows.append([
            str(idx),
            d["pid"],
            d["port_str"],
            d["service"],
            d["created"][5:] if d["created"] else "-",
            cmd_short,
        ])

    print_table(rows)
    print(f"\n  共 {len(display)} 个进程\n")

    while True:
        ans = input("输入序号关闭进程 (多个用逗号分隔, 直接回车退出): ").strip()
        if not ans:
            break
        try:
            indices = [int(x.strip()) for x in ans.split(",")]
        except ValueError:
            print("  [!] 请输入数字序号")
            continue

        targets = []
        for i in indices:
            if 1 <= i <= len(display):
                targets.append(display[i - 1])
            else:
                print(f"  [!] 序号 {i} 超出范围, 已跳过")

        if not targets:
            continue

        print("\n  即将关闭:")
        for t in targets:
            print(f"    PID {t['pid']}  {t['service']}  {t['port_str']}")

        confirm = input("  确认? (y/N): ").strip().lower()
        if confirm != "y":
            print("  已取消")
            continue

        for t in targets:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", t["pid"]],
                    capture_output=True, text=True,
                )
                print(f"  [OK] PID {t['pid']} ({t['service']}) 已终止")
            except Exception as e:
                print(f"  [FAIL] PID {t['pid']}: {e}")

        print()


def _parse_indices(s: str) -> list[int]:
    if not s or not str(s).strip():
        return []
    parts = re.split(r"[,，、\s]+", str(s).strip())
    out = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            out.append(int(p))
    return out


def main():
    p = argparse.ArgumentParser(description="Python 进程管理（本机 Windows）")
    p.add_argument(
        "--markdown-list",
        action="store_true",
        help="输出钉钉可读 Markdown 到 stdout，并写入 --state-file",
    )
    p.add_argument(
        "--state-file",
        metavar="PATH",
        help="会话快照路径（与 --markdown-list / --kill-indices 配合）",
    )
    p.add_argument(
        "--kill-indices",
        metavar="LIST",
        help="逗号分隔序号，配合 --state-file 关闭对应 PID",
    )
    args = p.parse_args()

    if args.markdown_list:
        if not args.state_file:
            print("缺少 --state-file", file=sys.stderr)
            sys.exit(2)
        display = collect_display_rows()
        write_session_file(display, args.state_file)
        sys.stdout.write(format_markdown_table(display))
        return

    if args.kill_indices:
        if not args.state_file:
            print("缺少 --state-file", file=sys.stderr)
            sys.exit(2)
        indices = _parse_indices(args.kill_indices)
        if not indices:
            print("未解析到序号", file=sys.stderr)
            sys.exit(2)
        rc, md = run_kill_from_session(args.state_file, indices)
        sys.stdout.write(md)
        sys.exit(rc)

    main_interactive()


if __name__ == "__main__":
    main()
