# Multica 接入（Cloud A + pm-system 试点 + 钉钉 Stream 派单）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 **Multica Cloud（方案 A）** 上跑通 **pm-system** 试点工单流；用 **钉钉企业机器人 Stream 模式** 私聊/群 @ 触发 `#派单` 在本机执行 `multica issue create`；可选 Webhook 回执；文档与 **WORK_LOG** 互链纪律可执行。

**Architecture:** 钉钉侧用官方 **`dingtalk-stream`** 长连接收消息（无需公网回调 URL）；建单通过本机已登录的 **`multica` CLI** 子进程调用（与 [CLI_AND_DAEMON.md](https://raw.githubusercontent.com/multica-ai/multica/main/CLI_AND_DAEMON.md) 一致）；出站通知复用现有 **Markdown Webhook** 形态（可选环境变量）。

**Tech Stack:** Multica CLI（Homebrew 或官方安装脚本）、Python 3.11+、`dingtalk-stream`、可选 `urllib` 发群 Webhook。

**依据 spec:** `docs/superpowers/specs/2026-04-18-multica-integration-design.md`（§3.1、§5–§8）。

**执行环境建议：** 在独立 **git worktree** 或干净分支上改 `tools/` 与文档，避免与并行会话踩踏（见 `git-branch-guard.mdc`）。

---

## 文件与目录（实施将创建/修改）

| 路径 | 职责 |
|------|------|
| `tools/multica-dingtalk-bridge/README.md` | 环境变量、钉钉开放平台勾选项、运行与排障 |
| `tools/multica-dingtalk-bridge/requirements.txt` | Python 依赖 |
| `tools/multica-dingtalk-bridge/dispatch_bot.py` | Stream 机器人 + 调 `multica issue create` |
| `pm-system/WORK_LOG.md` | 顶部增加 3～5 行「Multica 关单互链」操作提示（可选但推荐） |
| `docs/superpowers/specs/2026-04-18-multica-integration-design.md` | 若实施中发现与 spec 偏差，回写「修订记录」一小段（可选） |

---

### Task 1: 本机安装 Multica CLI 并完成 Cloud 登录

**Files:** 无仓库内文件；本机环境。

- [ ] **Step 1: 安装 CLI（macOS 示例）**

```bash
brew install multica-ai/tap/multica
multica version
```

Expected: 打印版本号，无 `command not found`。

- [ ] **Step 2: 一键接入 Cloud 并启动 daemon**

```bash
multica setup
```

Expected: 浏览器完成登录；`~/.multica/` 下生成配置；daemon 已启动或按提示 `multica daemon start`。

- [ ] **Step 3: 校验**

```bash
multica auth status
multica daemon status
multica workspace list
```

Expected: `auth status` 显示已登录；daemon 为 running；至少一个 workspace 带 `*` watch。

- [ ] **Step 4: 降级备忘（回滚）**

若需停用：`multica daemon stop`；彻底退出登录：`multica auth logout`。不删仓库代码。

---

### Task 2: 在 Multica Web 上固定「pm-system」试点

**Files:** 无代码；浏览器操作，结果记在 `tools/multica-dingtalk-bridge/README.md` 或本机密码管理器。

- [ ] **Step 1:** 打开 `https://multica.ai/app`（或 spec 中自托管 URL，本 plan 按 Cloud），进入默认 workspace。

- [ ] **Step 2:** 在 **Settings → Agents** 创建至少一个 Agent（例如绑定本机 Runtime + **Cursor Agent** 或已安装的 CLI），名称便于指派（如 `pm-cursor`）。

- [ ] **Step 3:** 在 **Projects** 创建项目，标题建议：`pm-system 试点`，记下 **project id**（CLI 过滤用）。

- [ ] **Step 4:** 用 CLI 建第一条试跑 Issue（标题含 `pm-system` 便于检索）

```bash
multica config show
# 若 default workspace 不对：
# multica config set workspace_id <你的-workspace-uuid>

multica issue create \
  --title "pm-system 试点：Multica 首单" \
  --description "范围仅限 pm-system/；关单时补 WORK_LOG 并互链 Multica。" \
  --priority medium \
  --status todo \
  --project <上一步-project-id>
```

Expected: 命令返回成功；Web 看板可见该 Issue。

- [ ] **Step 5: 默认 workspace 写入 README**

把 `workspace_id`、project 名称、`multica agent list` 里可用的 Agent 名写进 **Task 3** 的 README 模板中（避免口述丢失）。

---

### Task 3: 编写 `tools/multica-dingtalk-bridge/README.md` 与 `requirements.txt`

**Files:**
- Create: `tools/multica-dingtalk-bridge/README.md`
- Create: `tools/multica-dingtalk-bridge/requirements.txt`

- [ ] **Step 1: 写入 `requirements.txt`**

```text
dingtalk-stream>=0.24.0
```

- [ ] **Step 2: 写入 `README.md` 必备章节（可复制下列 Markdown 为初稿，再按你环境改占位符）**

```markdown
# Multica × 钉钉 Stream 派单桥

## 前提

- 本机已 `multica login` 且 `multica issue create` 手工可成功。
- 钉钉开放平台：企业自建应用已开启 **机器人** 且接入 **Stream 模式**（非传统 HTTP 回调）；记录 `Client ID` / `Client Secret`。
- 运行桥的主机须能访问钉钉与 Multica Cloud（公司网络策略自行放行）。

## 运行

```bash
cd tools/multica-dingtalk-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python dispatch_bot.py --client_id "<Client ID>" --client_secret "<Client Secret>"
```

## 群内 / 私聊发单格式

首行必须以 `#派单` 开头，紧跟标题；从第二行起为描述（可选）。

## 可选出站

设置环境变量 `DINGTALK_WEBHOOK_URL` 后，建单成功会向该 Webhook 发一条 Markdown（与仓库 `cursor-to-dingtalk` 机器人格式兼容）。

## 安全

- 勿在 Issue 正文写密钥、内网未公开数据；见 spec §3.1 脱敏。
- `Client Secret` 建议用环境变量注入，避免写进 shell history：`export DINGTALK_CLIENT_SECRET=...` 后改脚本读 env（实施时可小改 `dispatch_bot.py`）。
```

- [ ] **Step 3: 提交（仅当用户要求提交时）**  
按 `git-workflow.mdc`，本步完成后由用户决定是否 `git add` 上述文件并提交。

---

### Task 4: 实现 `dispatch_bot.py`（钉钉 Stream → `multica issue create`）

**Files:**
- Create: `tools/multica-dingtalk-bridge/dispatch_bot.py`

- [ ] **Step 1: 创建文件，内容如下（整文件替换）**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""钉钉 Stream 机器人收消息 -> 本机 multica issue create。运行前须 multica login 且 multica 在 PATH。"""

import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.request
from typing import Optional

from dingtalk_stream import AckMessage
import dingtalk_stream

PREFIX = "#派单"
LOG = logging.getLogger("multica-bridge")


def _notify_webhook(title: str, text: str) -> None:
    url = (os.environ.get("DINGTALK_WEBHOOK_URL") or "").strip()
    if not url:
        return
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title[:50], "text": text},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except OSError as e:
        LOG.warning("webhook notify failed: %s", e)


class MulticaDispatchHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__()
        self._log = logger or LOG

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        tc = incoming.text
        raw = ((tc.content if tc else "") or "").strip()
        if not raw.startswith(PREFIX):
            self.reply_text(
                "未建单。请以 `#派单 一行标题` 开头；第二行起为描述（可选）。",
                incoming,
            )
            return AckMessage.STATUS_OK, "OK"

        body = raw[len(PREFIX) :].lstrip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if not lines:
            self.reply_text("标题不能为空。", incoming)
            return AckMessage.STATUS_OK, "OK"

        title = lines[0][:500]
        description = "\n".join(lines[1:]) if len(lines) > 1 else "（钉钉派单，无额外描述）"

        cmd = [
            "multica",
            "issue",
            "create",
            "--title",
            title,
            "--description",
            description,
            "--priority",
            "medium",
            "--status",
            "todo",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        out_b, err_b = await proc.communicate()
        out = (out_b or b"").decode("utf-8", errors="replace")
        err = (err_b or b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            self._log.warning("multica exit=%s stderr=%s stdout=%s", proc.returncode, err, out)
            self.reply_text(
                "Multica 建单失败。请检查本机：`multica auth status`、default workspace、`multica issue create` 手工是否正常。",
                incoming,
            )
            return AckMessage.STATUS_OK, "OK"

        self.reply_text(
            "已创建 Multica Issue（todo / medium）。CLI 输出：\n```\n" + out[:1200] + "\n```",
            incoming,
        )
        _notify_webhook(
            "Multica 新单",
            "### Multica 钉钉派单\n\n" + title + "\n\n```\n" + out[:800] + "\n```\n",
        )
        return AckMessage.STATUS_OK, "OK"


def setup_logger() -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        root.addHandler(h)
    root.setLevel(logging.INFO)
    return root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client_id",
        default=os.environ.get("DINGTALK_CLIENT_ID", ""),
        help="钉钉应用 Client ID（或环境变量 DINGTALK_CLIENT_ID）",
    )
    parser.add_argument(
        "--client_secret",
        default=os.environ.get("DINGTALK_CLIENT_SECRET", ""),
        help="钉钉应用 Client Secret（或环境变量 DINGTALK_CLIENT_SECRET）",
    )
    args = parser.parse_args()
    if not args.client_id or not args.client_secret:
        print("需要 --client_id / --client_secret 或对应环境变量", file=sys.stderr)
        sys.exit(2)

    logger = setup_logger()
    credential = dingtalk_stream.Credential(args.client_id, args.client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        MulticaDispatchHandler(logger),
    )
    logger.info("DingTalk stream started; ensure `multica` is on PATH and logged in.")
    client.start_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法检查**

```bash
cd tools/multica-dingtalk-bridge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m py_compile dispatch_bot.py
```

Expected: 无输出即通过。

- [ ] **Step 3: 联调（需真实钉钉凭据）**  
启动 `python dispatch_bot.py ...`，在钉钉私聊发送：

```text
#派单 测试来自钉钉
第二行描述
```

Expected: Multica Web 出现新 Issue；机器人回复含 CLI 输出片段。

---

### Task 5: pm-system WORK_LOG 互链提示（可选但推荐）

**Files:**
- Modify: `pm-system/WORK_LOG.md`（在文件最顶部 `# Work Log` 标题下追加一个短小节）

- [ ] **Step 1: 在 `pm-system/WORK_LOG.md` 顶部「# Work Log」下一行插入如下小节**

```markdown
## Multica 协作提示

- 与 Multica 相关的交付：在对应 WORK_LOG 条目末尾增加 `Multica: <issue-id 或链接>`。  
- Multica 关单评论：写清交付摘要并指向本文件中的日期条目。  
- 试点期内代码变更范围默认在 `pm-system/`；跨子模块须在 Multica 单内写明。

```

- [ ] **Step 2: 目视确认**  
打开 `pm-system/WORK_LOG.md`，确认不与原有首条日志冲突（若首条紧贴标题，可在该小节与首条日志之间保留一空行）。

---

### Task 6: 试点验收（人工清单，4 周内）

**Files:** 无新增；行为验收。

- [ ] **Step 1:** 完成 ≥10 条 **与 pm-system 相关** 的 Multica Issue（可混合手工 Web 创建与钉钉 `#派单`）。  
- [ ] **Step 2:** ≥1 条由 **非制作人账号** 认领并完成。  
- [ ] **Step 3:** 每条关闭的 Issue 在评论中 **手写** `WORK_LOG: YYYY-MM-DD - 标题片段`，且 `pm-system/WORK_LOG.md` 对应条有 `Multica:` 反向引用。  
- [ ] **Step 4:** 复盘是否继续 **方案 A** 或启动迁 **方案 B**（见 spec §3.1）。

---

## Plan 自检（对照 spec）

| spec 章节 | 对应 Task |
|-----------|-----------|
| §3.1 方案 A | Task 1 |
| §5–§6 钉钉入站 / 可选出站 | Task 3–4 |
| §8 pm-system 试点 | Task 2、6 |
| §7 WORK_LOG 互链 | Task 5、6 |

**占位符扫描：** 本 plan 中 `<上一步-project-id>` 等为 **操作者当场替换**，非代码 TODO。

---

## 执行方式（任选）

Plan 已保存至 `docs/superpowers/plans/2026-04-18-multica-integration.md`。

**1. Subagent-Driven（推荐）** — 每个 Task 新开 subagent，Task 之间人工快速验收。  
**2. Inline Execution** — 本会话用 executing-plans 按 Task 顺序执行，遇钉钉/Multica 真机步骤暂停等你操作。

回复 **「1」** 或 **「2」** 即表示选择的执行模式（由你或后续会话实施；本回复不自动执行 Task 1 的安装命令）。

---

## 收工快照（2026-04-18）

> 本会话整理：进展 + 剩余 ToDo + **周一换工作用 Windows PC** 的迁移要点。  
> 权威 spec：`docs/superpowers/specs/2026-04-18-multica-integration-design.md`。

### 当前进展（已达成）

| 项 | 状态 |
|----|------|
| **Multica Cloud** | 已在 Web 登录；workspace（如 UU-MyAgents）与试点 **Project** 已创建。 |
| **CLI 建单闭环** | `multica issue create`（含 `--project <项目 UUID>`）已验证：**看板可即时出现新 Issue**。Project ID 即浏览器地址栏 `/projects/` 后一段 UUID。 |
| **仓库落地** | `tools/multica-dingtalk-bridge/`：`README.md`、`requirements.txt`、`dispatch_bot.py` 已就绪（钉钉 Stream → 本机 `multica issue create`）。 |
| **macOS CLI** | 可通过 `brew install multica-ai/tap/multica` 安装 `multica`（本机曾用此路径装通）。 |

### 已知坑（已记录，不必重复踩）

| 项 | 说明 |
|----|------|
| **daemon 起不来** | `~/.multica/daemon.log` 若提示 **no agent CLI**，需在 PATH 中提供 `cursor-agent`（或 `claude` / `codex` 等其一）。Cursor 侧可装官方 CLI 并保证 `~/.local/bin` 等在 PATH；**仅钉钉派单建单**不依赖 daemon。 |
| **子模块 / 根仓库** | 根目录若有其他子模块或脏文件，与 Multica 工具目录无关；提交时只 `git add tools/multica-dingtalk-bridge/` 下需入库文件即可。 |

### 剩余 ToDo（按 plan / spec）

| 优先级 | 内容 | 对应 |
|--------|------|------|
| 高 | **钉钉 Stream 真机联调**（若尚未做）：开放平台机器人 + Stream、`DINGTALK_CLIENT_*`、运行 `dispatch_bot.py`，私聊/群 `@` 发 `#派单 标题` + 可选第二行描述，确认 Multica 与机器人回复。 | Task 4 Step 3 |
| 中 | **`tools/.../README.md` 试点表**：填入默认 `workspace_id`、project 名称与 **project id**（勿写 Client Secret）。 | Task 2 Step 5 |
| 中 | **`multica daemon start`**：在已安装编码 Agent CLI 的前提下确认 `multica daemon status` 为 running（需要本机 Runtime 再接）。 | Task 1 |
| 低 | **`pm-system/WORK_LOG.md` 顶部**增加「Multica 协作提示」小节（plan Task 5，推荐）。 | Task 5 |
| 持续 | **4 周试点验收**：≥10 条 pm-system 相关 Issue、≥1 条非本人认领、关单与 WORK_LOG 互链、复盘 A/B（plan Task 6）。 | Task 6 |
| 流程 | 根仓库 **git commit**：按 `git-workflow.mdc`，在用户明确「请提交 / 验收通过」时再提交 `tools/multica-dingtalk-bridge/`（勿夹带其他会话脏文件）。 | — |

### 周一换到工作电脑（Windows PC）要做啥

工作区约定：**主力开发环境为 Windows PowerShell**（见 `shell-git.mdc`）。换机本质是 **重装 CLI + 重登 Multica + 重建 Python 虚拟环境 + 钉钉凭据**，不依赖把 Mac 整机搬过去。

1. **拉代码**  
   - 在新 PC 上 clone / pull **MyAgents** 根仓库，确认存在 `tools/multica-dingtalk-bridge/`。

2. **安装 Multica CLI（Windows，无 Homebrew）**  
   - 使用 [Multica 官方文档 / 安装方式](https://raw.githubusercontent.com/multica-ai/multica/main/CLI_AND_DAEMON.md) 中适用于 Windows 的安装指引（安装包或官方脚本等，以当前文档为准）。  
   - 在 **PowerShell** 中验证：`multica version`（若 `python` 不可用，优先用 `py` 仅针对本仓库 Python 脚本，**multica 为独立二进制则直接调用 `multica`**）。

3. **重新接入 Cloud**  
   - 执行 `multica setup`，用浏览器完成登录（与 Mac 上同一账号即可）。  
   - `multica config show`，必要时 `multica config set workspace_id <与现网一致的 UUID>`。  
   - **一般不建议**把 Mac 上 `~/.multica/` 整目录裸拷到工作机（含 token，且路径/权限易出问题）；除非内控允许且你清楚风险。

4. **确认试点项目**  
   - Project ID 与 Mac 相同：`https://multica.ai/.../projects/<uuid>` 最后一节；CLI 试跑一条 `multica issue create ... --project <uuid>` 验证。

5. **钉钉桥（Python）**  
   - `cd tools\multica-dingtalk-bridge`  
   - `py -m venv .venv`  
   - `.\.venv\Scripts\Activate.ps1`  
   - `pip install -r requirements.txt`  
   - 设置环境变量或参数传入 **Client ID / Client Secret**（勿写入仓库）；可选 `DINGTALK_WEBHOOK_URL`。  
   - `python dispatch_bot.py`（或 `py dispatch_bot.py`，以本机 PATH 为准）。

6. **daemon（若需要）**  
   - 在工作机安装并配置 **Cursor CLI / 其他受支持 Agent CLI**，保证 PowerShell 里 `Get-Command cursor-agent`（或文档列出的名称）可用，再 `multica daemon start`。  
   - 仍失败则读 **`%USERPROFILE%\.multica\daemon.log`**（路径以本机为准，与 Mac 的 `~/.multica/daemon.log` 对应）。

7. **网络与公司策略**  
   - 放行本机访问 **钉钉开放平台 / Stream** 与 **multica.ai**（及 CLI 所需端点），否则建单或长连会失败。

8. **编码习惯（Windows）**  
   - PowerShell 下**不要用 `&&` 串联**（用 `;`）；本仓库 Python **避免在 print 里用 emoji**（部分终端 GBK 会炸）。桥接脚本本身以英文/ASCII 日志为主，一般无妨。

### PC 试用 Claude Code（明日，工作机）

- **安装与 PATH**：按 Anthropic 官方「Claude Code」Windows 安装指引装好后，**新开一个 PowerShell**，执行 `Get-Command claude`（或文档给出的命令名）确认在 PATH 里；不要只在安装向导里点完就关窗，避免当前会话拿不到 PATH。  
- **登录与密钥**：首次运行会走浏览器/账号流程；API Key、组织配置等只放在 **Claude 官方配置 / 本机环境变量**，**不要**写进仓库、不要贴进钉钉/邮件正文。  
- **与 Multica daemon**：`~/.multica/daemon.log` 里列出的受支持 CLI 含 **`claude`**。若你希望工作机上 **Multica 本机 runtime** 能拉起：先在同一 PowerShell 里确认 `claude` 可执行，再 `multica daemon start`；仍失败就看 `%USERPROFILE%\.multica\daemon.log`。  
- **网络**：公司出口若拦截 Anthropic API，需提前问 IT 或走合规通道；否则会出现「能装不能连」。  
- **习惯对齐本仓**：PowerShell 用 `;` 串联命令；终端里少依赖 emoji 输出；先在 **小目录 / 单任务** 试跑，再进大仓库，避免一上来全仓索引拖慢或误改。
