import subprocess
from pathlib import Path

node = "YMyQA2dXW7972ggAI5712QkLJzlwrZgb"
md_path = Path(r"D:/MyAgents/tmp/ai-share-production-relations-integration.remote-latest.md")
markdown = md_path.read_text(encoding="utf-8")

cmd = [
    "dws", "doc", "update",
    "--node", node,
    "--mode", "overwrite",
    "--markdown", markdown,
    "--format", "json",
    "--yes",
]
res = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("RETURN_CODE", res.returncode)
print("STDOUT_START")
print(res.stdout)
print("STDOUT_END")
print("STDERR_START")
print(res.stderr)
print("STDERR_END")
raise SystemExit(res.returncode)
