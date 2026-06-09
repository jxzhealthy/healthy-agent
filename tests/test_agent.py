"""Tests for agent loop, RAG, multi-agent, and workflow."""
from healthy_agent.agent import AgentLoop, RAGMixin, SimpleVectorStore, MultiAgentCoordinator, AgentConfig, Workflow
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.skill import SkillRegistry
from healthy_agent.skill.base import Skill, SkillParam, SkillResult
from healthy_agent.drivers.base import LLMDriver, IOResult


# --- Mock driver ---

class MockDriver(LLMDriver):
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self._index = 0

    @property
    def name(self): return "mock"

    async def generate(self, messages, **kwargs):
        if self._index < len(self._responses):
            r = self._responses[self._index]
            self._index += 1
        else:
            r = {"text": "done", "tool_calls": [], "stop_reason": "end_turn"}
        return IOResult(success=True, data=r, tokens_used=10)

    async def stream(self, messages, **kwargs):
        yield "mock"


# --- Mock skill ---

class AddSkill(Skill):
    @property
    def name(self): return "add"
    @property
    def description(self): return "Add two numbers"
    @property
    def parameters(self):
        return [SkillParam(name="a", type="integer", description="First"), SkillParam(name="b", type="integer", description="Second")]
    async def execute(self, params, process, kernel):
        return SkillResult(success=True, data=params.get("a", 0) + params.get("b", 0))


# --- Agent Loop ---

async def test_agent_loop_no_tools():
    driver = MockDriver([{"text": "Hello!", "tool_calls": [], "stop_reason": "end_turn"}])
    skills = SkillRegistry()
    agent = AgentLoop(driver, skills)
    result = await agent.run("Hi")
    assert result.answer == "Hello!"
    assert result.total_rounds == 1


async def test_agent_loop_with_tool_call():
    driver = MockDriver([
        {"text": "", "tool_calls": [{"id": "t1", "name": "add", "input": {"a": 3, "b": 4}}], "stop_reason": "tool_use"},
        {"text": "The answer is 7.", "tool_calls": [], "stop_reason": "end_turn"},
    ])
    skills = SkillRegistry()
    skills.register(AddSkill())
    agent = AgentLoop(driver, skills)
    result = await agent.run("What is 3+4?")
    assert "7" in result.answer
    assert result.total_rounds == 2
    assert any(s.tool_name == "add" for s in result.steps)


async def test_agent_loop_on_step_callback():
    driver = MockDriver([{"text": "Hi", "tool_calls": [], "stop_reason": "end_turn"}])
    skills = SkillRegistry()
    agent = AgentLoop(driver, skills)
    seen = []
    await agent.run("Hello", on_step=lambda s: seen.append(s.role))
    assert "assistant" in seen


# --- RAG ---

def test_rag_ingest_search():
    rag = RAGMixin()
    rag.ingest("Python is a programming language")
    rag.ingest("Rust is a systems programming language")
    rag.ingest("Cooking pasta requires water")

    ctx = rag.retrieve_context("programming language")
    assert "Python" in ctx or "Rust" in ctx
    assert "pasta" not in ctx or "programming" in ctx


def test_rag_empty():
    rag = RAGMixin()
    assert rag.retrieve_context("anything") == ""


def test_vector_store_crud():
    store = SimpleVectorStore()
    doc_id = store.add_text("hello world")
    assert store.size == 1
    results = store.search("hello")
    assert len(results) == 1
    store.delete(doc_id)
    assert store.size == 0


# --- Multi-agent ---

async def test_multi_agent_parallel():
    async def agent_a(process, kernel):
        return "result_a"
    async def agent_b(process, kernel):
        return "result_b"

    k = Kernel(num_cores=2)
    async def parent(process, kernel):
        coord = MultiAgentCoordinator(kernel)
        result = await coord.parallel([
            AgentConfig(name="a", handler=agent_a),
            AgentConfig(name="b", handler=agent_b),
        ], process)
        return result.results

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result == {"a": "result_a", "b": "result_b"}


async def test_multi_agent_pipeline():
    async def step1(process, kernel):
        inp = process.payload.get("_pipeline_input", 0)
        return inp + 10
    async def step2(process, kernel):
        inp = process.payload.get("_pipeline_input", 0)
        return inp * 2

    k = Kernel(num_cores=2)
    async def parent(process, kernel):
        coord = MultiAgentCoordinator(kernel)
        result = await coord.pipeline([
            AgentConfig(name="add10", handler=step1),
            AgentConfig(name="double", handler=step2),
        ], process, initial_input=5)
        return result.results

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result["add10"] == 15
    assert result["double"] == 30


# --- Workflow ---

async def test_workflow_dag():
    async def fetch(process, kernel):
        return "data"
    async def parse(process, kernel):
        return f"parsed({process.payload['_workflow_outputs']['fetch']})"
    async def analyze(process, kernel):
        return f"analyzed({process.payload['_workflow_outputs']['fetch']})"
    async def report(process, kernel):
        outs = process.payload["_workflow_outputs"]
        return f"report({outs['parse']},{outs['analyze']})"

    k = Kernel(num_cores=4)
    async def parent(process, kernel):
        wf = Workflow(kernel)
        wf.add("fetch", fetch)
        wf.add("parse", parse, depends_on=["fetch"])
        wf.add("analyze", analyze, depends_on=["fetch"])
        wf.add("report", report, depends_on=["parse", "analyze"])
        return await wf.execute(process)

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert result.outputs["fetch"] == "data"
    assert "parsed(data)" in result.outputs["parse"]
    assert "analyzed(data)" in result.outputs["analyze"]
    assert "report(" in result.outputs["report"]
    assert result.execution_order.index("fetch") < result.execution_order.index("parse")
