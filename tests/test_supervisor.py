"""Tests for supervised_fork — retry, error correction, and judge."""
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import supervised_fork


async def test_success_on_first_try():
    async def handler(process, kernel):
        return "ok"

    async def parent(process, kernel):
        return await supervised_fork(kernel, process, "task", {}, handler)

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert result.result == "ok"
    assert result.total_rounds == 1
    assert len(result.attempts) == 1


async def test_retry_on_exception():
    call_count = 0

    async def flaky_handler(process, kernel):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"fail #{call_count}")
        return "finally works"

    async def parent(process, kernel):
        return await supervised_fork(kernel, process, "flaky", {}, flaky_handler, max_retries=5)

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert result.result == "finally works"
    assert result.total_rounds == 3
    assert not result.attempts[0].success
    assert not result.attempts[1].success
    assert result.attempts[2].success


async def test_max_retries_exhausted():
    async def always_fail(process, kernel):
        raise RuntimeError("always broken")

    async def parent(process, kernel):
        return await supervised_fork(kernel, process, "fail", {}, always_fail, max_retries=3)

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert not result.success
    assert result.total_rounds == 3
    assert all(not a.success for a in result.attempts)


async def test_judge_rejects_bad_result():
    call_count = 0

    async def handler(process, kernel):
        nonlocal call_count
        call_count += 1
        return call_count * 10

    async def judge(result, payload):
        if result >= 30:
            return True, ""
        return False, f"Result {result} is too small, need >= 30"

    async def parent(process, kernel):
        return await supervised_fork(kernel, process, "quality", {}, handler, max_retries=5, judge=judge)

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert result.result == 30
    assert result.total_rounds == 3
    assert "too small" in result.attempts[0].feedback


async def test_error_context_passed_to_retry():
    received_contexts = []

    async def handler(process, kernel):
        prev_error = process.payload.get("_previous_error")
        received_contexts.append(prev_error)
        if prev_error is None:
            raise ValueError("first attempt fails")
        return f"fixed after: {prev_error}"

    async def parent(process, kernel):
        return await supervised_fork(kernel, process, "ctx", {"input": "test"}, handler, max_retries=3)

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert "fixed after" in result.result
    assert received_contexts[0] is None
    assert "first attempt fails" in received_contexts[1]


async def test_on_retry_callback():
    retries = []

    async def handler(process, kernel):
        if process.payload.get("_retry_round") is None:
            raise ValueError("fail")
        return "ok"

    def on_retry(attempt):
        retries.append(attempt.round)

    async def parent(process, kernel):
        return await supervised_fork(kernel, process, "cb", {}, handler, max_retries=3, on_retry=on_retry)

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert retries == [1]


# --- Exponential backoff ---

async def test_backoff_delays_retries():
    """Verify that backoff actually introduces delay between retries."""
    import time
    timestamps = []

    async def handler(process, kernel):
        timestamps.append(time.monotonic())
        if len(timestamps) < 3:
            raise ValueError("fail")
        return "ok"

    async def parent(process, kernel):
        return await supervised_fork(
            kernel, process, "backoff", {}, handler,
            max_retries=3, backoff_base=0.1, backoff_max=5.0,
        )

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert len(timestamps) == 3
    # First retry delay should be ~0.1s (backoff_base * 2^0)
    gap1 = timestamps[1] - timestamps[0]
    assert gap1 >= 0.08  # allow small timing variance
    # Second retry delay should be ~0.2s (backoff_base * 2^1)
    gap2 = timestamps[2] - timestamps[1]
    assert gap2 >= 0.15


async def test_backoff_disabled():
    """With backoff_base=0, retries should happen immediately."""
    import time
    timestamps = []

    async def handler(process, kernel):
        timestamps.append(time.monotonic())
        if len(timestamps) < 3:
            raise ValueError("fail")
        return "ok"

    async def parent(process, kernel):
        return await supervised_fork(
            kernel, process, "no_backoff", {}, handler,
            max_retries=3, backoff_base=0,
        )

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    assert len(timestamps) == 3
    total_time = timestamps[-1] - timestamps[0]
    assert total_time < 0.5  # Should be very fast without backoff


async def test_backoff_max_cap():
    """Verify backoff delay is capped at backoff_max."""
    import time
    timestamps = []

    async def handler(process, kernel):
        timestamps.append(time.monotonic())
        if len(timestamps) < 3:
            raise ValueError("fail")
        return "ok"

    async def parent(process, kernel):
        return await supervised_fork(
            kernel, process, "capped", {}, handler,
            max_retries=3, backoff_base=10.0, backoff_max=0.1,
        )

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result.success
    # Despite large backoff_base, max caps it at 0.1s
    total_time = timestamps[-1] - timestamps[0]
    assert total_time < 1.0
