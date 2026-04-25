"""
硅基军团 总管服务（满满大人）
端口: 8299

职责:
1. 健康监控：检查各Advisor服务状态
2. 任务调度：定时触发各Advisor生成建议
3. 消息转发：接收群消息，分发给各Advisor
4. 认知汇聚：汇总各Advisor输出，提出冲突解决方案
"""

import os
import sys
import httpx
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel

# 路径设置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.config import get_settings
from core.pm_client import get_pm_client
from core.scheduler import get_scheduler, add_cron_job, shutdown_scheduler

settings = get_settings()

# Advisor 服务地址
ADVISOR_SERVICES = {
    "pm": "http://localhost:8301",      # 阿茶
    "design": "http://localhost:8302",  # 小美
    "care": "http://localhost:8303",    # 妙妙
}


# ---------------------------------------------------------------------------
# 调度逻辑
# ---------------------------------------------------------------------------

async def trigger_advisor(advisor_type: str, endpoint: str = "/trigger/daily-advice"):
    """通过HTTP触发指定Advisor"""
    base_url = ADVISOR_SERVICES.get(advisor_type)
    if not base_url:
        print(f"[总管] 未知Advisor类型: {advisor_type}")
        return

    url = f"{base_url}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url)
            data = resp.json()
            print(f"[总管] 触发{advisor_type}完成: {data}")
    except Exception as e:
        print(f"[总管] 触发{advisor_type}失败: {e}")


async def run_daily_flow():
    """每日流程：依次触发各Advisor"""
    print(f"[总管] 每日流程开始 {datetime.now().isoformat()}")
    # MVP版先只触发阿茶
    await trigger_advisor("pm")
    print(f"[总管] 每日流程结束")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    print(f"[总管] 服务启动 - 端口{settings.service_port}")
    # 注册每日9:00定时任务
    add_cron_job(run_daily_flow, hour=9, minute=0, id="director_daily")
    print("[总管] 每日9:00定时任务已注册")
    yield
    # 关闭时
    shutdown_scheduler()
    print("[总管] 服务已关闭")


app = FastAPI(
    title="Silicon Legion Director",
    version="0.2.0",
    description="硅基军团总管服务",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """健康检查：检查总管本身及各Advisor"""
    pm_status = "unknown"
    try:
        pm = get_pm_client()
        info = await pm.get_versions()
        pm_status = "connected"
    except Exception as e:
        pm_status = f"error: {str(e)[:50]}"

    # 检查各Advisor
    advisor_status = {}
    for name, url in ADVISOR_SERVICES.items():
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/health")
                advisor_status[name] = resp.json()
        except Exception as e:
            advisor_status[name] = {"status": "error", "error": str(e)[:50]}

    return {
        "status": "ok",
        "service": "director",
        "name": "满满大人",
        "version": "0.2.0",
        "timestamp": datetime.now().isoformat(),
        "pm_system": pm_status,
        "advisors": advisor_status,
    }


@app.post("/trigger/daily-flow")
async def trigger_daily():
    """手动触发每日流程"""
    await run_daily_flow()
    return {"status": "ok", "message": "每日流程已触发"}


@app.post("/trigger/advisor/{advisor_type}")
async def trigger_specific_advisor(advisor_type: str):
    """手动触发指定Advisor"""
    await trigger_advisor(advisor_type)
    return {"status": "ok", "advisor": advisor_type}


# ---------------------------------------------------------------------------
# 群消息回调（用户召唤总管时）
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    chat_id: str
    sender_id: str
    sender_name: str
    content: str
    msg_type: str = "text"


@app.post("/webhook/chat-message")
async def on_chat_message(msg: ChatMessage):
    """接收群消息（由外部转发）
    TODO: 实现消息解析与分发逻辑
    """
    print(f"[总管] 收到消息 from {msg.sender_name}: {msg.content[:50]}")
    return {"status": "received"}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SERVICE_PORT", settings.service_port))
    uvicorn.run(app, host="0.0.0.0", port=port)
