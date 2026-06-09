from __future__ import annotations

import json
from typing import Any, Callable

from .protocol import (
    McpRequest, McpResponse, McpError,
    MCP_PROTOCOL_VERSION, METHOD_NOT_FOUND, INTERNAL_ERROR, PARSE_ERROR,
)


class McpServer:
    """MCP Server — exposes healthy_agent capabilities via tools, resources, and prompts."""

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._tools: list[dict] = []
        self._resources: dict[str, dict] = {}
        self._prompts: dict[str, dict] = {}
        self._resource_subscriptions: dict[str, list[Callable]] = {}
        self._setup_builtins()

    def _setup_builtins(self) -> None:
        self._handlers["initialize"] = self._handle_initialize
        self._handlers["tools/list"] = self._handle_tools_list
        self._handlers["tools/call"] = self._handle_tools_call
        self._handlers["resources/list"] = self._handle_resources_list
        self._handlers["resources/read"] = self._handle_resources_read
        self._handlers["resources/subscribe"] = self._handle_resources_subscribe
        self._handlers["prompts/list"] = self._handle_prompts_list
        self._handlers["prompts/get"] = self._handle_prompts_get

    # --- Tool registration ---

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

    # --- Resource registration ---

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str = "",
        mime_type: str = "text/plain",
        provider: Callable[..., Any] | None = None,
        static_content: str | None = None,
    ) -> None:
        """Register a resource that clients can read.

        Args:
            uri: Unique resource URI (e.g. "file:///config.json").
            name: Human-readable name.
            description: Resource description.
            mime_type: MIME type of the content.
            provider: Async callable returning content string. Called on each read.
            static_content: Fixed content. Used if provider is None.
        """
        self._resources[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mimeType": mime_type,
            "_provider": provider,
            "_static": static_content,
        }

    # --- Prompt registration ---

    def register_prompt(
        self,
        name: str,
        description: str = "",
        arguments: list[dict] | None = None,
        template: str = "",
        handler: Callable[..., Any] | None = None,
    ) -> None:
        """Register a prompt template.

        Args:
            name: Unique prompt name.
            description: Prompt description.
            arguments: List of argument descriptors, e.g.
                       [{"name": "topic", "description": "...", "required": True}]
            template: Static template string with {arg_name} placeholders.
            handler: Async callable(arguments) -> list[dict]. Used if template is empty.
        """
        self._prompts[name] = {
            "name": name,
            "description": description,
            "arguments": arguments or [],
            "_template": template,
            "_handler": handler,
        }

    # --- Message dispatch ---

    async def handle_message(self, msg: dict) -> str:
        try:
            request = McpRequest.deserialize(msg)
        except (KeyError, TypeError):
            return McpResponse(
                error=McpError(PARSE_ERROR, "Invalid request").to_dict(),
                id=msg.get("id", 0),
            ).serialize()

        handler = self._handlers.get(request.method)
        if not handler:
            return McpResponse(
                error=McpError(METHOD_NOT_FOUND, f"Unknown: {request.method}").to_dict(),
                id=request.id,
            ).serialize()

        try:
            result = await handler(request.params)
            return McpResponse(result=result, id=request.id).serialize()
        except Exception as exc:
            return McpResponse(
                error=McpError(INTERNAL_ERROR, str(exc)).to_dict(),
                id=request.id,
            ).serialize()

    # --- Built-in handlers ---

    async def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
                "resources": {"subscribe": True},
                "prompts": {},
            },
            "serverInfo": {"name": "healthy-agent", "version": "0.2.0"},
        }

    async def _handle_tools_list(self, params: dict) -> dict:
        tools = [
            {k: v for k, v in t.items() if not k.startswith("_")}
            for t in self._tools
        ]
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        for tool in self._tools:
            if tool["name"] == name:
                result = await tool["_handler"](arguments)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }

    async def _handle_resources_list(self, params: dict) -> dict:
        resources = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in self._resources.values()
        ]
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        resource = self._resources.get(uri)
        if not resource:
            raise ValueError(f"Resource not found: {uri}")

        provider = resource.get("_provider")
        if provider:
            content = await provider()
        else:
            content = resource.get("_static", "")

        return {
            "contents": [{
                "uri": uri,
                "mimeType": resource["mimeType"],
                "text": content if isinstance(content, str) else json.dumps(content),
            }],
        }

    async def _handle_resources_subscribe(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if uri not in self._resources:
            raise ValueError(f"Resource not found: {uri}")
        return {}

    async def _handle_prompts_list(self, params: dict) -> dict:
        prompts = [
            {k: v for k, v in p.items() if not k.startswith("_")}
            for p in self._prompts.values()
        ]
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        prompt = self._prompts.get(name)
        if not prompt:
            raise ValueError(f"Prompt not found: {name}")

        handler = prompt.get("_handler")
        if handler:
            messages = await handler(arguments)
        else:
            template = prompt.get("_template", "")
            text = template.format(**arguments) if arguments else template
            messages = [{"role": "user", "content": {"type": "text", "text": text}}]

        return {"description": prompt.get("description", ""), "messages": messages}
