"""Resilient driver wrapper with retry and circuit breaker integration."""
from __future__ import annotations

import logging

from ..drivers.base import LLMDriver, IOResult
from ..observability.metrics import metrics
from .retry import RetryPolicy, with_retry
from .circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)


class ResilientDriver(LLMDriver):
    """Wrapper around a primary LLM driver with fallback support.
    
    Provides fault tolerance through:
    - Retry with exponential backoff for transient failures
    - Circuit breaker to prevent cascading failures
    - Fallback driver when primary is unavailable
    
    Attributes:
        primary: The primary LLM driver.
        fallback: Optional fallback driver if primary fails.
        retry_policy: Configuration for retry behavior.
        circuit_breaker: Circuit breaker instance.
    """
    
    def __init__(
        self,
        primary: LLMDriver,
        fallback: LLMDriver | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self._primary = primary
        self._fallback = fallback
        self._retry_policy = retry_policy or RetryPolicy()
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
    
    @property
    def name(self) -> str:
        return f"{self._primary.name}+resilient"
    
    @property
    def driver_type(self) -> str:
        return "llm"
    
    async def generate(self, messages: list[dict], **kwargs) -> IOResult:
        """Generate response with resilience mechanisms.
        
        Flow:
        1. Try primary with retry policy
        2. If circuit breaker opens or all retries fail, use fallback
        
        Args:
            messages: List of message dictionaries.
            **kwargs: Additional arguments for the driver.
            
        Returns:
            IOResult with generation result.
        """
        # Try primary with circuit breaker and retry
        try:
            result = await self._circuit_breaker.call(
                with_retry,
                self._primary.generate,
                self._retry_policy,
                messages,
                **kwargs
            )
            metrics.increment("resilience.retries", tags={"driver": self.name, "outcome": "success"})
            return result
            
        except CircuitOpenError:
            logger.warning(f"Circuit breaker open for {self._primary.name}, using fallback")
            metrics.increment("resilience.circuit_opens", tags={"driver": self.name})
            
        except Exception as e:
            logger.error(f"Primary driver failed after retries: {e}")
            metrics.increment("resilience.retries", tags={"driver": self.name, "outcome": "failure"})
        
        # Fallback to secondary driver
        if self._fallback:
            logger.info(f"Using fallback driver: {self._fallback.name}")
            metrics.increment("resilience.fallbacks", tags={"from": self.name, "to": self._fallback.name})
            try:
                return await self._fallback.generate(messages, **kwargs)
            except Exception as e:
                logger.error(f"Fallback driver also failed: {e}")
                return IOResult(success=False, error=f"Both primary and fallback failed: {e}")
        
        return IOResult(success=False, error="Primary driver failed and no fallback configured")
    
    async def stream(self, messages: list[dict], **kwargs):
        """Stream response with fallback support.
        
        Flow:
        1. Try primary.stream()
        2. If it fails, use fallback.stream()
        
        Args:
            messages: List of message dictionaries.
            **kwargs: Additional arguments for the driver.
            
        Yields:
            Streamed response chunks.
        """
        try:
            async for chunk in self._primary.stream(messages, **kwargs):
                yield chunk
        except Exception as e:
            logger.warning(f"Primary stream failed: {e}, switching to fallback")
            metrics.increment("resilience.fallbacks", tags={"from": self.name, "to": self._fallback.name if self._fallback else "none"})
            
            if self._fallback:
                async for chunk in self._fallback.stream(messages, **kwargs):
                    yield chunk
            else:
                raise
