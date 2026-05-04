import json
import subprocess
from pathlib import Path

node = "YMyQA2dXW7972ggAI5712QkLJzlwrZgb"
backup_path = Path(r"D:/MyAgents/tmp/ai-share-production-relations-before-ai-world-update.md")
updated_path = Path(r"D:/MyAgents/tmp/ai-share-production-relations-with-ai-world.md")

read_cmd = ["dws", "doc", "read", "--node", node, "--format", "json", "--yes"]
read_res = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
if read_res.returncode != 0:
    print(read_res.stdout)
    print(read_res.stderr)
    raise SystemExit(read_res.returncode)

data = json.loads(read_res.stdout)
md = data["markdown"]
backup_path.write_text(md, encoding="utf-8")

# Idempotent cleanup if this script is re-run.
marker_start = "\n### 1.8 AI 世界的构成：不是术语课，是派活地图\n"
marker_end = "\n---\n\n## 2. 建议插入到原分享的位置"
if marker_start in md:
    before, rest = md.split(marker_start, 1)
    _, after = rest.split(marker_end, 1)
    md = before + marker_end + after

section_18 = """
### 1.8 AI 世界的构成：不是术语课，是派活地图

妙妙补的这段非常适合放进分享，但建议不要讲成“AI 名词解释”，而是讲成一张派活地图：你把 AI 当成一个新来的硅基同事，就得先知道它的身体构造，才知道什么活能交、怎么交、交到什么程度。

可以写成一页基础科普：

| 构成 | 用硅基同事来理解 | 解决什么问题 | 常见误区 |
|---|---|---|---|
| LLM 大语言模型 | 大脑 | 决定它理解、推理、生成的基础能力 | 把“模型强”误以为“工具就一定好用” |
| Agent 智能体 | 有手有脚的完整员工 | 能读文件、查资料、写代码、发消息、调用工具 | 把普通聊天窗口误以为 Agent |
| Skill 技能包 | 岗位培训手册 | 把“这摊活怎么干”的 SOP 固化下来 | 每次都从头教，经验不沉淀 |
| Memory 长期记忆 | 员工工作档案 | 记住偏好、习惯、项目背景和长期约定 | 把一次性聊天当成长期协作 |
| MCP 接口协议 | 万能转接头 | 让 AI 能连接钉钉、文档、系统、数据库等外部工具 | 以为 AI 聪明就自然能操作公司系统 |

这页最重要的不是让大家记住术语，而是形成三个判断：
1. **只需要想法和初稿时，用对话窗口就够了**：比如脑暴标题、改写表达、整理会议纪要。
2. **需要跨系统执行时，要找 Agent**：比如读文档、查日程、改文件、发消息、跑脚本。
3. **高频任务要沉成 Skill / Memory / MCP**：Skill 解决“怎么干”，Memory 解决“别每次重说”，MCP 解决“能不能摸到系统”。

可以用一句话串起来：
> 你招了一个新硅基同事：LLM 是它的脑子好不好使，Agent 是它有没有手有脚能干实事，Skill 是它的岗位 SOP，Memory 是它记不记得你的习惯，MCP 是它能不能调用公司系统。  

放在分享里，它的价值是破除两类迷思：
1. **不是所有 AI 都一样**：模型、工具、Agent、工作流不是一个层级。
2. **不是会聊天就会解决问题**：真正能解决问题，靠的是“脑子 + 手脚 + SOP + 记忆 + 接口”一起工作。

建议插入位置：放在“为什么 AI 让你更累了？”之后、“重新定义：AI 不是工具，是需要被训练的硅基伙伴”之前。先解释大家为什么懵，再给一张简单地图，然后再讲怎么驯化。
"""

md = md.replace("\n---\n\n## 2. 建议插入到原分享的位置", "\n---\n\n" + section_18.strip() + "\n\n---\n\n## 2. 建议插入到原分享的位置")

# Update outline module count and add basic knowledge point.
md = md.replace("### 2. 建议并入原分享的 5 个模块\n1. **开篇后加一层定义**：AI 不是工具，是需要被训练的硅基伙伴。", "### 2. 建议并入原分享的 8 个模块\n1. **开篇先破除疲劳感迷思**：AI 省下执行时间，但会制造判断疲劳。\n2. **补一页基础科普**：用“硅基同事的身体构造”讲清 LLM / Agent / Skill / Memory / MCP。\n3. **开篇后加一层定义**：AI 不是工具，是需要被训练的硅基伙伴。")
md = md.replace("5. **收尾拔高**：AI 不会平均提升所有人，它会放大自驱力、思考深度和沉淀能力。\n6. **开篇痛点补一页真实代价**：AI 省下执行时间，但会制造判断疲劳。\n7. **人才分层补一层判断力逻辑**：新手被加速，老手被放大，中间执行层最容易被挤压。", "5. **公司资源前加一段基建逻辑**：AI 基建的前提是信息基建。\n6. **收尾拔高**：AI 不会平均提升所有人，它会放大自驱力、思考深度和沉淀能力。\n7. **人才分层补一层判断力逻辑**：新手被加速，老手被放大，中间执行层最容易被挤压。\n8. **每个概念都落到派活方法**：这次分享不是术语课，也不是炫技，而是告诉大家什么问题该用什么 AI 能力解决。")

# Insert a new suggested insertion page before existing 2.2 and renumber subsequent headings.
insert_21b = """
---

### 2.2 插入位置二：开篇和观点之间

新增基础科普页：
> 先认清硅基同事的身体构造  

正文建议：
> 很多人觉得 AI 概念眼花缭乱，是因为把不同层级的东西混在了一起：模型、工具、Agent、Skill、Memory、MCP，听起来都像 AI，但解决的问题完全不同。可以把 AI 想象成一个新来的硅基同事：LLM 是脑子，Agent 是有手有脚的员工，Skill 是岗位培训手册，Memory 是工作档案，MCP 是连接公司系统的万能转接头。  
>
> 所以我们判断一个 AI 能不能解决问题，不是只问“它聪不聪明”，而是问五件事：脑子够不够用？有没有手脚？有没有岗位 SOP？记不记得我的习惯？能不能连接我要用的系统？这五件事凑齐，它才从一个会聊天的人，变成一个能干活的硅基伙伴。  

这一页下面可以配一个“派活判断”：
1. 只要想法、初稿、改写：对话窗口够用。
2. 要读文件、查资料、改代码、发消息：需要 Agent。
3. 高频重复任务：沉成 Skill。
4. 长期偏好和项目背景：放进 Memory。
5. 要碰公司系统和外部工具：需要 MCP 或类似接口。
"""
md = md.replace("\n---\n\n### 2.2 插入位置二：开篇和观点之间\n\n新增小节：", insert_21b + "\n---\n\n### 2.3 插入位置三：开篇和观点之间\n\n新增小节:")
md = md.replace("### 2.3 插入位置三：观点部分", "### 2.4 插入位置四：观点部分")
md = md.replace("### 2.4 插入位置四：驯化五层之后", "### 2.5 插入位置五：驯化五层之后")
md = md.replace("### 2.5 插入位置五：公司资源之前", "### 2.6 插入位置六：公司资源之前")
md = md.replace("### 2.6 插入位置六：收尾", "### 2.7 插入位置七：收尾")

# Update directory: add a new section after opening and renumber old sections.
old_dir = """### 一、开篇：为什么你觉得 AI 不好用？
1. 期望错位
2. 磨合不足
3. 场景错配
4. 自我价值焦虑
5. 拖延等待
6. AI 让你更累：从执行疲劳变成判断疲劳

### 二、重新定义：AI 不是工具，是野生硅基伙伴
1. 工具等你操作，伙伴需要训练
2. 通用 AI 默认是路人甲
3. 驯化的本质是喂上下文、给反馈、定标准、沉资产

### 三、核心观点：未来的最小生产单元是“人 + AI”"""
new_dir = """### 一、开篇：为什么你觉得 AI 不好用？
1. 期望错位
2. 磨合不足
3. 场景错配
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

### 四、核心观点：未来的最小生产单元是“人 + AI”"""
md = md.replace(old_dir, new_dir)
# Renumber subsequent Chinese section headings in directory only.
replacements = [
    ("### 四、驯化路径：从野生 AI 到专属伙伴的五层训练", "### 五、驯化路径：从野生 AI 到专属伙伴的五层训练"),
    ("### 五、产品岗最值得先做的 6 类场景", "### 六、产品岗最值得先做的 6 类场景"),
    ("### 六、现场演示：把一个粗糙想法驯化成可评审方案", "### 七、现场演示：把一个粗糙想法驯化成可评审方案"),
    ("### 七、从个人工具到组织资产", "### 八、从个人工具到组织资产"),
    ("### 八、行动指南：今天下班前完成一轮驯化", "### 九、行动指南：今天下班前完成一轮驯化"),
    ("### 九、收尾：别等 AI 准备好，先让它认识你", "### 十、收尾：别等 AI 准备好，先让它认识你"),
]
for a, b in replacements:
    md = md.replace(a, b)

# Update final advice with the new practical framing.
md = md.replace("如果只加一页，就加：\n> 为什么 AI 让你更累了：从执行疲劳到判断疲劳。", "如果只加一页基础科普，就加：\n> 先认清硅基同事的身体构造：LLM 是脑子，Agent 是员工，Skill 是 SOP，Memory 是档案，MCP 是转接头。  \n\n如果只加一页体感问题，就加：\n> 为什么 AI 让你更累了：从执行疲劳到判断疲劳。")

updated_path.write_text(md, encoding="utf-8")

update_cmd = [
    "dws", "doc", "update",
    "--node", node,
    "--mode", "overwrite",
    "--markdown", md,
    "--format", "json",
    "--yes",
]
update_res = subprocess.run(update_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("UPDATE_RETURN_CODE", update_res.returncode)
print(update_res.stdout)
print(update_res.stderr)
if update_res.returncode != 0:
    raise SystemExit(update_res.returncode)

verify_res = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("VERIFY_RETURN_CODE", verify_res.returncode)
if verify_res.returncode != 0:
    print(verify_res.stdout)
    print(verify_res.stderr)
    raise SystemExit(verify_res.returncode)
verify_data = json.loads(verify_res.stdout)
verify_md = verify_data["markdown"]
checks = [
    "AI 世界的构成：不是术语课，是派活地图",
    "先认清硅基同事的身体构造",
    "LLM 是脑子，Agent 是员工，Skill 是 SOP，Memory 是档案，MCP 是转接头",
]
for check in checks:
    print(f"CHECK {check}: {check in verify_md}")
