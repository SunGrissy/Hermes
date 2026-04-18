# 第三方仓库（external）

本目录用于存放**与 MyAgents 主仓松耦合**的外部开源仓库克隆，便于本地阅读、对比或按需拷贝 Skill/Prompt，**不替代** `.cursor/skills/` 中的权威技能源。

## Khazix Skills（卡兹克 AI 工具箱）

- 上游：<https://github.com/KKKKhazix/khazix-skills>
- 说明：内含 **Prompts**（如横纵分析法）与 **Skills**（`hv-analysis`、`khazix-writer` 等），MIT 协议。

### 在本机拉取（推荐）

在仓库根目录执行：

```bash
cd external
git clone --depth 1 https://github.com/KKKKhazix/khazix-skills.git
```

得到路径：`external/khazix-skills/`。

若 HTTPS 不稳定，可改用 SSH（需已配置 GitHub SSH）：

```bash
cd external
git clone --depth 1 git@github.com:KKKKhazix/khazix-skills.git
```

### 备选：下载 ZIP 解压

1. 浏览器打开：<https://github.com/KKKKhazix/khazix-skills/archive/refs/heads/main.zip>
2. 解压到本目录下，并将文件夹重命名为 `khazix-skills`（与上面 `git clone` 路径一致）。

在 macOS 终端解压时若报中文文件名错误，可先执行：

```bash
export LC_ALL=en_US.UTF-8
```

再 `unzip`。

### 与 Cursor 的衔接

上游 README 中的安装路径针对 Claude Code / Codex 等；若要在本工作区给 Agent 用，需将对应 **Skill 目录**按 [skill-authoring-guide](https://github.com/KKKKhazix/khazix-skills) 的格式评估后，**合并或引用**到 `.cursor/skills/`，并更新 `.cursor/skills/README.md`（以你们规范为准）。
