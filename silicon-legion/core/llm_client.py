"""
通用 LLM 客户端
支持 OpenAI-compatible API 和 Anthropic Messages API
"""

import os
import httpx
from typing import Optional


class LLMClient:
    """异步 LLM 调用封装"""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4",
        api_type: str = "openai",  # "openai" or "anthropic"
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_type = api_type

    async def chat(self, system_prompt: str, user_message: str, temperature: float = 0.7, max_tokens: int = 4096) -> str:
        if self.api_type == "anthropic":
            return await self._chat_anthropic(system_prompt, user_message, temperature, max_tokens)
        return await self._chat_openai(system_prompt, user_message, temperature, max_tokens)

    async def _chat_openai(self, system_prompt: str, user_message: str, temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _chat_anthropic(self, system_prompt: str, user_message: str, temperature: float, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
