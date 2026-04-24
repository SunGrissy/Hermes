# Hermes 与 TyGit / GitHub 分工说明

本文说明本机 Hermes Agent 如何与现有双 remote 规范对齐，供人类查阅；机器侧行为以 **`D:\hermes\SOUL.md`** 与 **`D:\hermes\config.yaml`** 为准。

## 已做的 Hermes 侧设置

| 位置 | 作用 |
|------|------|
| `D:\hermes\config.yaml` → `terminal.cwd` | 默认在 `D:\MyAgents` 执行终端命令。 |
| `D:\hermes\config.yaml` → `terminal.env_passthrough` | 向 Hermes 启动的子进程透传 `GITHUB_TOKEN` / `GH_TOKEN` / SSH 相关变量，便于 `gh` 与 `git` 使用本机凭证。 |
| `D:\hermes\SOUL.md` | 注入 TyGit 默认、`github` 仅显式口令、禁 force/hard reset 等规则。 |

## 本机仍需你维护的（Hermes 无法代劳）

1. **`git remote -v`**：确认 `origin` 仅 tygit、`github` 单独一条（与 `git-ops` skill 一致）。
2. **SSH 密钥或 HTTPS 凭据**：访问 tygit / GitHub 的认证与平时在 PowerShell 里一致；Hermes 终端继承透传变量，不替你生成密钥。
3. **`gh auth login`**：若要用 `gh pr` 等，在本机先登录一次。
4. **（可选）`D:\hermes\.env`**：若希望用变量名提供 token，可设置 `GITHUB_TOKEN` 或 `GH_TOKEN`（勿提交到 Git）。

## 可选：GitHub MCP

若要在 Hermes 里增加 GitHub 官方 MCP 工具，需在配置里声明 `mcp_servers` 并从环境注入 token；实现方式见 Hermes 仓库内 `cli-config.yaml.example` 的 MCP 章节。当前未默认开启，避免在 yaml 中硬编码密钥。

## 与 Cursor 的分工

日常改代码、按仓库规则验收仍以 **Cursor** 为主；Hermes 适合在 **`D:\MyAgents`** 下做状态查看、拉取、按口令推送、整理说明等终端类操作，且须遵守 `SOUL.md` 与仓库 rules。
