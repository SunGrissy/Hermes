"""
定时任务调度器
支持：每日9:00自动触发、用户主动召唤
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from typing import Callable, Optional

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def init_scheduler():
    """初始化定时器"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        print(f"[调度器] APScheduler 已启动 - {datetime.now().isoformat()}")


def schedule_daily_task(hour: int, minute: int, callback: Callable):
    """设置每日定时任务
    
    Args:
        hour: 小时 (0-23)
        minute: 分钟 (0-59)
        callback: 异步回调函数
    """
    scheduler = get_scheduler()
    trigger = CronTrigger(hour=hour, minute=minute)
    
    job = scheduler.add_job(
        callback,
        trigger=trigger,
        id="daily_advice",
        name="每日工作建议",
        replace_existing=True,
    )
    print(f"[调度器] 每日任务已配置: {hour:02d}:{minute:02d}")
    return job


def add_cron_job(callback, hour: int, minute: int, id: str):
    """添加每日定时任务（新API）"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    trigger = CronTrigger(hour=hour, minute=minute)
    job = scheduler.add_job(
        callback,
        trigger=trigger,
        id=id,
        replace_existing=True,
    )
    print(f"[调度器] Cron任务已添加: {hour:02d}:{minute:02d} id={id}")
    return job


def shutdown_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        _scheduler = None
        print("[调度器] 已关闭")
