"""Conversation compression module for long dialogues.

Provides utilities to compress conversation history by summarizing
older messages while preserving recent context.
"""
from .compressor import ConversationCompressor, CompressionResult

__all__ = ["ConversationCompressor", "CompressionResult"]
