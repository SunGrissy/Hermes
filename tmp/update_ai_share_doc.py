import subprocess
from pathlib import Path

DWS = r"C:\Users\TU\.local\bin\dws.exe"
NODE = "lyQod3RxJK3Pgee4T4aoRg69Jkb4Mw9r"
MD = Path(r"D:\MyAgents\tmp\taming-wild-silicon-share-outline-rewrite.md")
content = MD.read_text(encoding="utf-8")

cmd = [DWS, "doc", "update", "--node", NODE, "--markdown", content, "--mode", "overwrite"]
res = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("exit", res.returncode)
if res.stdout:
    print("STDOUT:")
    print(res.stdout)
if res.stderr:
    print("STDERR:")
    print(res.stderr)
raise SystemExit(res.returncode)
