# dingtalk-desktop — AI Agent 操作手册

> 本文档供 AI Agent 阅读。你通过此 skill 获得控制钉钉 Windows 桌面端的能力：收发消息、读取历史、监听实时消息、提取日报。
> 技术细节和协议参考见 [SKILL.md](./SKILL.md)。

---

## 你能做什么

| 能力 | 怎么做 | 前置条件 |
|------|--------|---------|
| 发文本消息 | `POST /send {name:"张三", message:"你好"}` | daemon 运行 |
| 发图片 | `POST /send-image {name:"张三", file_path:"..."}` | daemon 运行，图片文件存在 |
| 读历史消息 | `POST /fetch {name:"张三", count:20}` | daemon 运行 |
| 按关键词搜索消息 | `GET /search?keyword=xxx&limit=30` | daemon 运行 |
| 查联系人/CID | `GET /contacts?name=张三` | daemon 运行 |
| 读日报/周报 | `POST /fetch_reports {count:10, author:"张三"}` | daemon 运行 + `config.json` 配好 `report_cid` |
| 实时监听消息 | daemon 启动后自动运行 Monitor，消息写入 `data/dingtalk/_msg_log.jsonl` | daemon 运行 |
| 在 CEF 里跑任意 JS | `POST /exec_js {js:"...", timeout:15}` | daemon 运行 + JSAPI browser 可用 |

所有 HTTP 调用地址：`http://127.0.0.1:19200`。

---

## 首次部署

### 环境要求

- Windows 10/11（x64）
- 钉钉桌面端 8.x 已安装并登录
- Python 3.9+（`python` 在 PATH 中）
- 已安装依赖：`pip install frida-tools msgpack`

### 配置

复制 `config.example.json` 为 `config.json`，填入你的信息：

```json
{
  "my_uid": "你的钉钉 UID（必填，数字字符串）",
  "report_cid": "工作汇报会话 CID（可选）",
  "my_report_group_cid": "我的报群 CID（可选）",
  "silent_download_dir": "文件静默下载目录（可选）"
}
```

`config.json` 已 gitignore。所有字段也可通过环境变量覆盖（`DINGTALK_MY_UID` 等）。

获取 UID 的方法：daemon 启动后 `/health` 返回中包含 UID；或查看 `data/dingtalk/contacts.json` 中的 CID（单聊格式 `UID_A:UID_B`）。

### MCP 集成（可选）

如果你的 Agent 框架支持 MCP（如 Cursor、Claude Desktop），在 MCP 配置中注册 `mcp_server.py`：

**Cursor — `.cursor/mcp.json`：**
```json
{
  "mcpServers": {
    "dingtalk-desktop": {
      "command": "python",
      "args": ["path/to/skills/dingtalk-desktop/mcp_server.py"]
    }
  }
}
```

**Claude Desktop — `claude_desktop_config.json`：**
```json
{
  "mcpServers": {
    "dingtalk-desktop": {
      "command": "python",
      "args": ["path/to/skills/dingtalk-desktop/mcp_server.py"]
    }
  }
}
```

依赖：`pip install mcp frida-tools msgpack`

MCP server 会自动启动 daemon（如未运行）。注册后 Agent 可直接调用以下工具：

| MCP 工具 | daemon 端点 | 说明 |
|----------|------------|------|
| `dingtalk_send_message` | `/send` | 发送文本消息 |
| `dingtalk_fetch_history` | `/fetch` | 获取历史消息 |
| `dingtalk_search_log` | `/search` | 搜索消息日志 |
| `dingtalk_find_conversation` | `/contacts` | 按姓名查 CID |
| `dingtalk_fetch_reports` | `/fetch_reports` | 获取工作汇报 |
| `dingtalk_fetch_my_reports` | `/fetch_my_reports` | 获取自己的汇报 |
| `dingtalk_monitor_status` | `/health` | 运行状态检查 |

---

## 操作流程

### 启动 daemon

每次使用前，按以下步骤启动（顺序不可乱）：

1. **确认钉钉在运行**
   ```powershell
   Get-Process DingTalk -ErrorAction SilentlyContinue
   ```
   如果没有进程，启动它：
   ```powershell
   Start-Process "C:\Program Files (x86)\DingDing\DingtalkLauncher.exe"
   Start-Sleep -Seconds 10
   ```

2. **清理残留 Python 进程**（daemon 异常退出后可能残留）
   ```powershell
   Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
   ```

3. **启动 daemon**
   ```powershell
   python skills/dingtalk-desktop/daemon.py
   ```
   后台运行。等待 8 秒让 Frida 完成附加。

4. **验证**
   ```powershell
   curl.exe -s http://127.0.0.1:19200/health
   ```
   确认返回中 `frida_attached: true`、`cef_ready: true`、`monitor_running: true`。

### 停止 daemon

```powershell
curl.exe -X POST http://127.0.0.1:19200/shutdown
```

**绝对不要用 `taskkill` 或 `Stop-Process` 强杀 Python 进程**——会导致钉钉崩溃。

---

## 关键约束（必须遵守）

1. **串行调用** — daemon 是单线程 HTTP Server，并发请求会互相阻塞导致全部超时。MCP 并行调用同样有此问题。**所有请求必须一个接一个。**

2. **用 `curl.exe` 不用 `curl`** — PowerShell 中 `curl` 是 `Invoke-WebRequest` 的 alias，行为不同。必须写 `curl.exe`。

3. **name 参数必须精确匹配** — `name` 字段必须与钉钉显示名 strip 后完全一致。多个同名联系人会报错 409，此时改用 `cid`。

4. **图片消息有延迟** — ct=203 纯图片依赖钉钉客户端异步下载到本地缓存（约 10-15 秒）。daemon 内置图片等待机制（15s debounce + 最长 3 分钟重试），但极端情况下可能图片未就绪。

5. **钉钉窗口状态** — 钉钉最小化到托盘时 Renderer 进程可能被回收，导致 JS 注入失败（影响发送和历史获取，不影响 Monitor 监听）。遇到 CEF 相关错误时，确认钉钉窗口在前台或至少未最小化。

---

## API 速查

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/health` | GET | — | 健康检查（含 Frida/CEF/Monitor 状态） |
| `/send` | POST | `{cid\|name, message}` | 发送文本消息 |
| `/send-image` | POST | `{cid\|name, file_path}` | 发送本地图片 |
| `/fetch` | POST | `{cid\|name, count?, before?, after?}` | 获取历史消息 |
| `/contacts` | GET | `?name=` | 按姓名查找会话 CID |
| `/search` | GET | `?keyword=&limit=` | 搜索消息日志 |
| `/fetch_reports` | POST | `{count?, before?, after?, author?, report_type?}` | 获取工作汇报（需配置 `report_cid`） |
| `/fetch_my_reports` | POST | `{count?, before?, after?, report_type?, full_content?}` | 获取我的工作汇报（需配置 `my_report_group_cid`） |
| `/exec_js` | POST | `{js, timeout?}` | 在 CEF 中执行任意 JS |
| `/probe_jsapi` | POST | — | 枚举所有可用的钉钉 JSAPI |
| `/shutdown` | POST | — | 安全停止 daemon |

`cid` 和 `name` 参数二选一。推荐优先用 `name`，省去查 CID 的步骤。

---

## 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| daemon 启动报 "Failed to attach" | 钉钉未运行，或有残留 Frida session | 确认钉钉在运行；清理残留 Python 进程后重试 |
| 发消息/拉历史超时 | 并发请求阻塞，或 CEF browser 不可用 | 确保串行调用；检查 `/health` 中 `cef_ready` |
| 联系人查不到 | 该联系人从未有过消息往来 | 联系人库只记录 daemon 运行期间收到过消息的人。新联系人需要先有消息产生 |
| 端口 19200 被占用 | 上次 daemon 未正常退出 | 等 30 秒让 TIME_WAIT 释放，或设环境变量 `DINGTALK_DAEMON_PORT` 换端口 |
| ct=203 图片内容为空 | 钉钉尚未下载图片到本地 | 正常情况下 daemon 的图片等待机制会自动处理；确认钉钉已打开过对应聊天 |

---

## 架构概览

```
┌─────────────┐     Frida      ┌──────────────────┐
│  钉钉桌面端  │◄──── attach ────│    daemon.py      │
│  (DingTalk)  │                │  HTTP :19200      │
│              │  CEF 注入 JS   │  ├── sender.py    │
│  ┌────────┐  │◄───────────────│  ├── monitor.py   │
│  │ libcef │  │  Native Hook   │  └── utils.py     │
│  └────────┘  │◄───────────────│                    │
└─────────────┘                └────────┬───────────┘
                                        │ HTTP API
                               ┌────────┴───────────┐
                               │  你（AI Agent）      │
                               │  通过 HTTP 或 MCP    │
                               └─────────────────────┘
```

- **CEF 脚本**：注入钉钉内嵌 Chromium，通过 JSAPI 发送消息、获取历史
- **Monitor 脚本**：Native Hook 钉钉消息管道，实时捕获收发消息，写入 JSONL 日志
- **HTTP API**：统一对外接口，所有操作通过 HTTP 调用

---

## 数据目录

daemon 运行后在 `data/dingtalk/` 下生成：

| 文件 | 说明 |
|------|------|
| `_msg_log.jsonl` | 消息日志（JSONL 格式，实时追加） |
| `contacts.json` | 联系人库（自动维护，收到消息自动更新） |
| `cache/images/` | daemon 下载的图片缓存 |
| `cache/files/` | daemon 下载的文件缓存 |

---

## 深入参考

[SKILL.md](./SKILL.md) 包含完整技术文档：消息协议格式、JSAPI 签名、字段结构、CDN URL 构造规则、CEF 注入原理、逆向探索记录等。
