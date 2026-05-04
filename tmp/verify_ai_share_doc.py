import subprocess
import json

DWS = r"C:\Users\TU\.local\bin\dws.exe"
NODE = "lyQod3RxJK3Pgee4T4aoRg69Jkb4Mw9r"
cmd = [DWS, "doc", "read", "--node", NODE, "--format", "json", "--yes"]
res = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("exit", res.returncode)
if res.stderr:
    print("STDERR:")
    print(res.stderr)
if res.returncode != 0:
    print(res.stdout)
    raise SystemExit(res.returncode)
data = json.loads(res.stdout)
md = data.get("markdown") or ""
checks = {
    "success": data.get("success"),
    "title": data.get("title"),
    "docUrl": data.get("docUrl"),
    "has_jika": "集卡素材" in md,
    "has_llm_brain": "LLM 是大脑" in md,
    "has_basic_section": "基础科普：先认清硅基同事的身体构造" in md,
    "has_ordered_nine": "## 九、收尾" in md,
    "length": len(md),
}
print(json.dumps(checks, ensure_ascii=False, indent=2))
