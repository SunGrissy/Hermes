# -*- coding: utf-8 -*-
"""
SVN 文件变更查询工具（self-contained）

查询指定代码文件在某个时间段内经历了多少次提交变更。
适用于检查文档参考的代码文件是否已发生变化。

用法1 - 命令行参数:
  python svn_file_changes.py -f lua/game_mode/master_data.lua --since 2026-01-13
  python svn_file_changes.py -f file1.lua -f file2.lua --since 2026-01-13 --until 2026-02-24 -o result.txt

用法2 - JSON配置文件（推荐，支持中文路径）:
  python svn_file_changes.py --config _changes_config.json

  _changes_config.json 格式:
  {
    "files": [
      "lua/game_mode/master_data.lua",
      "lua/framework/components/game_module/module_impl/master_module.lua"
    ],
    "since": "2026-01-13",
    "until": "",
    "path": ".",
    "output": "_file_changes.txt"
  }
"""

import subprocess
import argparse
import re
import os
import sys
import io
import json
from datetime import datetime

# ── stdout UTF-8 修复 ────────────────────────────────────────
# Windows 终端默认 GBK 编码，print 含中文或特殊字符时会抛 UnicodeEncodeError。
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )

# ── SVN 工具函数（内联自 lib.svn_utils）──────────────────────


def decode_svn_output(raw_bytes):
    """智能解码 SVN 命令的原始字节输出。

    按 UTF-8 -> GBK -> GB18030 -> Latin-1 顺序尝试。
    验证策略：如果解码文本包含 "---"（SVN log 分隔线 / diff 标记），
    或者输出长度很短（< 100 字节），则认为解码成功。
    """
    for encoding in ["utf-8", "gbk", "gb18030", "latin-1"]:
        try:
            text = raw_bytes.decode(encoding)
            if "---" in text or len(raw_bytes) < 100:
                return text
        except (UnicodeDecodeError, AttributeError):
            continue
    return raw_bytes.decode("latin-1")


def parse_svn_log_blocks(text):
    """解析 SVN log 文本模式输出为结构化条目列表。

    SVN log 文本模式以 72 个 "-" 分隔每条提交记录。

    Returns:
        list[dict]: 每条含 rev, author, date, msg
    """
    entries = []
    blocks = text.split("-" * 72)

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 2:
            continue

        header = lines[0].strip()
        match = re.match(r"(r\d+)\s*\|\s*(\S+)\s*\|\s*(.+?)\s*\|", header)
        if not match:
            continue

        msg_lines = [ln.strip() for ln in lines[1:] if ln.strip()]
        entries.append({
            "rev": match.group(1),
            "author": match.group(2),
            "date": match.group(3).strip(),
            "msg": " ".join(msg_lines),
        })

    return entries


# ── 核心逻辑 ─────────────────────────────────────────────────


def query_file_changes(svn_path, file_path, since, until_date=None):
    if until_date:
        rev_range = "{%s}:{%s}" % (since, until_date)
    else:
        rev_range = "{%s}:HEAD" % since

    full_path = os.path.join(svn_path, file_path) if svn_path != "." else file_path
    cmd = ["svn", "log", "-r", rev_range, full_path]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        err = decode_svn_output(result.stderr)
        return [], err.strip()

    text = decode_svn_output(result.stdout)
    entries = parse_svn_log_blocks(text)
    entries.sort(key=lambda e: int(e["rev"][1:]))
    return entries, None


def check_local_modification(svn_path, file_path):
    full_path = os.path.join(svn_path, file_path) if svn_path != "." else file_path

    result = {"has_local_mod": False, "file_mtime": "", "svn_last_commit": "", "svn_status": ""}

    if not os.path.exists(full_path):
        result["svn_status"] = "file not found"
        return result

    file_mtime = datetime.fromtimestamp(os.path.getmtime(full_path))
    result["file_mtime"] = file_mtime.strftime("%Y-%m-%d %H:%M:%S")

    cmd = ["svn", "info", full_path]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        result["svn_status"] = "not under version control"
        return result

    info_text = decode_svn_output(proc.stdout)
    date_match = re.search(r"Last Changed Date:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", info_text)
    if date_match:
        svn_date_str = date_match.group(1)
        result["svn_last_commit"] = svn_date_str
        svn_date = datetime.strptime(svn_date_str, "%Y-%m-%d %H:%M:%S")
        if abs((file_mtime - svn_date).total_seconds()) > 2:
            result["has_local_mod"] = True

    cmd_st = ["svn", "status", full_path]
    proc_st = subprocess.run(cmd_st, capture_output=True)
    st_text = decode_svn_output(proc_st.stdout).strip()
    if st_text:
        result["svn_status"] = st_text.split("\n")[0][:1]
        result["has_local_mod"] = True
    else:
        result["svn_status"] = "clean" if not result["has_local_mod"] else "mtime differs"

    return result


def format_report(results, since, until_date):
    lines = []
    period_end = until_date or "HEAD"
    lines.append("=== SVN File Changes Report ===")
    lines.append("Period: %s ~ %s" % (since, period_end))
    lines.append("")

    total_commits = 0
    changed_files = []
    unchanged_files = []
    error_files = []
    local_mod_files = []

    for file_path, entries, error, local_mod in results:
        if error:
            lines.append("[%s] ERROR: %s" % (file_path, error))
            error_files.append(file_path)
            continue

        count = len(entries)
        total_commits += count

        local_tag = ""
        if local_mod and local_mod.get("has_local_mod"):
            local_tag = " [LOCAL MODIFIED: %s]" % local_mod.get("svn_status", "")
            local_mod_files.append(file_path)

        if count == 0:
            lines.append("[%s] no svn changes%s" % (file_path, local_tag))
            if not local_tag:
                unchanged_files.append(file_path)
        else:
            lines.append("[%s] %d commit(s)%s" % (file_path, count, local_tag))
            changed_files.append((file_path, count))
            for entry in entries:
                date_short = entry["date"]
                date_match = re.match(r"\d{4}-(\d{2}-\d{2}\s+\d{2}:\d{2})", date_short)
                if date_match:
                    date_short = date_match.group(1)
                lines.append("  %s | %s | %s | %s" % (
                    entry["rev"], entry["author"], date_short, entry["msg"]))
        lines.append("")

    lines.append("--- Summary ---")
    lines.append("Files checked: %d" % len(results))
    if changed_files:
        desc = ", ".join("%s(%d)" % (f, c) for f, c in changed_files)
        lines.append("SVN changed: %s" % desc)
    if local_mod_files:
        lines.append("Local modified: %s" % ", ".join(local_mod_files))
    if unchanged_files:
        lines.append("Unchanged: %s" % ", ".join(unchanged_files))
    if error_files:
        lines.append("Errors: %s" % ", ".join(error_files))
    lines.append("Total svn commits: %d" % total_commits)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="SVN 文件变更查询工具")
    parser.add_argument("-f", "--file", action="append", dest="files",
                        help="要查询的文件路径（可多次指定）")
    parser.add_argument("--since", help="起始日期（如 2026-01-13）")
    parser.add_argument("--until", dest="until_date", default=None,
                        help="截止日期（默认 HEAD）")
    parser.add_argument("-p", "--path", default=".",
                        help="SVN 工作目录路径（默认当前目录）")
    parser.add_argument("-o", "--output",
                        help="输出到文件（UTF-8），不指定则输出到终端")
    parser.add_argument("-c", "--config",
                        help="从 JSON 配置文件读取参数")

    args = parser.parse_args()

    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f)
        files = config.get("files", [])
        since = config.get("since")
        until_date = config.get("until") or None
        svn_path = config.get("path", ".")
        output_file = config.get("output")
    else:
        if not args.files or not args.since:
            parser.error("必须指定 --file 和 --since，或使用 --config")
        files = args.files
        since = args.since
        until_date = args.until_date
        svn_path = args.path
        output_file = args.output

    results = []
    for file_path in files:
        entries, error = query_file_changes(svn_path, file_path, since, until_date)
        local_mod = check_local_modification(svn_path, file_path)
        results.append((file_path, entries, error, local_mod))

    output_text = format_report(results, since, until_date)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output_text)
        changed = sum(1 for _, entries, err, _ in results if not err and len(entries) > 0)
        total = sum(len(entries) for _, entries, err, _ in results if not err)
        local = sum(1 for _, _, _, lm in results if lm and lm.get("has_local_mod"))
        print("Result: %d/%d svn changed, %d local modified, %d total commits, saved to %s" % (
            changed, len(results), local, total, output_file))
    else:
        print(output_text)


if __name__ == "__main__":
    main()
