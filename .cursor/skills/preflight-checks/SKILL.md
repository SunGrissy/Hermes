---
name: preflight-checks
description: Remediation guide for gate check failures defined in agent-core.mdc. Use when a pre-commit, pre-push, post-edit, or acceptance gate check fails and the Agent needs guidance on how to fix the issue. Also use when scanning for secrets, checking reference consistency, or auditing .gitignore coverage. Covers Windows .bat CRLF vs LF and .gitattributes eol=crlf overrides when cmd.exe mis-parses batch files.
---

# 门禁检查修复指南

`agent-core.mdc` 定义了 post-edit / pre-commit / pre-push / on-accept 四道门禁。本 Skill 提供每项检查失败时的详细修复流程。

## E1 — Lint 错误修复

```
ReadLints → 有新增错误
```

1. 区分"新增错误"和"已有错误"：只修复本次编辑引入的
2. 常见原因：未闭合括号、缺少 import、变量名拼写、缩进不一致
3. 如果错误来自依赖方而非本次编辑 → 跳过，向用户报告

## E2 — 引用一致性检查

```
改了常量/枚举/接口签名/CSS变量/函数名 → Grep 搜索引用方
```

**高风险变更类型及搜索策略：**

| 变更类型 | 搜索方式 | 示例 |
|---------|---------|------|
| JS 函数名 | `Grep` 函数名，glob `*.js` | 改了 `saveData` → 搜所有 `.js` |
| CSS 变量 | `Grep` 变量名，glob `*.css,*.js,*.html` | 改了 `--primary` → 搜全部 |
| Python 函数/类名 | `Grep` 函数名，glob `*.py` | 改了 `def load_data` → 搜 `.py` |
| API 路由 | `Grep` 路径字符串，glob `*.js,*.py,*.html` | 改了 `/api/data` → 搜前后端 |
| HTML id/class | `Grep` id/class 名，glob `*.js,*.css,*.html` | 改了 `#importModal` → 搜全部 |
| 常量/枚举值 | `Grep` 常量名 | 改了 `STATUS_ACTIVE` → 搜全部 |

**流程：**
1. 搜索完毕后列出所有引用位置
2. 逐个判断是否需要同步修改
3. 全部修改完后重新跑 E1

**MyAgents 已知的跨文件引用热点：**
- `pm-system`: `data-manager.js` ↔ `app.js` ↔ `ui/components/*.js`（事件名、函数调用）
- `pm-system`: `styles.css` 中的 CSS 变量被 JS 内联样式引用
- `pm-system`: `backend/main.py` 的 API 路由被前端 `fetch()` 调用
- `performeval`: `backend/main.py` 的路由被 `index.html` 内的 fetch 调用

## C3 — 敏感信息扫描

```
git diff --cached 中发现 secret/password/token/api_key/private_key
```

**修复流程：**

1. 定位：确认是真实密钥还是变量名/注释/示例值
2. 如果是真实密钥：
   - 从代码中移除，改为从环境变量读取
   - 添加 `.env.example` 示例（值留空或用占位符）
   - 确认 `.env` 在 `.gitignore` 中
3. 如果是变量名/注释中的关键词（如 `secret_key = os.getenv(...)`）→ 属于误报，可继续
4. 对于 pm-system `config.py`：密钥外置化方案见 `PLAN_双Git工作流迁移.md` P-1 节

**常见敏感模式：**

```
secret_key\s*=\s*["'][^"']{8,}
password\s*=\s*["'][^"']+
token\s*=\s*["'][^"']{20,}
api_key\s*=\s*["']
private_key
-----BEGIN.*KEY-----
```

## P2 — 敏感路径审计

```
git ls-files 发现 backend/data/ 或 .env 被 track
```

**修复流程：**

1. 确认 `.gitignore` 是否覆盖该路径
2. 如果缺少规则 → 添加到对应仓库的 `.gitignore`

**注意：子模块有独立的 `.gitignore`**。根仓库的 `.gitignore` 不会保护子模块内的文件。需要在每个子模块中单独配置。

3. 已被 track 的文件需要 untrack：

```bash
git rm --cached <file>      # 从 git 移除但保留本地文件
git commit -m "chore: untrack sensitive file"
```

**各项目的敏感路径清单：**

| 项目 | 敏感路径 | 应在项目自身 .gitignore 中 |
|------|---------|--------------------------|
| pm-system | `backend/data/*.json`, `backend/data/backups/` | ✅ 已配置（逐文件） |
| performeval | `backend/data/`, `*.db` | 需确认 |
| cci_system | 无运行时数据目录 | — |
| task_reminder | `*.db` | 需确认 |
| 所有项目 | `.env` | 需确认每个子模块 |

## P3 — 子模块推送顺序

```
父仓库有子模块 gitlink 变更，但子模块未先推送
```

**修复流程：**

1. `git submodule status` → 找到有 `+` 前缀的子模块（ahead of recorded commit）
2. 逐个进入子模块目录执行 `git push origin main`
3. 全部子模块推送成功后，回到父仓库推送
4. 如果某个子模块推送失败 → 停止，不推父仓库

**标准操作序列：**

```bash
# 检查
git submodule status

# 推子模块（有变更的）
cd pm-system && git push origin main && cd ..
cd performeval && git push origin main && cd ..

# 最后推父仓库
git push origin main
```

## Windows 批处理（`.bat`）换行与 `.gitattributes`

**典型现象（cmd.exe 执行 `.bat` 时）**：`'65001'`、`'lor'`、`'eq'`、`'cho'`、`'THON_CMD'` 等被当成「不是内部或外部命令」；`echo`、`chcp`、`taskkill` 等行看似被拆碎。

**根因**：`cmd.exe` 依赖 **CRLF（`\r\n`）** 作为行尾。若工作区里是 **纯 LF**，或与全局 `eol=lf` 策略叠加，解析会错位。

**与仓库策略的关系**：若 `.gitattributes` 中存在 `* text=auto eol=lf`，检出会把文本统一为 LF，**`.bat` 也会被误伤**。

**修复步骤：**

1. **把受影响的 `.bat` 存为 CRLF**（编辑器「换行符：CRLF」，或对单文件用脚本 `open(..., newline='\r\n')` 重写）。
2. **在 `.gitattributes` 里为批处理单独覆盖**（规则写在通配 `*` 之后，以便后行覆盖前行）：

```gitattributes
* text=auto eol=lf

*.bat text eol=crlf
```

3. 变更较多时可在该仓库执行：`git add --renormalize "*.bat"`，再检查 `git diff` 确认仅换行与意图一致。

**自检**：`git check-attr eol -- path/to/quick_start.bat` 应显示 `eol: crlf`；二进制查看文件头若干字节应含 `0d 0a`。

## 门禁检查速查表

```
编辑文件后 → E1(lint) → E2(引用)
git commit 前 → C1(暂存列表) → C2(lint) → C3(密钥) → C4(WORK_LOG)
git push 前 → P1(子模块状态) → P2(敏感路径) → P3(推送顺序)
验收时 → A1(=C1-C4) → A2(WORK_LOG状态) → A3(=P1-P3)
```

## 变更记录

| 日期 | 版本 | 变更 | 来源会话 |
|------|------|------|----------|
| 2026-04-14 | v1.1 | 新增「Windows 批处理换行与 .gitattributes」：LF-only / `eol=lf` 误伤 `.bat` 的识别与修复 | AgentFix |
| （既有） | v1.0 | 初始内容 | 仓库既有 |
