from __future__ import annotations

import asyncio
import json
from typing import Any

from .protocol import McpRequest, McpResponse


class McpClient:
    """MCP Client — connects to external MCP servers via subprocess (stdio).

    Supports tools, resources, and prompts protocols.
    """

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def connect(self, command: list[str]) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def disconnect(self) -> None:
        if self._proc:
            self._proc.terminate()
            await self._proc.wait()
            self._proc = None

    @property
    def connected(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    # --- Initialize ---

    async def initialize(self) -> dict:
        return await self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "healthy-agent-client", "version": "0.2.0"},
        })

    # --- Tools ---

    async def list_tools(self) -> list[dict]:
        result = await self._call("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        result = await self._call("tools/call", {"name": name, "arguments": arguments or {}})
        content = result.get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    # --- Resources ---

    async def list_resources(self) -> list[dict]:
        result = await self._call("resources/list", {})
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI. Returns the first content item."""
        result = await self._call("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        if not contents:
            return {}
        return contents[0]

    async def subscribe_resource(self, uri: str) -> None:
        await self._call("resources/subscribe", {"uri": uri})

    # --- Prompts ---

    async def list_prompts(self) -> list[dict]:
        result = await self._call("prompts/list", {})
        return result.get("prompts", [])

    async def get_prompt(self, name: str, arguments: dict | None = None) -> dict[str, Any]:
        """Get a prompt by name with optional arguments."""
        result = await self._call("prompts/get", {
            "name": name,
            "arguments": arguments or {},
        })
        return result

    # --- Transport ---

    async def _call(self, method: str, params: dict) -> dict:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise ConnectionError("Not connected")

        self._request_id += 1
        request = McpRequest(method=method, params=params, id=self._request_id)
        self._proc.stdin.write((request.serialize() + "\n").encode())
        await self._proc.stdin.drain()

        line = await self._proc.stdout.readline()
        if not line:
            raise ConnectionError("Server closed")
        response = McpResponse.deserialize(json.loads(line.decode()))
        if response.error:
            raise RuntimeError(f"MCP error: {response.error}")
        return response.result or {}
