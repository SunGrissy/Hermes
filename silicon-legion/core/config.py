import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    多租户配置支持。
    各服务通过传入不同的 env_file 路径来加载各自的配置。
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PmSystem 连接配置（共享）
    pm_system_url: str = "http://192.168.20.160:8112"
    pm_service_key: str = ""

    # DingTalk 应用配置
    dingtalk_app_id: str = ""
    dingtalk_agent_id: str = ""
    dingtalk_client_id: str = ""
    dingtalk_app_secret: str = ""

    # 目标群
    target_chat_id: str = ""

    # 服务端口
    service_port: int = 8299

    # Kimi LLM 配置
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.kimi.com/coding"
    kimi_model: str = "kimi-k2.6"
    kimi_api_type: str = "anthropic"  # "openai" or "anthropic"


def _load_pm_service_key() -> str:
    """如果未配置 pm_service_key，尝试从 PmSystem 本地 .env 读取 SERVICE_API_KEY。"""
    pm_env = "D:/MyAgents/pm-system/backend/.env"
    if os.path.exists(pm_env):
        with open(pm_env, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SERVICE_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return val
    return ""


@lru_cache()
def get_settings(env_file: str | None = None) -> Settings:
    """
    获取配置实例。

    Args:
        env_file: 环境变量文件路径。为 None 时使用默认路径（调用方所在目录的 .env）。
    """
    kwargs = {}
    if env_file and os.path.exists(env_file):
        kwargs["_env_file"] = env_file

    s = Settings(**kwargs)

    # 补充读取 PmSystem 的 API Key
    if not s.pm_service_key:
        s.pm_service_key = _load_pm_service_key()

    return s
