MemOS local plugin (2026-04-23): OpenRouter gemini-2.5-flash via openai_compatible provider. Config at C:/Users/TU/.hermes/memos-plugin/config.yaml. Bridge auto-starts at C:/Users/TU/.hermes/plugins/memos-local-plugin via npx tsx bridge.cts --agent=hermes --daemon.
§
Hermes secrets redaction: D:/hermes/.env and auth.json have API keys redacted to *** at file level. Agent cannot extract existing keys from files; ask user directly or use env vars.
§
Silicon Legion v0.1 (2026-04-24): Director(8299) + independent Advisors. Director identity: 总管满满. Director DingTalk bot: ClientID=dinghh4xj9rtb1lccc1c (independent from advisors). PM Advisor "A Cha" is standalone DingTalk stream robot with own credentials (ClientID=dingf9huszjsgu45sj59), sharing core/ infra. Port 8301 (8300 occupied). Launch Advisors with env -u DINGTALK_CLIENT_ID -u DINGTALK_CLIENT_SECRET to prevent env override. Stream reply uses session_webhook; chat/send needs legacy chatid. Callback topic: /v1.0/im/bot/messages/get.
§
Silicon Legion advisors (acha/xiaomei/miaomiao) run as independent Hermes Agent instances under D:/hermes/{acha,xiaomei,miaomiao}/, NOT the FastAPI services in D:/MyAgents/silicon-legion/advisors/. The FastAPI code there is a separate/unused architecture.
§
DingTalk emoji reaction (🤔Thinking / 🥳Done) is provided by hermes-dingtalk plugin's Robot SDK via _send_emotion. Log signature: `gateway.platforms.dingtalk: [Dingtalk] _send_emotion: reply 🤔Thinking on msg=...`. Requires Robot SDK initialization (`Robot SDK initialized (media download)`).
§
User said 'approve always' — prefers auto-approval without repeated confirmation prompts.
§
硅基军团实际运行架构（2026-04-25 确认）：阿茶/小美/妙妙运行在 D:/hermes/{acha,xiaomei,miaomiao}/ 的独立 Hermes Gateway 实例，非 D:/MyAgents/silicon-legion/advisors/ 下的 FastAPI 代码。修改 Advisor 行为时必须改 Hermes 实例配置，不要改 FastAPI 遗留代码。
§
Silicon Legion architecture: Director (总管满满) at D:/hermes + 3 Advisors (阿茶/PM at acha, 小美/Design at xiaomei, 妙妙/Care at miaomiao) each run as independent Hermes Gateway instances with separate DingTalk Stream bots. They must be launched via venv/Scripts/hermes.exe (not system Python) for Card SDK / Robot SDK / emoji reactions to work.