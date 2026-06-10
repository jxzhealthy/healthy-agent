"""Tests for new modules: SQLiteStore, MetricsCollector, Plugin system, Kernel ResourceError, Executor run_stream, and Skill hot-reload."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from healthy_agent.persistence.sqlite_store import SQLiteStore
from healthy_agent.observability.metrics import MetricsCollector
from healthy_agent.plugin.base import Plugin, PluginContext, PluginHook, PluginMetadata
from healthy_agent.plugin.manager import PluginManager
from healthy_agent.kernel.runtime import Kernel, ResourceError
from healthy_agent.execution.executor import Executor, AgentResult
from healthy_agent.skill.registry import SkillRegistry


# ============================================================================
# SQLiteStore Tests
# ============================================================================

class TestSQLiteStore:
    """Test suite for SQLiteStore persistence."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a temporary SQLiteStore instance."""
        db_path = tmp_path / "test_store.db"
        store = SQLiteStore(str(db_path))
        yield store
        store.close()

    def test_sqlite_save_load_session(self, store):
        """Test creating session, saving, loading, and verifying messages and metadata."""
        session_id = "test-session-001"
        messages = [
            {"role": "user", "content": "Hello", "timestamp": 1000.0},
            {"role": "assistant", "content": "Hi there!", "timestamp": 1001.0},
        ]
        metadata = {"user_id": "alice", "tags": ["greeting"]}

        store.save_session(session_id, messages=messages, metadata=metadata)
        loaded = store.load_session(session_id)

        assert loaded is not None
        assert loaded["session_id"] == session_id
        assert loaded["metadata"] == metadata
        assert len(loaded["messages"]) == 2
        assert loaded["messages"][0]["role"] == "user"
        assert loaded["messages"][0]["content"] == "Hello"
        assert loaded["messages"][1]["role"] == "assistant"
        assert loaded["messages"][1]["content"] == "Hi there!"

    def test_sqlite_add_message(self, store):
        """Test appending messages and verifying order."""
        session_id = "test-session-002"
        store.save_session(session_id, messages=[], metadata={})

        store.add_message(session_id, "user", "First message")
        time.sleep(0.01)  # Ensure different timestamps
        store.add_message(session_id, "assistant", "Second message")
        time.sleep(0.01)
        store.add_message(session_id, "user", "Third message")

        loaded = store.load_session(session_id)
        assert len(loaded["messages"]) == 3
        assert loaded["messages"][0]["content"] == "First message"
        assert loaded["messages"][1]["content"] == "Second message"
        assert loaded["messages"][2]["content"] == "Third message"
        # Verify timestamps are in order
        timestamps = [m["timestamp"] for m in loaded["messages"]]
        assert timestamps == sorted(timestamps)

    def test_sqlite_memory_crud(self, store):
        """Test put_memory, get_memory, search_memory, delete_memory."""
        session_id = "test-session-003"

        # put_memory
        store.put_memory(session_id, "user_name", "Alice", tags=["profile"])
        store.put_memory(session_id, "user_age", 30, tags=["profile", "demographics"])
        store.put_memory(session_id, "preference", "dark_mode", tags=["settings"])

        # get_memory
        assert store.get_memory(session_id, "user_name") == "Alice"
        assert store.get_memory(session_id, "user_age") == 30
        assert store.get_memory(session_id, "nonexistent") is None

        # search_memory by tag
        profile_entries = store.search_memory(session_id, "profile")
        assert len(profile_entries) == 2
        keys = {e["key"] for e in profile_entries}
        assert keys == {"user_name", "user_age"}

        settings_entries = store.search_memory(session_id, "settings")
        assert len(settings_entries) == 1
        assert settings_entries[0]["key"] == "preference"

        # delete_memory
        store.delete_memory(session_id, "user_age")
        assert store.get_memory(session_id, "user_age") is None
        assert store.get_memory(session_id, "user_name") == "Alice"

    def test_sqlite_list_sessions(self, store):
        """Test listing multiple sessions."""
        for i in range(3):
            session_id = f"session-{i}"
            store.save_session(session_id, messages=[], metadata={"index": i})
            time.sleep(0.01)  # Ensure different created_at

        sessions = store.list_sessions()
        assert len(sessions) == 3
        session_ids = {s["session_id"] for s in sessions}
        assert session_ids == {"session-0", "session-1", "session-2"}

        # Test active_only filter
        store.close_session("session-1")
        active_sessions = store.list_sessions(active_only=True)
        assert len(active_sessions) == 2
        active_ids = {s["session_id"] for s in active_sessions}
        assert "session-1" not in active_ids

    def test_sqlite_delete_session(self, store):
        """Test deleting a session and confirming it no longer exists."""
        session_id = "test-session-delete"
        store.save_session(session_id, messages=[{"role": "user", "content": "test"}], metadata={})
        store.put_memory(session_id, "key1", "value1")

        assert store.load_session(session_id) is not None
        assert store.get_memory(session_id, "key1") == "value1"

        store.delete_session(session_id)

        assert store.load_session(session_id) is None
        assert store.get_memory(session_id, "key1") is None
        sessions = store.list_sessions()
        assert all(s["session_id"] != session_id for s in sessions)

    def test_sqlite_stats(self, store):
        """Test verifying statistics."""
        # Initially empty
        stats = store.stats
        assert stats["sessions"] == 0
        assert stats["messages"] == 0
        assert stats["memory_entries"] == 0
        assert "db_path" in stats

        # Add data
        store.save_session("s1", messages=[{"role": "user", "content": "msg1"}], metadata={})
        store.save_session("s2", messages=[{"role": "user", "content": "msg2"}, {"role": "assistant", "content": "msg3"}], metadata={})
        store.put_memory("s1", "k1", "v1")
        store.put_memory("s2", "k2", "v2")

        stats = store.stats
        assert stats["sessions"] == 2
        assert stats["messages"] == 3
        assert stats["memory_entries"] == 2


# ============================================================================
# MetricsCollector Tests
# ============================================================================

class TestMetricsCollector:
    """Test suite for MetricsCollector."""

    @pytest.fixture
    def metrics(self):
        """Create a fresh MetricsCollector instance for each test."""
        return MetricsCollector()

    def test_metrics_counter(self, metrics):
        """Test incrementing counter and verifying snapshot."""
        metrics.increment("requests.total")
        metrics.increment("requests.total", value=5)
        metrics.increment("errors.count", value=2)

        snapshot = metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 6
        assert snapshot["counters"]["errors.count"] == 2

    def test_metrics_gauge(self, metrics):
        """Test setting gauge and verifying."""
        metrics.gauge("cpu.usage", 75.5)
        metrics.gauge("memory.mb", 1024.0)

        snapshot = metrics.snapshot()
        assert snapshot["gauges"]["cpu.usage"] == 75.5
        assert snapshot["gauges"]["memory.mb"] == 1024.0

    def test_metrics_latency(self, metrics):
        """Test recording multiple latencies and verifying min/max/mean/p50."""
        for val in [0.1, 0.2, 0.3, 0.4, 0.5]:
            metrics.record_latency("request.latency", val)

        snapshot = metrics.snapshot()
        latency_stats = snapshot["latencies"]["request.latency"]
        assert latency_stats["count"] == 5
        assert latency_stats["min"] == 0.1
        assert latency_stats["max"] == 0.5
        assert abs(latency_stats["mean"] - 0.3) < 0.01
        assert latency_stats["p50"] == 0.3

    def test_metrics_timer(self, metrics):
        """Test using timer context manager."""
        with metrics.timer("operation.time"):
            time.sleep(0.05)

        snapshot = metrics.snapshot()
        assert "operation.time" in snapshot["latencies"]
        latency_stats = snapshot["latencies"]["operation.time"]
        assert latency_stats["count"] == 1
        assert latency_stats["min"] >= 0.04  # Allow some variance

    def test_metrics_reset(self, metrics):
        """Test that reset clears all metrics."""
        metrics.increment("counter.test", value=10)
        metrics.gauge("gauge.test", 99.9)
        metrics.record_latency("latency.test", 1.5)

        metrics.reset()
        snapshot = metrics.snapshot()

        assert snapshot["counters"] == {}
        assert snapshot["gauges"] == {}
        assert snapshot["latencies"] == {}

    def test_metrics_tags(self, metrics):
        """Test counter with tags."""
        metrics.increment("api.calls", tags={"method": "GET", "endpoint": "/users"})
        metrics.increment("api.calls", tags={"method": "POST", "endpoint": "/users"})
        metrics.increment("api.calls", tags={"method": "GET", "endpoint": "/users"})

        snapshot = metrics.snapshot()
        assert snapshot["counters"]["api.calls"] == 3
        # Tags are tracked internally
        assert "api.calls" in metrics._tags


# ============================================================================
# Plugin System Tests
# ============================================================================

class MockPlugin1(Plugin):
    """Simple mock plugin for testing."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="mock-plugin-1", version="1.0.0", description="Test plugin 1")

    def on_register(self, ctx: PluginContext) -> None:
        ctx.add_skill({"name": "skill1", "type": "mock"})

    def on_start(self) -> None:
        self.started = True

    def on_shutdown(self) -> None:
        self.shutdown_called = True


class MockPlugin2(Plugin):
    """Mock plugin with dependency."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="mock-plugin-2",
            version="1.0.0",
            description="Test plugin 2",
            requires=["mock-plugin-1"]
        )

    def pre_generate(self, messages: list[dict], **kwargs) -> list[dict]:
        messages.append({"role": "system", "content": "pre-generated"})
        return messages

    def post_generate(self, result: Any) -> Any:
        return f"post-processed: {result}"


class TestPluginSystem:
    """Test suite for Plugin system."""

    @pytest.fixture
    def plugin_manager(self):
        """Create a fresh PluginManager instance."""
        return PluginManager()

    def test_plugin_register(self, plugin_manager):
        """Test registering plugin and verifying list_plugins."""
        plugin = MockPlugin1()
        plugin_manager.register(plugin)

        plugins = plugin_manager.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["name"] == "mock-plugin-1"
        assert plugins[0]["version"] == "1.0.0"
        assert plugins[0]["skills"] == 1

    def test_plugin_lifecycle(self, plugin_manager):
        """Test start_all/shutdown_all calls."""
        plugin = MockPlugin1()
        plugin_manager.register(plugin)

        plugin_manager.start_all()
        assert hasattr(plugin, 'started') and plugin.started

        plugin_manager.shutdown_all()
        assert hasattr(plugin, 'shutdown_called') and plugin.shutdown_called

    def test_plugin_hooks(self, plugin_manager):
        """Test emitting events and verifying callbacks."""
        received_messages = []

        class HookPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="hook-plugin", version="1.0.0")

            def on_message(self, session_id: str, role: str, content: str) -> None:
                received_messages.append((session_id, role, content))

        plugin = HookPlugin()
        plugin_manager.register(plugin)

        plugin_manager.emit(PluginHook.ON_MESSAGE, session_id="test", role="user", content="hello")
        assert len(received_messages) == 1
        assert received_messages[0] == ("test", "user", "hello")

    def test_plugin_skills(self, plugin_manager):
        """Test that skills registered by plugins are accessible via all_skills."""
        plugin = MockPlugin1()
        plugin_manager.register(plugin)

        skills = plugin_manager.all_skills
        assert len(skills) == 1
        assert skills[0]["name"] == "skill1"

    def test_plugin_dependency(self, plugin_manager):
        """Test that missing dependencies raise errors."""
        plugin_with_dep = MockPlugin2()

        with pytest.raises(RuntimeError, match="requires.*mock-plugin-1.*not registered"):
            plugin_manager.register(plugin_with_dep)

        # Register dependency first, then it should work
        plugin1 = MockPlugin1()
        plugin_manager.register(plugin1)
        plugin_manager.register(plugin_with_dep)  # Should succeed now
        assert plugin_manager.count == 2

    def test_plugin_pre_post_generate(self, plugin_manager):
        """Test pre_generate/post_generate pipeline."""
        # Register dependency first
        plugin1 = MockPlugin1()
        plugin_manager.register(plugin1)
        
        plugin = MockPlugin2()
        plugin_manager.register(plugin)

        # Test pre_generate
        messages = [{"role": "user", "content": "test"}]
        modified = plugin_manager.pre_generate(messages)
        assert len(modified) == 2
        assert modified[-1]["role"] == "system"
        assert modified[-1]["content"] == "pre-generated"

        # Test post_generate
        result = plugin_manager.post_generate("original")
        assert result == "post-processed: original"


# ============================================================================
# Kernel ResourceError Tests
# ============================================================================

class TestKernelResourceError:
    """Test suite for Kernel resource limits."""

    def test_kernel_max_processes(self):
        """Test that exceeding max_processes raises ResourceError."""
        kernel = Kernel(num_cores=1, max_processes=2, max_spawn_rate=1000.0)

        async def dummy_handler():
            return "done"

        # Spawn up to the limit
        kernel.spawn("task1", {}, handler=dummy_handler)
        kernel.spawn("task2", {}, handler=dummy_handler)

        # Next spawn should fail
        with pytest.raises(ResourceError, match="Max processes exceeded"):
            kernel.spawn("task3", {}, handler=dummy_handler)

        # Cleanup
        kernel.shutdown()

    def test_kernel_spawn_rate_limit(self):
        """Test that exceeding max_spawn_rate raises ResourceError."""
        kernel = Kernel(num_cores=1, max_processes=1000, max_spawn_rate=2.0)

        async def dummy_handler():
            return "done"

        # Spawn at the rate limit
        kernel.spawn("task1", {}, handler=dummy_handler)
        kernel.spawn("task2", {}, handler=dummy_handler)

        # Next spawn within same second should fail
        with pytest.raises(ResourceError, match="Spawn rate exceeded"):
            kernel.spawn("task3", {}, handler=dummy_handler)

        # Cleanup
        kernel.shutdown()


# ============================================================================
# Executor run_stream Tests
# ============================================================================

class TestExecutorRunStream:
    """Test suite for Executor run_stream method."""

    @pytest.mark.asyncio
    async def test_executor_run_stream(self):
        """Test that on_token callback is called during streaming."""
        # Create mock driver
        mock_driver = MagicMock()
        mock_driver.name = "test-driver"

        # Mock stream to return tokens
        async def mock_stream(*args, **kwargs):
            tokens = ["Hello", " ", "world", "!"]
            for token in tokens:
                yield token

        mock_driver.stream = mock_stream
        mock_driver.generate = AsyncMock(return_value=MagicMock(
            success=True,
            data={"text": "Hello world!", "tool_calls": [], "stop_reason": "stop"},
            tokens_used=4
        ))

        # Create skill registry
        skills = SkillRegistry()

        # Create executor
        executor = Executor(driver=mock_driver, skills=skills, max_rounds=1)

        # Track tokens received
        received_tokens = []

        async def on_token(token: str):
            received_tokens.append(token)

        # Run stream
        result = await executor.run_stream("test prompt", on_token=on_token)

        # Verify on_token was called
        assert len(received_tokens) > 0
        assert "".join(received_tokens) == "Hello world!"
        assert isinstance(result, AgentResult)
        assert result.answer == "Hello world!"


# ============================================================================
# Skill Hot-Reload Tests
# ============================================================================

class TestSkillHotReload:
    """Test suite for Skill hot-reload functionality."""

    def test_skill_hot_reload(self, tmp_path):
        """Test that modifying file mtime triggers _check_reload to call load_directory."""
        # Create a temporary directory with a dummy file
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        dummy_file = skills_dir / "dummy.md"
        dummy_file.write_text("---\nname: dummy\ndescription: test\nparameters: []\n---\nHello {}")

        # Create registry and manually set up watched state
        registry = SkillRegistry()
        registry._watched_dirs.append(skills_dir)
        registry._file_mtimes[str(dummy_file)] = dummy_file.stat().st_mtime

        # Initially no change detected - _check_reload should not reload
        with patch.object(registry, 'load_directory', wraps=registry.load_directory) as mock_load:
            registry._check_reload()
            mock_load.assert_not_called()

        # Modify the file (change mtime)
        time.sleep(0.05)
        dummy_file.write_text("---\nname: dummy\ndescription: updated\nparameters: []\n---\nUpdated")

        # Now _check_reload should detect the change and call load_directory
        with patch.object(registry, 'load_directory') as mock_load:
            registry._check_reload()
            mock_load.assert_called_once_with(skills_dir)
