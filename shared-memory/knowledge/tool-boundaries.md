# Agent 工具边界与环境限制

## Browser 工具 [Hermes]

- 当前环境下 `browser_navigate`、`browser_vision` 等调用会报 **WinError 193** "%1 is not a valid Win32 application"。
- 所有 Agent 在此环境不应依赖 browser 工具进行 web 访问或文档检索。

## DingTalk Docs MCP [Hermes]

- `mcp_dingtalk_docs_*` 系列工具只能读取**本组织内的钉钉在线文档（alidocs）**。
- 无法访问：
  1. yunpan/qr.dingtalk.com 云盘文件
  2. 其他组织的 alidocs（跨组织访问被拒绝）
- 用户发送文档链接时，优先处理 alidocs URL；yunpan/跨组织链接预期会失败。

## Kimi API Key [OpenClaw/Hermes]

- 用户提供的 "Kimi API key" 实际上是 **OpenRouter key**。
- 必须使用的参数：`base_url=https://openrouter.ai/api/v1`，`model=moonshotai/kimi-k2.6`。
- 原生 Moonshot API（api.moonshot.cn）对此 key 返回 401。
