"""Conversation compressor for managing long dialogue histories.

Provides functionality to compress conversation messages by summarizing
older messages while preserving recent context, helping to stay within
LLM token limits.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..drivers.base import LLMDriver
from ..observability.metrics import metrics

logger = logging.getLogger("healthy_agent.compression")


@dataclass
class CompressionResult:
    """Result of a conversation compression operation."""
    summary: str
    original_count: int
    compressed_count: int
    tokens_saved_estimate: int


DEFAULT_SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Summarize the following conversation history into a concise paragraph "
    "that preserves all important facts, decisions, user preferences, and context needed for continuing the "
    "conversation. Be specific and factual."
)


class ConversationCompressor:
    """Compresses long conversation histories by summarizing older messages.

    Usage:
        compressor = ConversationCompressor(max_tokens=4000, keep_recent=10)
        messages, result = await compressor.compress_if_needed(messages, driver)
    """

    def __init__(
        self,
        max_tokens: int | None = None,
        keep_recent: int = 10,
        summary_system_prompt: str = DEFAULT_SUMMARY_SYSTEM_PROMPT,
    ):
        if max_tokens is None:
            from healthy_agent.config.settings import settings
            max_tokens = settings.compression.max_tokens_threshold
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent
        self.summary_system_prompt = summary_system_prompt

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """Estimate token count using simple character-based heuristic.

        Approximation: 4 characters ~ 1 token.
        """
        total_chars = sum(len(msg.get("content", "")) for msg in messages)
        return total_chars // 4

    def should_compress(self, messages: list[dict]) -> bool:
        """Check if compression should be triggered based on token estimate."""
        estimated_tokens = self.estimate_tokens(messages)
        return estimated_tokens > self.max_tokens

    async def compress(self, messages: list[dict], driver: LLMDriver) -> CompressionResult:
        """Compress old messages by generating a summary via LLM.

        Args:
            messages: Full conversation history
            driver: LLMDriver instance for generating summary

        Returns:
            CompressionResult with summary and statistics
        """
        # Split messages into old (to compress) and recent (to keep)
        recent_count = min(self.keep_recent, len(messages))
        old_messages = messages[:-recent_count] if recent_count < len(messages) else []
        recent_messages = messages[-recent_count:] if recent_count > 0 else []

        if not old_messages:
            # Nothing to compress
            return CompressionResult(
                summary="",
                original_count=len(messages),
                compressed_count=len(messages),
                tokens_saved_estimate=0,
            )

        # Build prompt for summarization
        conversation_text = self._format_messages(old_messages)
        summary_messages = [
            {"role": "system", "content": self.summary_system_prompt},
            {"role": "user", "content": f"Please summarize the following conversation:\n\n{conversation_text}"},
        ]

        # Generate summary using LLM
        logger.info(f"Compressing {len(old_messages)} messages into summary...")
        result = await driver.generate(summary_messages)

        if not result.success:
            logger.warning(f"Compression failed: {result.error}")
            # Return original messages if compression fails
            return CompressionResult(
                summary="",
                original_count=len(messages),
                compressed_count=len(messages),
                tokens_saved_estimate=0,
            )

        summary = result.data.get("text", "").strip()
        original_tokens = self.estimate_tokens(old_messages)
        compressed_tokens = self.estimate_tokens([{"role": "system", "content": summary}])
        tokens_saved = original_tokens - compressed_tokens

        # Record metrics
        metrics.increment("compression.runs")
        metrics.increment("compression.tokens_saved", value=max(0, tokens_saved))

        logger.info(f"Compression complete: saved ~{tokens_saved} tokens")

        return CompressionResult(
            summary=summary,
            original_count=len(messages),
            compressed_count=len(recent_messages) + 1,  # 1 for summary message
            tokens_saved_estimate=max(0, tokens_saved),
        )

    @staticmethod
    def apply(messages: list[dict], summary: str) -> list[dict]:
        """Apply compression result to create new message list.

        Args:
            messages: Original messages (used to determine recent messages)
            summary: Generated summary text

        Returns:
            New messages list with summary + recent messages
        """
        # This method needs to know keep_recent, so we'll handle it in compress_if_needed
        # For standalone use, caller should manage recent messages
        return [{"role": "system", "content": summary}]

    async def compress_if_needed(
        self, messages: list[dict], driver: LLMDriver
    ) -> tuple[list[dict], CompressionResult | None]:
        """Compress messages if they exceed token threshold.

        Args:
            messages: Full conversation history
            driver: LLMDriver instance

        Returns:
            Tuple of (messages, compression_result).
            If no compression needed, returns (messages, None).
        """
        if not self.should_compress(messages):
            return messages, None

        # Perform compression
        result = await self.compress(messages, driver)

        if not result.summary:
            # Compression failed or nothing to compress
            return messages, result

        # Apply compression: summary + recent messages
        recent_count = min(self.keep_recent, len(messages))
        recent_messages = messages[-recent_count:] if recent_count > 0 else []
        compressed_messages = [{"role": "system", "content": result.summary}] + recent_messages

        return compressed_messages, result

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """Format messages into a readable string for summarization."""
        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n\n".join(parts)
