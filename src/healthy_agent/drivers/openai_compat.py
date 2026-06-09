from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import LLMDriver, IOResult


class OpenAICompatDriver(LLMDriver):
    """Driver for any OpenAI-compatible API (OpenAI, DeepSeek, Zhipu, Ollama, vLLM, etc.)."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        max_tokens: int = 4096,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or ""

    @property
    def name(self) -> str:
        return f"openai_compat:{self.model}"

    async def generate(self, messages: list[dict], **kwargs) -> IOResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "messages": self._build_messages(messages, kwargs.get("system")),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            choice = data["choices"][0]
            text = choice["message"].get("content", "")
            tool_calls = choice["message"].get("tool_calls", [])
            usage = data.get("usage", {})

            return IOResult(
                success=True,
                data={
                    "text": text,
                    "tool_calls": tool_calls,
                    "finish_reason": choice.get("finish_reason", ""),
                },
                tokens_used=usage.get("total_tokens", 0),
            )
        except Exception as e:
            return IOResult(success=False, error=str(e))

    async def stream(self, messages: list[dict], **kwargs):
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "messages": self._build_messages(messages, kwargs.get("system")),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions",
                headers=headers, json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    def _build_messages(self, messages: list[dict], system: str | None) -> list[dict]:
        result = []
        if system:
            result.append({"role": "system", "content": system})
        result.extend(messages)
        return result


class DeepSeekDriver(OpenAICompatDriver):
    """DeepSeek API driver."""

    def __init__(self, *, model: str = "deepseek-chat", api_key: str | None = None, **kwargs):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com/v1",
            **kwargs,
        )

    @property
    def name(self) -> str:
        return f"deepseek:{self.model}"


class ZhipuDriver(OpenAICompatDriver):
    """Zhipu (GLM) API driver."""

    def __init__(self, *, model: str = "glm-4", api_key: str | None = None, **kwargs):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("ZHIPU_API_KEY", ""),
            base_url="https://open.bigmodel.cn/api/paas/v4",
            **kwargs,
        )

    @property
    def name(self) -> str:
        return f"zhipu:{self.model}"


class OpenAIDriver(OpenAICompatDriver):
    """OpenAI API driver."""

    def __init__(self, *, model: str = "gpt-4o", api_key: str | None = None, **kwargs):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url="https://api.openai.com/v1",
            **kwargs,
        )

    @property
    def name(self) -> str:
        return f"openai:{self.model}"


class QwenDriver(OpenAICompatDriver):
    """Qwen (Tongyi Qianwen) via DashScope API."""

    def __init__(self, *, model: str = "qwen-plus", api_key: str | None = None, **kwargs):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("DASHSCOPE_API_KEY", ""),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            **kwargs,
        )

    @property
    def name(self) -> str:
        return f"qwen:{self.model}"


class OllamaDriver(OpenAICompatDriver):
    """Ollama local model driver."""

    def __init__(self, *, model: str = "llama3", base_url: str = "http://localhost:11434/v1", **kwargs):
        super().__init__(
            model=model,
            api_key="ollama",
            base_url=base_url,
            **kwargs,
        )

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"
