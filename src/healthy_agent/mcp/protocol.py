from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

METHOD_NOT_FOUND = -32601
PARSE_ERROR = -32700
INTERNAL_ERROR = -32603


@dataclass
class McpRequest:
    method: str
    params: dict = field(default_factory=dict)
    id: int | str = 0

    def serialize(self) -> str:
        return json.dumps({"jsonrpc": JSONRPC_VERSION, "method": self.method, "params": self.params, "id": self.id})

    @classmethod
    def deserialize(cls, data: str | dict) -> McpRequest:
        d = json.loads(data) if isinstance(data, str) else data
        return cls(method=d["method"], params=d.get("params", {}), id=d.get("id", 0))


@dataclass
class McpResponse:
    result: Any = None
    error: dict | None = None
    id: int | str = 0

    def serialize(self) -> str:
        d: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return json.dumps(d)

    @classmethod
    def deserialize(cls, data: str | dict) -> McpResponse:
        d = json.loads(data) if isinstance(data, str) else data
        return cls(result=d.get("result"), error=d.get("error"), id=d.get("id", 0))


@dataclass
class McpError:
    code: int
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}
