---
name: interview-checklist-dingtalk
description: 面试清单（*.md）生成完成后，将 md-reader 的**本机 IP 直链**（含 ?path=）通过钉钉机器人发到**助理通知群**；正文含**面试岗位**与会话 Agent 代号。Use when the user asks to「面试清单发钉钉」「清单推助理群」或刚写完 interviews/**/ *-面试清单.md 需要通知团队。
---

# 面试清单 → 钉钉助理通知群（md-reader 链接）

在**面试清单 Markdown 已写入磁盘**后，向助理通知群推送一条机器人消息，内容为 **md-reader 打开该文件的局域网 URL**（`http://<本机IP>:8899/?path=相对工作区路径`），便于同事用浏览器直接打开。

## 何时执行

- 用户明确说「把面试清单发钉钉」「推助理通知群」「清单好了通知一下」
- Agent 刚生成或更新 `interviews/**/ *-面试清单.md`（或同类路径），用户希望同步到群里

## 前置条件

1. **md-reader** 在本机运行，监听 **`0.0.0.0:8899`**。`pm-system/quick_start.bat`、`md-reader/start.bat` 及钉钉 `status_check` 自动拉起时会设置 **`MD_READER_ROOT`= MyAgents 根**，链接里的 `?path=` 可直接打开对应 md。**若手工用 `uvicorn` 启动且未设环境变量**，仍需在页面选择工作区根，或设 `MD_READER_ROOT`。
2. 修改启动方式后请**重启 md-reader** 再测链接。
3. **Webhook**：在 `dingtalk-desktop/webhook_config.json` 中配置 **`interview_checklist`**（推荐，助理通知群专用机器人 URL）；若留空，脚本会回退使用 **`default`**（与 `send_result_webhook.py` 行为一致）。
4. 参考模板：`webhook_config.json.example` 中的 `interview_checklist` 说明。

## 执行步骤（Agent 必做）

1. 确认清单文件已保存，记下**相对工作区根**的路径（如 `interviews/zhangling_ops_2026-03-24/张凌-面试清单.md`）。
2. **面试岗位**：钉钉正文在「面试清单已生成」下增加一行 **`面试岗位`**。优先传 `--role "运营策划"`（或环境变量 `INTERVIEW_ROLE`）；未传时脚本会读**同目录** `README.md` 里 `- 目标岗位：…` 一行自动推断（故资料包 README 建议写清目标岗位）。
3. 运行通知脚本（**不要用管道传长中文路径**，直接传文件路径参数）：

```powershell
cd "d:\MyAgents"
$env:AGENT_SESSION_CODE = "AgentXXX"
py .cursor/skills/interview-checklist-dingtalk/scripts/notify_interview_md_reader.py "interviews\xxx\候选人-面试清单.md" --role "运营策划"
```

- **指定 IP**（自动探测不准时）：`--host 172.16.3.197` 或 `MD_READER_PUBLIC_HOST=172.16.3.197`
- **端口**：`--port 8899` 或 `MD_READER_PORT`

4. 成功时脚本退出码 0 且输出 `sent`（由 `send_result_webhook.py` 打印）；失败看 stderr。
5. 钉钉正文需包含 **本会话代号**（`--agent` 或 `AGENT_SESSION_CODE`）；**不要**再堆「使用前请确认」类冗长说明。footer 仍由 Webhook 脚本自动加 `###### ※ 小秘书提醒`。

## 与 dingtalk-actions 的关系

- 仍走 **机器人 Webhook**，不用 daemon `/send`。
- 使用 `.cursor/skills/dingtalk-actions/scripts/send_result_webhook.py`，通过环境变量 **`DINGTALK_WEBHOOK_KEY=interview_checklist`** 选择配置项；发送记录写入 `dingtalk-desktop/logs/cursor_webhook_sends.log`，标题为 **`面试清单-md-reader`**。

## md-reader 深链说明

- URL 形态：`http://<IP>:8899/?path=<UTF-8 编码的相对路径>`
- 前端在根目录与文件列表就绪后优先打开 `path` 对应文件（见 `md-reader/index.html` 的 `App.init`）。

## 禁止

- 不要把含密钥的 `webhook_config.json` 提交进 Git；仅维护 `.example` 与本地私有配置。
