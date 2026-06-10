"""Retry mechanism with exponential backoff and jitter."""
from __future__ import annotations

import asyncio
import random
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Type

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Configuration for retry behavior.
    
    Attributes:
        max_retries: Maximum number of retry attempts (0 means no retry).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Base for exponential backoff calculation.
        retryable_exceptions: Tuple of exception types that should trigger retry.
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[Type[Exception], ...] = field(
        default_factory=lambda: (Exception,)
    )


async def with_retry(fn: Callable[..., Awaitable[Any]], policy: RetryPolicy, *args, **kwargs) -> Any:
    """Execute an async function with retry logic using exponential backoff.
    
    Args:
        fn: Async callable to execute.
        policy: Retry policy configuration.
        *args: Positional arguments to pass to fn.
        **kwargs: Keyword arguments to pass to fn.
        
    Returns:
        The result of the successful function call.
        
    Raises:
        Exception: The last exception if all retries are exhausted.
    """
    last_exception: Exception | None = None
    
    for attempt in range(policy.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except policy.retryable_exceptions as e:
            last_exception = e
            
            if attempt < policy.max_retries:
                # Calculate delay with exponential backoff and jitter
                delay = min(
                    policy.base_delay * (policy.exponential_base ** attempt),
                    policy.max_delay
                )
                jitter = random.uniform(0, 0.1 * delay)
                total_delay = delay + jitter
                
                logger.warning(
                    f"Attempt {attempt + 1}/{policy.max_retries + 1} failed: {e}. "
                    f"Retrying in {total_delay:.2f}s..."
                )
                
                await asyncio.sleep(total_delay)
            else:
                logger.error(
                    f"All {policy.max_retries + 1} attempts failed. Last error: {e}"
                )
    
    # This should never be reached, but for type safety
    raise last_exception  # type: ignore
