"""
设计小美 独立服务
端口: 8302

功能:
1. FastAPI服务：健康检查、手动触发建议
2. 钉钉Stream连接：实时接收@消息，以小美身份回复
3. 定时任务：每日9:00主动生成建议
"""

import os
import sys
import json
import asyncio
import threading
from datetime import datetime
from typing import Dict, Any

# 将项目根目录加入路径，确保 core/ 可被导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import FastAPI
from pydantic import BaseModel
from contextlib import asynccontextmanager

from core.config import get_settings
from core.pm_client import get_pm_client
from core.scheduler import get_scheduler
from advisors.xiaomei_advisor import get_xiaomei_advisor

# ---------------------------------------------------------------------------
# Stream 相关导入
# ---------------------------------------------------------------------------
HAS_STREAM = False
try:
    from dingtalk_stream import AckMessage, DingTalkStreamClient, ChatbotHandler, ChatbotMessage
    import dingtalk_stream
    HAS_STREAM = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
settings = get_settings(
    os.path.join(os.path.dirname(__file__), ".env")
)
stream_client: Any = None
stream_thread: threading.Thread | None = None

# ---------------------------------------------------------------------------
# Stream 消息处理器（仅在 SDK 安装时定义）
# ---------------------------------------------------------------------------

if HAS_STREAM:
    class XiaomeiChatbotHandler(ChatbotHandler):
        """小美机器人消息处理器：处理@消息"""

        def __init__(self, settings):
            super().__init__()
            self.settings = settings
            self.advisor = get_xiaomei_advisor()
            self.loop = asyncio.new_event_loop()

        async def raw_process(self, callback_message):
            """重写 raw_process 直接同步调用 process，捕获异常"""
            log_path = os.path.join(os.path.dirname(__file__), 'xiaomei_stream.log')
            try:
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{__import__('datetime').datetime.now().isoformat()}] raw_process called\n")
                    f.write(f"  topic={callback_message.headers.topic}\n")
                    f.write(f"  data_keys={list(callback_message.data.keys()) if callback_message.data else 'EMPTY'}\n")
                # 直接同步调用 process
                self.process(callback_message)
            except Exception as e:
                import traceback
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"  raw_process异常: {str(e)}\n")
                    f.write(traceback.format_exc() + "\n")

        def process(self, callback_message) -> AckMessage:
            """处理机器人消息"""
            try:
                # 从 CallbackMessage.data 提取 ChatbotMessage
                message = ChatbotMessage.from_dict(callback_message.data)

                # 写日志到文件
                log_path = os.path.join(os.path.dirname(__file__), 'xiaomei_stream.log')
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{__import__('datetime').datetime.now().isoformat()}] 收到消息 sender={message.sender_staff_id}\n")
                    f.write(f"  内容={message.text.content if message.text else 'None'}\n")
                    f.write(f"  is_in_at_list={message.is_in_at_list}\n")
                    f.write(f"  session_webhook={message.session_webhook}\n")

                print(f"[小美Stream] 收到消息 sender={message.sender_staff_id}")
                print(f"[小美Stream] 内容={message.text.content if message.text else 'None'}")
                print(f"[小美Stream] is_in_at_list={message.is_in_at_list}")

                if not message.is_in_at_list and "@" not in (message.text.content or ""):
                    return AckMessage.STATUS_OK, "OK"

                content = message.text.content if message.text else ""
                user_query = self._extract_query(content)
                print(f"[小美Stream] 处理查询: {user_query[:50]}")

                self.reply_text("⏳ 处理中...", message)

                asyncio.set_event_loop(self.loop)
                reply = self.loop.run_until_complete(self._handle_query(user_query))

                # 写日志
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"  回复内容={reply[:100]}\n")

                self.reply_text(reply, message)
                return AckMessage.STATUS_OK, "OK"

            except Exception as e:
                print(f"[小美Stream] 处理消息异常: {e}")
                import traceback
                traceback.print_exc()
                # 写日志
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"  异常: {str(e)}\n")
                    f.write(f"  {traceback.format_exc()}\n")
                self.reply_text(f"[小美] 处理消息时出错了，请稍后再试", message)
                return AckMessage.STATUS_OK, "OK"

        def _extract_query(self, content: str) -> str:
            """提取用户问题（去掉@部分）"""
            import re
            cleaned = re.sub(r"@[^\s]+", "", content).strip()
            return cleaned if cleaned else content

        async def _handle_query(self, query: str) -> str:
            """处理用户查询"""
            if "建议" in query or "今日" in query or "进度" in query:
                advice = await self.advisor.generate_advice()
                return advice
            return f"[小美] 收到你的消息：{query}\n\n我可以帮你查看项目进度、风险、里程碑等信息，请直接说「今日建议」或「项目进度」"

    def _start_stream_client(settings):
        """在后台线程中启动Stream客户端"""
        global stream_client, stream_thread

        if not settings.dingtalk_client_id or not settings.dingtalk_app_secret:
            print("[小美Stream] 未配置钉钉凭证，跳过Stream连接")
            return

        def run_stream():
            global stream_client
            credential = dingtalk_stream.Credential(
                settings.dingtalk_client_id,
                settings.dingtalk_app_secret,
            )
            stream_client = DingTalkStreamClient(credential)
            handler = XiaomeiChatbotHandler(settings)
            stream_client.register_callback_handler(ChatbotMessage.TOPIC, handler)
            print("[小美Stream] 正在连接钉钉Stream服务器...")
            stream_client.start_forever()

        stream_thread = threading.Thread(target=run_stream, daemon=True)
        stream_thread.start()
        print("[小美Stream] 后台线程已启动")

else:
    def _start_stream_client(settings):
        print("[小美Stream] dingtalk-stream SDK未安装，跳过Stream连接")


# ---------------------------------------------------------------------------
# 定时任务
# ---------------------------------------------------------------------------

async def send_daily_advice():
    """每日主动发送建议"""
    print(f"[小美] 执行每日建议任务 {datetime.now().isoformat()}")
    advisor = get_xiaomei_advisor()
    advice = await advisor.generate_advice()

    from core.dingtalk_client import get_dingtalk_client
    client = get_dingtalk_client(settings)
    await client.send_group_message(settings.target_chat_id, advice)
    print("[小美] 每日建议已发送")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：初始化调度器
    from core.scheduler import add_cron_job
    add_cron_job(send_daily_advice, hour=9, minute=0, id="xiaomei_daily")
    print("[小美] 定时任务已注册（每日9:00）")

    # 启动Stream连接（除非显式禁用）
    if os.environ.get("DISABLE_STREAM", "").lower() not in ("1", "true", "yes"):
        _start_stream_client(settings)
    else:
        print("[小美] DISABLE_STREAM=1，跳过Stream连接（由Hermes Gateway处理）")

    yield

    # 关闭时
    from core.scheduler import shutdown_scheduler
    shutdown_scheduler()
    print("[小美] 服务已关闭")


app = FastAPI(title="设计小美服务", lifespan=lifespan)


@app.get("/health")
async def health():
    """健康检查"""
    pm_status = "unknown"
    try:
        pm = get_pm_client()
        info = await pm.get_versions()
        pm_status = "connected" if "data" in info or "versions" in str(info) else "error"
    except Exception as e:
        pm_status = f"error: {str(e)[:50]}"

    return {
        "status": "ok",
        "service": "xiaomei_advisor",
        "name": "小美",
        "port": settings.service_port,
        "pm_system": pm_status,
        "stream_connected": stream_client is not None and stream_thread is not None and stream_thread.is_alive(),
    }


@app.post("/trigger/daily-advice")
async def trigger_daily_advice():
    """手动触发每日建议"""
    await send_daily_advice()
    return {"status": "ok", "message": "每日建议已发送"}


# ---------------------------------------------------------------------------
# 任务接收端点（总管调度用）
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    task: str
    context: str = ""
    notify_group: bool = True

@app.post("/task")
async def handle_task(req: TaskRequest):
    """接收总管分配的任务，处理后返回结果。如notify_group=True则主动发群消息汇报。"""
    print(f"[小美] 收到任务: {req.task[:60]}")

    advisor = get_xiaomei_advisor()
    result = await advisor.handle_task(req.task, req.context)

    # 如需要，主动发群消息汇报
    if req.notify_group and settings.target_chat_id:
        from core.dingtalk_client import get_dingtalk_client
        client = get_dingtalk_client(settings)
        markdown = (
            f"**[小美完成任务]**\n\n"
            f"任务：{req.task}\n\n"
            f"结果：\n{result}"
        )
        try:
            await client.send_group_message(settings.target_chat_id, markdown)
            print("[小美] 任务结果已发送到群里")
        except Exception as e:
            print(f"[小美] 发群消息失败: {e}")

    return {"status": "ok", "result": result}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SERVICE_PORT", settings.service_port))
    uvicorn.run(app, host="0.0.0.0", port=port)
