import httpx
from typing import Optional, Dict, Any
from core.config import Settings


class PmSystemClient:
    """PmSystem API 客户端
    
    使用 X-Api-Key 认证，仅读取数据
    """

    def __init__(self, settings: Optional[Settings] = None):
        from core.config import get_settings
        self.settings = settings or get_settings()
        self.base_url = self.settings.pm_system_url.rstrip("/")
        self.api_key = self.settings.pm_service_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-Api-Key": self.api_key},
            timeout=30.0,
        )

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        resp = await self._client.get("/api/health")
        resp.raise_for_status()
        return resp.json()

    async def get_full_data(self) -> Dict[str, Any]:
        """获取整包数据（包含版本、Feature、任务等）"""
        resp = await self._client.get("/api/data")
        resp.raise_for_status()
        return resp.json()

    async def get_data_meta(self) -> Dict[str, Any]:
        """获取数据元信息"""
        resp = await self._client.get("/api/data/meta")
        resp.raise_for_status()
        return resp.json()

    async def get_pm_calendar(self) -> Dict[str, Any]:
        """获取PM日历（工作日/假日）"""
        resp = await self._client.get("/api/pm-calendar")
        resp.raise_for_status()
        return resp.json()

    async def get_versions(self) -> Dict[str, Any]:
        """获取版本列表"""
        data = await self.get_full_data()
        return {"data": data.get("versions", [])}

    async def get_features(self) -> Dict[str, Any]:
        """获取Feature列表"""
        data = await self.get_full_data()
        return {"data": data.get("features", [])}

    async def get_tasks(self) -> Dict[str, Any]:
        """获取任务列表"""
        data = await self.get_full_data()
        # 从 features 中提取 tasks
        tasks = []
        for f in data.get("features", []):
            for t in f.get("tasks", []):
                t["feature_name"] = f.get("name", "")
                t["feature_id"] = f.get("id", "")
                tasks.append(t)
        return {"data": tasks}

    async def get_milestones(self) -> Dict[str, Any]:
        """获取里程碑列表"""
        data = await self.get_full_data()
        return {"data": data.get("milestones", [])}

    async def get_teams(self) -> Dict[str, Any]:
        """获取团队列表"""
        data = await self.get_full_data()
        return {"data": data.get("teams", [])}

    async def get_planner_items(self) -> Dict[str, Any]:
        """获取策划周计划项"""
        data = await self.get_full_data()
        return {"data": data.get("plannerItems", [])}

    async def close(self):
        """关闭HTTP客户端"""
        await self._client.aclose()


def get_pm_client(settings: Optional[Settings] = None) -> PmSystemClient:
    return PmSystemClient(settings=settings)
