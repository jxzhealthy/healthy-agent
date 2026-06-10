"""Tests for new features: Config, Resilience, Auth, Sandbox, Compression, Multimodal."""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from healthy_agent.config.settings import (
    Settings,
    load_config,
)
from healthy_agent.resilience.retry import RetryPolicy, with_retry
from healthy_agent.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
)
from healthy_agent.auth.middleware import verify_api_key, verify_jwt, verify_token
from healthy_agent.sandbox.executor import Sandbox
from healthy_agent.compression.compressor import ConversationCompressor
from healthy_agent.multimodal.attachment import ImageAttachment, FileAttachment
from healthy_agent.multimodal.message import MultimodalMessage
from healthy_agent.multimodal.utils import detect_media_type, extract_text_from_file


# ==================== Config Tests ====================

class TestConfig:
    """Configuration system tests."""

    def test_default_settings(self):
        """Test that default settings are returned when no config file exists."""
        settings = load_config(path="/nonexistent/path.toml")
        assert isinstance(settings, Settings)
        assert settings.server.host == "0.0.0.0"
        assert settings.server.port == 8000
        assert settings.driver.name == "openai"
        assert settings.driver.model == "gpt-4o"
        assert settings.kernel.num_cores == 4

    def test_load_config_from_toml(self, tmp_path):
        """Test loading configuration from a TOML file."""
        toml_content = """
[server]
host = "127.0.0.1"
port = 9000

[driver]
name = "anthropic"
model = "claude-3-opus"
"""
        config_file = tmp_path / "test_config.toml"
        config_file.write_text(toml_content)

        settings = load_config(path=str(config_file))
        assert settings.server.host == "127.0.0.1"
        assert settings.server.port == 9000
        assert settings.driver.name == "anthropic"
        assert settings.driver.model == "claude-3-opus"

    def test_env_override(self, monkeypatch):
        """Test that environment variables override configuration values."""
        monkeypatch.setenv("HEALTHY_AGENT_DRIVER_NAME", "azure")
        monkeypatch.setenv("HEALTHY_AGENT_SERVER_PORT", "8080")

        settings = load_config()
        assert settings.driver.name == "azure"
        assert settings.server.port == 8080

        # Clean up
        monkeypatch.delenv("HEALTHY_AGENT_DRIVER_NAME")
        monkeypatch.delenv("HEALTHY_AGENT_SERVER_PORT")

    def test_nested_config_access(self, tmp_path):
        """Test accessing nested configuration values."""
        toml_content = """
[driver]
name = "openai"
model = "gpt-4-turbo"
api_key = "sk-test123"
max_tokens = 8192
"""
        config_file = tmp_path / "nested_config.toml"
        config_file.write_text(toml_content)

        settings = load_config(path=str(config_file))
        assert settings.driver.name == "openai"
        assert settings.driver.model == "gpt-4-turbo"
        assert settings.driver.api_key == "sk-test123"
        assert settings.driver.max_tokens == 8192


# ==================== Resilience Tests ====================

class TestResilience:
    """Resilience mechanism tests (retry and circuit breaker)."""

    @pytest.mark.asyncio
    async def test_retry_success_first_try(self):
        """Test that retry succeeds on first attempt without retries."""
        call_count = 0

        async def successful_fn():
            nonlocal call_count
            call_count += 1
            return "success"

        policy = RetryPolicy(max_retries=3)
        result = await with_retry(successful_fn, policy)

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_eventual_success(self):
        """Test that retry succeeds after some failures."""
        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Attempt {call_count} failed")
            return "success"

        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        result = await with_retry(flaky_fn, policy)

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_all_fail(self):
        """Test that retry raises exception after all attempts fail."""
        call_count = 0

        async def failing_fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Always fails")

        policy = RetryPolicy(max_retries=2, base_delay=0.01)

        with pytest.raises(RuntimeError, match="Always fails"):
            await with_retry(failing_fn, policy)

        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self):
        """Test that circuit breaker opens after consecutive failures."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

        async def failing_fn():
            raise ValueError("Service down")

        # Trigger failures to open circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(failing_fn)

        assert cb.state == CircuitState.OPEN

        # Next call should raise CircuitOpenError immediately
        with pytest.raises(CircuitOpenError):
            await cb.call(failing_fn)

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test that circuit breaker transitions to half-open and recovers."""
        cb = CircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.1,  # Short timeout for testing
            success_threshold=2,
        )

        async def failing_fn():
            raise ValueError("Fail")

        async def success_fn():
            return "ok"

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_fn)

        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Should be half-open now
        assert cb.state == CircuitState.HALF_OPEN

        # Successful calls should close the circuit
        for _ in range(2):
            result = await cb.call(success_fn)
            assert result == "ok"

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_reset(self):
        """Test manual reset of circuit breaker."""
        cb = CircuitBreaker(failure_threshold=2)

        async def failing_fn():
            raise ValueError("Fail")

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_fn)

        assert cb.state == CircuitState.OPEN

        # Manual reset
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_resilient_driver_fallback(self):
        """Test fallback driver when primary fails."""
        primary_cb = CircuitBreaker(failure_threshold=1)
        fallback_calls = []

        async def primary_fn():
            raise RuntimeError("Primary unavailable")

        async def fallback_fn():
            fallback_calls.append(1)
            return "fallback_result"

        # Primary should fail and open circuit
        with pytest.raises(RuntimeError):
            await primary_cb.call(primary_fn)

        assert primary_cb.state == CircuitState.OPEN

        # Use fallback
        result = await fallback_fn()
        assert result == "fallback_result"
        assert len(fallback_calls) == 1


# ==================== Auth Tests ====================

class TestAuth:
    """Authentication middleware tests."""

    def test_verify_api_key_valid(self):
        """Test verification of valid API key."""
        valid_keys = ["key1", "key2", "secret-token"]
        assert verify_api_key("key1", valid_keys) is True
        assert verify_api_key("key2", valid_keys) is True

    def test_verify_api_key_invalid(self):
        """Test verification of invalid API key."""
        valid_keys = ["key1", "key2"]
        assert verify_api_key("invalid", valid_keys) is False
        assert verify_api_key("", valid_keys) is False
        assert verify_api_key("key1", []) is False

    def test_verify_jwt_valid(self):
        """Test verification of valid JWT token using HMAC fallback."""
        import hmac
        import hashlib
        import base64
        import json

        secret = "test-secret"

        # Create a simple JWT-like token manually
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b'=').decode()
        payload_data = {"sub": "user123", "exp": 9999999999}
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b'=').decode()

        signing_input = f"{header}.{payload}".encode('utf-8')
        signature = hmac.new(secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()

        token = f"{header}.{payload}.{sig_b64}"

        result = verify_jwt(token, secret)
        assert result is not None
        assert result["sub"] == "user123"

    def test_verify_jwt_invalid(self):
        """Test verification of invalid JWT token."""
        result = verify_jwt("invalid.token.here", "secret")
        assert result is None

        result = verify_jwt("not.a.jwt", "wrong-secret")
        assert result is None

    def test_auth_disabled_passthrough(self):
        """Test that authentication is bypassed when disabled."""
        result = verify_token("any-token", "bearer", api_keys=[], jwt_secret="")
        assert result is None  # No secret means no validation possible


# ==================== Sandbox Tests ====================

class TestSandbox:
    """Sandbox executor tests."""

    @pytest.mark.asyncio
    async def test_sandbox_run_python_success(self):
        """Test successful Python code execution."""
        sandbox = Sandbox(timeout=10)
        code = "print('Hello, World!')"

        result = await sandbox.run_python(code)

        assert result.exit_code == 0
        assert "Hello, World!" in result.stdout
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_sandbox_run_python_timeout(self):
        """Test Python code execution timeout."""
        sandbox = Sandbox(timeout=1)
        code = "import time\ntime.sleep(5)"

        result = await sandbox.run_python(code)

        assert result.timed_out is True
        assert result.exit_code == -1

    @pytest.mark.asyncio
    async def test_sandbox_run_shell_success(self):
        """Test successful shell command execution."""
        sandbox = Sandbox(timeout=10)

        result = await sandbox.run_shell("echo 'test output'")

        assert result.exit_code == 0
        assert "test output" in result.stdout

    @pytest.mark.asyncio
    async def test_sandbox_run_shell_blocked(self):
        """Test that blocked commands are rejected."""
        sandbox = Sandbox(timeout=10, allowed_commands=["echo", "ls"])

        result = await sandbox.run_shell("rm -rf /")

        assert result.exit_code == -1
        assert "not allowed" in result.error

    @pytest.mark.asyncio
    async def test_sandbox_env_filtered(self):
        """Test that sensitive environment variables are filtered."""
        # Set some test env vars
        os.environ["TEST_API_KEY"] = "secret123"
        os.environ["SAFE_VAR"] = "safe_value"

        sandbox = Sandbox()
        filtered = sandbox._filter_env()

        assert "TEST_API_KEY" not in filtered
        assert "SAFE_VAR" in filtered

        # Clean up
        del os.environ["TEST_API_KEY"]
        del os.environ["SAFE_VAR"]


# ==================== Compression Tests ====================

class TestCompression:
    """Conversation compressor tests."""

    def test_estimate_tokens(self):
        """Test token estimation accuracy."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # "Hello" (5 chars) + "Hi there!" (9 chars) = 14 chars
        # 14 // 4 = 3 tokens (approximate)
        estimated = ConversationCompressor.estimate_tokens(messages)
        assert estimated == 3

    def test_should_compress_false(self):
        """Test that compression is not triggered for short conversations."""
        compressor = ConversationCompressor(max_tokens=1000)
        messages = [
            {"role": "user", "content": "Short message"},
        ]

        assert compressor.should_compress(messages) is False

    def test_should_compress_true(self):
        """Test that compression is triggered for long conversations."""
        compressor = ConversationCompressor(max_tokens=100)
        messages = [
            {"role": "user", "content": "x" * 500},  # ~125 tokens
            {"role": "assistant", "content": "y" * 500},  # ~125 tokens
        ]

        assert compressor.should_compress(messages) is True

    @pytest.mark.asyncio
    async def test_compress_generates_summary(self):
        """Test that compression generates a summary using mock driver."""
        compressor = ConversationCompressor(max_tokens=100, keep_recent=1)

        # Create mock driver
        mock_driver = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"text": "Summary of conversation"}
        mock_driver.generate.return_value = mock_result

        messages = [
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": "Recent question"},
        ]

        result = await compressor.compress(messages, mock_driver)

        assert result.summary == "Summary of conversation"
        assert result.original_count == 3
        assert result.compressed_count == 2  # 1 summary + 1 recent
        mock_driver.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_compress_if_needed_no_action(self):
        """Test that no compression happens when not needed."""
        compressor = ConversationCompressor(max_tokens=10000)
        messages = [{"role": "user", "content": "Short"}]

        new_messages, result = await compressor.compress_if_needed(messages, AsyncMock())

        assert new_messages == messages
        assert result is None

    def test_apply_format(self):
        """Test that apply returns correct format."""
        messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "response"}]
        summary = "Conversation summary"

        compressed = ConversationCompressor.apply(messages, summary)

        assert len(compressed) == 1
        assert compressed[0]["role"] == "system"
        assert compressed[0]["content"] == summary


# ==================== Multimodal Tests ====================

class TestMultimodal:
    """Multimodal attachment and message tests."""

    def test_image_attachment_base64_block(self):
        """Test base64 image attachment generates correct content block."""
        attachment = ImageAttachment(
            content_type="image",
            base64_data="iVBORw0KGgo=",
            media_type="image/png",
        )

        block = attachment.to_content_block()

        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"
        assert block["source"]["data"] == "iVBORw0KGgo="

    def test_image_attachment_url_block(self):
        """Test URL image attachment generates correct content block."""
        attachment = ImageAttachment(
            content_type="image",
            url="https://example.com/image.png",
        )

        block = attachment.to_content_block()

        assert block["type"] == "image"
        assert block["source"]["type"] == "url"
        assert block["source"]["url"] == "https://example.com/image.png"

    def test_file_attachment_block(self):
        """Test file attachment generates correct content block."""
        attachment = FileAttachment(
            content_type="text/plain",
            filename="document.txt",
            text_content="File content here",
        )

        block = attachment.to_content_block()

        assert block["type"] == "text"
        assert "[File: document.txt]" in block["text"]
        assert "File content here" in block["text"]

    def test_multimodal_message_anthropic(self):
        """Test multimodal message conversion to Anthropic format."""
        image = ImageAttachment(
            content_type="image",
            base64_data="base64data",
            media_type="image/jpeg",
        )

        message = MultimodalMessage(
            role="user",
            text="What is this?",
            attachments=[image],
        )

        api_msg = message.to_api_message(provider="anthropic")

        assert api_msg["role"] == "user"
        assert isinstance(api_msg["content"], list)
        assert len(api_msg["content"]) == 2  # text + image
        assert api_msg["content"][0]["type"] == "text"
        assert api_msg["content"][1]["type"] == "image"

    def test_multimodal_message_openai(self):
        """Test multimodal message conversion to OpenAI format."""
        image = ImageAttachment(
            content_type="image",
            url="https://example.com/img.png",
        )

        message = MultimodalMessage(
            role="user",
            text="Describe this",
            attachments=[image],
        )

        api_msg = message.to_api_message(provider="openai")

        assert api_msg["role"] == "user"
        assert isinstance(api_msg["content"], list)
        assert api_msg["content"][1]["type"] == "image_url"
        assert "image_url" in api_msg["content"][1]

    def test_multimodal_message_no_attachment(self):
        """Test message without attachments uses simple format."""
        message = MultimodalMessage(role="user", text="Hello")

        api_msg = message.to_api_message()

        assert api_msg == {"role": "user", "content": "Hello"}

    def test_detect_media_type(self):
        """Test media type detection for common extensions."""
        assert detect_media_type("image.png") == "image/png"
        assert detect_media_type("photo.jpg") in ("image/jpeg", "image/jpg")
        assert detect_media_type("document.pdf") == "application/pdf"
        # .xyz extension may map to different types depending on system mime database
        result = detect_media_type("unknown.xyz")
        assert result in ("application/octet-stream", "chemical/x-xyz")

    def test_extract_text_from_file(self, tmp_path):
        """Test text extraction from files."""
        # Test txt file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello, World!")

        content = extract_text_from_file(txt_file)
        assert content == "Hello, World!"

        # Test binary file
        bin_file = tmp_path / "test.bin"
        bin_file.write_bytes(b"\x00\x01\x02")

        content = extract_text_from_file(bin_file)
        assert "[Binary file:" in content
