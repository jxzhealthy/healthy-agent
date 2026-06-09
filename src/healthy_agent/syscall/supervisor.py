from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, TYPE_CHECKING

from .api import fork, wait

if TYPE_CHECKING:
    from ..kernel.runtime import Kernel
    from ..kernel.process import Process


@dataclass
class Attempt:
    round: int
    result: Any = None
    error: str = ""
    feedback: str = ""
    success: bool = False


@dataclass
class SupervisedResult:
    success: bool
    result: Any = None
    attempts: list[Attempt] = field(default_factory=list)
    total_rounds: int = 0


async def supervised_fork(
    kernel: Kernel,
    parent: Process,
    task_type: str,
    payload: dict,
    handler: Callable[..., Coroutine],
    *,
    max_retries: int = 3,
    judge: Callable[..., Coroutine] | None = None,
    on_retry: Callable | None = None,
    backoff_base: float = 0.5,
    backoff_max: float = 30.0,
) -> SupervisedResult:
    """Fork a child process with automatic retry, error correction, and exponential backoff.

    Like a supervisor that restarts crashed processes, but smarter —
    it feeds error context back into the next attempt.

    Args:
        kernel: The kernel instance
        parent: Parent process
        task_type: Process type name
        payload: Initial payload
        handler: The async handler to execute
        max_retries: Max number of retry attempts
        judge: Optional async function(result, payload) -> (passed: bool, feedback: str)
               If None, any non-Exception result is considered success.
        on_retry: Optional callback(attempt) called before each retry
        backoff_base: Base delay in seconds for exponential backoff (0 to disable)
        backoff_max: Maximum backoff delay in seconds
    """
    attempts: list[Attempt] = []
    current_payload = dict(payload)

    for round_num in range(1, max_retries + 1):
        attempt = Attempt(round=round_num)

        child_pid = await fork(kernel, parent, f"{task_type}_r{round_num}", current_payload, handler=handler)
        result = await wait(kernel, parent, child_pid)

        if isinstance(result, Exception):
            attempt.error = str(result)
            attempt.success = False
        elif judge:
            passed, feedback = await judge(result, current_payload)
            attempt.result = result
            attempt.success = passed
            attempt.feedback = feedback
        else:
            attempt.result = result
            attempt.success = True

        attempts.append(attempt)

        if attempt.success:
            return SupervisedResult(
                success=True, result=attempt.result,
                attempts=attempts, total_rounds=round_num,
            )

        error_context = attempt.error or attempt.feedback
        current_payload = dict(payload)
        current_payload["_retry_round"] = round_num
        current_payload["_previous_error"] = error_context
        current_payload["_previous_result"] = attempt.result

        if on_retry:
            on_retry(attempt)

        # Exponential backoff before next attempt
        if round_num < max_retries and backoff_base > 0:
            delay = min(backoff_base * (2 ** (round_num - 1)), backoff_max)
            await asyncio.sleep(delay)

    return SupervisedResult(
        success=False, result=attempts[-1].result if attempts else None,
        attempts=attempts, total_rounds=len(attempts),
    )
