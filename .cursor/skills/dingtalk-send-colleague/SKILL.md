---
name: dingtalk-send-colleague
description: 通过 dingtalk-desktop daemon 向同事发送钉钉私聊消息。自动追加 🤖，用 Python 确保 UTF-8 编码正确。
---

# 给同事发钉钉私聊

## 触发条件

用户说"给{某人}发个消息{内容}"或类似表述。某人必须在 `D:/MyAgents/shared-memory/identity-map.md` 的「发消息通讯录」中有 CID 记录。

## 前置检查

1. 读取 `D:/MyAgents/shared-memory/identity-map.md`，确认目标同事的 `cid`
2. 若 cid 不存在，告知用户该同事还未录入通讯录，请先手工发一条消息收集 CID
3. 确认 daemon 是否在运行：`curl -s http://127.0.0.1:19200/health`

## 消息内容要求

- **末尾必须加 ` 🤖`**（空格+🤖），让同事知道是机器人代发
- 如果用户提供的消息末尾已有 🤖，不再重复追加
- 确认消息内容是**完整的一句话**，不要只有"收到""好的"这种短回复——机器人的消息要有头有尾

## 发送方式

用 Python 发送 POST 请求，不要用 PowerShell curl（emoji 编码会乱码）。

```python
import urllib.request, json

data = json.dumps({
    'cid': '<目标CID>',
    'message': '<消息内容 🤖>'
}).encode('utf-8')

req = urllib.request.Request(
    'http://127.0.0.1:19200/send',
    data=data,
    headers={'Content-Type': 'application/json'}
)
resp = urllib.request.urlopen(req, timeout=12)
```

## 验证

发送后检查返回值 `{"success": true}`。如果 false，将错误信息报给用户。

## 已知同事 CID

| 称呼 | cid |
|------|-----|
| 笛笛（杨柳荻） | 46459012:300405507 |
| 张颖 | 待确认 |

## 注意事项

- 所有发给人（非机器人/群）的私聊都必须加 🤖
- 如果发送的是通知类消息（如面试改约），确保内容清晰包含：原时间、新时间、原因
