from __future__ import annotations

import json
from typing import Callable

from .protocol import (
    McpRequest, McpResponse, McpError,
    MCP_PROTOCOL_VERSION, METHOD_NOT_FOUND, INTERNAL_ERROR, PARSE_ERROR,
)


class McpServer:
    """MCP Server — exposes healthy_agent capabilities as tools."""

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._tools: list[dict] = []
        self._setup_builtins()

    def _setup_builtins(self) -> None:
        self._handlers["initialize"] = self._handle_initialize
        self._handlers["tools/list"] = self._handle_tools_list
        self._handlers["tools/call"] = self._handle_tools_call

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable,
    ) -> None:
        self._tools.append({
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "_handler": handler,
        })

    async def handle_message(self, msg: dict) -> str:
        try:
            request = McpRequest.deserialize(msg)
        except (KeyError, TypeError):
            return McpResponse(error=McpError(PARSE_ERROR, "Invalid request").to_dict(), id=msg.get("id", 0)).serialize()

        handler = self._handlers.get(request.method)
        if not handler:
            return McpResponse(error=McpError(METHOD_NOT_FOUND, f"Unknown: {request.method}").to_dict(), id=request.id).serialize()

        try:
            result = await handler(request.params)
            return McpResponse(result=result, id=request.id).serialize()
        except Exception as e:
            return McpResponse(error=McpError(INTERNAL_ERROR, str(e)).to_dict(), id=request.id).serialize()

    async def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "healthy-agent", "version": "0.1.0"},
        }

    async def _handle_tools_list(self, params: dict) -> dict:
        return {"tools": [{k: v for k, v in t.items() if k != "_handler"} for t in self._tools]}

    async def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        for tool in self._tools:
            if tool["name"] == name:
                result = await tool["_handler"](arguments)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
