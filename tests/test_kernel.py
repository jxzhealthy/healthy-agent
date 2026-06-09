"""Core kernel tests: process, scheduler, core, runtime."""
import asyncio
from healthy_agent.kernel.process import Process, ProcessState
from healthy_agent.kernel.scheduler import MLFQScheduler
from healthy_agent.kernel.runtime import Kernel
from healthy_agent.syscall import fork
from healthy_agent.ipc import Channel, Message


# --- Process ---

def test_process_lifecycle():
    p = Process(1, "test", {"x": 1})
    assert p.pid == 1
    assert p.state == ProcessState.NEW
    p.state = ProcessState.READY
    p.block("io")
    assert p.state == ProcessState.BLOCKED
    p.unblock()
    assert p.state == ProcessState.READY
    p.terminate(42)
    assert p.pcb.result == 42


# --- Scheduler ---

def test_scheduler_admit_schedule():
    s = MLFQScheduler()
    p = Process(1, "t", {})
    s.admit(p)
    assert s.total_ready == 1
    got = s.schedule()
    assert got.pid == 1
    assert got.state == ProcessState.RUNNING


def test_scheduler_preempt_demotes():
    s = MLFQScheduler()
    p = Process(1, "t", {})
    s.admit(p)
    s.schedule()
    s.preempt(p)
    assert p.pcb.priority == 1


def test_scheduler_boost():
    s = MLFQScheduler()
    p = Process(1, "t", {})
    s.admit(p)
    s.schedule()
    s.preempt(p)
    s.schedule()
    s.preempt(p)
    assert p.pcb.priority == 2
    s.boost()
    assert p.pcb.priority == 0


def test_scheduler_empty():
    s = MLFQScheduler()
    assert s.is_empty
    assert s.schedule() is None


# --- Kernel ---

async def test_kernel_simple():
    async def handler(process, kernel):
        return "hello"

    k = Kernel(num_cores=1)
    pid = k.spawn("test", {}, handler=handler)
    result = await k.exec(pid)
    assert result == "hello"


async def test_kernel_fork():
    async def parent(process, kernel):
        cpid = await fork(kernel, process, "child", {}, handler=child)
        event = kernel._get_event(cpid)
        await event.wait()
        return f"got:{kernel.process_table[cpid].pcb.result}"

    async def child(process, kernel):
        return 99

    k = Kernel(num_cores=2)
    pid = k.spawn("parent", {}, handler=parent, preemptible=False)
    result = await k.exec(pid)
    assert result == "got:99"


async def test_kernel_multiple_tasks():
    async def parent_handler(process, kernel):
        pids = []
        for i in range(5):
            cpid = await fork(kernel, process, "work", {"val": i}, handler=work_handler)
            pids.append(cpid)
        results = []
        for cpid in pids:
            await kernel._get_event(cpid).wait()
            results.append(kernel.process_table[cpid].pcb.result)
        return sorted(results)

    async def work_handler(process, kernel):
        await asyncio.sleep(0.01)
        return process.payload["val"]

    k = Kernel(num_cores=4)
    pid = k.spawn("parent", {}, handler=parent_handler, preemptible=False)
    result = await k.exec(pid)
    assert result == [0, 1, 2, 3, 4]


async def test_kernel_ps():
    async def handler(p, k):
        return None
    k = Kernel(num_cores=1)
    k.spawn("a", {}, handler=handler)
    k.spawn("b", {}, handler=handler)
    ps = k.ps()
    assert len(ps) == 2
    assert ps[0]["type"] == "a"


# --- IPC ---

async def test_channel():
    ch = Channel("test")
    await ch.send(Message(sender_pid=1, data="hello"))
    msg = await ch.recv(timeout=1.0)
    assert msg is not None
    assert msg.data == "hello"
    assert msg.sender_pid == 1


async def test_channel_empty():
    ch = Channel("test")
    msg = ch.try_recv()
    assert msg is None


# --- Driver ---

async def test_shell_driver():
    from healthy_agent.drivers.tool_builtin import ShellDriver
    drv = ShellDriver()
    result = await drv.invoke("exec", {"command": "echo hello"})
    assert result.success
    assert "hello" in result.data["stdout"]


async def test_shell_driver_failure():
    from healthy_agent.drivers.tool_builtin import ShellDriver
    drv = ShellDriver()
    result = await drv.invoke("exec", {"command": "false"})
    assert not result.success


# --- IPC: message history ---

async def test_channel_history():
    ch = Channel("test", history_size=5)
    await ch.send(Message(sender_pid=1, data="msg1"))
    await ch.send(Message(sender_pid=2, data="msg2"))
    await ch.send(Message(sender_pid=3, data="msg3"))

    history = ch.get_history()
    assert len(history) == 3
    assert history[0].data == "msg1"

    recent = ch.get_history(last_n=2)
    assert len(recent) == 2
    assert recent[0].data == "msg2"


async def test_channel_no_history():
    ch = Channel("test")  # history_size=0 by default
    await ch.send(Message(sender_pid=1, data="msg1"))
    assert ch.get_history() == []


# --- IPC: BroadcastChannel ---

async def test_broadcast_channel():
    from healthy_agent.ipc import BroadcastChannel
    broadcast = BroadcastChannel("events")
    sub1 = broadcast.subscribe("agent_1")
    sub2 = broadcast.subscribe("agent_2")

    delivered = await broadcast.publish(Message(sender_pid=0, data="hello"))
    assert delivered == 2
    assert broadcast.subscriber_count == 2

    msg1 = await sub1.recv(timeout=1.0)
    msg2 = await sub2.recv(timeout=1.0)
    assert msg1 is not None and msg1.data == "hello"
    assert msg2 is not None and msg2.data == "hello"


async def test_broadcast_unsubscribe():
    from healthy_agent.ipc import BroadcastChannel
    broadcast = BroadcastChannel("events")
    sub1 = broadcast.subscribe("a")
    sub2 = broadcast.subscribe("b")

    sub1.unsubscribe()
    assert broadcast.subscriber_count == 1

    delivered = await broadcast.publish(Message(sender_pid=0, data="test"))
    assert delivered == 1

    msg = await sub2.recv(timeout=1.0)
    assert msg is not None and msg.data == "test"


# --- IPC: TopicRouter ---

async def test_topic_router():
    from healthy_agent.ipc import TopicRouter
    errors_ch = Channel("errors")
    metrics_ch = Channel("metrics")

    router = TopicRouter()
    router.register("errors", errors_ch)
    router.register("metrics", metrics_ch)

    assert sorted(router.topics) == ["errors", "metrics"]

    routed = await router.route(Message(sender_pid=1, data="oops", topic="errors"))
    assert routed is True
    msg = await errors_ch.recv(timeout=1.0)
    assert msg is not None and msg.data == "oops"

    routed = await router.route(Message(sender_pid=1, data="cpu=50", topic="metrics"))
    assert routed is True

    routed = await router.route(Message(sender_pid=1, data="lost", topic="unknown"))
    assert routed is False


async def test_topic_router_default():
    from healthy_agent.ipc import TopicRouter
    default_ch = Channel("default")
    router = TopicRouter()
    router.set_default(default_ch)

    routed = await router.route(Message(sender_pid=1, data="catch_all", topic="anything"))
    assert routed is True
    msg = await default_ch.recv(timeout=1.0)
    assert msg is not None and msg.data == "catch_all"
