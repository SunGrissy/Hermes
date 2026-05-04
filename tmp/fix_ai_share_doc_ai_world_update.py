import json
import subprocess

node = "YMyQA2dXW7972ggAI5712QkLJzlwrZgb"
read_cmd = ["dws", "doc", "read", "--node", node, "--format", "json", "--yes"]
r = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
r.check_returncode()
md = json.loads(r.stdout)["markdown"]

start = md.index("### 2\\. 建议并入原分享的")
end = md.index("\n\n### 3\\. 建议不要重讲的内容", start)
new_block = """### 2\\. 建议并入原分享的 8 个模块
1. **开篇先破除疲劳感迷思**：AI 省下执行时间，但会制造判断疲劳。
2. **补一页基础科普**：用“硅基同事的身体构造”讲清 LLM / Agent / Skill / Memory / MCP。
3. **开篇后加一层定义**：AI 不是工具，是需要被训练的硅基伙伴。
4. **观点区强化一句生产力公式**：未来最小生产单元是“人 \\+ 一组硅基伙伴”。
5. **驯化五层里补一层组织视角**：从个人对话，走向工作流资产和硅基编队。
6. **公司资源前加一段基建逻辑**：AI 基建的前提是信息基建。
7. **收尾拔高**：AI 不会平均提升所有人，它会放大自驱力、思考深度和沉淀能力。
8. **每个概念都落到派活方法**：这次分享不是术语课，也不是炫技，而是告诉大家什么问题该用什么 AI 能力解决。"""
md = md[:start] + new_block + md[end:]

# Normalize the inserted subheading colon.
md = md.replace("新增小节:\n> 重新定义：AI 不是工具，是需要被训练的硅基伙伴", "新增小节：\n> 重新定义：AI 不是工具，是需要被训练的硅基伙伴")

update_cmd = ["dws", "doc", "update", "--node", node, "--mode", "overwrite", "--markdown", md, "--format", "json", "--yes"]
u = subprocess.run(update_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
print("UPDATE_RETURN_CODE", u.returncode)
print(u.stdout)
print(u.stderr)
u.check_returncode()

v = subprocess.run(read_cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
v.check_returncode()
vm = json.loads(v.stdout)["markdown"]
checks = {
    "8 modules": "建议并入原分享的 8 个模块" in vm,
    "no duplicate module line": vm.count("公司资源前加一段基建逻辑") == 1,
    "basic page": "新增基础科普页" in vm and "先认清硅基同事的身体构造" in vm,
    "dispatch judgment": "这一页下面可以配一个“派活判断”" in vm,
    "final one page": "如果只加一页基础科普" in vm,
}
for k, ok in checks.items():
    print(f"CHECK {k}: {ok}")
