# SKILL: 钉钉桌面端消息控制

> 通过 Frida 注入钉钉桌面端，实现消息收发和历史读取  
> 目标版本: DingTalk 8.2.15 / Windows  
> 依赖: Python + Frida + msgpack + winotify  
> 脚本位置: `skills/dingtalk-desktop/`

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
| 实时消息监听（收发双向） | daemon Monitor 脚本 | ✅ 生产可用 |
| 历史消息获取 | daemon `/fetch` (JSAPI) | ✅ 生产可用 |
| 联系人/CID 查询 | daemon `/contacts` | ✅ 生产可用 |
| 消息日志搜索 | daemon `/search` | ✅ 生产可用 |
| 日报/周报/月报提取 | Monitor (ct=300) | ✅ 生产可用 |
| Windows 桌面通知 | winotify | ✅ 生产可用 |
| 消息日志持久化 | JSONL | ✅ 生产可用 |

**所有能力均通过常驻 daemon（端口 19200）的单一 Frida session 提供，无需反复 attach。**

---

## 0. CID 发现（前置步骤）

发送消息和拉取历史都需要 CID，但钉钉没有提供直接的 CID 查询接口。

### 获取方式（按优先级）

| 方式 | 说明 |
|------|------|
| `dingtalk_find_conversation` 工具 | **推荐**。自动搜索 contacts.json → 消息日志 |
| 联系人库 `contacts.json` | `data/dingtalk/contacts.json`，daemon 持续维护，每收到消息自动记录新联系人，含完整 CID 列表 |
| 实时监听捕获 | daemon 消息监听器自动记录 CID 到 `data/dingtalk/_msg_log.jsonl` |
| 手动拼接（单聊） | `自己UID:对方UID`，如 `316550726:611424765` |

### 联系人库 (`data/dingtalk/contacts.json`)

daemon 运行时**自动维护**，每收到一条消息会：
1. 检查该 CID 是否已在库中
2. 新联系人 → 从已有 contacts.json 条目解析 UID→姓名 → 写入
3. 已有联系人 → 更新 `last_seen` 和 `msg_count`

**结构（私聊/群聊分开存储）：**

```json
{
  "p2p": {
    "316550726:1212298396": {
      "cid": "316550726:1212298396",
      "uid": "1212298396",
      "name": "乔子骜",
      "first_seen": "2026-03-10 09:00:00",
      "last_seen": "2026-03-10 18:00:00",
      "msg_count": 15,
      "name_resolved": true
    }
  },
  "group": {
    "324215852": {
      "cid": "324215852",
      "name": "面试通知群~",
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
| `cid` | 两者 | 会话 ID |
| `uid` | p2p | 对方 UID |
| `name` | 两者 | 联系人姓名 / 群名 |
| `first_seen` / `last_seen` | 两者 | 首次/最后出现时间 |
| `msg_count` | 两者 | 已记录消息数 |
| `name_resolved` | 两者 | 是否已解析名称 |
| `member_count` | group | 群成员数（通过 conv_info 获取） |
| `owner_id` | group | 群主 UID |
| `conv_type` | group | 会话类型（2=普通群） |

查询 API：`GET http://127.0.0.1:19200/contacts` 列出所有，`?name=乔子骜` 按名搜索。

### 推荐工作流

**直接用姓名操作**——`/send` 和 `/fetch` 端点均支持 `name` 参数，自动解析 CID：
- 发消息：`POST /send {name: "张三", message: "你好"}`
- 拉历史：`POST /fetch {name: "张三", count: 20}`
- MCP 工具 `dingtalk_send_message` 和 `dingtalk_fetch_history` 也支持 `name` 参数

不需要先查 CID 再操作，一步到位。

### 日志格式 (`_msg_log.jsonl`)

每行一条 JSON：
```json
{"time": "17:06:14", "cid": "316550726:611424765", "sender": "车君怡", "text": "...", "direction": "→ 发送", ...}
```

搜索时关注 `sender` 字段（发送消息有昵称）和 `cid` 字段（接收消息 sender 是 UID）。

---

## 1. 发送消息

### 调用方式

```python
from dt_jsapi_send import DingTalkSender

sender = DingTalkSender()
sender.send_text('611424765', '你好')          # 单聊（目标 UID）
sender.send_to_group('63536915431', '群消息')   # 群聊（群 CID）
sender.close()
```

### CID 格式

| 类型 | 格式 | 示例 |
|------|------|------|
| 单聊 | `自己UID:对方UID` | `316550726:611424765` |
| 群聊 | 纯数字 | `63536915431` |

当前用户 UID: `316550726`

### 技术原理

Frida 附加主进程 → 通过 `libcef.dll` 在 Browser 1 (`advancedSearch.html`) 注入 JS → 调用 `dingtalk.message.sendTextMsg(cid, text, '', callback)` → HTTP Beacon 回收结果。

### 约束

- 钉钉**必须在前台或托盘运行**（最小化时可能无 Renderer，无法注入 JS）
- 非 ASCII 字符需 `\uXXXX` 转义（脚本已内置处理）
- 不需要先打开会话，任意 CID 可直接发送

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
| 发送者昵称 | `[8]` | 如 "车君怡" |

### 会话类型判断

- CID 含 `:` 且不以 `cid` 开头 → **单聊**
- 否则 → **群聊**

### contentType 速查

| 值 | 类型 | 有文本 |
|----|------|--------|
| 1 | 文本 | ✅ |
| 101 | 图文 | ✅ |
| 203 | 图片 | ❌ |
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
  "atOpenIds": {"303215458": "崔正钦"},
  "atMsgStatusList": [{"openId": "303215458", "status": 1}],
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
        "cardInstanceId": "433910504906",
        "interactiveCardLastMessage": "赵圃瑞 将执行者从 刘兆蕊 变更为 张颖",
        "LastMessageI18n": {"zh_CN": "...", "en_US": "..."},
        "messageCreateTime": "1773237947209",
        "miniAppId": "5000000004926193",
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
| 1200 | Markdown | attachments | `attachments[0].extension.markdown` |
| 1202 | Markdown 系统消息 | attachments | `attachments[0].extension.markdown` |
| 2001 | 文件 | attachments | 文件名 |
| 2950 | 互动卡片 | attachments[0].extension | `interactiveCardLastMessage` |
| 3100 | 富文本/@ | textContent + atOpenIds | textContent.text |

### daemon API（推荐）

```bash
# 通过 CID
curl -X POST http://127.0.0.1:19200/fetch -d '{"cid":"316550726:1212298396","count":20}'

# 通过姓名（自动解析 CID）
curl -X POST http://127.0.0.1:19200/fetch -d '{"name":"张三","count":20}'
```

历史消息获取通过 JSAPI (dingtalk.message.listMessage) 实现，复用常驻 Frida CEF session。

---

## 4. 日报/周报/月报提取

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
  "name": "面试通知群~",
  "data": {
    "title": "面试通知群~",
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

## 6. 已知限制

1. 接收消息原始 sender 是 UID——已通过 `contacts.json` 自动解析姓名
2. 图片/文件/语音消息无文本内容，只有元数据
3. 钉钉最小化且无 Renderer 时无法注入 JS（影响发送和历史获取，不影响 Native Hook 监听）
5. 部分机器人/系统消息无 `origin_text`，需用备选字段

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

## 9. 环境信息

| 项目 | 值 |
|------|-----|
| 当前用户 UID | `316550726` |
| 企业 corpId | `ding37c967956637d20d` |
| DingTalk 路径 | `C:\Program Files (x86)\DingDing\main\current\` |
| 用户数据 | `%APPDATA%\DingTalk\316550726_v2\` |
| IM 网络核心 | `libgaea.dll` (Monitor Hook 消息监听) |
| JS 注入目标 | Browser 1 (`advancedSearch.html`) via `libcef.dll` |
| 研究资料 | （历史研究资料，已归档） |
