from __future__ import annotations

import os

import anthropic

from .base import LLMDriver, IOResult


class AnthropicDriver(LLMDriver):
    def __init__(
        self,
        *,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.max_tokens = max_tokens
        resolved_key = api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
        resolved_base = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        old_token = os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        self._client = anthropic.AsyncAnthropic(
            api_key=resolved_key,
            base_url=resolved_base,
            default_headers={"User-Agent": "claude-code/1.0"},
        )
        if old_token is not None:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = old_token

    @property
    def name(self) -> str:
        return f"anthropic:{self.model}"

    async def generate(self, messages: list[dict], **kwargs) -> IOResult:
        try:
            response = await self._client.messages.create(
                model=kwargs.get("model", self.model),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                system=kwargs.get("system", "You are a helpful assistant."),
                messages=messages,
                tools=kwargs.get("tools"),
            )
            text_parts = []
            tool_calls = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            return IOResult(
                success=True,
                data={
                    "text": "".join(text_parts),
                    "tool_calls": tool_calls,
                    "stop_reason": response.stop_reason,
                },
                tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            )
        except Exception as e:
            return IOResult(success=False, error=str(e))

    async def stream(self, messages: list[dict], **kwargs):
        async with self._client.messages.stream(
            model=kwargs.get("model", self.model),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            system=kwargs.get("system", "You are a helpful assistant."),
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
