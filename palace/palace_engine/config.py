"""Configuration loader for Palace engine."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()
PALACE_ROOT = Path(__file__).resolve().parent.parent
# 无论从仓库根还是 palace 目录启动，都尝试读取 palace/.env
load_dotenv(PALACE_ROOT / ".env", override=False)
ROLES_DIR = PALACE_ROOT / "roles"
SCENARIOS_DIR = PALACE_ROOT / "scenarios"

PLAYBOOK_PATH = Path(os.getenv(
    "PALACE_PLAYBOOK_PATH",
    str(PALACE_ROOT.parent / "PLAYBOOK.md"),
))

PALACE_PROVIDER = os.getenv("PALACE_PROVIDER", "mock")
PALACE_API_KEY = os.getenv("PALACE_API_KEY", "")
PALACE_API_BASE = os.getenv("PALACE_API_BASE", "")
PALACE_MODEL = os.getenv("PALACE_MODEL", "glm-4")


def load_role(role_id: str) -> dict:
    path = ROLES_DIR / f"{role_id}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_scenario(scenario_id: str) -> dict:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_provider():
    """Return the configured LLM provider instance."""
    if PALACE_PROVIDER == "mock":
        from .llm_client import MockProvider
        return MockProvider()
    if PALACE_PROVIDER == "openai_compatible":
        from .llm_client import OpenAICompatibleProvider
        if not PALACE_API_KEY:
            raise ValueError("PALACE_API_KEY is required for openai_compatible provider")
        return OpenAICompatibleProvider(
            api_key=PALACE_API_KEY,
            base_url=PALACE_API_BASE,
            model=PALACE_MODEL,
        )
    raise ValueError(f"Unknown provider: {PALACE_PROVIDER}")
