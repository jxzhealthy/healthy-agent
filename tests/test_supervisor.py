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
