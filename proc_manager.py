"""Python 进程管理工具 -- 查看运行中的服务并支持关闭指定进程"""

import subprocess
import re
import sys
import os

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")

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


def print_table(rows):
    """简单对齐输出"""
    if not rows:
        print("  (无运行中的 Python 进程)")
        return
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    for i, row in enumerate(rows):
        line = "  ".join(str(cell).ljust(w) for cell, w in zip(row, widths))
        print(line)
        if i == 0:
            print("-" * sum(widths) + "-" * (len(widths) * 2))


def main():
    print("\n== Python 进程管理工具 ==\n")

    procs = get_python_processes()
    pid_ports = get_listening_ports()

    def _normalize_args(cmdline):
        """去掉可执行路径, 只保留参数部分用于去重"""
        s = re.sub(r'^"[^"]*"\s*', '', cmdline).strip()
        s = re.sub(r'^\S*?(?:python\d*|py)(?:\.exe)?\s+', '', s).strip()
        return " ".join(s.split())

    # 第一轮: 收集所有有端口进程的参数签名
    port_proc_args = set()
    for p in procs:
        if pid_ports.get(p["pid"]):
            port_proc_args.add(_normalize_args(p["cmdline"]))

    # 第二轮: 构建展示列表
    seen_args = set()
    display = []
    for p in procs:
        if "multiprocessing" in p["cmdline"]:
            continue

        ports = pid_ports.get(p["pid"], [])
        args = _normalize_args(p["cmdline"])

        # 无端口的进程: 如果参数签名已被有端口的进程覆盖 -> 跳过(是启动器/父进程)
        if not ports and args in port_proc_args:
            continue
        # 无端口的进程之间也去重
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

    if not display:
        print("  (无运行中的 Python 进程)")
        return

    # 按端口排序, 有端口的排前面
    display.sort(key=lambda x: (x["port_str"] == "-", x["port_str"]))

    header = ["#", "PID", "端口", "服务/功能", "启动时间", "命令行(摘要)"]
    rows = [header]
    for idx, d in enumerate(display, 1):
        cmd_short = d["cmdline"]
        # 截断过长的命令行
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

    # 交互: 关闭进程
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


if __name__ == "__main__":
    main()
