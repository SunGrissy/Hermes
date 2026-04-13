# SKILL 写作指南

硅基伙伴训练俱乐部出品。帮你写出第一份 SKILL，或把已有的 SKILL 写得更好。

## 什么是 SKILL

**给 AI 的岗位说明书。** 把你做某件事的思路、步骤、判断标准写成一份 Markdown 文档，AI 读了之后就能按你的方式做事。不需要会写代码。

## 怎么用

### 我完全不知道 SKILL 是什么

跟 AI 说：

```
SKILL 是什么？跟我有什么关系？我平时做 [你的工作内容]，有什么能写成 SKILL 的吗？
```

### 我想写第一份 SKILL，但不知道从哪开始

跟 AI 说：

```
帮我写一份 SKILL。我想教 AI 怎么 [做某件事]。
我平时是这么做的：[用大白话描述你的步骤]。
最容易出问题的地方是：[描述常见的坑]。
```

AI 会追问几个问题帮你理清思路，然后生成一份完整的 SKILL 文档和 README。

### 我已经写了一份 SKILL，想让人帮我看看

跟 AI 说：

```
帮我看看这份 SKILL 写得怎么样，有什么能改进的。
[粘贴你的 SKILL 内容]
```

### 我想把某个专家或大佬的思维方式变成 SKILL

跟 AI 说：

```
用女娲的方法，帮我蒸馏 [人名] 的思维方式，做成一份 perspective SKILL。
```

需要先安装 [女娲 · Skill 造人术](https://github.com/alchaincyf/nuwa-skill)。

### Cursor 用户额外福利

如果你用 Cursor 且安装了 [Superpowers](https://github.com/cursor-public/superpowers) 技能包，可以获得更严格的 SKILL 质量保障：

- **写之前**：Superpowers 的 `brainstorming` 技能会引导你先想清楚再动手
- **写的时候**：`writing-skills` 技能提供 TDD 式的 SKILL 创建流程——先看 AI 没有 SKILL 时怎么做（基线），再写 SKILL，再验证效果
- **写完之后**：`verification-before-completion` 技能确保你验证过才算完成

直接跟 Cursor Agent 说"帮我创建一份 SKILL"，它会自动调用这些技能。

## 在不同 AI 工具中怎么放

| 工具 | 放哪里 |
|------|--------|
| Cursor | `~/.cursor/skills/你的skill名/SKILL.md` |
| Claude Code | `~/.claude/skills/你的skill名/SKILL.md` |
| ChatGPT / Claude 网页版 | 对话开头粘贴内容，或上传为文件 |
| 其他 AI 工具 | 作为 system prompt 或上下文文件提供，要求AI保存为SKILL |

## 提交清单

每次提交 SKILL 作业时，确认：

- [ ] 一份 `SKILL.md`
- [ ] 一份 `README.md`（几句话说清楚怎么用）
- [ ] 有明确的触发场景、可执行的步骤、至少一条陷阱或"不要做什么"
- [ ] 用至少一个真实场景验证过效果

## 参考资源

- [女娲 · Skill 造人术](https://github.com/alchaincyf/nuwa-skill) — 蒸馏任何人的思维方式
- [ljg-skills](https://github.com/lijigang/ljg-skills) — 高质量 SKILL 示例合集（概念解剖、论文阅读、写作引擎等）
- [awesome-ai-agent-skills](https://github.com/seb1n/awesome-ai-agent-skills) — 90+ 开源 SKILL 索引
- [Superpowers](https://github.com/cursor-public/superpowers) — Cursor 增强技能包（含 SKILL 创建的 TDD 流程）
