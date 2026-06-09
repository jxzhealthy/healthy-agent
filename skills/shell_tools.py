"""Shell and HTTP tools."""
from healthy_agent.skill.base import Tool, SkillParam, SkillResult


class ShellTool(Tool):
    @property
    def name(self): return "shell"
    @property
    def description(self): return "Execute a shell command and return stdout/stderr."
    @property
    def parameters(self):
        return [SkillParam(name="command", type="string", description="Shell command")]

    async def execute(self, params, process=None, kernel=None):
        import asyncio
        command = params.get("command", "")
        if not command:
            return SkillResult(success=False, error="Missing 'command'")
        try:
            proc = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            output = stdout.decode(errors="replace")[:50000]
            if proc.returncode == 0:
                return SkillResult(success=True, data=output)
            return SkillResult(success=False, data=output, error=stderr.decode(errors="replace")[:5000])
        except asyncio.TimeoutError:
            return SkillResult(success=False, error="Command timed out")


class HttpTool(Tool):
    @property
    def name(self): return "http_request"
    @property
    def description(self): return "Make an HTTP GET or POST request."
    @property
    def parameters(self):
        return [
            SkillParam(name="url", type="string", description="URL"),
            SkillParam(name="method", type="string", description="GET or POST", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        import httpx
        url = params.get("url", "")
        method = params.get("method", "GET").upper()
        if not url:
            return SkillResult(success=False, error="Missing 'url'")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(method, url)
                return SkillResult(success=resp.is_success, data=resp.text[:50000])
        except Exception as e:
            return SkillResult(success=False, error=str(e))
