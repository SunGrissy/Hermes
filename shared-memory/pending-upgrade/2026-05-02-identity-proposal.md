# 身份升级候选 - 2026-05-02

## 1. [openclaw/memory]

  2. D:\OpenClaw\extensions\dingtalk-connector\src\core\message-handler.ts - extractMessageContent 的 text/richText/reply 三个 case，同时检查 text.extensions 路径
- 回退方式：Hermes 用 git checkout；OpenClaw 用备份文件 message-handler.ts.bak.20260427
- 验证：妙妙(Hermes) + 小马(OpenClaw) 均已通过
- 清理：调试日志和 [AgentXia Task] 标记已全部删除

## 规范沉淀：代码修改标记规范 §7.1
- 位置：D:/MyAgents/shared-memory/legion-charter.md §7.1
- 内容：任何 Agent 修改非自身工作区代码时，必须加 [Agent{代号} Task] 标记
- 代号：虾叔=Xia, 满满=Man, 阿茶=Cha, 小美=Mei, 妙妙=Miao, 小马=Ma
- AGENTS.md 已加引用指向 §7.1

## OpenClaw 流式体验优化调研
- 问题：老大反馈 OpenClaw 在钉钉里"卡啊卡然后一大堆消息"，工具调用期间完全静默
- 现状：dingtalk-connector 已有 AI Card 流式文字输出，但工具调用期间无进度提示
- 原生支持：OpenClaw tool-progress preview 只支持 Discord/Slack/Telegram/Mattermost，不支持钉钉
- 可行方案：自研——在 reply-dispatcher.ts 的 onPartialReply 外加工具调用中间状态推送，类似 Hermes 的 tool_progress:all + interim_assistant_messages:true
- 状态：方案已和老大对齐，暂不实施，后续再排

## 踩坑：Hermes venv 重启不加载源码改动

---

## 2. [openclaw/memory]

- 协作：各Agent独立运行+共享框架、每日动态通过 shared-memory/ 汇聚、记忆回传写入共享目录
- 完整文件：D:/MyAgents/shared-memory/legion-charter.md

## 共享记忆体系
- 共享目录：D:/MyAgents/shared-memory/
- hub/YYYY-MM-DD.md：每日汇聚报告（满满凌晨2:00生成）
- knowledge/xiaxia-YYYY-MM-DD.md：我的发现写入处（§分隔）
- paused-tasks.md：明确搁置事项
- 军团成员：满满(总管)、阿茶(PM Advisor)、小美(设计Advisor)、妙妙(HR/关怀)、小马(运维)
- 检查点：[x] legion-charter 已读取/摘录、[x] 第一份 knowledge 已写入、[x] 有方式跟踪 hub 报告

## 重要事件
- 2026-04-23：第一次上线，和老大在钉钉认识了
- 2026-04-26：运维小马上线（OpenClaw2/D:/OpenClaw2/端口18790/deepseek-v4-flash），加入硅基军团
- 2026-04-26：妙妙配了 DeepSeek API
- 2026-04-26：老大要求所有列表必须编号，写入共享规则
- 2026-04-27：军团代码修改标记规范 §7.1 写入 legion-charter.md（Agent代号：Xia/Man/Cha/Mei/Miao/Ma）
- 2026-04-27：修复群聊引用消息读取——钉钉 Stream API 将 isReplyMsg/repliedMsg 放在 text.extensions 里而非顶层，Hermes+OpenClaw 两端已改，妙妙+小马验证通过
- 2026-04-28：写小马专用启动脚本 start_xiaoma.bat；PowerShell && 坑再次翻车被老大点名


---

