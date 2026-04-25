---
name: tuyoo-oidc-auth
description: 接入途游统一身份认证（OIDC / zxty.tuyoo.com）。覆盖后端授权码换 token、获取用户信息、JWT 签发验证，以及前端跳转登录的完整流程。当用户提到 OIDC、统一认证、单点登录、SSO、zxty、launchpad、app_key/app_secret 或要接入公司登录体系时自动应用。
---

# 途游统一身份认证（OIDC）接入 Skill

一步步引导用户完成 OIDC 接入，从申请 key 到写代码到跑通。

## 核心原则

**面向不会写代码的用户**：能自动检测的绝不问，能自动写入的绝不输出让用户拷贝。用户只需要提供 app_key / app_secret，其余全部自动完成。

---

## 执行步骤

当用户触发此 skill 时，**必须按以下步骤顺序执行**，不要跳步，不要一次输出全部内容。每一步完成后等用户确认再进入下一步。

### Step 1: 确认是否已申请 app_key / app_secret

问用户：**"你已经申请过途游 OIDC 的 app_key 和 app_secret 了吗？"**

- **已申请** → 记下 `app_key`、`app_secret`，进入 Step 3
- **未申请** → 进入 Step 2

### Step 2: 引导申请（仅未申请时）

告诉用户：

> 请在钉钉客户端打开以下链接，填写审批表单：
>
> ```
> dingtalk://dingtalkclient/action/openapp?app_id=-4&container_type=work_platform&corpid=ding37c967956637d20d&ddtab=true&redirect_type=jump&redirect_url=https%3A%2F%2Faflow.dingtalk.com%2Fdingtalk%2Fmobile%2Fhomepage.htm%3FappUuid%3Dding37c967956637d20d%26backcontrol%3Dfalse%26corpid%3Dding37c967956637d20d%26dd_progress%3Dfalse%26dd_share%3Dfalse%26ddtab%3Dtrue%26showmenu%3Dfalse%23%2Fcustom%3Fpcredirect%3Dself%26processCode%3DPROC-498BDF97-0AC4-4712-9813-E635323F354B
> ```

帮用户准备好表单中需要填写的内容：

1. **应用名 / 业务用途** — 用户自己根据实际情况填写
2. **redirect_uri 回调地址** — 自动读取项目的 host/port 拼出本地回调地址，同时**提示用户输入测试/生产环境的 IP 或域名**，格式为 `http://{host}:{port}/callback`。提醒用户：**末尾斜杠敏感**，所有环境地址都要报备
3. **scope** — 默认 `sub name email`，一般够用

审批通过后对接人会下发 `app_key` 和 `app_secret`。

> 如果审批流走不通，直接联系对接人：李卓然、许龙

### Step 3: 自动检测项目环境

**全部自动，不问用户。**

#### 3.1 检测后端框架

**Python 项目**（通过 `requirements.txt`、`pyproject.toml`、`Pipfile` 等判断）：
- `fastapi` → FastAPI
- `flask` → Flask
- `django` → Django
- 都没有 → 原生 http.server

**Node.js/TypeScript 项目**（通过 `package.json` 判断）：
- `express` → Express
- `fastify` → Fastify
- `koa` → Koa
- `@nestjs/core` → NestJS

#### 3.2 检测回调地址

从项目配置中读取 port，host 必须使用本机局域网 IP（不能是 `127.0.0.1` / `localhost`，否则外部无法回调）。

自动获取本机局域网 IP：
```bash
python -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0]);s.close()"
```

拼出回调地址：`http://{局域网IP}:{port}/callback`。如果自动获取失败，再问用户。

#### 3.3 检测前端框架

- `package.json` 依赖含 `react` → React
- `package.json` 依赖含 `vue` → Vue
- 有 `.html` 文件 → 纯 HTML/JS
- 都没有 → 无前端，跳过前端代码生成

#### 3.4 检测已有认证机制

- 已有 JWT / 登录代码 → 复用已有的 `JWT_SECRET` 和鉴权逻辑
- 没有 → 新生成 `JWT_SECRET`

检测完成后，**简要告知用户检测结果**（一句话），直接进入 Step 4。

### Step 4: 自动生成并写入环境变量

**自动执行，不问用户。**

1. 生成随机 `JWT_SECRET`（`python -c "import secrets; print(secrets.token_urlsafe(32))"`）
2. 检查并写入 `.env` 文件（有则追加，无则新建）
3. 确保 `.gitignore` 中包含 `.env`
4. 写入内容：
```
OIDC_CLIENT_ID=<app_key>
OIDC_CLIENT_SECRET=<app_secret>
OIDC_REDIRECT_URI=<回调地址>
JWT_SECRET=<随机密钥>
```

### Step 5: 自动生成并写入后端路由代码

**自动执行，不问用户。**

1. 读取 `oidc_ops.py`（本 skill 目录下）作为逻辑参考，生成项目自包含的 OIDC 路由代码
2. 自动找到项目的路由/主入口文件写入
3. 自动微调：匹配路由前缀风格，有前端则 callback 后 302 跳转携带 token

**生成规则见下方「代码生成规则」章节。**

### Step 6: 自动生成并写入前端对接代码

**无前端则跳过。** 找到前端入口/登录页，写入登录跳转 + token 存储逻辑。

### Step 7: 自动验证并启动测试

1. 检查 `.env` 四项是否齐全
2. 启动项目
3. 告诉用户访问地址，确认能跳转到 `zxty.tuyoo.com` 登录页并回调成功

如果验证失败，参照「常见排查清单」自动排查修复。

---

## 代码生成规则

### 通用规则

1. **生成自包含代码**：不引用 `oidc_ops.py`，不使用 `sys.path.insert`，核心逻辑内联到项目中
2. **`oidc_ops.py` 仅作为逻辑参考**：理解 OIDC 流程后将逻辑内联
3. **仅依赖标准库 + 项目已有依赖**：不引入新依赖（Python 项目无 `httpx` 则用 `urllib.request`）
4. **不要硬编码密钥**：`client_secret`、`jwt_secret` 必须走环境变量
5. **state 防 CSRF**：必须用 `encode_state` / `decode_state`，不能省略
6. **不要复用 OIDC access_token 做业务鉴权**：用 `create_session_jwt` 签自家 JWT
7. **redirect_uri 必须报备白名单**：本地开发地址也要报备，末尾斜杠敏感，变了必须重新报备
8. **回调地址必须用局域网 IP**：不能用 `127.0.0.1` / `localhost`；服务监听地址必须绑 `0.0.0.0`

### Node.js / TypeScript 项目特殊规则

> **这是最常踩的坑，必须严格遵守。**

1. **环境变量必须延迟读取**：`process.env.X` 不能在模块顶层以常量形式读取（如 `const JWT_SECRET = process.env.JWT_SECRET`），因为模块加载时 `dotenv` 可能尚未执行，读到空字符串。**必须用函数延迟读取**：
   ```typescript
   // 错误 — 模块加载时 dotenv 可能还没执行
   const JWT_SECRET = process.env.JWT_SECRET || '';

   // 正确 — 每次调用时才读取
   function getJwtSecret() { return process.env.JWT_SECRET || ''; }
   ```

2. **dotenv 加载顺序**：`import 'dotenv/config'` 必须放在入口文件最顶部，在所有业务路由 import 之前。`tsx` ESM 模式下 `__dirname` 不可用，需用 `process.cwd()` 定位 `.env` 路径。

3. **后果**：如果违反上述规则，后端鉴权中间件的 `JWT_SECRET` 为空 → 验签永远失败 → 所有请求 401 → 前端收到 401 清 token 跳登录 → **登录成功后又跳回登录页的死循环**。

---

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `OIDC_CLIENT_ID` | 是 | 途游 app_key |
| `OIDC_CLIENT_SECRET` | 是 | 途游 app_secret |
| `OIDC_REDIRECT_URI` | 是 | 回调地址 |
| `JWT_SECRET` | 是 | 自家 JWT 签名密钥 |
| `OIDC_HOST` | 否 | 默认 `https://zxty.tuyoo.com` |
| `OIDC_SCOPE` | 否 | 默认 `sub name email` |
| `JWT_EXPIRES` | 否 | JWT 有效期秒数，默认 `86400` |

## 核心端点

| 用途 | 方法 | URL |
|------|------|-----|
| 用户登录页 | GET | `https://zxty.tuyoo.com/launchpad/login/` |
| 授权码换 Token | POST | `https://zxty.tuyoo.com/oauth/token` |
| 获取用户信息 | GET | `https://zxty.tuyoo.com/oauth/userinfo` |

## oidc_ops.py 函数参考

| 函数 / 方法 | 说明 |
|-------------|------|
| `OIDCConfig.from_env(**overrides)` | 从环境变量创建配置 |
| `OIDCConfig.validate()` | 返回缺失配置项列表 |
| `create_oidc(**overrides)` | 快捷创建 `TuyooOIDC` 实例 |
| `build_auth_url(state=None)` | 生成登录跳转 URL + state |
| `exchange_code(code)` | 授权码换 access_token |
| `get_userinfo(access_token)` | 获取用户信息 |
| `handle_callback(code)` | 一步完成：换码 → 取用户 → 签 JWT |
| `create_session_jwt(userinfo)` | 签发自家 JWT（HS256，零依赖） |
| `verify_session_jwt(token)` | 验证 JWT，返回 claims |
| `encode_state(state)` / `decode_state(jwt)` | state 编解码（短期 JWT，5min） |
| `extract_bearer(authorization)` | 从 Authorization 头提取 Bearer token |

## 完整流程

```
浏览器           后端                    zxty.tuyoo.com
  │  1.点击登录    │                         │
  │ ────────────> │                         │
  │  2.返回URL    │                         │
  │ <──────────── │                         │
  │  3.跳转登录    │                         │
  │ ─────────────────────────────────────> │
  │               │   4.回调 ?code=&state=  │
  │               │ <─────────────────────  │
  │               │   5.code→token          │
  │               │ ──────────────────────> │
  │               │   6.access_token        │
  │               │ <─────────────────────  │
  │               │   7.Bearer→userinfo     │
  │               │ ──────────────────────> │
  │               │   8.userinfo            │
  │               │ <─────────────────────  │
  │  9.JWT+302    │                         │
  │ <──────────── │                         │
  v 业务页面       v                         v
```

## 安全加固（生产必做）

- [ ] `app_secret` / `jwt_secret` 只走环境变量，绝不写进代码或 git
- [ ] 登录跳转带 `state` 参数，回调校验，防 CSRF
- [ ] 全流程 HTTPS
- [ ] 业务鉴权用自家 JWT，不复用 OIDC 的 `access_token`
- [ ] `access_token` 注意 `expires_in` 过期时间
- [ ] `code` 只能用一次

## 常见排查清单

| 现象 | 可能原因 |
|------|----------|
| OIDC 报 `invalid_client` | `client_id` 错或应用未开通 |
| 回调 404 / 跨域 | `redirect_uri` 没报备白名单，或末尾斜杠不一致 |
| token 接口 400 `invalid_grant` | code 已用过/过期，或 `redirect_uri` 与登录时不一致 |
| token 接口 401 | `client_secret` 错 |
| userinfo 接口 401 | `Authorization: Bearer {token}` 格式不对或 token 过期 |
| userinfo 字段缺失 | `scope` 不足，找对接人增加 |
| 本地回调不通 | 本地 `redirect_uri` 也要报备白名单 |
| 登录后又跳回登录页 | `JWT_SECRET` 为空（dotenv 加载顺序问题），验签失败导致 401 死循环。见「Node.js 特殊规则」 |
| auth URL 中 `client_id=` 为空 | `dotenv` 未正确加载 `.env`（路径不对或加载晚于路由模块初始化） |
