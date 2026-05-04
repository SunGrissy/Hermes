import json
import subprocess
from pathlib import Path

path = Path(r"D:/MyAgents/会议材料/驯化野生硅基伙伴-修改整合稿.md")
markdown = path.read_text(encoding="utf-8")
cmd = [
    "dws", "doc", "create",
    "--name", "《驯化野生硅基伙伴》修改整合稿",
    "--markdown", markdown,
    "--format", "json",
    "--yes",
]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
print(proc.stdout)
if proc.stderr:
    print(proc.stderr)
raise SystemExit(proc.returncode)
