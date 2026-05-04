import json
import subprocess
from pathlib import Path

node = "YMyQA2dXW7972ggAI5712QkLJzlwrZgb"
read_cmd = ["dws", "doc", "read", "--node", node, "--format", "json", "--yes"]
r = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("READ", r.returncode)
if r.returncode != 0:
    print(r.stdout); print(r.stderr); raise SystemExit(r.returncode)
md = json.loads(r.stdout)["markdown"]
Path(r"D:/MyAgents/tmp/ai-share-before-promote-cases.md").write_text(md, encoding="utf-8")

# 1) Replace "most recommended page" block to include the two cases explicitly.
start = md.index("### 4\\. 最推荐新增的一页")
end = md.index("\n\n---\n\n## 二、填内容", start)
new_top_block = """### 4\\. 最推荐新增的 3 页

#### 第 1 页：场景错配的正解
> 不是拿着锤子找钉子，而是一直有钉子  

这页必须放在开篇迷思里，作为“场景错配”的主案例页。核心不是讲 AI 有多强，而是讲：**真正有效的 AI 应用来自长期真实问题，不来自追逐新工具。**

两个例子直接放这里：
1. **PM 管线**：问题一直在——项目管理、信息流转、流程沉淀都有长期痛点；所以先用 Cursor 做系统，再扩展到硅基军团。
2. **集卡素材**：问题也一直在——人工产卡面 2-3 周；早期 AI 成本高效果差；公版照片是阶段性替代；2022 年底用 Disco Diffusion 试集卡；现在沉淀到 5 分钟一套。

#### 第 2 页：基础科普
> 先认清硅基同事的身体构造  

用 LLM / Agent / Skill / Memory / MCP 帮大家建立派活地图，解决“概念太多、分不清”的问题。

#### 第 3 页：管理视角
> 从“会用 AI”到“会管理硅基劳动力”  

这一页承接原提纲的“驯化”主题，也能吸收第 3 份文档里的生产关系思考。"""
md = md[:start] + new_top_block + md[end:]

# 2) Make section 1.8 title even more searchable.
md = md.replace(
    "### 1.8 场景错配：不是拿着锤子找钉子，而是一直有钉子",
    "### 1.8 开篇主案例：PM 管线 / 集卡素材——不是拿着锤子找钉子，而是一直有钉子"
)

# 3) Make section 2.3 title more explicit.
md = md.replace(
    "### 2.3 插入位置三：开篇场景错配案例",
    "### 2.3 插入位置三：开篇主案例页（PM 管线 + 集卡素材）"
)

# 4) Strengthen module list item.
md = md.replace(
    "3. **重写场景错配**：不是拿着锤子找钉子，而是一直有钉子，所以每次新锤子都要试。",
    "3. **开篇主案例页**：PM 管线 + 集卡素材，证明不是拿着锤子找钉子，而是一直有钉子，所以每次新锤子都要试。"
)

# 5) Ensure directory has searchable PM/集卡 wording near top.
md = md.replace(
    "3. 场景错配：不是拿着锤子找钉子，而是一直有钉子",
    "3. 场景错配主案例：PM 管线 / 集卡素材——不是拿着锤子找钉子，而是一直有钉子"
)

Path(r"D:/MyAgents/tmp/ai-share-after-promote-cases.md").write_text(md, encoding="utf-8")

u = subprocess.run(["dws", "doc", "update", "--node", node, "--mode", "overwrite", "--markdown", md, "--format", "json", "--yes"], text=True, capture_output=True, encoding="utf-8", errors="replace")
print("UPDATE", u.returncode)
print(u.stdout); print(u.stderr)
if u.returncode != 0:
    raise SystemExit(u.returncode)

v = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("VERIFY", v.returncode)
if v.returncode != 0:
    print(v.stdout); print(v.stderr); raise SystemExit(v.returncode)
vm = json.loads(v.stdout)["markdown"]
checks = {
    "top recommended 3 pages": "最推荐新增的 3 页" in vm,
    "pm in recommended": "PM 管线" in vm and "先用 Cursor 做系统，再扩展到硅基军团" in vm,
    "card in recommended": "人工产卡面 2-3 周" in vm and "5 分钟一套" in vm,
    "section explicit": "开篇主案例：PM 管线 / 集卡素材" in vm,
    "insert explicit": "开篇主案例页（PM 管线 + 集卡素材）" in vm,
    "directory explicit": "场景错配主案例：PM 管线 / 集卡素材" in vm,
}
for k, ok in checks.items():
    print(f"CHECK {k}: {ok}")
if not all(checks.values()):
    raise SystemExit(2)
