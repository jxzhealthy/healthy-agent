from __future__ import annotations

import asyncio

import httpx

from .base import ToolDriver, IOResult


class ShellDriver(ToolDriver):
    def __init__(self, *, timeout: float = 30.0):
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "shell"

    def capabilities(self) -> list[str]:
        return ["exec"]

    async def invoke(self, action: str, params: dict) -> IOResult:
        command = params.get("command", "")
        if not command:
            return IOResult(success=False, error="Missing 'command'")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            return IOResult(
                success=proc.returncode == 0,
                data={"stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace")},
                error="" if proc.returncode == 0 else stderr.decode(errors="replace")[:500],
            )
        except asyncio.TimeoutError:
            return IOResult(success=False, error=f"Timed out after {self._timeout}s")
        except Exception as e:
            return IOResult(success=False, error=str(e))


class HttpDriver(ToolDriver):
    def __init__(self, *, timeout: float = 30.0):
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "http"

    def capabilities(self) -> list[str]:
        return ["get", "post"]

    async def invoke(self, action: str, params: dict) -> IOResult:
        url = params.get("url", "")
        if not url:
            return IOResult(success=False, error="Missing 'url'")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                if action == "post":
                    resp = await client.post(url, json=params.get("body"))
                else:
                    resp = await client.get(url)
                return IOResult(
                    success=resp.is_success,
                    data={"status": resp.status_code, "body": resp.text[:50000]},
                    error="" if resp.is_success else f"HTTP {resp.status_code}",
                )
        except Exception as e:
            return IOResult(success=False, error=str(e))
