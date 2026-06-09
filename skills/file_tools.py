"""File tools: read, write, list, search, edit."""
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
    def description(self): return "Write content to a file at the given path. Overwrites existing content."
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


class EditFileTool(Tool):
    @property
    def name(self): return "edit_file"
    @property
    def description(self): return "Replace a specific string in a file with new content. Fails if old_str is not found."
    @property
    def parameters(self):
        return [
            SkillParam(name="path", type="string", description="File path"),
            SkillParam(name="old_str", type="string", description="Exact string to find and replace"),
            SkillParam(name="new_str", type="string", description="Replacement string"),
        ]

    async def execute(self, params, process=None, kernel=None):
        from pathlib import Path
        path = params.get("path", "")
        old_str = params.get("old_str", "")
        new_str = params.get("new_str", "")
        if not path or not old_str:
            return SkillResult(success=False, error="Missing 'path' or 'old_str'")
        try:
            p = Path(path)
            content = p.read_text(encoding="utf-8")
            if old_str not in content:
                return SkillResult(success=False, error=f"String not found in {path}")
            new_content = content.replace(old_str, new_str, 1)
            p.write_text(new_content, encoding="utf-8")
            return SkillResult(success=True, data=f"Replaced in {path}")
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class ListDirTool(Tool):
    @property
    def name(self): return "list_dir"
    @property
    def description(self): return "List files and directories at the given path."
    @property
    def parameters(self):
        return [
            SkillParam(name="path", type="string", description="Directory path (default: .)"),
            SkillParam(name="recursive", type="boolean", description="Include subdirectories", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        from pathlib import Path
        path = params.get("path", ".")
        recursive = params.get("recursive", False)
        try:
            p = Path(path)
            if not p.exists():
                return SkillResult(success=False, error=f"Path not found: {path}")
            if recursive:
                entries = [str(f.relative_to(p)) for f in sorted(p.rglob("*")) if not any(part.startswith(".") for part in f.parts)][:200]
            else:
                entries = [f.name + ("/" if f.is_dir() else "") for f in sorted(p.iterdir()) if not f.name.startswith(".")]
            return SkillResult(success=True, data="\n".join(entries))
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class SearchTextTool(Tool):
    @property
    def name(self): return "search_text"
    @property
    def description(self): return "Search for a text pattern in files (like grep). Returns matching lines with file paths."
    @property
    def parameters(self):
        return [
            SkillParam(name="pattern", type="string", description="Text or regex to search for"),
            SkillParam(name="path", type="string", description="File or directory to search in", required=False),
        ]

    async def execute(self, params, process=None, kernel=None):
        import re
        from pathlib import Path
        pattern = params.get("pattern", "")
        path = params.get("path", ".")
        if not pattern:
            return SkillResult(success=False, error="Missing 'pattern'")
        try:
            p = Path(path)
            matches = []
            files = [p] if p.is_file() else sorted(p.rglob("*"))
            for f in files:
                if not f.is_file() or f.suffix in (".pyc", ".so", ".egg"):
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(content.splitlines(), 1):
                        if re.search(pattern, line):
                            matches.append(f"{f}:{i}: {line.strip()}")
                            if len(matches) >= 50:
                                break
                except (OSError, UnicodeDecodeError):
                    continue
                if len(matches) >= 50:
                    break
            if not matches:
                return SkillResult(success=True, data="No matches found.")
            return SkillResult(success=True, data="\n".join(matches))
        except Exception as e:
            return SkillResult(success=False, error=str(e))
