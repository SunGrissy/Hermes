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
Path(r"D:/MyAgents/tmp/ai-share-before-opening-fix.md").write_text(md, encoding="utf-8")

# Replace Simon paragraph in total judgment to avoid over-weighting fatigue.
old = """Simon Willison 这篇补充材料，最适合帮这条主线落到真实体感：AI 没有让人天然更轻松，它把工作从“亲手执行”迁移到“持续判断”。所以分享里可以把“提效”讲得更真实：AI 省掉的是动手时间，新增的是判断负荷；真正稀缺的能力，从“我会不会做”转向“我能不能判断 AI 做得对不对、该不该继续、什么时候叫停”。"""
new = """开头要先把大家用 AI 的困惑分层，而不是一上来就讲“越用越累”。真实情况是：大多数人还没到判断疲劳阶段，主要卡在前三类：不得其法、等待一键成品、找不到真实场景。少数深度使用者才会进入“越用越累”的阶段——因为 AI 把工作从亲手执行，迁移到了持续判断。"""
if old not in md:
    print("old total judgment paragraph not found")
else:
    md = md.replace(old, new)

# Replace module list opening item.
md = md.replace(
    "1. **开篇先破除疲劳感迷思**：AI 省下执行时间，但会制造判断疲劳。",
    "1. **开篇先分层用户困惑**：不得其法、等待一键成品、场景错配、越用越累，其中“越用越累”是进阶问题，不是大多数人的起点。"
)

# Replace section 2.1.
start = md.index("### 2.1 插入位置一：开篇和观点之间")
end = md.index("\n\n---\n\n### 2.2", start)
new_21 = """### 2.1 插入位置一：开篇第一组问题

新增开篇页：
> 大家用 AI 的困惑，不是同一种困惑  

正文建议：
> 聊 AI 之前，先把问题分清楚。不是所有人都卡在同一个地方。有人是还不得其法：试了几次，觉得 AI 输出虚、泛、不可用；有人是在等“一键成品”：希望工具再成熟一点，最好一句话直接交付最终结果；有人是场景错配：看到新工具就找地方试，结果变成拿着锤子找钉子；还有少数深度使用者，已经进入“越用越累”的阶段——AI 确实省掉了执行时间，但把人推到了连续判断、连续验收的位置。  

这页的作用：先校准听众，不把所有问题都归因于“AI 让你更累”。大多数人真正需要解决的，是怎么开始、怎么选场景、怎么从等成品转向训练伙伴。"""
md = md[:start] + new_21 + md[end:]

# Replace new directory opening section.
start = md.index("### 一、开篇：为什么你觉得 AI 不好用？")
end = md.index("\n\n### 二、基础科普", start)
new_dir = """### 一、开篇：大家用 AI 的困惑，其实不是同一种
1. 还不得其法：试了几次，输出虚、泛、不可用
2. 等一键成品：想拖延到工具足够成熟，最好一句话直接交付
3. 场景错配：拿着锤子找钉子，追工具而不是追问题
4. 真实钉子：PM 管线 / 集卡素材——问题一直在，所以每次新锤子都要试
5. 进阶困惑：少数深度使用者会越用越累，因为执行疲劳变成判断疲劳
6. 开篇收束：这场分享不是教大家追工具，而是教大家把 AI 驯化进真实工作流"""
md = md[:start] + new_dir + md[end:]

# Add a new 1.6 preface paragraph to mark fatigue as advanced.
md = md.replace(
    "### 1.6 AI 没有让你更闲，而是把累从执行转到判断\n\nSimon Willison 的案例适合放在开篇痛点里，用来回应一个很真实的感受：为什么用了 AI，效率明明变高，人反而更累？",
    "### 1.6 AI 没有让你更闲，而是把累从执行转到判断\n\n这部分不要放成开篇主问题，只适合作为“进阶困惑”。因为大多数人还没用到这个深度，真正会越用越累的人，通常已经开始高频调用 AI、同时管理多个输出、持续做验收判断。\n\nSimon Willison 的案例适合放在开篇分层的最后，用来回应一个更进阶的真实感受：为什么用了 AI，效率明明变高，人反而更累？"
)

# If phrase remains in final advice? keep if context ok. Write and update.
Path(r"D:/MyAgents/tmp/ai-share-after-opening-fix.md").write_text(md, encoding="utf-8")

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
    "opening classification title": "大家用 AI 的困惑，不是同一种困惑" in vm,
    "not same confusion directory": "大家用 AI 的困惑，其实不是同一种" in vm,
    "不得其法": "还不得其法" in vm,
    "一键成品": "一键成品" in vm,
    "进阶困惑": "进阶困惑" in vm,
    "fatigue not main": "这部分不要放成开篇主问题，只适合作为“进阶困惑”" in vm,
    "module updated": "开篇先分层用户困惑" in vm,
}
for k, ok in checks.items():
    print(f"CHECK {k}: {ok}")
if not all(checks.values()):
    raise SystemExit(2)
