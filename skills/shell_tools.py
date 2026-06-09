"""Shell, HTTP, and Python eval tools."""
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


class PythonEvalTool(Tool):
    @property
    def name(self): return "python_eval"
    @property
    def description(self): return "Evaluate a Python expression or execute a short script. Returns the result or stdout."
    @property
    def parameters(self):
        return [SkillParam(name="code", type="string", description="Python code to evaluate")]

    async def execute(self, params, process=None, kernel=None):
        import asyncio
        import sys
        import tempfile
        import os
        code = params.get("code", "")
        if not code:
            return SkillResult(success=False, error="Missing 'code'")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            output = stdout.decode(errors="replace")[:30000]
            if proc.returncode == 0:
                return SkillResult(success=True, data=output or "(no output)")
            return SkillResult(success=False, data=output, error=stderr.decode(errors="replace")[:5000])
        except asyncio.TimeoutError:
            return SkillResult(success=False, error="Execution timed out (15s)")
        finally:
            os.unlink(path)
