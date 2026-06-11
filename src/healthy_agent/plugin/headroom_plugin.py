"""Headroom integration plugin.

Provides two-layer context compression:
  Layer 1 (this plugin): Rule-based compression of tool outputs, JSON, code via Headroom
  Layer 2 (ConversationCompressor): LLM-based summarization of old conversation history

Install: pip install healthy-agent[headroom]

Usage:
    from healthy_agent.plugin import PluginManager
    from healthy_agent.plugin.headroom_plugin import HeadroomPlugin

    manager = PluginManager()
    manager.register(HeadroomPlugin())
    manager.start_all()
"""
from __future__ import annotations

import logging
from .base import Plugin, PluginContext, PluginMetadata

# Re-export HeadroomConfig from the canonical location
from healthy_agent.config.settings import HeadroomConfig

logger = logging.getLogger("healthy_agent.plugin.headroom")

def _check_headroom() -> bool:
    """Check if headroom-ai is installed."""
    try:
        import headroom  # noqa: F401
        return True
    except ImportError:
        return False


class HeadroomPlugin(Plugin):
    """Plugin that uses Headroom for rule-based context compression.

    Compresses tool outputs, JSON data, code snippets, and logs
    before they reach the LLM. This is a fast, deterministic first pass
    that doesn't require an LLM call.

    Works in the pre_generate hook to compress message content.
    """

    def __init__(self, config: HeadroomConfig | None = None):
        self._config = config or HeadroomConfig()
        self._compress_fn = None
        self._stats = {"calls": 0, "tokens_saved": 0}

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="headroom",
            version="1.0.0",
            description="Rule-based context compression via Headroom (tool outputs, JSON, code)",
            tags=["compression", "optimization", "tokens"],
        )

    def on_register(self, ctx: PluginContext) -> None:
        """Verify headroom is available on registration."""
        if not _check_headroom():
            logger.warning("headroom-ai not installed. Run: pip install headroom-ai")

    def on_start(self) -> None:
        """Initialize the headroom compress function."""
        if not _check_headroom():
            self._config.enabled = False
            return

        try:
            from headroom import compress
            self._compress_fn = compress
            logger.info("Headroom plugin started - rule-based compression enabled")
        except Exception as exc:
            logger.warning("Failed to initialize headroom: %s", exc)
            self._config.enabled = False

    def pre_generate(self, messages: list[dict], **kwargs) -> list[dict]:
        """Compress tool outputs and long content in messages before LLM call.

        Only compresses content that looks like tool output, JSON, or code.
        Short messages and user/assistant conversation are left untouched.
        """
        if not self._config.enabled or self._compress_fn is None:
            return messages

        compressed_messages = []
        for msg in messages:
            compressed_messages.append(self._compress_message(msg))
        return compressed_messages

    def _compress_message(self, msg: dict) -> dict:
        """Compress a single message if it contains compressible content."""
        content = msg.get("content", "")

        # Handle string content
        if isinstance(content, str):
            if self._should_compress(content, msg.get("role", "")):
                compressed = self._do_compress(content)
                if compressed != content:
                    self._stats["calls"] += 1
                    self._stats["tokens_saved"] += (len(content) - len(compressed)) // 4
                    return {**msg, "content": compressed}
            return msg

        # Handle list content (multi-part messages like tool results)
        if isinstance(content, list):
            new_content = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if self._should_compress(text, msg.get("role", "")):
                        compressed = self._do_compress(text)
                        if compressed != text:
                            self._stats["calls"] += 1
                            self._stats["tokens_saved"] += (len(text) - len(compressed)) // 4
                            new_content.append({**part, "text": compressed})
                            continue
                new_content.append(part)
            return {**msg, "content": new_content}

        return msg

    def _should_compress(self, content: str, role: str) -> bool:
        """Determine if content should be compressed."""
        if len(content) < self._config.min_content_length:
            return False

        # Don't compress user messages (preserve intent)
        if role == "user":
            return False

        # Compress tool outputs
        if role == "tool":
            return self._config.compress_tool_outputs

        # For assistant messages, only compress if it looks like code/JSON
        if role == "assistant":
            return self._looks_like_structured(content)

        # System messages with embedded data
        if role == "system" and self._looks_like_structured(content):
            return True

        return False

    def _looks_like_structured(self, content: str) -> bool:
        """Heuristic: does this content look like JSON, code, or logs?"""
        stripped = content.strip()

        # JSON
        if self._config.compress_json and (
            stripped.startswith("{") or stripped.startswith("[")
        ):
            return True

        # Code blocks
        if self._config.compress_code and (
            stripped.startswith("```") or
            "def " in stripped[:200] or
            "class " in stripped[:200] or
            "import " in stripped[:100]
        ):
            return True

        # Logs / structured output (many short lines)
        lines = stripped.split("\n")
        if len(lines) > 20:
            return True

        return False

    def _do_compress(self, content: str) -> str:
        """Call headroom compress on content."""
        try:
            result = self._compress_fn(content)
            # headroom.compress may return str or a result object
            if isinstance(result, str):
                return result
            if hasattr(result, "text"):
                return result.text
            if hasattr(result, "compressed"):
                return result.compressed
            return str(result)
        except Exception as exc:
            logger.debug("Headroom compression failed, using original: %s", exc)
            return content

    @property
    def stats(self) -> dict:
        """Return compression statistics."""
        return dict(self._stats)


class HeadroomFallbackPlugin(Plugin):
    """Lightweight fallback when headroom-ai is not installed.

    Applies simple rule-based compression:
    - Truncates very long tool outputs
    - Removes redundant whitespace from JSON
    - Strips comments from code blocks
    """

    def __init__(self, max_tool_output_chars: int = 3000):
        self._max_chars = max_tool_output_chars
        self._stats = {"calls": 0, "chars_saved": 0}

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="headroom-fallback",
            version="1.0.0",
            description="Lightweight rule-based compression (no external deps)",
            tags=["compression", "optimization"],
        )

    def pre_generate(self, messages: list[dict], **kwargs) -> list[dict]:
        """Apply simple compression to tool outputs."""
        return [self._compress_message(msg) for msg in messages]

    def _compress_message(self, msg: dict) -> dict:
        content = msg.get("content", "")
        role = msg.get("role", "")

        if not isinstance(content, str) or role == "user":
            return msg

        if len(content) <= self._max_chars:
            return msg

        # Only compress tool outputs and very long system messages
        if role not in ("tool", "system"):
            return msg

        original_len = len(content)
        compressed = self._simple_compress(content)
        if len(compressed) < original_len:
            self._stats["calls"] += 1
            self._stats["chars_saved"] += original_len - len(compressed)
            return {**msg, "content": compressed}
        return msg

    def _simple_compress(self, content: str) -> str:
        """Simple compression: collapse whitespace, truncate with summary."""
        import re

        # Collapse multiple blank lines
        result = re.sub(r"\n{3,}", "\n\n", content)

        # Collapse multiple spaces
        result = re.sub(r"[ \t]{4,}", "  ", result)

        # If still too long, truncate with indicator
        if len(result) > self._max_chars:
            keep_start = self._max_chars * 2 // 3
            keep_end = self._max_chars // 3
            truncated_count = len(result) - keep_start - keep_end
            result = (
                result[:keep_start]
                + f"\n\n[... {truncated_count} chars truncated ...]\n\n"
                + result[-keep_end:]
            )

        return result

    @property
    def stats(self) -> dict:
        return dict(self._stats)
