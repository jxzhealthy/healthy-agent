"""Tests for memory, session, MCP, and skill systems."""
import json
import tempfile

from healthy_agent.memory import ShortTermMemory, LongTermMemory, MemoryManager
from healthy_agent.session import SessionManager
from healthy_agent.mcp.server import McpServer
from healthy_agent.skill import Skill, SkillRegistry
from healthy_agent.skill.base import SkillParam, SkillResult
from healthy_agent.skill.builtin import SummarizeSkill, CodeGenSkill


# --- Memory ---

def test_short_term_put_get():
    m = ShortTermMemory()
    m.put("key1", "value1")
    assert m.get("key1") == "value1"
    assert m.get("missing") is None


def test_short_term_ttl():
    m = ShortTermMemory()
    m.put("key1", "value1", ttl=0)
    import time
    time.sleep(0.01)
    assert m.get("key1") is None


def test_short_term_tags():
    m = ShortTermMemory()
    m.put("a", 1, tags=["num"])
    m.put("b", 2, tags=["num"])
    m.put("c", "x", tags=["str"])
    assert len(m.search("num")) == 2
    assert len(m.search("str")) == 1


def test_long_term_persist():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    lt = LongTermMemory(path=path)
    lt.put("key1", {"data": 42})
    lt2 = LongTermMemory(path=path)
    assert lt2.get("key1") == {"data": 42}
    import os
    os.unlink(path)


def test_memory_manager():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    mm = MemoryManager(long_term_path=path)
    mm.remember("temp", "goes away")
    mm.remember("perm", "stays", persist=True)
    assert mm.recall("temp") == "goes away"
    assert mm.recall("perm") == "stays"
    mm.short.clear()
    assert mm.recall("temp") is None
    assert mm.recall("perm") == "stays"
    import os
    os.unlink(path)


async def test_redis_memory_backend():
    import fakeredis.aioredis as fake
    from healthy_agent.memory.backend import RedisMemoryBackend

    backend = RedisMemoryBackend.__new__(RedisMemoryBackend)
    backend._client = fake.FakeRedis(decode_responses=True)
    backend._prefix = "test:mem:"
    backend._tags_key = "test:mem:_tags"

    await backend.put("k1", {"data": 42}, tags=["num"])
    await backend.put("k2", "hello", tags=["str"])

    assert await backend.get("k1") == {"data": 42}
    assert await backend.get("k2") == "hello"
    assert await backend.get("missing") is None

    results = await backend.search("num")
    assert len(results) == 1
    assert results[0]["key"] == "k1"

    all_data = await backend.all()
    assert len(all_data) == 2

    await backend.delete("k1")
    assert await backend.get("k1") is None
    assert await backend.size() == 1

    await backend.clear()
    assert await backend.size() == 0

    await backend._client.aclose()


def test_memory_manager_backend_selection():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    mm_local = MemoryManager(long_term_path=path)
    assert not mm_local.distributed
    assert mm_local.backend_name == "local"

    mm_redis = MemoryManager(long_term_path=path, redis_url="redis://localhost:6379")
    assert mm_redis.distributed
    assert mm_redis.backend_name == "redis"

    mm_redis2 = MemoryManager(long_term_path=path, backend="redis")
    assert mm_redis2.backend_name == "redis"

    import os
    os.unlink(path)


# --- Session ---

def test_session_creation():
    sm = SessionManager(memory_dir=tempfile.mkdtemp())
    s = sm.create()
    assert s.active
    assert len(s.session_id) == 12


def test_session_messages():
    sm = SessionManager(memory_dir=tempfile.mkdtemp())
    s = sm.create()
    s.add_message("user", "hello")
    s.add_message("assistant", "hi")
    assert len(s.get_history()) == 2
    assert s.get_history(last_n=1)[0]["role"] == "assistant"


def test_session_memory_isolation():
    sm = SessionManager(memory_dir=tempfile.mkdtemp())
    s1 = sm.create()
    s2 = sm.create()

    s1.memory.put("key", "session1_short")
    s2.memory.put("key", "session2_short")
    assert s1.memory.get("key") == "session1_short"
    assert s2.memory.get("key") == "session2_short"

    s1.mem.remember("pref", "dark_mode", persist=True)
    s2.mem.remember("pref", "light_mode", persist=True)
    assert s1.mem.recall("pref") == "dark_mode"
    assert s2.mem.recall("pref") == "light_mode"

    s1.mem.short.clear()
    s2.mem.short.clear()
    assert s1.mem.recall("pref") == "dark_mode"
    assert s2.mem.recall("pref") == "light_mode"


def test_session_lifecycle():
    sm = SessionManager(memory_dir=tempfile.mkdtemp())
    s = sm.create(metadata={"user": "test"})
    assert sm.active_count == 1
    sm.close(s.session_id)
    assert not s.active
    sm.destroy(s.session_id)
    assert sm.get(s.session_id) is None


def test_session_to_dict_shows_backend():
    sm = SessionManager(memory_dir=tempfile.mkdtemp())
    s = sm.create()
    d = s.to_dict()
    assert d["memory_backend"] == "local"


# --- MCP ---

async def test_mcp_server_initialize():
    server = McpServer()
    result = await server.handle_message(
        {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
    )
    data = json.loads(result)
    assert data["result"]["serverInfo"]["name"] == "healthy-agent"


async def test_mcp_server_tool_roundtrip():
    server = McpServer()

    async def add_handler(args):
        return {"sum": args.get("a", 0) + args.get("b", 0)}

    server.register_tool(
        "add", "Add two numbers",
        {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
        handler=add_handler,
    )

    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2,
    })
    tools = json.loads(result)["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "add"

    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 3, "b": 7}}, "id": 3,
    })
    content = json.loads(json.loads(result)["result"]["content"][0]["text"])
    assert content["sum"] == 10


async def test_mcp_unknown_method():
    server = McpServer()
    result = await server.handle_message(
        {"jsonrpc": "2.0", "method": "unknown", "params": {}, "id": 1}
    )
    assert json.loads(result)["error"]["code"] == -32601


# --- Skill ---

def test_skill_registry():
    reg = SkillRegistry()
    reg.register(SummarizeSkill())
    reg.register(CodeGenSkill())
    assert reg.count == 2
    assert reg.get("summarize") is not None
    skills = reg.list_skills()
    assert len(skills) == 2


async def test_skill_invoke_mock():
    reg = SkillRegistry()
    reg.register(SummarizeSkill())
    result = await reg.invoke("summarize", {"text": "hello world"}, None, None)
    assert result.success
    assert "mock" in result.data


async def test_skill_not_found():
    reg = SkillRegistry()
    result = await reg.invoke("nonexistent", {}, None, None)
    assert not result.success
    assert "not found" in result.error


async def test_custom_skill():
    class UpperSkill(Skill):
        @property
        def name(self): return "upper"
        @property
        def description(self): return "Uppercase text"
        @property
        def parameters(self):
            return [SkillParam(name="text", type="string", description="Input")]

        async def execute(self, params, process, kernel):
            return SkillResult(success=True, data=params.get("text", "").upper())

    reg = SkillRegistry()
    reg.register(UpperSkill())
    result = await reg.invoke("upper", {"text": "hello"}, None, None)
    assert result.data == "HELLO"


# --- MCP: resources ---

async def test_mcp_resources_roundtrip():
    server = McpServer()

    async def config_provider():
        return '{"theme": "dark"}'

    server.register_resource(
        uri="config://app/theme",
        name="App Theme",
        description="Application theme configuration",
        mime_type="application/json",
        provider=config_provider,
    )

    # List resources
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "resources/list", "params": {}, "id": 10,
    })
    resources = json.loads(result)["result"]["resources"]
    assert len(resources) == 1
    assert resources[0]["name"] == "App Theme"
    assert resources[0]["uri"] == "config://app/theme"

    # Read resource
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "resources/read",
        "params": {"uri": "config://app/theme"}, "id": 11,
    })
    contents = json.loads(result)["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["mimeType"] == "application/json"
    assert '"dark"' in contents[0]["text"]


async def test_mcp_resources_static():
    server = McpServer()
    server.register_resource(
        uri="file:///readme",
        name="README",
        static_content="Hello from README",
    )

    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "resources/read",
        "params": {"uri": "file:///readme"}, "id": 12,
    })
    text = json.loads(result)["result"]["contents"][0]["text"]
    assert text == "Hello from README"


async def test_mcp_resources_not_found():
    server = McpServer()
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "resources/read",
        "params": {"uri": "nonexistent://x"}, "id": 13,
    })
    data = json.loads(result)
    assert "error" in data


# --- MCP: prompts ---

async def test_mcp_prompts_template():
    server = McpServer()
    server.register_prompt(
        name="summarize",
        description="Summarize a topic",
        arguments=[{"name": "topic", "description": "Topic to summarize", "required": True}],
        template="Please summarize the following topic: {topic}",
    )

    # List prompts
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "prompts/list", "params": {}, "id": 20,
    })
    prompts = json.loads(result)["result"]["prompts"]
    assert len(prompts) == 1
    assert prompts[0]["name"] == "summarize"

    # Get prompt with arguments
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "prompts/get",
        "params": {"name": "summarize", "arguments": {"topic": "AI safety"}}, "id": 21,
    })
    data = json.loads(result)["result"]
    assert "AI safety" in data["messages"][0]["content"]["text"]


async def test_mcp_prompts_handler():
    server = McpServer()

    async def custom_prompt_handler(arguments):
        lang = arguments.get("language", "en")
        return [{"role": "user", "content": {"type": "text", "text": f"Translate to {lang}"}}]

    server.register_prompt(
        name="translate",
        description="Translate text",
        handler=custom_prompt_handler,
    )

    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "prompts/get",
        "params": {"name": "translate", "arguments": {"language": "Japanese"}}, "id": 22,
    })
    messages = json.loads(result)["result"]["messages"]
    assert "Japanese" in messages[0]["content"]["text"]


async def test_mcp_prompts_not_found():
    server = McpServer()
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "prompts/get",
        "params": {"name": "nonexistent"}, "id": 23,
    })
    data = json.loads(result)
    assert "error" in data


async def test_mcp_initialize_capabilities():
    server = McpServer()
    result = await server.handle_message({
        "jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 30,
    })
    caps = json.loads(result)["result"]["capabilities"]
    assert "tools" in caps
    assert "resources" in caps
    assert "prompts" in caps
