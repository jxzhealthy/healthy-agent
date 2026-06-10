"""Circuit breaker pattern implementation for fault tolerance."""
from __future__ import annotations

import asyncio
import time
import logging
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tripped, requests fail fast
    HALF_OPEN = "half_open" # Testing if service recovered


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and request is rejected."""
    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message)


class CircuitBreaker:
    """Circuit breaker implementation with three states.
    
    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Circuit tripped after consecutive failures, requests fail immediately
        - HALF_OPEN: After recovery timeout, allows one test request
        
    Attributes:
        failure_threshold: Number of consecutive failures before opening circuit.
        recovery_timeout: Seconds to wait before transitioning from OPEN to HALF_OPEN.
        success_threshold: Number of consecutive successes in HALF_OPEN to close circuit.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for automatic transitions."""
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state
    
    async def call(self, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        """Execute function through circuit breaker.
        
        Args:
            fn: Async callable to execute.
            *args: Positional arguments to pass to fn.
            **kwargs: Keyword arguments to pass to fn.
            
        Returns:
            The result of the function call.
            
        Raises:
            CircuitOpenError: If circuit is open and request is rejected.
            Exception: Any exception from the function call.
        """
        async with self._lock:
            current_state = self.state
            
            if current_state == CircuitState.OPEN:
                logger.warning("Circuit breaker is OPEN, rejecting request")
                raise CircuitOpenError()
            
            if current_state == CircuitState.HALF_OPEN:
                self._state = CircuitState.HALF_OPEN
        
        try:
            result = await fn(*args, **kwargs)
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise
    
    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logger.info("Circuit breaker closed after successful recovery")
                    self._close()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0
    
    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker re-opened after failure in half-open state")
                self._open()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    logger.warning(
                        f"Circuit breaker opened after {self._failure_count} consecutive failures"
                    )
                    self._open()
    
    def _open(self) -> None:
        """Transition to OPEN state."""
        self._state = CircuitState.OPEN
        self._success_count = 0
    
    def _close(self) -> None:
        """Transition to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
    
    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logger.info("Circuit breaker manually reset")
