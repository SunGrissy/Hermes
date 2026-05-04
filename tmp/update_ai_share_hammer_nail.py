import json
import re
import subprocess
from pathlib import Path

node = "YMyQA2dXW7972ggAI5712QkLJzlwrZgb"
backup_path = Path(r"D:/MyAgents/tmp/ai-share-before-hammer-nail-update.md")
updated_path = Path(r"D:/MyAgents/tmp/ai-share-after-hammer-nail-update.md")

read_cmd = ["dws", "doc", "read", "--node", node, "--format", "json", "--yes"]
r = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("READ_RETURN_CODE", r.returncode)
if r.returncode != 0:
    print(r.stdout)
    print(r.stderr)
    raise SystemExit(r.returncode)
md = json.loads(r.stdout)["markdown"]
backup_path.write_text(md, encoding="utf-8")

# Remove previous version of this update if re-run.
def remove_between(text, start_marker, end_marker):
    if start_marker in text:
        before, rest = text.split(start_marker, 1)
        if end_marker in rest:
            _, after = rest.split(end_marker, 1)
            return before.rstrip() + "\n\n" + end_marker + after
    return text

md = remove_between(md, "### 1.8 场景错配：不是拿着锤子找钉子", "---\n\n## 2\\. 建议插入到原分享的位置")
md = remove_between(md, "### 2.3 插入位置三：开篇场景错配案例", "---\n\n### 2.4")

section_18 = """### 1.8 场景错配：不是拿着锤子找钉子，而是一直有钉子

“场景错配”这点可以再讲准一点：很多人用 AI 的问题，不是工具不够新，而是先被工具吸引，才临时去找一个能用的场景。妙妙说的“拿着锤子找钉子”很形象：手里突然多了一把锤子，于是到处找东西敲，最后当然容易觉得 AI 不稳定、不好用、不解决真问题。

但真正的深度应用，路径通常反过来：先有一个长期存在、反复刺痛你的问题，再持续寻找新工具去解决它。不是“新锤子来了，我去找钉子”，而是“这颗钉子一直扎在这里，所以每次有新锤子，我都要试一下”。

可以用两个例子讲：
1. **PM 管线案例**：我自己的深度应用不是从“我要玩 AI”开始，而是从 PM 管线里的真实问题开始。先用 Cursor 把系统做起来，解决项目管理、信息流转、流程沉淀里的具体痛点；再慢慢扩展到今天的硅基军团。它不是工具驱动，而是问题驱动。
2. **集卡素材案例**：策划产集卡素材这个问题，几年前就存在。最早人工产卡面，一套要 2-3 周；后来尝试早期 AI，效果不理想，时间成本也高，于是阶段性转向公版照片；再后来每次生成式 AI 有明显发展，都继续试 AI 生图。2022 年底已经开始用 Disco Diffusion 出集卡；再逐步演进到现在的工作流，做到 5 分钟一套。

这个案例的收束句可以是：
> 问题一直都在。关键不是工具进化到什么程度，而是你有没有迫切想解决这个问题的欲望。真正有效的 AI 应用，不是拿着锤子找钉子，而是一直有钉子，所以每次出了新锤子都要试一下。  

这段非常适合放在开篇“为什么你觉得 AI 不好用”的“场景错配”下面。它能把分享从“AI 方法论”拉回真实业务：我们不是为了显得先进才用 AI，而是因为问题真实存在、成本长期存在，所以工具一旦进化，就值得立刻重新评估。
"""

insert_before = "---\n\n## 2\\. 建议插入到原分享的位置"
if insert_before not in md:
    raise RuntimeError("Cannot find insertion point before section 2")
md = md.replace(insert_before, section_18 + "\n\n---\n\n## 2\\. 建议插入到原分享的位置", 1)

# Insert a concrete opening/case page in section 2 after 2.2 basic science page.
case_insert = """---

### 2.3 插入位置三：开篇场景错配案例

新增案例页：
> 不是拿着锤子找钉子，而是一直有钉子  

正文建议：
> AI 用不起来，很多时候不是因为工具不够强，而是场景一开始就错了。最典型的是“拿着锤子找钉子”：看到一个新工具很火，就到处想它能不能用，最后容易变成炫技、试用、浅尝辄止。真正跑得深的 AI 应用，通常反过来：问题早就存在，成本一直很高，只是过去没有足够好的工具。工具每进化一次，就值得重新试一次。  
>
> 比如 PM 管线这件事，我不是因为 Cursor 新鲜才去做系统，而是项目管理、信息流转、流程沉淀这些问题一直存在，所以先从 PM 管线入手，用 Cursor 把系统做起来，再逐步扩展到今天的硅基军团。再比如集卡素材，最早人工产卡面一套要 2-3 周；早期 AI 试过，但效果和时间成本都不理想；中间转过公版照片；后来生成式 AI 每次大幅进步，我们都继续试。2022 年底已经开始用 Disco Diffusion 出集卡，直到现在沉淀成 5 分钟一套的工作流。  
>
> 所以真正的分水岭，不是“你会不会追最新工具”，而是“你有没有一个足够想解决的真问题”。问题一直都在，关键是每次新锤子出现时，你会不会拿它去敲那颗早就存在的钉子。  

这一页的作用：把“场景错配”从负面提醒变成正面方法——先找长期问题，再看工具成熟度；不是为了用 AI 而用 AI，而是用 AI 重新评估那些过去做不了、做不好、做太慢的事。
"""
# Renumber existing headings after 2.2 by inserting before current 2.3.
marker_23 = "---\n\n### 2.3 插入位置三：开篇和观点之间"
if marker_23 not in md:
    raise RuntimeError("Cannot find current section 2.3")
md = md.replace(marker_23, case_insert + "\n\n---\n\n### 2.4 插入位置四：开篇和观点之间", 1)
# Renumber subsequent section headings.
renums = [
    ("### 2.4 插入位置四：观点部分", "### 2.5 插入位置五：观点部分"),
    ("### 2.5 插入位置五：驯化五层之后", "### 2.6 插入位置六：驯化五层之后"),
    ("### 2.6 插入位置六：公司资源之前", "### 2.7 插入位置七：公司资源之前"),
    ("### 2.7 插入位置七：收尾", "### 2.8 插入位置八：收尾"),
]
for a, b in renums:
    md = md.replace(a, b)

# Update module list count/content.
start = md.index("### 2\\. 建议并入原分享的")
end = md.index("\n\n### 3\\. 建议不要重讲的内容", start)
new_modules = """### 2\\. 建议并入原分享的 9 个模块
1. **开篇先破除疲劳感迷思**：AI 省下执行时间，但会制造判断疲劳。
2. **补一页基础科普**：用“硅基同事的身体构造”讲清 LLM / Agent / Skill / Memory / MCP。
3. **重写场景错配**：不是拿着锤子找钉子，而是一直有钉子，所以每次新锤子都要试。
4. **开篇后加一层定义**：AI 不是工具，是需要被训练的硅基伙伴。
5. **观点区强化一句生产力公式**：未来最小生产单元是“人 \\+ 一组硅基伙伴”。
6. **驯化五层里补一层组织视角**：从个人对话，走向工作流资产和硅基编队。
7. **公司资源前加一段基建逻辑**：AI 基建的前提是信息基建。
8. **收尾拔高**：AI 不会平均提升所有人，它会放大自驱力、思考深度和沉淀能力。
9. **每个概念都落到派活方法**：这次分享不是术语课，也不是炫技，而是告诉大家什么问题该用什么 AI 能力解决。"""
md = md[:start] + new_modules + md[end:]

# Fix and enrich suggested new directory. Replace whole directory section 3 between header and section 4.
dir_start = md.index("## 3\\. 建议形成的新版目录")
dir_end = md.index("\n\n---\n\n## 4\\. 最后建议", dir_start)
new_dir = """## 3\\. 建议形成的新版目录

### 一、开篇：为什么你觉得 AI 不好用？
1. 期望错位
2. 磨合不足
3. 场景错配：不是拿着锤子找钉子，而是一直有钉子
4. 自我价值焦虑
5. 拖延等待
6. AI 让你更累：从执行疲劳变成判断疲劳

### 二、基础科普：先认清硅基同事的身体构造
1. LLM：大脑，决定基础智力
2. Agent：有手有脚的完整员工，能调用工具做事
3. Skill：岗位 SOP，把高频任务变成可复用方法
4. Memory：工作档案，记住偏好、背景和长期约定
5. MCP：万能转接头，让 AI 能连接公司系统
6. 派活判断：对话窗口 / Agent / Skill / Memory / MCP 分别解决什么问题

### 三、重新定义：AI 不是工具，是野生硅基伙伴
1. 工具等你操作，伙伴需要训练
2. 通用 AI 默认是路人甲
3. 驯化的本质是喂上下文、给反馈、定标准、沉资产

### 四、核心观点：未来的最小生产单元是“人 \\+ AI”
1. AI 省掉的是执行时间，新增的是判断负荷
2. AI 不会平均提升所有人，只会加速分化
3. 价值问题从“我会不会被替代”变成“我 \\+ AI 为什么更强”
4. 学的不是某个工具，而是协作接口
5. 管理者未来管理的不只是人力，也包括硅基劳动力

### 五、业务案例：一直有钉子，所以每次新锤子都要试
1. PM 管线：从真实管理痛点出发，用 Cursor 做系统，再扩展到硅基军团
2. 集卡素材：人工 2-3 周 → 早期 AI 试错 → 公版照片 → Disco Diffusion → 5 分钟一套工作流
3. 收束：问题一直都在，关键是解决欲望和持续试错

### 六、驯化路径：从野生 AI 到专属伙伴的五层训练
1. 给背景：从发命令到交代上下文
2. 做迭代：从一次产出到多轮反馈
3. 促思考：从替我写到帮我想
4. 沉资产：从聊天记录到工作流模板
5. 组编队：从一个 AI 到一组硅基伙伴

### 七、产品岗最值得先做的 6 类场景
1. 资料压缩
2. 初稿生成
3. 边界穷举
4. 多角色评审
5. 表达改写
6. 流程沉淀

### 八、现场演示：把一个粗糙想法驯化成可评审方案
1. 野生提问
2. 补上下文
3. 让 AI 反问
4. 多角色挑战
5. 沉淀模板

### 九、从个人工具到组织资产
1. 当前最确定的 ROI：自动化清扫摩擦成本
2. AI 基建的前提：信息基建
3. 个人经验要沉淀成 Prompt、Checklist、Skill
4. 判断标准要外化：让 AI 先读历史记录、案例和验收标准再开始
5. 公司资源是为了让好工作流跨人复用

### 十、行动指南：今天下班前完成一轮驯化
1. 选一个 30 分钟以上的真实任务
2. 按背景 / 目标 / 约束 / 输出格式 / 验收标准交代
3. 至少迭代两轮
4. 把有效提示词存下来
5. 明天复用一次

### 十一、收尾：别等 AI 准备好，先让它认识你
1. 野生 AI 不属于任何人
2. 被训练过的 AI 才是你的伙伴
3. 半年后的差距，从今天第一轮磨合开始"""
md = md[:dir_start] + new_dir + md[dir_end:]

# Add final advice bullet for hammer/nail.
final_insert_after = "4\\. **疲劳类型变了**：AI 不是让人天然更轻松，而是把负担从执行疲劳迁移到判断疲劳。越能同时指挥多个 AI，越需要稳定的判断标准和验收机制。"
if final_insert_after in md and "**问题驱动变了**" not in md:
    md = md.replace(final_insert_after, final_insert_after + "\n5. **问题驱动变了**：不是先有 AI 再找场景，而是先有长期钉子，再持续测试每一代新锤子。", 1)

updated_path.write_text(md, encoding="utf-8")

update_cmd = ["dws", "doc", "update", "--node", node, "--mode", "overwrite", "--markdown", md, "--format", "json", "--yes"]
u = subprocess.run(update_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("UPDATE_RETURN_CODE", u.returncode)
print(u.stdout)
print(u.stderr)
if u.returncode != 0:
    raise SystemExit(u.returncode)

v = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("VERIFY_RETURN_CODE", v.returncode)
if v.returncode != 0:
    print(v.stdout)
    print(v.stderr)
    raise SystemExit(v.returncode)
vm = json.loads(v.stdout)["markdown"]
checks = {
    "hammer nail section": "不是拿着锤子找钉子，而是一直有钉子" in vm,
    "pm cursor legion": "用 Cursor 把系统做起来，再逐步扩展到今天的硅基军团" in vm,
    "card workflow": "5 分钟一套" in vm and "Disco Diffusion" in vm,
    "modules 9": "建议并入原分享的 9 个模块" in vm,
    "directory fixed basic": "基础科普：先认清硅基同事的身体构造" in vm,
    "directory business case": "业务案例：一直有钉子，所以每次新锤子都要试" in vm,
    "section 2.8 exists": "### 2.8 插入位置八：收尾" in vm,
}
for k, ok in checks.items():
    print(f"CHECK {k}: {ok}")
if not all(checks.values()):
    raise SystemExit(2)
