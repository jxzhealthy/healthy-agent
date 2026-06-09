"""File read/write tools."""
from healthy_agent.skill.base import Tool, SkillParam, SkillResult


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
            SkillParam(name="path", type="string", description="File path"),
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
