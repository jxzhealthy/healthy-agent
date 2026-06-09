from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Tool, Skill, SkillParam, SkillResult

if TYPE_CHECKING:
    pass


# ── Tools (pure execution, no LLM) ──────────────────────────

class ReadFileTool(Tool):
    @property
    def name(self): return "read_file"
    @property
    def description(self): return "Read the content of a file at the given path."
    @property
    def parameters(self):
        return [SkillParam(name="path", type="string", description="File path to read")]

    async def execute(self, params, process=None, kernel=None):
        from pathlib import Path
        path = params.get("path", "")
        if not path:
            return SkillResult(success=False, error="Missing 'path'")
        try:
            return SkillResult(success=True, data=Path(path).read_text(encoding="utf-8", errors="replace")[:50000])
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class WriteFileTool(Tool):
    @property
    def name(self): return "write_file"
    @property
    def description(self): return "Write content to a file at the given path."
    @property
    def parameters(self):
        return [
            SkillParam(name="path", type="string", description="File path to write"),
            SkillParam(name="content", type="string", description="Content to write"),
        ]

    async def execute(self, params, process=None, kernel=None):
        from pathlib import Path
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return SkillResult(success=False, error="Missing 'path'")
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return SkillResult(success=True, data=f"Written {len(content)} bytes to {path}")
        except Exception as e:
            return SkillResult(success=False, error=str(e))


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
            SkillParam(name="url", type="string", description="URL to request"),
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


# ── Skills (use LLM) ────────────────────────────────────────

class SummarizeSkill(Skill):
    @property
    def name(self): return "summarize"
    @property
    def description(self): return "Summarize text using LLM."
    @property
    def parameters(self):
        return [
            SkillParam(name="text", type="string", description="Text to summarize"),
            SkillParam(name="max_sentences", type="integer", description="Max sentences", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        text = params.get("text", "")
        max_s = params.get("max_sentences", 3)
        if not text:
            return SkillResult(success=False, error="Missing 'text'")
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data=f"[mock] Would summarize {len(text)} chars")
        result = await driver.generate(
            [{"role": "user", "content": f"Summarize in {max_s} sentences:\n\n{text}"}],
            system=f"Write exactly {max_s} sentences.",
        )
        return SkillResult(success=result.success, data=result.data["text"].strip() if result.success else "", error=result.error)


class CodeGenSkill(Skill):
    @property
    def name(self): return "code_gen"
    @property
    def description(self): return "Generate code using LLM."
    @property
    def parameters(self):
        return [
            SkillParam(name="task", type="string", description="What code to write"),
            SkillParam(name="language", type="string", description="Programming language", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        task = params.get("task", "")
        lang = params.get("language", "Python")
        if not task:
            return SkillResult(success=False, error="Missing 'task'")
        driver = params.get("_driver")
        if not driver:
            return SkillResult(success=True, data=f"[mock] Would generate {lang} code for: {task}")
        result = await driver.generate(
            [{"role": "user", "content": f"Write {lang} code: {task}. Output only code."}],
            system="Output only raw code, no markdown.",
        )
        return SkillResult(success=result.success, data=result.data["text"].strip() if result.success else "", error=result.error)


class WebSearchSkill(Skill):
    @property
    def name(self): return "web_search"
    @property
    def description(self): return "Search the web for information."
    @property
    def parameters(self):
        return [SkillParam(name="query", type="string", description="Search query")]

    async def execute(self, params, process=None, kernel=None):
        query = params.get("query", "")
        if not query:
            return SkillResult(success=False, error="Missing 'query'")
        return SkillResult(success=True, data=f"[mock] Would search: {query}")
