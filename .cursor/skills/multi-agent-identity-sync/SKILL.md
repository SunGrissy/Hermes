---
name: multi-agent-identity-sync
description: |
  多 Agent 身份同步与记忆汇聚方案——维持 Hermes、OpenClaw、Cursor 三方核心大脑一致，同时保留各自独身份和动态记忆。
  触发场景：新增备份Agent、身份配置变更、记忆升级、多Agent协同架构设计。
---

# 多 Agent 身份同步与记忆汇聚

## 三层架构

```
├── 身份层（Identity） ← 三方一致，变更时同步
│   • 核心思维框架
│   • 基本执行纪律
│   • 称呼规范
│   • 沟通风格
│
├── 动态记忆（Memory） ← 各自独立，定期汇聚
│   • 对话细节
│   • 新偏好
│   • 临时教训
│
└── 环境知识（Context） ← 共享，随时更新
    • 项目路径
    • 服务端口
    • 工具配置
```

## 各平台身份注入方式

| 平台 | 身份存储位置 | 注入方式 |
|------|-------------|---------|
| **Cursor** | `.cursor/rules/*.mdc` | 规则文件，会话启动时加载 |
| **Hermes** | `memory` 工具 + 系统提示 | 每次会话自动加载 |
| **OpenClaw** | `openclaw.json` → `channels.dingtalk-connector.systemPrompt` | 修改配置后重启 Gateway |

## OpenClaw 身份注入步骤

### Step 1: 备份配置
```bash
cp D:/OpenClaw/openclaw.json D:/OpenClaw/openclaw.json.bak.$(date +%Y%m%d-%H%M%S)
```

### Step 2: 修改 systemPrompt
用 Python 修改 `openclaw.json`：
```python
import json

with open('D:/OpenClaw/openclaw.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

config['channels']['dingtalk-connector']['systemPrompt'] = "身份提示词"

with open('D:/OpenClaw/openclaw.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)
```

### Step 3: 重启 Gateway
```python
import subprocess
import os

# 杀掉旧进程
# 先查找监听 18789 的 PID，然后 taskkill //F //PID <pid>

# 启动新进程
env = os.environ.copy()
env['OPENCLAW_STATE_DIR'] = r'D:\OpenClaw'
env['OPENCLAW_CONFIG_PATH'] = r'D:\OpenClaw\openclaw.json'
env['OPENCLAW_GATEWAY_PORT'] = '18789'

p = subprocess.Popen(
    [r'C:\Program Files\nodejs\node.exe',
     r'C:\Users\TU\AppData\Roaming\npm\node_modules\openclaw\dist\index.js',
     'gateway', '--port', '18789'],
    env=env,
    creationflags=0x00000010  # CREATE_NEW_CONSOLE
)
```

### Step 4: 验证
```bash
netstat -ano | grep 18789 | grep LISTENING
# 应该显示新 PID 在监听
```

## 动态记忆汇聚中心

### 目录结构
```
D:/MyAgents/shared-memory/
├── hub/              # 每日汇聚报告（保留 30 天）
├── knowledge/        # 共享环境知识（长期）
├── pending-upgrade/  # 待审核的身份升级候选
└── scripts/
    └── daily-sync.py  # 汇聚脚本
```

### 升级判定标准
满足以下任一即进入 `pending-upgrade/` 等待审核：
- 同一内容 7 天内出现 2 次+
- 影响工作流或决策模式
- 属于环境/工具/路径等可复用信息

### Cronjob 配置
```
时间: 每日 2:00
脚本: py D:/MyAgents/shared-memory/scripts/daily-sync.py
通知: 仅有升级候选时通知用户
```

## 同步工作流

```
Cursor 规则变更（唯一真源）
    ↓
Hermes 检测变更
    ↓
自动同步到 OpenClaw systemPrompt
    ↓
重启 OpenClaw Gateway
    ↓
钉钉通知用户："身份配置已更新，请重启 Cursor 重载"
```

## 常见陷阱

1. **OpenClaw systemPrompt 过肠**: 环境知识不应放入 systemPrompt，应放入 knowledge/ 共享
2. **动态记忆误升级**: 一次性对话细节不应升级为身份层
3. **Gateway 重启失败**: 检查 PID 是否正确杀掉，端口是否释放
4. **编码问题**: Windows 下写 JSON 必须用 utf-8 + ensure_ascii=False

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-04-23 | v1.0 | 初始架构设计：三层架构 + OpenClaw 注入 + 汇聚脚本 |
