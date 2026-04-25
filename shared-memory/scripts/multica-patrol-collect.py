import json
import subprocess
import sys
from datetime import datetime

MULTICA_PATH = "C:/Users/TU/AppData/Local/Programs/multica/multica"

def run_multica(status=None):
    cmd = [MULTICA_PATH, "issue", "list", "--output", "json", "--limit", "200"]
    if status:
        cmd.extend(["--status", status])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {"ok": True, "data": data}
        else:
            return {"ok": False, "error": f"exit={result.returncode} stderr={result.stderr[:500]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def fmt_issues(issues, max_show=10):
    lines = []
    for i, issue in enumerate(issues[:max_show]):
        assignee = "未指派" if not issue.get("assignee_id") else f"已指派({issue.get('assignee_type', '?')})"
        lines.append(f"  - {issue['identifier']}: {issue['title']} [{assignee}]")
    if len(issues) > max_show:
        lines.append(f"  ... 还有 {len(issues) - max_show} 个")
    return "\n".join(lines) if lines else "  （无）"

def main():
    now = datetime.now().strftime("%H:%M")

    todo_raw = run_multica("todo")
    ip_raw = run_multica("in_progress")
    all_raw = run_multica()

    if not todo_raw["ok"]:
        print(f"【Multica 巡检失败】{now}\n获取 todo 列表失败: {todo_raw.get('error', 'unknown')}")
        return
    if not ip_raw["ok"]:
        print(f"【Multica 巡检失败】{now}\n获取 in_progress 列表失败: {ip_raw.get('error', 'unknown')}")
        return

    todo_issues = todo_raw["data"].get("issues", [])
    ip_issues = ip_raw["data"].get("issues", [])
    all_issues = all_raw["data"].get("issues", []) if all_raw["ok"] else []

    todo_unassigned = [i for i in todo_issues if not i.get("assignee_id")]

    report = f"""【Multica 巡检】{now}

待认领（todo）：{len(todo_issues)} 个
未指派：{len(todo_unassigned)} 个
{fmt_issues(todo_unassigned)}

进行中（in_progress）：{len(ip_issues)} 个
{fmt_issues(ip_issues)}

总任务数：{len(all_issues)} 个
"""
    print(report)

if __name__ == "__main__":
    main()
