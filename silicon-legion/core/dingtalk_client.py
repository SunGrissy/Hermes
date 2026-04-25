import time
import httpx
from typing import Optional, List, Dict, Any
from core.config import Settings


class DingTalkClient:
    """钉钉官方API客户端
    支持：
    - 获取access_token
    - 发送群消息（机器人webhook或聊天API）
    - 读取群历史消息
    """

    def __init__(self, settings: Optional[Settings] = None):
        from core.config import get_settings
        self.settings = settings or get_settings()
        self.app_key = self.settings.dingtalk_client_id
        self.app_secret = self.settings.dingtalk_app_secret
        self._access_token: Optional[str] = None
        self._token_expire: float = 0

    async def _get_access_token(self) -> str:
        """获取应用级access_token（新版企业内部应用接口）"""
        if self._access_token and time.time() < self._token_expire - 60:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        body = {
            "appKey": self.app_key,
            "appSecret": self.app_secret,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body)
            data = resp.json()
            if "accessToken" not in data:
                # 尝试旧版接口
                old_url = "https://oapi.dingtalk.com/gettoken"
                old_resp = await client.get(old_url, params={"appkey": self.app_key, "appsecret": self.app_secret})
                old_data = old_resp.json()
                if old_data.get("errcode") != 0:
                    raise RuntimeError(f"DingTalk token error: {data} / {old_data}")
                self._access_token = old_data["access_token"]
                self._token_expire = time.time() + old_data.get("expires_in", 7200)
                return self._access_token
            self._access_token = data["accessToken"]
            self._token_expire = time.time() + data.get("expireIn", 7200)
            return self._access_token

    async def send_group_message(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "markdown",
        at_users: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """通过聊天API发送群消息
        
        Args:
            chat_id: 群会话ID
            content: 消息内容（markdown格式）
            msg_type: 消息类型，默认markdown
            at_users: 需要@ 的用户ID列表
        """
        token = await self._get_access_token()
        url = f"https://oapi.dingtalk.com/chat/send?access_token={token}"

        if msg_type == "markdown":
            body = {
                "chatid": chat_id,
                "msg": {
                    "msgtype": "markdown",
                    "markdown": {"title": content.split("\n")[0][:20], "text": content},
                },
            }
        else:
            body = {
                "chatid": chat_id,
                "msg": {
                    "msgtype": "text",
                    "text": {"content": content},
                },
            }

        if at_users:
            body["msg"]["at"] = {"atUserIds": at_users}

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body)
            return resp.json()

    async def get_group_messages(
        self,
        chat_id: str,
        cursor: Optional[str] = None,
        size: int = 20,
    ) -> Dict[str, Any]:
        """获取群历史消息
        注意：此接口需要应用有对应权限，且可能有调用频率限制
        """
        token = await self._get_access_token()
        url = f"https://oapi.dingtalk.com/topapi/im/chat/scene/group/message/query?access_token={token}"

        body = {
            "open_conversation_id": chat_id,
            "cursor": cursor,
            "size": size,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body)
            return resp.json()

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """获取群会话信息"""
        token = await self._get_access_token()
        url = f"https://oapi.dingtalk.com/chat/get?access_token={token}&chatid={chat_id}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            return resp.json()


def get_dingtalk_client(settings: Optional[Settings] = None) -> DingTalkClient:
    return DingTalkClient(settings=settings)
