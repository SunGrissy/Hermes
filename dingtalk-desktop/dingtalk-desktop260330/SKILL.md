# SKILL: 钉钉桌面端消息控制

> 通过 Frida 注入钉钉桌面端，实现消息收发和历史读取  
> 目标版本: DingTalk 8.3.0 (Chrome/133.0.6943.142) / Windows  
> 依赖: Python + Frida + msgpack + winotify  
> 脚本位置: `skills/dingtalk-desktop/`

### 首次配置

复制 `config.example.json` 为 `config.json`，填入个人信息：

```json
{
  "my_uid": "你的钉钉 UID",
  "report_cid": "工作汇报会话 CID（可选，用于 /fetch_reports）",
  "my_report_group_cid": "我的报群 CID（可选，用于 /fetch_my_reports）",
  "silent_download_dir": "文件静默下载目录（可选，默认 ~/Downloads/DingTalkFiles）"
}
```

`config.json` 已 gitignore，不会被提交。所有字段也可通过环境变量覆盖（`DINGTALK_MY_UID` 等）。

### 执行限制与注意事项

- **禁止使用原生 DLL Hook / HTTP 抓包实现钉钉功能**。所有钉钉数据获取统一通过 JSAPI + Beacon 路径
- **所有功能统一通过 daemon 提供**——CEF（发送/获取）、Monitor（监听）两个脚本共享同一个 Frida session
- **不要**单独运行 `_fetch_conv.py` 或 `_msg_monitor.py`——会与 daemon 的 session 冲突
- **结束 daemon 必须用 `POST /shutdown`**，`Stop-Process -Force` 会导致钉钉崩溃

### Beacon HTTP 端口注意事项

- 脚本通过本地 HTTP 服务器（BeaconServer）接收 CEF 内 JS 的 XHR 回调
- **端口冲突**：`Stop-Process -Force` 后 OS 可能保留端口 TIME_WAIT 状态，CEF 端 XHR 连接失败（表现为"JS未执行"超时）
- **推荐**：使用动态端口 `19100 + os.getpid() % 900`，避免固定端口冲突
- **XHR 不能设 `Content-Type: application/json`**：会触发 CORS preflight 被 CEF 页面拦截。正确做法是 `x.send(JSON.stringify(data))` 不设 header

---

## 能力一览

| 能力 | 实现 | 状态 |
|------|------|------|
| 发送文本消息（单聊/群聊） | daemon `/send` | ✅ 生产可用 |
| 发送图片消息（本地文件） | daemon `/send-image` 或 Channel `sendImage` (upload→mediaId) | ✅ 两种方式均可用 |
| 发送富文本消息 | JSAPI `sendRichTextMsg` | ✅ 已验证（ct=3100） |
| 发送文件消息 | Channel `sendFile` (upload→sampleFile) | ✅ 已验证（txt/png 均可） |
| 发送链接卡片 | robot API `sampleLink` | ✅ 已验证 |
| 发送操作卡片 | robot API `sampleActionCard` | ✅ 已验证 |
| 实时消息监听（收发双向） | daemon Monitor 脚本 | ✅ 生产可用 |
| 历史消息获取 | daemon `/fetch` (JSAPI) | ✅ 生产可用 |
| 联系人/CID 查询 | daemon `/contacts` | ✅ 生产可用 |
| 消息日志搜索 | daemon `/search` | ✅ 生产可用 |
| 日报/周报/月报提取 | Monitor (ct=300) + daemon `/fetch_reports` | ✅ 生产可用（需配置 `report_cid`） |
| 执行任意 JS（探测用） | daemon `/exec_js` | ✅ 可用 |
| Windows 桌面通知 | winotify | ✅ 生产可用 |
| 消息日志持久化 | JSONL | ✅ 生产可用 |

**所有能力均通过常驻 daemon（端口 19200）的单一 Frida session 提供，无需反复 attach。**

---

## 0. CID 发现（前置步骤）

发送消息和拉取历史都需要 CID，但钉钉没有提供直接的 CID 查询接口。

### 获取方式（按优先级）

| 方式 | 说明 |
|------|------|
| `dingtalk_find_conversation` 工具 | 调 daemon `GET /contacts?name=`：**显示姓名精确匹配** ContactsDB + `contacts.json`；**不**扫消息日志；多条同名会话返回歧义 |
| 联系人库 `contacts.json` | `data/dingtalk/contacts.json`，daemon 持续维护，每收到消息自动记录新联系人，含完整 CID 列表 |
| 实时监听捕获 | daemon 消息监听器自动记录 CID 到 `data/dingtalk/_msg_log.jsonl` |
| 手动拼接（单聊） | `UID_A:UID_B`，顺序不固定，以 `contacts.json` 实际存储的为准 |

**按姓名发消息（`/send`）或按姓名拉历史（`/fetch`）**：只用「联系人库 ContactsDB + 静态 `contacts.json`」，且 **显示姓名须 strip 后完全一致**；**不按 CID/UID 子串匹配**；**不会**扫 `_msg_log.jsonl`。若同一姓名对应多条会话 → HTTP 409 / MCP 报错，须改用 `cid`。

### 联系人库 (`data/dingtalk/contacts.json`)

daemon 运行时**自动维护**，每收到一条消息会：
1. 检查该 CID 是否已在库中
2. 新联系人 → 从已有 contacts.json 条目解析 UID→姓名 → 写入
3. 已有联系人 → 更新 `last_seen` 和 `msg_count`

**单聊 CID 存储**：`contacts.json` 的 p2p 字典键直接使用钉钉原始 CID，不做任何规范化。UID 顺序不固定（大多数 `己方:对方`，少数 `对方:己方`）。首次加载时会检测并合并互反键（同一会话出现两种顺序时保留 msg_count 更高的）。查找时自动检查两种顺序。

**结构（私聊/群聊分开存储）：**

```json
{
  "p2p": {
    "YOUR_UID:PEER_UID": {
      "cid": "YOUR_UID:PEER_UID",
      "uid": "PEER_UID",
      "name": "张三",
      "first_seen": "2026-03-10 09:00:00",
      "last_seen": "2026-03-10 18:00:00",
      "msg_count": 15,
      "name_resolved": true
    }
  },
  "group": {
    "324215852": {
      "cid": "324215852",
      "name": "示例群名",
      "first_seen": "2026-02-26 16:17:23",
      "last_seen": "2026-03-11 14:59:00",
      "msg_count": 8,
      "name_resolved": true,
      "member_count": 304,
      "owner_id": "7312401",
      "conv_type": 2
    }
  }
}
```

| 字段 | 范围 | 说明 |
|------|------|------|
| `cid` | 两者 | 会话 ID（钉钉原始值，直接用于 API 调用） |
| `uid` | p2p | 对方 UID |
| `name` | 两者 | 联系人姓名 / 群名 |
| `first_seen` / `last_seen` | 两者 | 首次/最后出现时间 |
| `msg_count` | 两者 | 已记录消息数 |
| `name_resolved` | 两者 | 是否已解析名称 |
| `member_count` | group | 群成员数（通过 conv_info 获取） |
| `owner_id` | group | 群主 UID |
| `conv_type` | group | 会话类型（2=普通群） |

查询 API：`GET http://127.0.0.1:19200/contacts` 列出所有，`?name=张三` 按名搜索。

### 推荐工作流

**直接用姓名操作**——`/send` 和 `/fetch` 端点均支持 `name` 参数，自动解析 CID：
- 发消息：`POST /send {name: "张三", message: "你好"}`
- 拉历史：`POST /fetch {name: "张三", count: 20}`
- MCP 工具 `dingtalk_send_message` 和 `dingtalk_fetch_history` 也支持 `name` 参数

不需要先查 CID 再操作，一步到位。

### 日志格式 (`_msg_log.jsonl`)

每行一条 JSON：
```json
{"time": "17:06:14", "cid": "YOUR_UID:PEER_UID", "sender": "发送者姓名", "text": "...", "direction": "→ 发送", ...}
```

搜索时关注 `sender` 字段（发送消息有昵称）和 `cid` 字段（接收消息 sender 是 UID）。

---

## 1. 发送消息

### 调用方式

```bash
# 通过 daemon HTTP API（推荐）
curl.exe -X POST http://127.0.0.1:19200/send -d '{"name":"张三","message":"你好"}'
curl.exe -X POST http://127.0.0.1:19200/send -d '{"cid":"<GROUP_CID>","message":"群消息"}'
```

### CID 格式

| 类型 | 格式 | 示例 |
|------|------|------|
| 单聊 | `UID_A:UID_B`（顺序不固定，以 `contacts.json` 存储的为准） | `YOUR_UID:PEER_UID` 或 `PEER_UID:YOUR_UID` |
| 群聊 | 纯数字 | `63536915431` |

### 技术原理

Frida 附加主进程 → 通过 `libcef.dll` 在 Browser 1 (`advancedSearch.html`) 注入 JS → 调用 `dingtalk.message.sendTextMsg(cid, text, '', callback)` → HTTP Beacon 回收结果。

### 约束

- 钉钉**必须在前台或托盘运行**（最小化时可能无 Renderer，无法注入 JS）
- 非 ASCII 字符需 `\uXXXX` 转义（脚本已内置处理）
- 不需要先打开会话，任意 CID 可直接发送

### 1.2 发送图片

```bash
# daemon HTTP API
curl -X POST http://127.0.0.1:19200/send-image \
  -d '{"cid":"<GROUP_CID>","file_path":"/path/to/image.png"}'
# 支持 name 代替 cid（自动解析联系人库）
```

**技术原理**：调用 `dingtalk.message.sendLocalImage(cid, filePath, callback)` JSAPI，以当前用户身份发送本地图片文件。callback 返回 null（正常行为，通过 beacon 的 'sent' 信号判断成功）。

**约束**：
- 文件必须是本地存在的图片文件（支持 png/jpg/webp 等常见格式）
- 路径支持正斜杠和反斜杠
- 发送后钉钉自动复制到 `ImageFiles/{orgId}/{ts13}_{filename}.ext`

### 1.3 发送富文本消息

```bash
# 通过 exec_js 或封装为 daemon 端点
# sendRichTextMsg(cid, payload_string, '', callback)
```

**技术原理**：调用 `dingtalk.message.sendRichTextMsg(cid, payload, '', callback)` JSAPI，发送 ct=3100 富文本消息。payload 是字符串，直接写入 `attachments[0].extension.payload`。

**payload 格式**（与 ct=3100 接收消息的 payload 一致）：
```json
{"items": [{"type": "rt", "value": {"textRuns": [{"text": "内容"}]}}]}
```

**约束**：
- callback 返回 null（正常行为）
- payload 直接作为字符串存储，不做服务端解析
- 不能通过此方式发送文件（只是文本/引用的组合）

### 1.4 发送自定义消息（消息信封）

`sendCustomMessage(cid, contentType, extensionJson, callback)` 可以创建任意 contentType 的消息信封：
- contentType 为整数（如 502）
- extensionJson 为 JSON 字符串
- **不会触发文件上传**——即使指定了 ct=502，文件内容为空（f_size=0, filePath=""）
- 仅适用于创建纯协议层消息，不适合实际文件发送

### 1.5 文件发送能力总结（2026-03-27 验证）

**机器人 API 路径（已验证可用）：**
1. `POST oapi.dingtalk.com/media/upload?type=file` → 获得 `media_id`
2. `sampleFile` + `{"mediaId": "<media_id>", "fileName": "name.ext", "fileType": "ext"}` → 以文件附件发送
3. DingTalk Channel `sendFile(chatId, filePath)` 封装了完整流程

**JSAPI 路径（不可用）：**

| 消息类型 | contentType | JSAPI 方法 | 能否发送 | 说明 |
|----------|-------------|------------|----------|------|
| 文本 | 1 | `sendTextMsg(cid, text, '', cb)` | ✅ | 生产可用 |
| 图片 | 203 | `sendLocalImage(cid, path, cb)` | ✅ | 仅限图片格式（.txt → code 51 fail） |
| 富文本 | 3100 | `sendRichTextMsg(cid, payload, '', cb)` | ✅ | 文本+引用，不含文件 |
| 普通文件 | 502 | 无可用 JSAPI | ❌ | 需要 native C++ 路径 |
| 大文件 | 501 | 无可用 JSAPI | ❌ | 需要 native C++ 路径 |
| 文件夹 | 503 | 无可用 JSAPI | ❌ | 需要 native C++ 路径 |

**文件发送（ct=501/502/503）不可用的原因**：
- `sendLinkFile` → 所有参数组合均返回 "invalid args"，推测仅用于钉盘链接文件引用
- `sendCustomMessage` → 可创建消息信封但不触发文件上传
- `cspace.batchUploadImFile` → "invalid arguments"（参数格式未知）
- `net.uploadfile` / `util.uploadFile` → "Invalid function parameters" / "arguments invalid"
- `sendLocalImage` → 校验文件格式，非图片返回 code 51

**真实文件消息结构**（来自 UI 手动发送）：
```json
{
  "contentType": 502,
  "attachments": [{
    "extension": {
      "appId": "1289", "cid": "<cid>",
      "f_id": "<server_file_id>", "f_name": "file.txt",
      "f_size": "1404", "f_type": "txt",
      "isEncrypt": "1", "oid": "<org_id>",
      "path": "C:/original/path.txt",
      "s_id": "<space_id>",
      "sp_dentrySpaceType": "imSingle", "type": "file"
    },
    "filePath": "C:/local/cache/path.txt"
  }]
}
```

文件发送的 native 流程：本地文件 → 上传到钉盘（获得 f_id + s_id）→ 创建 ct=501/502 消息。JSAPI 不暴露此流程。

**解决方案**：通过机器人 API 路径（上文）发送文件，绕过 JSAPI 限制。以机器人身份发送，非用户身份。

### 1.6 消息发送 JSAPI 完整清单

| API | 命名空间 | 参数 | 状态 |
|-----|----------|------|------|
| `sendTextMsg(cid, text, '', cb)` | dingtalk.message | 文本消息 | ✅ 生产可用 |
| `sendLocalImage(cid, filePath, cb)` | dingtalk.message | 图片消息 | ✅ 生产可用 |
| `sendRichTextMsg(cid, payload, '', cb)` | dingtalk.message | 富文本 ct=3100 | ✅ 已验证 |
| `sendCustomMessage(cid, ct, ext, cb)` | dingtalk.message | 自定义消息信封 | ⚠️ 不触发文件上传 |
| `sendLinkFile(cid, ?, ?, ?, cb)` | dingtalk.message | 钉盘链接文件 | ❌ 所有参数组合返回 306 "invalid args"（含 mediaId/spaceId/对象格式，2026-03-27 复测） |
| `sendCodeMessage(cid, ?, ?, ?, cb)` | dingtalk.message | 代码消息 | ❌ 参数未知 |
| `sendSystemLink(cid, ?, cb)` | dingtalk.message | 系统链接 | 未测试 |
| `shareImageToChatWithMediaId` | dingtalk.message | 3+ 参数 | 未测试 |
| `uploadLocalImage(filePath, cb)` | dingtalk.richText | 上传图片 | ⚠️ callback 返回 null |
| `uploadLocalImageV2` | dingtalk.richText | 未探索 | 未测试 |
| `getImageLocalURL(mediaId, cb)` | dingtalk.richText | 获取本地 URL | 未测试 |

### 1.7 文件相关 JSAPI 命名空间

| 命名空间 | 方法数 | 关键方法 | 状态 |
|----------|--------|----------|------|
| `dingtalk.cspace` | 13 | batchUploadImFile, uploadFiles, getLocalFilePath | ❌ 参数格式未知 |
| `dingtalk.net` | 10 | uploadfile, upload, downloadfile | ❌ "Invalid function parameters" |
| `dingtalk.util` | 60+ | uploadFile, chooseFile | ❌ "arguments invalid" |
| `dingtalk.download` | 4 | batchDownloadImFile, createTask | 未深入 |
| `dingtalk.fileTask` | 7 | findTask, listAllTask | 下载任务管理 |
| `dingtalk.fs` | 6 | openFileDialog, openSaveDialog | 仅 UI 对话框 |
| `dingtalk.screenshot` | 1 | captureAsMediaId | 截图转 mediaId |

### 1.8 钉钉机器人 API 图片/文件发送（服务端）

**图片消息** — `sampleImageMsg`，`photoURL` 字段同时支持公网 URL 和 media_id：

```json
{ "msgKey": "sampleImageMsg", "msgParam": "{\"photoURL\":\"https://example.com/image.png\"}" }
{ "msgKey": "sampleImageMsg", "msgParam": "{\"photoURL\":\"@lALPM2ymzteDwSUqzIE\"}" }
```

> media_id 通过 `oapi/media/upload?type=image` 获取，格式为 `@lAL...`。
> 2026-03-27 之前的错误：把 media_id 放到了 `{"mediaId":"..."}` 字段（错误字段名），导致图片渲染为损坏占位符。正确做法是放到 `{"photoURL":"..."}` 字段。

**本地图片发送流程**：
1. Channel `sendImage(chatId, filePath)` — upload → media_id → sampleImageMsg + photoURL（内联图片）
2. JSAPI `sendLocalImage(cid, filePath, cb)` — 桌面端直接发送，需内部 CID（daemon `/send-image`）

**文件消息** — `sampleFile`：
1. `POST oapi.dingtalk.com/media/upload?access_token=<token>&type=file` 上传 → 获得 `media_id`
2. `sampleFile` + `{"mediaId": "<media_id>", "fileName": "name.ext", "fileType": "ext"}` 发送

**链接卡片** — `sampleLink`：`{"title": "...", "text": "...", "messageUrl": "...", "picUrl": "..."}`（2026-03-27 验证通过）

**操作卡片** — `sampleActionCard`：`{"title": "...", "text": "markdown", "singleTitle": "按钮文字", "singleURL": "..."}`（2026-03-27 验证通过）

**音频/视频** — `sampleAudio` / `sampleVideo`：未测试（需音视频素材），参数见 dingtalk-api SKILL.md

DingTalk Channel 已内置 `sendImage(chatId, source)` 和 `sendFile(chatId, filePath)`。
Router 层支持 `[图片: path]` 和 `[文件: path]` 语法，agent 回复中包含这些标签会自动发送。
`sendImage` 公网 URL 和本地文件均走 `sampleImageMsg`（本地文件先 upload 获取 media_id）。

---

## 2. 实时消息监听（v4）

### 启动

```bash
python _msg_monitor.py
```

常驻运行，输出 JSONL 日志。

### 架构

```
接收: OnRecvRequest Hook → queue.Queue → worker 线程 → listMessage JSAPI → Beacon HTTP 回调
发送: ProcessRequest Hook → 直接提取 origin_text
```

单 script（hooks + CEF 合一）。接收消息统一通过 `listMessage` JSAPI 获取解密明文，解决手机端消息缺少 `origin_text` 的问题。

### 发出的消息结构（扁平，直接从 Hook 提取）

| 字段 | 路径 | 说明 |
|------|------|------|
| 会话 ID | `[2]` | CID |
| 内容类型 | `[5][1]` | contentType |
| **明文** | `[7]["origin_text"]` | 发送的文本 |
| 发送者昵称 | `[8]` | 如 "发送者昵称" |

### 会话类型判断

- CID 含 `:` 且不以 `cid` 开头 → **单聊**
- 否则 → **群聊**

### contentType 速查

| 值 | 类型 | 有文本 |
|----|------|--------|
| 1 | 文本 | ✅ |
| 101 | 图文 | ✅ |
| 203 | 图片 | ✅ 本地缓存 |
| 300 | 工作汇报 | ✅ b_form |
| 302 | 语音 | ❌ |
| 305 | 视频 | ❌ |
| 1200 | Markdown | ✅ |
| 2001 | 文件 | ✅ |
| 2950 | 互动卡片 | ✅ |
| 3100 | 富文本/@ | ✅ |

### 去重

- Hook 层: `(cid, msg_id, timestamp)` 三元组
- 显示层: `displayed_msg_ids` 集合
- 发送: `(cid, text[:50])` 二元组
- `OrderedDict` 保持最近 2000 条

---

## 3. 历史消息获取（⭐ 推荐：JSAPI 方案）

### JSAPI 签名

```javascript
dingtalk.message.listMessage(cid, createdAt, count, isForward, options, callback)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| cid | string | 会话 ID |
| createdAt | **string** | 时间戳游标（ms）。**必须是字符串**，传数字报错 130050 |
| count | number | 返回条数，可设 50 |
| isForward | boolean | `false`=向历史方向, `true`=向未来方向 |
| options | object | `{isFirstPull: true/false}` |
| callback | function | `function(err, msgs)` |

### isFirstPull 行为

| isFirstPull | 行为 | cursor |
|-------------|------|--------|
| `true` | 从最新消息开始拉取，**忽略 cursor** | 无效 |
| `false` | **从 cursor 位置翻页**，cursor 必须为字符串 | 生效 |

> `isFirstPull` 仅控制是否使用 cursor 定位，与数据源（本地/远程）无关。

### 调用示例

```javascript
// 获取最近消息（忽略 cursor，从最新开始）
listMessage(cid, String(Number.MAX_SAFE_INTEGER), 50, false, {isFirstPull: true})

// 翻页获取历史消息（从 cursor 位置继续）
listMessage(cid, oldestCreatedAt, 50, false, {isFirstPull: false})

// 跳到特定时间点
listMessage(cid, targetCreatedAt, 50, false, {isFirstPull: false}) // 之前
listMessage(cid, targetCreatedAt, 50, true, {isFirstPull: false})  // 之后
```

### 已知陷阱

- ❌ cursor 为数字 → 报错 130050，**必须是字符串**
- ❌ options 为 0 → 报错 130050，必须是 `{isFirstPull: ...}`
- B1 (advancedSearch.html) 的本地缓存不含 UI 聊天窗口接收的新消息；实时检测用 Hook 而非 JSAPI 轮询

### 返回消息结构（完整字段参考）

每条消息的顶层结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| `baseMessage` | object | 消息本体，所有核心数据 |
| `receiverMessageStatus` | object | `{readStatus: 0\|2}` — 0=未读, 2=已读 |
| `sendStatus` | number | 1=已发送 |
| `senderMessageStatus` | object | `{totalCount: -1, unReadCount: -1}` — 群聊中通常 -1 |

#### baseMessage 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `messageId` | string | 消息唯一 ID |
| `conversationId` | string | 会话 CID |
| `createdAt` | string | 毫秒时间戳（字符串） |
| `content` | object | 消息内容，结构随 contentType 变化，见下方 |
| `extension` | object | 扩展信息，含 `origin_text`、`openConversationId` 等 |
| `senderOpenId` | string | 发送者 UID |
| `type` | number | 会话类型：1=单聊, 5=群聊 |
| `contentVersion` | string | 通常 "0" |
| `creatorType` | number | 1=普通用户, 2=系统 |
| `decryptStatus` | number | 0=已加密, 1=已解密 |
| `isEncrypted` | boolean | 是否加密 |
| `recallStatus` | number | 0=正常, 1=已撤回 |
| `tag` | string | "0"=普通, "1"=含 @ |
| `uuid` | string | 消息 UUID |
| `memberTag` | string | 通常 "-1" |
| `shieldStatus` | number | 屏蔽状态 |
| `localExtension` | object | 本地扩展（通常空） |
| `memberExtension` | object | 成员扩展（通常空） |
| `downloadProgress/Status/TaskId` | string/number | 文件下载相关（文件消息用） |
| `uploadProgress/Status` | string/number | 文件上传相关 |
| `tmpMessageId` | string | 临时消息 ID，通常等于 messageId |

#### content 结构（按 contentType 分类）

**contentType=1（纯文本）**

```json
{
  "contentType": 1,
  "atCustomRoleIds": {},
  "atOpenIds": {"<UID>": "<昵称>"},
  "atMsgStatusList": [{"openId": "<UID>", "status": 1}],
  "textContent": {
    "text": "消息文本内容",
    "templateId": "",
    "templateData": []
  }
}
```

- `atOpenIds`: 被 @ 的人，key=UID, value=昵称
- `atMsgStatusList`: @ 状态，status=1 表示已 @
- `textContent.text`: 消息明文

对应 extension 常见字段：
- `origin_text`: 消息原文
- `openConversationId`: 开放会话 ID
- `oid` / `realmOrgid`: 组织 ID
- `realmFlag`: "1"=企业内
- `sameContentIdentifier`: 内容去重标识
- `sendMsgUUID`: 发送 UUID

**contentType=300（工作汇报/系统卡片）**

```json
{
  "contentType": 300,
  "atCustomRoleIds": {},
  "atOpenIds": {},
  "attachments": [
    {
      "type": 300,
      "extension": {
        "b_tl": "标题文本",
        "b_content": "正文文本",
        "h_tl": "我的HR助手",
        "h_bg": "0xFFBBBBBB",
        "date": "1773229875038",
        "pc_msg_url": "https://...",
        "b_form": [{"k": "章节名", "v": "内容"}]
      },
      "filePath": "",
      "isPreload": false,
      "size": "0",
      "thumbPath": "",
      "url": "https://..."
    }
  ]
}
```

- `attachments[0].extension` 是核心数据载体
- 日报/周报: `b_form` 是表单数组，`b_tl` 是标题（如 "王飞的日报"），`h_tl` 是分类（如 "日志"）
- HR/打卡: `b_content` 是正文，`h_tl` 是来源
- `pc_msg_url`: 浏览器查看链接

对应 extension 常见字段：
- `agg_entrance_id`: 聚合入口 ID
- `openConversationId`: 开放会话 ID
- `systemMsgNPSTag`: "1"=系统消息

**contentType=1202（Markdown 系统消息）**

```json
{
  "contentType": 1202,
  "atCustomRoleIds": {},
  "atOpenIds": {},
  "attachments": [
    {
      "extension": {
        "markdown": "你接受了笛笛的[日程](dingtalk://...)",
        "new_markdown": "你接受了笛笛的[日程](dingtalk://...)"
      }
    }
  ]
}
```

- `markdown` / `new_markdown`: Markdown 格式内容，含钉钉内部链接

对应 extension 常见字段：
- `BIType`: 业务类型（如 "calendar_single_chat_notice"）
- `msgSrcBizId`: 来源（如 "calendar.send.system"）
- `senderSilent`: "1"=静默发送

**contentType=2950（互动卡片）**

```json
{
  "contentType": 2950,
  "atCustomRoleIds": {},
  "atOpenIds": {},
  "attachments": [
    {
      "type": 2950,
      "extension": {
        "cardInstanceId": "<CARD_ID>",
        "interactiveCardLastMessage": "<用户A> 将执行者从 <用户B> 变更为 <用户C>",
        "LastMessageI18n": {"zh_CN": "...", "en_US": "..."},
        "messageCreateTime": "<TIMESTAMP_MS>",
        "miniAppId": "<MINI_APP_ID>",
        "widgetName": "34b300b4-..."
      },
      "filePath": "",
      "isPreload": false,
      "size": "0",
      "thumbPath": "",
      "url": ""
    }
  ]
}
```

- `interactiveCardLastMessage`: 卡片最新操作摘要
- `cardInstanceId`: 卡片实例 ID
- `miniAppId`: 关联小程序 ID

#### 已验证的 contentType 清单

| contentType | 类型 | content 结构 | 文本提取方式 |
|-------------|------|-------------|-------------|
| 1 | 纯文本 | `textContent.text` | `content.textContent.text` 或 `extension.origin_text` |
| 101 | 图文 | textContent + attachments | textContent.text |
| 203 | 图片 | attachments | 无文本 |
| 300 | 工作汇报/系统卡片 | attachments[0].extension | `b_form`(日报) / `b_content`(打卡) |
| 302 | 语音 | attachments | 无文本 |
| 305 | 视频 | attachments | 无文本 |
| 1200 | Markdown/回复 | attachments[0].extension | `extension.title`(回复文本) / `extension.markdown`(完整 Markdown) |
| 1202 | Markdown 系统消息 | attachments | `attachments[0].extension.markdown` |
| 2001 | 文件 | attachments | 文件名 |
| 2950 | 互动卡片 | attachments[0].extension | `interactiveCardLastMessage` |
| 3100 | 富文本/@ | attachments[0].extension.payload | 见下方富文本媒体格式章节 |

### ct=203 纯图片

#### 三层数据结构完整字段（2026-03-30 getAndSaveMessageById 实测验证）

**第一层：contentModel（`baseMessage.content`）**

content 仅有 4 个 key：`atCustomRoleIds`、`atOpenIds`、`attachments`、`contentType`。

```json
{
  "contentType": 203,
  "atCustomRoleIds": {},
  "atOpenIds": {},
  "attachments": [{
    "filePath": "http://loc.dingtalk.com/<sha256_64chars><base64_local_path>?render_height=H&render_orientation=1&render_width=W",
    "url": "",
    "thumbPath": "",
    "isPreload": false,
    "size": "0",
    "type": 0,
    "extension": {
      "appId": "1289",
      "cid": "<CONV_ID>",
      "f_id": "<F_ID>",
      "s_id": "<S_ID>",
      "f_name": "<FILENAME_HASH>.png",
      "f_size": "206796",
      "f_type": "tmp",
      "isEncrypt": "1",
      "oid": "<ORG_ID>",
      "orientation": "0",
      "p_height": "945",
      "p_width": "2241",
      "priority": "0",
      "sp_thumbSize": "0",
      "type": "file"
    }
  }]
}
```

关键：
- `filePath` 是 `loc.dingtalk.com` URL，路径部分 = 64字符 SHA256 hash + base64 编码的本地绝对路径
- base64 解码后格式：`{DingTalkDataDir}\{uid}_v2\ImageFiles\{orgId}\{s_id}_{f_id}_{f_name}`
- **本地文件是已解密的有效 PNG/JPEG**，可直接读取（尽管 `isEncrypted=true`）
- `url` 和 `thumbPath` **始终为空**
- `photoContent` 字段在 JSAPI 返回中始终为 `null`（仅存在于钉钉内部渲染模型中）
- extension 中 **没有** `mediaId`/`src`/`mediaCopyUrl`/`imageUrl`/`downloadCode` 等字段
- `f_id`/`s_id` 是钉盘存储标识

**第二层：baseMessage 完整字段**（getAndSaveMessageById 返回）

| 字段 | 已缓存图片实测值 | 说明 |
|------|------------------|------|
| `downloadStatus` | 0 | |
| `downloadProgress` | "-1" | 字符串类型 |
| `downloadTaskId` | "-1" | |
| `decryptStatus` | 0 | |
| `isEncrypted` | true | 但本地文件实际已解密可读 |
| `uploadStatus` | 0 | |
| `uploadProgress` | "-1" | |
| `contentVersion` | "0" | |
| `localExtension` | `{}` | |
| `memberExtension` | `{"clickInteraction":"{\"clickStatus\":2}"}` | |
| `recallStatus` | — | |
| `shieldStatus` | — | |

**第三层：baseMessage.extension**

| 字段 | 示例值 |
|------|--------|
| `openConversationId` | `cidEWdWxYuzNw6KushaHqsT0w==` |
| `realmFlag` | "1" |
| `realmOrgid` | "<ORG_ID>" |
| `sendMsgUUID` | "VFFCgzI@" |
| `source_from_type` | "1" |
| `sp_picStatus` | "1" |

**`dingtalk.message` 命名空间完整 API 列表**（2026-03-30 实测）：
`UpdateToViewWithBiz`, `addEmotion`, `autoTransformAudioToText`, `autoTranslateMsg`, `batchDeleteMessage`, `batchRecall`, `cancelSendMessage`, `clickInteraction`, `comboCopy`, `comboForwardOneByOne`, `comboForwardTotally`, `comboForwardTotallyV2`, `comboSaveImageFiles`, `copyMessage`, `createClassRoom`, `decryptMessage`, `deleteMessage`, `editAliFile`, `editAnswer`, `editLinkFile`, `editSpaceFileOnline`, `fetchEditHistory`, `finishLaterHandleMsg`, `focusMessage`, `forwardDingPangFile`, `forwardMessage`, `forwardMessageForCopilot`, `getAndSaveMessageById`, `getForwardMids`, `getGuideInfoForMsgBenefit`, `getICBUCardData`, `getImageMessage`, `getImageMessageThumb`, `getImageMsgOCRResult`, `getImgVideoMessage`, `getLinkMessage`, `getMediaStatus`, `getMessageById`, `getPinMsgList`, `getPreviewMessageStatusById`, `getTop1UnreadMessage`, `getTopic`, `getTopicEmotions`, `getTopicReplys`, `ignoreSecurityTip`, `insertKeyValueToLocalExtension`, `insertTextToInput`, `isMessageMediaExpired`, `isReplySupport`, `laterHandlerMsg`, `listComboMsgInfo`, `listMediaMessage`, `listMessage`, `listMultiNestComboMsgInfo`, `listRecommendAnswers`, `listRedEnvelopeMessage`, `loadCardSubMessages`, `localEditSpaceFile`, `localPreview`, `modifyTranslated`, `onlineEditEncryptFile`, `openGeoLocationViewer`, `openGroupRoleListViewer`, `openImageViewer`, `openImageViewerEx`, `openImageViewerWithUrl`, `openLikeEmotionView`, `openLinkFile`, `openLinkFileByDentryLink`, `openLinkFileFolderByDentryLink`, `openMergeCardLink`, `openMessageFile`, `openOnlineDocModifyStatusViewer`, `openReadStatusViewer`, `openRichTextInput`, `openTopicDetail`, `openVideoViewer`, `openVideoViewerWithUrl`, `pinMsg`, `previewAttach`, `previewComboMessage`, `previewFile`, `previewImage`, `quoteDing`, `quoteMessage`, `reEditMessage`, `recallEmotionV2`, `recallMessage`, `recallYunpanMsg`, `recommendAnswerFeedback`, `reeditRecallMessage`, `refetchForbiddenMessageByIds`, `registerMessageEvent`, `replyEmotion`, `replyEmotionV2`, `replyMessage`, `resendMessage`, `saveImageFile`, `scoreTranslatedData`, `sendAnswerDirect`, `sendCodeMessage`, `sendCustomMessage`, `sendLinkFile`, `sendLocalImage`, `sendRichTextMsg`, `sendSystemLink`, `sendTextMsg`, `sendTextMsgByMid`, `sendZan`, `setMsgTopStatus`, `shareImageToChatWithMediaId`, `shieldMessage`, `shieldYunpanMsg`, `showEditHistoryPanel`, `showPinMsgListPanel`, `transformAudioToText`, `translateInputText`, `translateMsg`, `undoTransformAudioToText`, `undoTranslatedMsg`, `updateToRead`, `updateToView`, `updateToViewWithBiz`

#### ct=203 vs ct=3100 图片下载能力对比

| 维度 | ct=203 纯图片 | ct=3100 富文本图片 |
|------|--------------|-------------------|
| 图片标识 | `f_id`+`s_id`（钉盘），无 `mediaId` | `mediaId`（`@<base64>` MsgPack） |
| CDN URL | ❌ 无法构造（没有 mediaId） | ✅ `https://static.dingtalk.com/media/{id}_{w}_{h}.ext` |
| 本地缓存 | ✅ `filePath` → loc.dingtalk.com → base64 解码为本地路径 → 已解密 PNG/JPEG | 无本地路径 |
| 下载方式 | ✅ 本地缓存文件直接读取（需客户端已缓存） | ✅ CDN 直接 HTTP GET，无需认证 |

#### CDN 图片下载机制（2026-03-29 验证可用）

**MediaID 内部结构**（base64 解码后为 MsgPack 数组）：
```
@lQLPJxVLXBuBUT7NAjrNCnSwC-TQHrBokrUEYkp57gAEAA
  → base64 decode → msgpack unpack →
  [version=2, fileId=2816240000960647486, height=570, width=2676, hash=<16 bytes>]
```

**CDN URL 构造**：
```
https://static.dingtalk.com/media/{mediaId_without_@}_{width}_{height}.{format}
```
示例：`https://static.dingtalk.com/media/lQLPJx...AA_2676_570.png` → HTTP 200, 无需认证

**验证结果**：5/5 个 QuickTransFiles 中的 MediaID 均能成功构造 CDN URL 并下载，文件大小与本地一致。

#### QuickTransFiles 元数据结构

位置：`%APPDATA%\DingTalk\{uid}_v2\QuickTransFiles\{md5}_mv2_i0_auth-1.json`

```json
{
  "MediaID": "@lQLPJxVLXB...",           // 公开 MediaID，可构造 CDN URL
  "AuthMediaID": "$iwEcAqNwbmcDAQTR...", // 认证 MediaID
  "FilePath": "C:\\...\\ImageFiles\\{ts}_{guid}.png",
  "ContentMd5": "0daf53f6d1ab2fdb2b45164c96dae71a",
  "DataSize": 2544121,
  "MediaVer": 2,
  "AuthType": -1,
  "UploadStatus": true
}
```

每个已下载的图片都有对应的 QuickTransFiles JSON。文件名格式为 `{md5}_mv2_i0_auth-{n}.json`。

#### ct=203 解决方案（2026-03-30 已验证可用）

**结论**：ct=203 纯图片通过本地缓存路径解析即可获取原图，无需 CDN 下载。

**完整流程**：
1. `listMessage` 返回 ct=203 消息的 `attachments[0].filePath`，格式 `http://loc.dingtalk.com/<sha256_64chars><base64_path>?render_height=H&render_width=W`
2. 提取 URL path 中前 64 字符（SHA256 hash）之后的部分，base64 解码得到本地绝对路径
3. 本地文件格式：`{DingTalkAppData}\ImageFiles\{orgId}\{s_id}_{f_id}_{f_name}`
4. 文件是已解密的有效 PNG/JPEG，可直接读取（尽管 `isEncrypted=true`、`decryptStatus=0`）

**关键发现**：
- `photoContent` 字段在 `listMessage`、`getAndSaveMessageById` 的 JSAPI 返回中始终为 `null`——它仅存在于钉钉内部 JS 层的消息渲染模型中（通过内存扫描发现注释引用 `baseMessage.content.photoContent.height/filePath/width`）
- `getImageMessage(cid, msgId)` 调用返回错误对象 `[object Object]`，不可用
- `mid2Url` 不在 `dingtalk.message` 命名空间暴露，是内部 webpack 模块 439055 的函数
- ct=203 没有 `mediaId`、`downloadCode`、`mediaCopyUrl` 等字段，无法构造 CDN URL
- **时序限制**：图片需要钉钉客户端异步下载到本地缓存（通常 10-15s），push 到达后立即检查文件可能不存在

**daemon 实现**：已在 `_format_jsapi_messages` 中完整支持，通过 `_resolve_image_local_path()` 解析 `loc.dingtalk.com` URL → base64 解码 → 本地路径 → 文件存在性检查。经实测 4 条 ct=203 消息全部成功解析。

**图片等待机制**（2026-03-30）：`EventDispatcher` 对 ct=203 消息使用动态 debounce：
- 普通消息 debounce 3s，ct=203 图片消息 debounce 15s
- debounce 到期后 `_process_cid` 检查 `image_local_path` 是否存在
- 不存在 → 重新入队再等 15s，直到文件就绪
- 超过 3 分钟 → 放弃等待，推送到 Gateway（agent 看不到图片）
- 不阻塞 daemon：整个过程在后台 loop 线程中异步执行

**内存扫描探索记录**（2026-03-30）：

通过 Frida 扫描钉钉进程内存中的 JS 源码（过滤掉 daemon 自身注入代码），发现：
- 钉钉 webpack 模块 148616 注册 `dingtalk.message.getImageMessage`、`getImgVideoMessage`、`mid2Url` 三个 JSAPI
- 消息渲染层使用 `e.content.contentType === V.IMG` 判断图片类型
- 内部注释确认 `photoContent` 结构：`baseMessage.content.photoContent.{height,filePath,width}`
- 但该字段只在内部处理后填充，JSAPI 层不暴露

#### 已验证不可行的 ct=203 远程下载路径

| 方案 | 结果 | 原因 |
|------|------|------|
| Storage API (`/v1.0/storage/spaces/{s_id}/dentries/{f_id}/...`) | 403 | `orgAuthLevelNotEnough`，应用权限不够 |
| JSAPI `download.createTask` | 弹确认框 | 难以自动化，**已搁置** |
| CEF JS 执行（vtable/gesture test/cef_post_task） | ❌ 全部失败 | 见下方 CEF 章节 |
| libcurl/WinHTTP hook | 无流量 | DingTalk 8.3.0 使用 Chromium 内置网络栈 |

#### CEF JavaScript 执行探索记录（2026-03-29）

**背景**：尝试通过 Frida 在钉钉 CEF 浏览器中执行 JavaScript，以获取 ct=203 图片数据。

**CEF C API struct 偏移量分析**（基于 `cef_browser_host_get_browser_by_identifier` 返回的 `cef_browser_t*`）：

`cef_browser_t`：
- offset 152: `get_main_frame`（browser 1 返回 null）
- offset 160: `get_focused_frame`（browser 1 有效）

`cef_frame_t`（基于 `get_url` 在 offset 200 的探测结果反推）：
- offset 136: `load_url`（触发 breakpoint）
- offset 144: `load_string`
- offset 152: `execute_java_script`（调用成功但无效果）
- offset 200: `get_url`（✅ 正常工作）

**测试的方法及结果**：
| 方法 | 结果 |
|------|------|
| C struct `execute_java_script` (offset 152) | 调用返回 ok，无实际效果（可能需 UI 线程） |
| `cef_execute_java_script_with_user_gesture_for_tests` | 调用后读 URL 触发 breakpoint，但 beacon 未收到 |
| `cef_post_task(TID_UI, task)` | posted=1 但回调未执行 |
| `load_url` (offset 136/144) | 136 触发 breakpoint，144 无效果 |
| Image/fetch/XHR/sendBeacon 到本地 HTTP 服务器 | 0 个 beacon 收到（app:// 协议阻断网络） |

**结论**：CEF JS 执行在当前版本下不可行，`app://` 协议页面完全阻断外部网络请求。

#### gaea RPC getDownloadInfo（2026-03-29 内存扫描发现）

**关键发现 — 真实下载 URL 格式**：
```
https://space.dingtalk.com/auth/download?spaceId={s_id}&path={f_id}
```

**gaea RPC 函数路径**：
- `/r/Adaptor/DingTalkCollabNeedleI/getDownloadInfo`
- `/r/Adaptor/DingTalkCollabNeedleI/listDownloadResource`

**getDownloadInfo 返回结构**（内存字段名推断）：
```
headerSignatureInfo: { resourceUrl, headerSignatureExpiration, headers }
stsSignatureInfo: { accessKeyId, accessKeySecret, accessToken, bucket, endPoint }
ossUrlPreSignatureInfo / cdnUrlPreSignatureInfo
```

**状态**：未验证。如果 CDN MediaID 路径走通，此 RPC 路径可能不需要。

### ct=1200 Markdown/回复消息

实际数据在 `attachments[0].extension` 下：
- `title`: 回复内容纯文本
- `markdown`: 完整 Markdown，格式为：
  ```
  > ###### 发送者昵称
  > 被引用的原文
  ---
  #### 回复内容
  ```

### ct=3100 富文本媒体格式

实际数据**不在** `textContent.text`（通常为空），而在 `attachments[0].extension` 下，有两个版本并存：

**payload (v0.1)**
```json
{
  "version": "0.1",
  "items": [
    {"type": "rt", "value": {"textRuns": [{"text": "文字内容"}, ...]}},
    {"type": "img", "value": {"src": "mediaId://@<base64>", "width": 667, "height": 212, "size": "small"}}
  ]
}
```

**payloadV2 (v1.2)**
```json
{
  "contents": [{
    "type": "markdown",
    "text": {
      "version": "1.2",
      "items": [
        {"type": "text", "data": {"text": "文字内容"}, "style": {}},
        {"type": "image", "data": {"authMediaId": "$<base64>", "url": "@<base64>"}, "style": {"width": 667, "height": 212, "mode": 1}},
        {"type": "newLine", "data": {}, "style": {}}
      ]
    }
  }]
}
```

另有 `extension.desc` 字段包含纯文字描述（不含图片）。

### 图片标识编码格式（MsgPack）

**mediaId** — `@` 前缀，base64url 编码，MsgPack **数组**

解码: `base64url_decode(value[1:])` → `msgpack.unpackb()`

| 索引 | 类型 | 含义 | 示例 |
|------|------|------|------|
| [0] | int | 类型标记 | 固定 2 |
| [1] | int64 | 文件 ID | 3016782000724125477 |
| [2] | int | 高度 | 60 |
| [3] | int | 宽度 | 2350 |
| [4] | bytes(16) | 文件哈希 | be4d81dffa55178c... |

出现位置：payload items `value.src`（含 `mediaId://` 前缀），payloadV2 items `data.url`

**authMediaId** — `$` 前缀，base64url 编码，MsgPack **map**（整数键）

解码: `base64url_decode(value[1:])` → `msgpack.unpackb(strict_map_key=False)`

| 键 | 类型 | 含义 | 示例 |
|----|------|------|------|
| 1 | int | 未知（变化） | 28, 29, 30 |
| 2 | bytes(3) | 图片格式 | "png" |
| 3 | int | 未知（固定 1） | 1 |
| 4 | int | 宽度 | 2350 |
| 5 | int | 高度 | 60 |
| 6 | bytes(16) | 文件哈希（= mediaId[4]） | be4d81dffa55178c... |
| 7 | int | 发送者 UID | `<SENDER_UID>` |
| 8 | int | 未知（固定 0） | 0 |
| 9 | bytes(2) | 域/范围 | "im" |
| 10 | int | 未知（固定 0） | 0 |
| 11 | int | 未知（变化） | 10894, 52775 |

出现位置：payloadV2 items `data.authMediaId`

authMediaId 包含 mediaId 的所有关键信息（hash/宽高）加额外信息（格式/发送者/域），两者通过 key 6 的哈希关联。

**base64url 解码注意事项**：
- 替换 `-` → `+`，`_` → `/`
- 补齐 `=` padding（长度需 4 的倍数）
- Python: `msgpack.unpackb()` 对 authMediaId 需要 `strict_map_key=False`（整数键 map）

### 本地文件缓存结构

根目录: `%APPDATA%\DingTalk\<YOUR_UID>_v2\`。

ct=203 纯图片的 `loc.dingtalk.com` URL 中 base64 部分解码后即为完整绝对路径，可直接验证。

**数据库加密**：所有本地 SQLite 数据库（`dingtalk.db`、`sync.sqlite`、`content_manager.sqlite` 等）均使用 SQLCipher 加密，无法直接读取。

**Cookies 数据库**（`%LOCALAPPDATA%\DingTalk\Cookies`）可读，包含 `.space.dingtalk.com`、`.alidocs.dingtalk.com` 等域的 cookie。

**网络栈**：DingTalk 8.3.0 使用 Chromium 内置网络栈（libcef.dll 239MB），不经过 libcurl.dll/WinHTTP/WinINet。Hook 这些库无法捕获浏览器发起的 HTTP 请求。

#### ImageFiles/

| 子目录 | 文件命名 | 来源 |
|--------|----------|------|
| `{orgId}/` | `{senderId}_{fileId}_{name}.ext` | ct=203 收到的原图 |
| `{orgId}/` | `{senderId}_{fileId}.webp` | ct=203 缩略图 |
| 根目录 | `{timestamp13}_{guid}.png` | 截图/粘贴板发送 |
| 根目录 | `{ts13}{senderId}_{fileId}_{guid}.ext` | 转发/合并消息 |
| `{hex}/` | `{mediaId_no@}_{w}_{h}.ext_60x60q90.ext` | 头像/缩略图缓存 |

验证示例:
```
ImageFiles\<orgId>\<senderId>_<fileId>_<name_hash>.png
           ↑orgId  ↑senderId  ↑fileId  ↑name(hash)  ↑ext
```

#### resource_cache/

| 子目录 | 文件命名 | 来源 |
|--------|----------|------|
| `{xx}/` | `{不可推导hash}.ext` | ct=3100 富文本内嵌图片 |

富文本图片的 mediaId hash（16 字节）无法直接推导出 resource_cache 中的文件名，两者之间的映射关系尚未逆向。

#### wukong/file_cache/upload/

| 文件命名 | 说明 |
|----------|------|
| `{hash}_mv2_auth-1_bizim.conf` | 上传记录，JSON 格式，包含 mediaId↔本地路径映射 |

#### QuickTransFiles/{ContentMd5}/

| 文件命名 | 说明 |
|----------|------|
| `{mediaId_no@}_mv2_i0_auth-1.json` | 图片传输映射，含 MediaID→FilePath+AuthMediaID+Md5HashKey+DataSize |

> **注意**: DingTalk 7.x+ 不再在本地持久化新图片到 ImageFiles，历史文件仍在但无新写入（2023 年后）。
> QuickTransFiles 同理，77 个 JSON 文件全部指向 2023 年旧路径。图片可能改为内存缓存或按需从 CDN 拉取。

#### mediaId hash 性质

mediaId[4] 的 16 字节 hash 不是文件内容 MD5，而是钉钉服务端的文件标识符（与 authMediaId[6] 一致）。
末字节恒为 0x00，中间有 0x04xx 模式，像是带元信息的存储 key。
该 hash 可关联同一图片的 mediaId 和 authMediaId，但无法直接用于定位本地缓存文件。

#### libgaea.dll MediaIdManager（逆向参考）

`gaea::media::MediaIdManager` 类负责 mediaId↔CDN URL 转换，关键 export：

| 函数 | 用途 |
|------|------|
| `TransferToImageUrl(mediaId, ImageSize, ...)` | mediaId → CDN 图片 URL（支持不同尺寸） |
| `TransferToCommonFileUrl(mediaId, ...)` | mediaId → CDN 文件 URL |
| `TransferToObject(mediaId, ...)` | mediaId → 内部对象 |
| `SetHost(HostType, url)` | 设置 CDN 域名 |
| `IsV1MediaId(mediaId)` / `IsV2MediaId(mediaId)` | 判断 mediaId 版本 |
| `GetUrlConstantPart(...)` | 获取 URL 固定部分 |
| `FilterMediaIdDomain(...)` | 过滤域名 |

实际无需调用原生函数——可直接通过下方 CDN URL 规则构建下载链接。

### 图片 CDN URL 构建（✅ 已验证）

钉钉图片存储在阿里云 OSS CDN 上，**公网可访问、无需认证**。

**URL 格式:**
```
https://static.dingtalk.com/media/{mediaId_去掉@前缀}_{宽}_{高}.{格式}
```

**构建规则:**

| 要素 | 说明 | 示例 |
|------|------|------|
| 去前缀 | 去掉 `@` 前缀（V1 的 `lAD` 无前缀则原样） | `@lQLPKd3D...` → `lQLPKd3D...` |
| 宽高 | **必须精确匹配**原始 MsgPack 中的值，不可修改 | `_2350_60` |
| 格式 | 必须与实际格式一致（可从 authMediaId key 2 获取） | `.png` / `.jpg` |

**适用范围:**

| mediaId 版本 | 前缀 | CDN 可用 |
|-------------|------|---------|
| V1 | `lAD` / `lAL` | ✅ `static.dingtalk.com/media/{id}_{w}_{h}.{ext}` |
| V2 | `@lQL` | ✅ 去掉 `@` 后同上 |

**OSS 图片处理（缩略图等）:**

原始 URL 后追加 `?x-oss-process=image/...` 参数即可实时处理：

```
# 按宽度等比缩放
?x-oss-process=image/resize,w_120

# 填充裁切到指定尺寸
?x-oss-process=image/resize,m_fill,w_120,h_120

# 获取图片元信息（JSON）
?x-oss-process=image/info

# 按宽度等比放大（不超过原图）
?x-oss-process=image/resize,w_600
```

**从 ct=3100 富文本消息构建 URL 的完整流程:**

1. 取 `payload.items` 中 `type=img` 的 `value.src`（格式 `mediaId://@lQL...`）
2. 去掉 `mediaId://` 前缀和 `@` 前缀 → `lQL...`
3. MsgPack 解码获取 `[type, fileId, height, width, hash]`
4. 从对应的 `payloadV2` 的 `authMediaId` 解码获取格式（key 2）
5. 拼接: `https://static.dingtalk.com/media/{lQL...}_{width}_{height}.{format}`

> **注意**: 宽高维度必须从 MsgPack 解码获取，URL 中的维度不可随意指定，否则 404。
> 如需缩略图请保持 URL 中的原始维度，通过 `?x-oss-process` 参数调整。

### daemon API（推荐）

```bash
# 通过 CID
curl -X POST http://127.0.0.1:19200/fetch -d '{"cid":"YOUR_UID:PEER_UID","count":20}'

# 通过姓名（自动解析 CID）
curl -X POST http://127.0.0.1:19200/fetch -d '{"name":"张三","count":20}'
```

历史消息获取通过 JSAPI (dingtalk.message.listMessage) 实现，复用常驻 Frida CEF session。

---

## 4. 日报/周报/月报提取

> 需要在 `config.json` 中配置 `report_cid`（工作汇报会话 CID）才能使用 `/fetch_reports` 端点。
> 通过 Monitor 实时监听不需要配置。

监听消息时自动识别 `contentType=300` 的工作汇报推送。

### 识别条件

| 条件 | 字段 | 值 |
|------|------|-----|
| contentType | `co[1]` | `300` |
| sender | `md[24]` | `"工作汇报(日志)"` |
| ext 标记 | `ext.lippiReport` | `"lippi_report_im_send"` |

### 内容提取

```python
co = md[7]                          # content object
cards = co[7]                       # 卡片数组
body = cards[0][6]                  # 卡片正文

report_content = body['b_form']     # [{"k": "章节名", "v": "内容"}, ...]
title = body['b_tl']                # "王飞的日报"
category = body['h_tl']            # "日志"/"日报"/"周报"/"月报"
url = body['pc_msg_url']           # 浏览器查看链接

ext = md[9]
report_id = ext['reportId']
corp_id = ext['corpId']
creator_id = ext['creatorId']
```

### 批量拉取工作汇报

daemon 提供 `/fetch_reports` 端点，从配置的 `report_cid` 会话分页拉取 ct=300 消息，支持按作者、日期范围、汇报类型过滤。

### 拉取"我的报"（ct=2950 互动卡片）

daemon 提供 `/fetch_my_reports` 端点，从配置的 `my_report_group_cid` 群拉取自己提交的汇报卡片（ct=2950），可选通过 CEF 加载卡片页面提取完整内容。

**实现思路**：
1. 钉钉的"我的报"群会收到每次提交日报/周报的互动卡片消息
2. 卡片的 `extension.biz_custom_action_url` 包含报告详情页 URL
3. 用 `fetch_report_content` 在 CEF 中加载该 URL，通过 CSS 选择器或自定义 JS 提取正文

> 这两个端点需要在 `config.json` 中配置对应 CID，未配置时返回错误。

---

## 5. 会话信息获取 (conv_info)

通过 `getBaseConversation` JSAPI 获取会话元数据。

```bash
curl -X POST http://127.0.0.1:19200/conv_info -d '{"cid":"324215852"}'
```

返回：
```json
{
  "success": true,
  "cid": "324215852",
  "name": "示例群名",
  "data": {
    "title": "示例群名",
    "memberCount": 304,
    "type": 2,
    "ownerId": "7312401"
  }
}
```

| data 字段 | 说明 |
|-----------|------|
| `title` / `name` | 群名（单聊返回对方昵称） |
| `memberCount` | 成员数 |
| `type` | 会话类型（2=普通群） |
| `ownerId` | 群主 UID |

注意：每次调用约 2-3 秒，批量查询建议间隔 0.2s+。

---

## 5A. 消息接收——图片与文件下载

系统有**两条完全不同的消息接收路径**，各自面对不同的数据结构和下载方式。

### 两条接收通道对比

| | 通道 1：机器人 Webhook（Gateway/Node.js） | 通道 2：Daemon（Frida 注入桌面端） |
|---|---|---|
| 触发场景 | 用户**通过机器人对话**发消息（私聊机器人、群里@机器人） | 桌面端收到**任意聊天消息**（含非机器人会话） |
| 入口代码 | `src/channels/dingtalk/index.ts` → `_handleRobotMessage` | `skills/dingtalk-desktop/daemon.py` → `_format_jsapi_messages` |
| 消息格式 | 钉钉 Stream SDK 推送的 webhook payload | JSAPI `listMessage` 返回的内部 JSON |
| 图片标识 | `downloadCode`（可直接换下载链接） | `mediaId`（MsgPack 编码，需 CDN URL 拼接） |
| 文件标识 | `downloadCode`（同上） | `f_id` + `s_id`（钉盘存储标识，需 Storage API） |
| 下载方式 | `/v1.0/robot/messageFiles/download` | CDN URL（图片）/ Storage API（文件） |

### 通道 1：机器人 Webhook 接收

入口函数 `_handleRobotMessage` 按 `msgtype` 分发处理：

| msgtype | 处理方式 | 产出 |
|---------|---------|------|
| `text` | 直接取 `text.content` | 纯文本 |
| `richText` | 遍历 richText 数组，text 段拼文字，picture 段取 `downloadCode` 下载 | 文本 + 本地图片路径 |
| `picture` | 取 `content.downloadCode` 下载 | 本地图片路径 |
| `file` | 取 `content.downloadCode` + `content.fileName` 下载 | `[文件: 本地路径]` |
| `audio` | 文字提取或占位 | 文本或 `[语音消息]` |

**下载函数 `_downloadRobotFile(downloadCode, originalFileName?)`**：
```
POST /v1.0/robot/messageFiles/download
  body: { downloadCode, robotCode: appKey }
  headers: { x-acs-dingtalk-access-token: token }
  → 返回 { downloadUrl: "https://..." }
  → GET downloadUrl → 保存到本地
```

**保存路径**：
- 图片: `data/dingtalk/cache/images/robot_{timestamp}_{hash}.{ext}`
- 文件: `data/dingtalk/cache/files/robot_{timestamp}_{safeName}`

**不需要额外权限**，downloadCode 是机器人 webhook 自带的一次性下载凭证。

### 通道 2：Daemon 接收

#### 图片（ct=203 / ct=3100）

**ct=203 纯图片**：图片路径在 `attachments[0].filePath`，格式 `http://loc.dingtalk.com/<prefix><base64>`，base64 解码后为本地缓存绝对路径。完整字段结构见上方「ct=203 纯图片」章节。

**ct=203 图片获取**（2026-03-30 已验证）：`attachments[0].filePath` 的 `loc.dingtalk.com` URL 中 base64 部分解码后即为本地缓存绝对路径，文件为已解密的有效 PNG/JPEG，可直接读取。ct=203 没有 mediaId，无法构造 CDN URL；文件不存在时 daemon 记录 warning 并跳过。

**ct=3100 富文本图片**：从 `payload.items` 中提取 `type=img` 的 `value.src`（`mediaId://@...`），MsgPack 解码得宽高，拼 CDN URL 下载：
```
https://static.dingtalk.com/media/{mediaId去@}_{width}_{height}.{format}
```
公网可访问、无需认证。下载到 `data/dingtalk/cache/images/{hash}.{ext}`，支持缓存命中跳过。

#### 文件（ct=501/502/503）

daemon 拦截到的 ct=501/502/503 消息结构：
```json
{
  "contentType": 502,
  "attachments": [{
    "extension": {
      "f_id": "215702218730",    // 钉盘文件 ID（dentryId）
      "s_id": "21814953402",     // 钉盘空间 ID（spaceId）
      "f_name": "测试.txt",      // 原始文件名
      "f_size": "24",            // 文件大小（字节）
      "f_type": "txt",           // 扩展名
      "oid": "<ORG_ID>",          // 组织 ID
      "isEncrypt": "1",          // 加密标记
      "sp_dentrySpaceType": "imSingle",  // 空间类型
      "type": "file"
    },
    "filePath": ""               // DingTalk 7.x 下为空（未本地缓存）
  }]
}
```

**关键差异**：daemon 侧只有 `f_id` + `s_id`，没有 `downloadCode`，也没有本地缓存路径。

#### 文件下载 JSAPI（2026-03-11 ~ 03-27）

**`createTask` 真实签名**（从 chatbox-index.js 源码分析得出）：
```javascript
dingtalk.download.createTask(url, options, callback)
// url: "https://space.dingtalk.com/auth/download?spaceId={s_id}&path={f_id}"
// options: {fileName, spaceId, fileId, messageId:'0', conversationId:'', isFolder:false}
// callback: function(err, taskId) { ... }
```
源码中 `createTask` 被 `promisify` 包装：`(0,p.A)(dingtalk.download.createTask, dingtalk.download)`。
URL 生成：`uf.y_` → `` `https://space.dingtalk.com/auth/download?spaceId=${e}&path=${t||n}` ``。

| API | 结果 | 说明 |
|-----|------|------|
| `download.createTask(url, opts, cb)` | ✅ **已调通** | B1 上下文 + Frida hook `GetSaveFileNameW` 实现静默下载 |
| `fileTask.listAllTask()` | ✅ 返回所有任务 | 含 filePath/status/taskId/url，下载后用此接口获取实际保存路径 |
| `fileTask.tryTaskAgain(taskId)` | ✅ 重新下载 | 创建新 taskId 下载到同一路径，适用于已有记录的文件 |
| `download.batchDownloadImFile` | ❌ code 50 | 下载引擎需要聊天渲染器上下文，B1 无法触发 |

**`createTask` + GetSaveFileNameW Hook 方案**（daemon `download_im_file` 实现）：

1. 检查本地缓存
2. `listAllTask` 查询是否已有下载记录（status=1 且文件存在）
3. `createTask(url, opts, cb)` 触发下载 → 原生会调用 `GetSaveFileNameW` 弹出 "另存为"
4. **Frida `Interceptor.replace`** 替换 `GetSaveFileNameW`：自动填入保存路径并返回 TRUE，对话框不会出现
5. 原生下载管理器从服务器获取加密文件 → SecurityGuardSDK 解密 → 明文写入 hook 指定路径
6. `createTask` 回调返回 `taskId`，检查文件是否已写入

**Native Hook 要点**：
- Frida 17.x 中 `Module.findExportByName` 已废弃，使用 `Process.getModuleByName('comdlg32.dll').getExportByName('GetSaveFileNameW')`
- `Interceptor.replace` 完全替换函数，不是 `attach` — 对话框根本不会创建
- x64 OPENFILENAMEW 布局：`lpstrFile` 在偏移 +48，`nMaxFile` 在偏移 +56
- 替换函数读取 `proposed` 文件名，拼接 `{SILENT_DL_DIR}\{name}`（见 `config.json` → `silent_download_dir`）写入缓冲区
- ABI 必须指定 `'win64'`（不支持 `'stdcall'`）
- hook 在 daemon CEF 脚本加载时自动安装，无需单独管理

**`listAllTask` 返回结构**：
```json
{
  "taskId": "1774604068891",
  "fileName": "test.md",
  "fileId": "215726537726",
  "spaceId": "28270003700",
  "filePath": "C:\\Users\\<USER>\\Documents\\test.md",
  "fileSize": "4062",
  "status": 1,
  "type": 0,
  "url": "https://space.dingtalk.com/auth/download?spaceId=28270003700&path=215726537726",
  "isFolder": false,
  "errorMsg": "",
  "createAt": "13419072064762192"
}
```

| 字段 | 说明 |
|------|------|
| status | 1=已完成, 2=失败/取消 |
| type | 0=用户"另存为", 1=自动预览下载 |
| url | `https://space.dingtalk.com/auth/download?spaceId={s_id}&path={f_id}` |
| filePath | 本地保存路径 |

**推荐文件下载方案**：

| 场景 | 方案 | 自动化 |
|------|------|--------|
| 用户已手动下载过 | `listAllTask()` 查 filePath | ✅ 全自动 |
| 需要重新下载 | `tryTaskAgain(taskId)` | ✅ 全自动 |
| **首次自动下载** | **`createTask` + `GetSaveFileNameW` Hook** | **✅ 全自动（静默，无弹窗）** |
| 备选 | Storage API（服务端） | ❌ 需 orgAuthLevel 权限 |

**Storage API 完整调用链**（备选方案）：

```
1. 读 ultraai.config.json 的 appKey + appSecret
   → POST /v1.0/oauth2/accessToken → access_token

2. POST /topapi/v2/user/get (userid=senderStaffId)
   → unionId（如 "giSgPuJkfLTXE9bo9dyhHZwiEiE"）

3. POST /v1.0/storage/spaces/{s_id}/dentries/{f_id}/downloadInfos/query?unionId={unionId}
   headers: { x-acs-dingtalk-access-token: access_token }
   body: {}
   → { headerSignatureInfo: { resourceUrls: ["https://..."], headers: {...} } }

4. GET resourceUrls[0] (带签名 headers)
   → 文件二进制内容 → 保存本地
```

**保存路径**：`data/dingtalk/cache/files/{f_id}_{safeName}`

#### 当前状态

| 接收场景 | 图片 | 文件 |
|---------|------|------|
| 机器人 webhook | ✅ downloadCode 下载 | ✅ downloadCode 下载 |
| daemon ct=203 | ✅ loc.dingtalk.com → base64 → 本地路径 | — |
| daemon ct=3100 | ✅ CDN URL 拼接下载 | — |
| daemon ct=501/502/503 | — | ✅ createTask + GetSaveFileNameW Hook（静默） |

### Agent 回复中的图片/文件发送语法

Agent（包括自动回复 agent）在回复中使用以下标签，系统自动提取并发送：

```
[图片: 本地路径或URL]
[文件: 本地文件路径]
```

**处理链路**：
1. Agent 回复文本中包含 `[图片: ...]` 或 `[文件: ...]`
2. `router._extractAndSendMedia()` / `trigger-executor._extractAndSendMedia()` 用正则提取
3. 图片 → `channel.sendImage(chatId, source)`（本地文件先 upload 获 media_id → sampleImageMsg）
4. 文件 → `channel.sendFile(chatId, filePath)`（upload → sampleFile）
5. 标签从文本中移除，剩余纯文本通过 `sendText` 发送

**对话记录中的图片引用**：daemon 下载的图片以 `[图片: Y:\UltraAI\data\dingtalk\cache\images\...]` 格式出现在对话记录中，agent 可用 Read 工具查看图片内容。

---

## 6. 已知限制

1. 接收消息原始 sender 是 UID——已通过 `contacts.json` 自动解析姓名
2. 图片/文件/语音消息无文本内容，只有元数据
3. 钉钉最小化且无 Renderer 时无法注入 JS（影响发送和历史获取，不影响 Native Hook 监听）
4. 部分机器人/系统消息无 `origin_text`，需用备选字段
5. **单聊 CID 顺序不固定**——不能假设己方 UID 一定在前。CID 原样存储、原样使用，不做规范化
6. **`advancedSearch.html` 的 `hideInput` 参数**——`_ensure_b1()` 加载该页面时若 URL 含 `hideInput=true`，会导致钉钉搜索栏输入框消失。必须设为 `hideInput=false`

---

## 7. 有用的 LWP 端点

| 端点 | 用途 |
|------|------|
| `/r/IDLSend/send` | 文本消息发送 |
| `/r/IDLMessage/listMessagesPagination` | 历史消息分页 |
| `/r/IDLConversation/listNewestExtV3` | 最新会话列表 |
| `/r/IDLConversation/listAllGroup` | 所有群组 |
| `/r/IDLConversation/listMembers` | 群成员 |
| `/r/Adaptor/ReportDetailI/get` | 日报详情（富文本版） |

---

## 8. CEF 注入技术参考

### vtable 偏移（DingTalk 8.2.15, Chrome 133）

```
cef_browser_host_get_browser_by_identifier(id) → browser
browser + 160 → get_main_frame → frame
frame + 152 → execute_java_script（偏移+8，非标准 CEF）
frame + 144 → load_url
frame + 136 → get_url
```

### Browser 环境

| ID | URL | 说明 |
|----|-----|------|
| 1 | `advancedSearch.html` | **主注入点**，消息发送和历史获取均可用 |
| 2-5 | 未知 | execJS ok 但无法回传数据 |

会话 UI 运行在 renderer 进程中（`--type=renderer`），消息加载走独立 Native 通道，不经过 `dingtalk.message.listMessage`。

### std::string (MSVC) 读取

```javascript
function readStdStr(p) {
    var len = p.add(16).readU32();
    var cap = p.add(24).readU32();
    if (!len || len > 500000 || cap < len) return null;
    var dp = (cap <= 15) ? p : p.readPointer(); // SSO
    return dp.readByteArray(len);
}
```

---

## 9. 钉钉在线文档数据提取（alidocs）

通过 daemon CEF 浏览器 + rawDataStore 读取钉钉在线文档内容。已验证适用于电子表格（wiki_sheet）。

### 核心原理

alidocs 是 SPA 应用，电子表格用 canvas 渲染（DOM 无内容），但前端框架将服务端原始数据缓存在 JS 全局变量中：

```
rawDataStore.docData.value.documentContent.checkpoint.content
→ JSON.parse → 遍历 cells → 提取文本
```

绕过三个障碍：
- **无需发 API 请求** — 读已加载的运行时数据，CSP/CORS 不影响
- **无需解析 canvas** — 直接读数据源
- **自带登录态** — CEF 浏览器继承钉钉 session

### 提取步骤

**1. 通过 daemon 加载文档页面**

```bash
curl -X POST http://127.0.0.1:19200/fetch_report_content \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://alidocs.dingtalk.com/i/nodes/<NODE_ID>",
    "wait": 15,
    "custom_js": "<提取脚本>"
  }'
```

- `url`: alidocs 文档 URL（从群聊消息中获取）
- `wait`: 等待页面加载的秒数（电子表格较大时需 15-20s）
- `custom_js`: 在页面上下文中执行的 JavaScript

**2. 提取脚本（电子表格 wiki_sheet）**

```javascript
(function() {
  try {
    var raw = rawDataStore.docData.value.documentContent.checkpoint.content;
    var data = JSON.parse(raw);
    var cells = data.cells || {};
    var result = [];
    var keys = Object.keys(cells).sort();
    for (var i = 0; i < keys.length; i++) {
      var cell = cells[keys[i]];
      if (cell && cell.content && cell.content.length > 0) {
        var text = '';
        for (var j = 0; j < cell.content.length; j++) {
          if (cell.content[j].text) text += cell.content[j].text;
        }
        if (text.trim()) {
          result.push({ key: keys[i], text: text.trim() });
        }
      }
    }
    var payload = JSON.stringify({ cells: result, total: result.length });
    fetch('http://127.0.0.1:' + _BEACON_PORT + '/beacon', {
      method: 'POST',
      mode: 'no-cors',
      body: payload
    });
  } catch(e) {
    fetch('http://127.0.0.1:' + _BEACON_PORT + '/beacon', {
      method: 'POST',
      mode: 'no-cors',
      body: JSON.stringify({ error: e.message })
    });
  }
})();
```

**关键**：用 `fetch` 回传数据，**不要用 `sendBeacon`**（64KB body 限制，超限静默丢弃）。

**3. 解析单元格坐标**

cells 的 key 格式为 `ROW_COL`（如 `0_0`, `1_3`），下划线分隔行列索引。据此可重建表格结构。

### 已验证失败的方案

| 方案 | 结果 | 原因 |
|------|------|------|
| WebFetch 直接抓取 | ❌ | 需要登录态 |
| 钉钉 Open API `/v2.0/wiki/nodes/queryByUrl` | ❌ | 应用缺 Wiki.Node.Read 权限 |
| `fetch_report_content` 默认 CSS 选择器 | ❌ | 只拿到导航栏（canvas 渲染，DOM 无数据） |
| 加长 wait 到 35s | ❌ | 同上 |
| 浏览器内 fetch 内部 API | ❌ | CSP/CORS NetworkError |

### 适用范围与局限

- ✅ 电子表格（wiki_sheet）— rawDataStore 方案已验证
- ⚠️ 文档（wiki_doc）— rawDataStore 路径可能不同，需探测
- ⚠️ 脑图/白板等 — 未测试
- ❌ 需要滚动加载的超大表格 — 可能只有首屏数据

---

## 10. 环境信息

个人环境信息（UID、数据路径等）通过 `config.json` 配置，参见 `config.example.json`。

| 项目 | 配置方式 |
|------|---------|
| 当前用户 UID | `config.json` → `my_uid`，或环境变量 `DINGTALK_MY_UID` |
| 工作汇报会话 CID | `config.json` → `report_cid`，或环境变量 `DINGTALK_REPORT_CID` |
| 我的报群 CID | `config.json` → `my_report_group_cid`，或环境变量 `DINGTALK_MY_REPORT_GROUP_CID` |
| 静默下载目录 | `config.json` → `silent_download_dir`，或环境变量 `DINGTALK_SILENT_DL_DIR` |
| DingTalk 路径 | Windows 默认 `C:\Program Files (x86)\DingDing\main\current\` |
| 用户数据 | `%APPDATA%\DingTalk\<YOUR_UID>_v2\`（可能因设置不同） |
| IM 网络核心 | `libgaea.dll` (Monitor Hook 消息监听) |
| JS 注入目标 | Browser 1 (`advancedSearch.html`) via `libcef.dll` |
