---
name: dws-dingtalk-cli
description: |
  dws (DingTalk Workspace CLI) — 钉钉官方 AI-native CLI，163 个命令，14 个产品线。
  覆盖 Hermes 现有 MCP 没有的能力：AITable、群聊/机器人、待办、审批、考勤、AI听记、邮箱、云盘、DING消息。
  通过 terminal 调用，输出 JSON，--yes 跳过确认，--format json 结构化输出。
triggers:
  - 发送钉钉消息给某人
  - 查 AI 表格
  - 操作钉钉待办
  - 查看审批/发起审批
  - 钉钉群聊
  - AI 听记
  - 云盘文件
  - DING 消息
  - 考勤
---

## 基本信息

- **安装路径**：`C:\Users\TU\.local\bin\dws.exe`
- **Token 有效期**：2026年5月27日（过期后运行 `dws auth login` 重新授权）
- **当前用户**：userId `0165313012750022`，企业「在线途游（北京）科技有限公司」
- **标准用法**：`dws <product> <command> [flags] --format json --yes`

## 与现有 MCP 的关系

| 能力 | 用哪个 |
|------|--------|
| 日历/日程 | 优先用 `mcp_dingtalk_calendar_*` |
| 文档读写 | 优先用 `mcp_dingtalk_docs_*` |
| 日志 | 优先用 `mcp_dingtalk_logs_*` |
| AI 表格 | **用 dws aitable** |
| 群聊/机器人 | **用 dws bot / dws chat** |
| 待办 | **用 dws todo** |
| 审批 | **用 dws oa** |
| 考勤 | **用 dws attendance** |
| AI 听记 | **用 dws minutes** |
| 邮箱 | **用 dws mail** |
| 云盘 | **用 dws drive** |
| DING 消息 | **用 dws ding** |

## 命令路径说明

dws 使用**子命令分组**，不是扁平 RPC 名。格式：`dws <产品> <子命令组> <动作>`

## 产品线速查（已验证路径）

### ding — DING消息
```bash
dws ding --help  # 查子命令
```

### mail — 邮箱
```bash
dws mail --help  # 查子命令
```

### bot — 机器人/群聊
```bash
dws bot --help  # 查子命令
```

### drive — 云盘
```bash
dws drive --help  # 查子命令
```

### aitable — AI 表格（已验证）
```bash
# Base 管理
dws aitable base list --format json --yes           # 列出所有 Base（已验证可用）
dws aitable base search --keyword=xxx --yes         # 按名搜索
dws aitable base get --baseId=xxx --yes             # 获取详情

# 记录操作
dws aitable record list --baseId=xxx --tableId=xxx --yes      # 查询记录
dws aitable record create --baseId=xxx --tableId=xxx --yes    # 新增
dws aitable record update --baseId=xxx --tableId=xxx --yes    # 更新
dws aitable record delete --baseId=xxx --tableId=xxx --yes    # 删除

# 表/字段/视图
dws aitable table list --baseId=xxx --yes           # 列出表
dws aitable field list --baseId=xxx --tableId=xxx --yes  # 列字段
dws aitable view list --baseId=xxx --tableId=xxx --yes   # 列视图

# Dashboard/图表
dws aitable dashboard --help
dws aitable chart --help
```

### minutes — AI 听记（已验证）
```bash
dws minutes list mine --max=10 --format json --yes          # 列出我的听记（--max 必填）
dws minutes list shared --max=10 --yes                      # 别人共享的
dws minutes get --help                                      # 获取详情（summary/transcription等）
```

### oa — 审批（已验证路径）
```bash
dws oa approval --help                                      # 查子命令
dws oa approval list --help                                 # 审批列表
```

### todo — 待办（已验证）
```bash
dws todo task list --format json --yes                      # 获取待办列表（已验证返回真实数据）
dws todo task create --subject="xxx" --yes                  # 创建待办
dws todo task get --taskId=xxx --yes                        # 查详情
dws todo task done --taskId=xxx --yes                       # 标记完成
dws todo task update --taskId=xxx --yes                     # 更新
dws todo task delete --taskId=xxx --yes                     # 删除
```

### attendance — 考勤（若干命令）
```bash
dws attendance --help  # 查看全部子命令
```

### doc — 文档（21个命令，与 MCP 重叠但支持下载）
```bash
dws doc get_document_content --nodeId=xxx  # 读文档内容（Markdown）
dws doc download_file --nodeId=xxx         # 获取文件下载链接
dws doc search_documents                   # 搜文档
```

### report — 日志/日报（已验证）
```bash
# 创建日报（正确 field key 必须与模板字段名完全一致）
dws report create \
  --template-id 153363afc40e225078a5a254ded82265 \
  --contents '[{"content":"xxx","sort":"0","key":"今日完成工作","contentType":"markdown","type":"1"}]' \
  --to-chat \
  --to-user-ids userId1,userId2 \
  --yes

# 查模板字段名（若 key 错误会报 PARAM_ERROR）
dws report template detail --name 日报 --yes

# 列出可用模板
dws report template list --yes
```

**Pitfall：** `key` 写成 `今日完成` 等简称会导致 `PARAM_ERROR`。必须与模板返回的 `field_name` 完全一致。

**日报抄送名单 JSON：** 见 `references/daily-report-cc-list.json`

### contact — 通讯录
```bash
dws contact user get-self --format json    # 获取自己的用户信息
dws contact user search --query=xxx        # 搜索用户（使用 --query，不是 --keyword）
dws contact user get --ids uid1,uid2       # 批量获取用户详情（使用 --ids）
dws contact dept list                      # 列部门
```

**Pitfall：** `search` 用 `--query` 而非 `--keyword`；`get` 用 `--ids` 而非 `--userId`。

## 常用 Flags

| Flag | 说明 |
|------|------|
| `--format json` | JSON 输出（默认就是 json） |
| `--yes` / `-y` | 跳过确认提示，Agent 模式必加 |
| `--jq '.xxx'` | 内置 jq 过滤输出 |
| `--fields name,id` | 只返回指定字段 |
| `--dry-run` | 预览不执行 |
| `--debug` | 显示调试日志 |

## 典型用法示例（已验证）

```bash
# 查我的待办（已验证，返回真实数据）
dws todo task list --format json --yes

# 列出所有 AI 表格（已验证）
dws aitable base list --format json --yes

# 查 AI 表格里的记录（先拿 baseId/tableId 再查）
dws aitable table list --baseId=XXX --yes
dws aitable record list --baseId=XXX --tableId=XXX --yes

# 列出我的听记（--max 必填）
dws minutes list mine --max=10 --format json --yes

# 查审批子命令（再具体探索）
dws oa approval --help

# 未知产品子命令先 --help 探索再使用
dws <product> --help
dws <product> <subcmd> --help
```

## 常见误区 / Pitfalls

| 误区 | 正确做法 |
|------|---------|
| ❌ 把 dws 当 MCP server 挂进 `config.yaml` | ✅ dws 是独立 CLI，**不走 MCP**，直接用 terminal 调用 |
| ❌ 用 `&&` 串联多个 dws 命令 | ✅ 单条执行；多条用分号 `;`（PowerShell）或分开调用 |
| ❌ 忘记 `--yes` | ✅ Agent 自动化场景必加 `--yes`，否则会卡交互确认 |
| ❌ 用扁平 RPC 思维猜命令名 | ✅ 先 `dws <product> --help` 探路子命令分组 |

## 注意事项

1. **命令参数用 `--` 长格式**：dws 参数是驼峰转短横线，如 `taskUuid` → `--taskUuid`
2. **分页**：大多数列表支持 `--nextToken` 翻页，检查返回结果中的 `nextToken` 字段
3. **ID 获取顺序**：通常先 list/search → 拿 ID → 再 get 详情
4. **aitable 访问 URL**：`https://docs.dingtalk.com/i/nodes/{baseId}`
5. **token 过期**：若命令返回 401/403，运行 `dws auth login` 重新授权
6. **Windows 路径**：PowerShell 下直接用 `dws`，PATH 已配置好
