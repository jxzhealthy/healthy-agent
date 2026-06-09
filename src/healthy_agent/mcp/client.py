from __future__ import annotations

import asyncio
import json

from .protocol import McpRequest, McpResponse


class McpClient:
    """MCP Client — connects to external MCP servers via subprocess (stdio)."""

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

    async def initialize(self) -> dict:
        return await self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "healthy-agent-client", "version": "0.1.0"},
        })

    async def list_tools(self) -> list[dict]:
        result = await self._call("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        result = await self._call("tools/call", {"name": name, "arguments": arguments or {}})
        content = result.get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

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
