"""LLM-powered skills."""
from healthy_agent.skill.base import Skill, SkillParam, SkillResult


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
