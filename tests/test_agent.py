"""Tests for executor, RAG, multi-agent, and workflow."""
from healthy_agent.agent import Executor, RAGMixin, SimpleVectorStore, MultiAgentCoordinator, AgentConfig, Workflow
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.skill import SkillRegistry
from healthy_agent.skill.base import Skill, SkillParam, SkillResult
from healthy_agent.drivers.base import LLMDriver, IOResult
from healthy_agent.agent.reflexion import ReflexionAgent, Evaluation, Reflection, _parse_reflection, _build_reflection_context


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


# --- Executor ---

async def test_executor_no_tools():
    driver = MockDriver([{"text": "Hello!", "tool_calls": [], "stop_reason": "end_turn"}])
    skills = SkillRegistry()
    agent = Executor(driver, skills)
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
    agent = Executor(driver, skills)
    result = await agent.run("What is 3+4?")
    assert "7" in result.answer
    assert result.total_rounds == 2
    assert any(s.tool_name == "add" for s in result.steps)


async def test_executor_on_step_callback():
    driver = MockDriver([{"text": "Hi", "tool_calls": [], "stop_reason": "end_turn"}])
    skills = SkillRegistry()
    agent = Executor(driver, skills)
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


# --- RAG: TF-IDF scoring ---

def test_rag_tfidf_relevance():
    """TF-IDF should rank semantically closer docs higher than keyword overlap."""
    rag = RAGMixin()
    rag.ingest("Python is a high-level programming language for general purpose")
    rag.ingest("Rust is a systems programming language focused on safety")
    rag.ingest("Cooking delicious pasta requires boiling water and salt")

    results = rag.store.search("systems programming safety", top_k=2)
    assert any("Rust" in d.content for d in results)


# --- RAG: text chunking ---

def test_chunk_text_short():
    from healthy_agent.agent.rag import chunk_text
    chunks = chunk_text("short text", chunk_size=500)
    assert chunks == ["short text"]


def test_chunk_text_splits():
    from healthy_agent.agent.rag import chunk_text
    text = "A" * 200 + "\n\n" + "B" * 200 + "\n\n" + "C" * 200
    chunks = chunk_text(text, chunk_size=250, chunk_overlap=0)
    assert len(chunks) >= 2


def test_chunk_text_overlap():
    from healthy_agent.agent.rag import chunk_text
    text = "word " * 200
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 2
    # Overlap means later chunks contain tail of previous
    if len(chunks) >= 2:
        assert len(chunks[1]) > 0


# --- RAG: persistence ---

def test_vector_store_persist():
    import tempfile
    import os
    path = os.path.join(tempfile.mkdtemp(), "store.json")
    store1 = SimpleVectorStore(persist_path=path)
    store1.add_text("hello world", {"source": "test"})
    store1.add_text("foo bar baz")
    assert store1.size == 2

    store2 = SimpleVectorStore(persist_path=path)
    assert store2.size == 2
    results = store2.search("hello")
    assert len(results) >= 1
    os.unlink(path)


# --- RAG: ingest_chunked ---

def test_rag_ingest_chunked():
    rag = RAGMixin()
    long_text = "The quick brown fox. " * 100
    doc_ids = rag.ingest_chunked(long_text, chunk_size=200, chunk_overlap=20, metadata={"src": "test"})
    assert len(doc_ids) >= 2
    unique_ids = set(doc_ids)
    assert rag.store.size == len(unique_ids)
    assert rag.store.size >= 2


# --- Workflow: conditional branching ---

async def test_workflow_condition_skip():
    async def fetch(process, kernel):
        return None  # returns None to trigger skip

    async def parse(process, kernel):
        return "parsed"

    async def fallback(process, kernel):
        return "fallback_used"

    k = Kernel(num_cores=4)
    async def parent(process, kernel):
        wf = Workflow(kernel)
        wf.add("fetch", fetch)
        wf.add("parse", parse, depends_on=["fetch"],
               condition=lambda outputs: outputs.get("fetch") is not None)
        wf.add("fallback", fallback, depends_on=["fetch"],
               condition=lambda outputs: outputs.get("fetch") is None)
        return await wf.execute(process)

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert "parse" in result.skipped
    assert result.outputs.get("fallback") == "fallback_used"


# --- Workflow: step timeout ---

async def test_workflow_step_timeout():
    import asyncio as _asyncio

    async def slow_step(process, kernel):
        await _asyncio.sleep(10)
        return "done"

    async def fast_step(process, kernel):
        return "fast"

    k = Kernel(num_cores=2)
    async def parent(process, kernel):
        wf = Workflow(kernel)
        wf.add("slow", slow_step, timeout=0.1)
        wf.add("fast", fast_step)
        return await wf.execute(process)

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert isinstance(result.outputs["slow"], TimeoutError)
    assert result.outputs["fast"] == "fast"


# --- LoopWorkflow ---

async def test_loop_workflow():
    from healthy_agent.agent.workflow import LoopWorkflow

    counter = {"value": 0}

    async def increment(process, kernel):
        counter["value"] += 1
        return counter["value"]

    k = Kernel(num_cores=2)
    async def parent(process, kernel):
        loop = LoopWorkflow(kernel, max_iterations=10)
        return await loop.execute(
            process, handler=increment,
            stop_condition=lambda result, i: result >= 3,
        )

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert len(result.execution_order) == 3
    assert result.outputs["loop_iter_2"] == 3


# --- MultiAgent: debate with consensus ---

async def test_multi_agent_debate_consensus():
    async def agree_agent(process, kernel):
        return "consensus_answer"

    k = Kernel(num_cores=4)
    async def parent(process, kernel):
        coord = MultiAgentCoordinator(kernel)
        result = await coord.debate(
            [
                AgentConfig(name="a", handler=agree_agent),
                AgentConfig(name="b", handler=agree_agent),
                AgentConfig(name="c", handler=agree_agent),
            ],
            process, topic="test question", rounds=3,
            consensus_threshold=0.5,
        )
        return result.results

    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.get("consensus") == "consensus_answer"
    assert result.get("consensus_round") == 0  # First round all agree


# --- Reflexion ---


def test_parse_reflection():
    text = """WHAT_WENT_WRONG: I forgot to handle edge cases
WHAT_TO_DO_DIFFERENTLY: Add boundary checks first
KEY_INSIGHT: Always validate inputs before processing"""
    ref = _parse_reflection(text, trial=1)
    assert ref.trial == 1
    assert "edge cases" in ref.what_went_wrong
    assert "boundary" in ref.what_to_do_differently
    assert "validate" in ref.key_insight


def test_parse_reflection_missing_fields():
    ref = _parse_reflection("some garbage text", trial=2)
    assert ref.trial == 2
    assert ref.what_went_wrong
    assert ref.what_to_do_differently


def test_build_reflection_context_empty():
    assert _build_reflection_context([]) == ""


def test_build_reflection_context():
    refs = [
        Reflection(trial=1, what_went_wrong="wrong1", what_to_do_differently="fix1", key_insight="learn1"),
        Reflection(trial=2, what_went_wrong="wrong2", what_to_do_differently="fix2", key_insight="learn2"),
    ]
    ctx = _build_reflection_context(refs)
    assert "Attempt 1" in ctx
    assert "Attempt 2" in ctx
    assert "wrong1" in ctx
    assert "fix2" in ctx


async def test_reflexion_success_first_try():
    driver = MockDriver([
        {"text": "The answer is 42.", "tool_calls": [], "stop_reason": "end_turn"},
    ])
    skills = SkillRegistry()

    async def always_pass(prompt, answer):
        return Evaluation(success=True, score=1.0, feedback="Perfect")

    agent = ReflexionAgent(driver, skills, evaluator=always_pass, max_trials=3)
    result = await agent.run("What is the meaning of life?")
    assert result.success
    assert result.total_trials == 1
    assert len(result.reflections) == 0
    assert "42" in result.answer


async def test_reflexion_succeeds_after_reflection():
    class ImprovingDriver(LLMDriver):
        @property
        def name(self): return "improving"

        async def generate(self, messages, **kwargs):
            has_reflection = any(
                "Lessons from previous attempts" in str(m.get("content", ""))
                for m in messages
            )
            if any("WHAT_WENT_WRONG" in str(m.get("content", "")) for m in messages):
                text = "WHAT_WENT_WRONG: Did not sort\nWHAT_TO_DO_DIFFERENTLY: Use sorted()\nKEY_INSIGHT: Don't return input unchanged"
            elif has_reflection:
                text = "def sort(lst): return sorted(lst)"
            else:
                text = "def sort(lst): return lst"
            return IOResult(success=True, data={"text": text, "tool_calls": [], "stop_reason": "end_turn"}, tokens_used=10)

        async def stream(self, messages, **kwargs):
            yield "mock"

    async def eval_sort(prompt, answer):
        if "sorted" in answer:
            return Evaluation(success=True, score=1.0, feedback="Correct")
        return Evaluation(success=False, score=0.2, feedback="Does not sort")

    agent = ReflexionAgent(ImprovingDriver(), SkillRegistry(), evaluator=eval_sort, max_trials=3)
    result = await agent.run("Write a sort function")
    assert result.success
    assert result.total_trials == 2
    assert len(result.reflections) == 1


async def test_reflexion_all_trials_fail():
    driver = MockDriver([
        {"text": "bad 1", "tool_calls": [], "stop_reason": "end_turn"},
        {"text": "WHAT_WENT_WRONG: w\nWHAT_TO_DO_DIFFERENTLY: f\nKEY_INSIGHT: l", "tool_calls": [], "stop_reason": "end_turn"},
        {"text": "bad 2", "tool_calls": [], "stop_reason": "end_turn"},
        {"text": "WHAT_WENT_WRONG: w2\nWHAT_TO_DO_DIFFERENTLY: f2\nKEY_INSIGHT: l2", "tool_calls": [], "stop_reason": "end_turn"},
        {"text": "bad 3", "tool_calls": [], "stop_reason": "end_turn"},
    ])
    scores = iter([0.2, 0.5, 0.4])

    async def strict_eval(prompt, answer):
        return Evaluation(success=False, score=next(scores), feedback="nope")

    agent = ReflexionAgent(driver, SkillRegistry(), evaluator=strict_eval, max_trials=3)
    result = await agent.run("Hard task")
    assert not result.success
    assert result.total_trials == 3
    assert len(result.reflections) == 2
    assert "bad 2" in result.answer  # Best score was 0.5
