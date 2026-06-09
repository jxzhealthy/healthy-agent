"""
Example 5: Multi-Agent - coordination, debate, IPC, and MCP.

Demonstrates:
  - MultiAgentCoordinator: parallel and pipeline modes
  - Debate with consensus detection
  - BroadcastChannel for inter-agent communication
  - MCP server exposing agent capabilities
"""
import asyncio
import json

from healthy_agent.kernel.runtime import Kernel
from healthy_agent.agent import MultiAgentCoordinator, AgentConfig
from healthy_agent.ipc import Message, BroadcastChannel
from healthy_agent.mcp.server import McpServer


# -- Parallel agents --

async def demo_parallel():
    print("=== Parallel Agents ===\n")

    async def analyzer(process, kernel):
        await asyncio.sleep(0.05)
        return {"analysis": "positive", "confidence": 0.85}

    async def summarizer(process, kernel):
        await asyncio.sleep(0.05)
        return {"summary": "Key findings: growth is strong", "words": 7}

    async def fact_checker(process, kernel):
        await asyncio.sleep(0.05)
        return {"verified": True, "claims_checked": 3}

    kernel = Kernel(num_cores=4)

    async def run_parallel(process, kernel_ref):
        coord = MultiAgentCoordinator(kernel_ref)
        return await coord.parallel(
            [
                AgentConfig(name="analyzer", handler=analyzer),
                AgentConfig(name="summarizer", handler=summarizer),
                AgentConfig(name="fact_checker", handler=fact_checker),
            ],
            process,
        )

    pid = kernel.spawn("parallel", {}, handler=run_parallel, preemptible=False)
    result = await kernel.exec(pid)

    print(f"  Agents: {result.total_agents}")
    for name, output in result.results.items():
        print(f"  {name}: {output}")


# -- Debate with consensus --

async def demo_debate():
    print("\n=== Debate with Consensus Detection ===\n")

    async def optimist(process, kernel):
        round_num = process.payload.get("_debate_round", 0)
        _history = process.payload.get("_debate_history", [])
        if round_num == 0:
            return "The market will grow 15%"
        return "The market will grow 15%"

    async def pessimist(process, kernel):
        round_num = process.payload.get("_debate_round", 0)
        if round_num == 0:
            return "The market will decline 5%"
        # After seeing round 0, pessimist adjusts
        return "The market will grow 15%"

    async def realist(process, kernel):
        return "The market will grow 15%"

    kernel = Kernel(num_cores=4)

    async def run_debate(process, kernel_ref):
        coord = MultiAgentCoordinator(kernel_ref)
        return await coord.debate(
            [
                AgentConfig(name="optimist", handler=optimist),
                AgentConfig(name="pessimist", handler=pessimist),
                AgentConfig(name="realist", handler=realist),
            ],
            process,
            topic="Q3 market outlook",
            rounds=3,
            consensus_threshold=0.66,
        )

    pid = kernel.spawn("debate", {}, handler=run_debate, preemptible=False)
    result = await kernel.exec(pid)

    consensus = result.results.get("consensus")
    consensus_round = result.results.get("consensus_round")
    print(f"  Consensus: {consensus}")
    print(f"  Reached at round: {consensus_round}")


# -- IPC: BroadcastChannel --

async def demo_ipc():
    print("\n=== IPC: Broadcast Channel ===\n")

    broadcast = BroadcastChannel("events")
    sub_logger = broadcast.subscribe("logger")
    sub_monitor = broadcast.subscribe("monitor")

    # Publish events
    await broadcast.publish(Message(sender_pid=1, data={"event": "task_started", "task": "analysis"}))
    await broadcast.publish(Message(sender_pid=2, data={"event": "task_completed", "result": "ok"}))

    # Each subscriber receives all messages
    logger_msgs = []
    while sub_logger.pending > 0:
        msg = sub_logger.try_recv()
        if msg:
            logger_msgs.append(msg.data)

    monitor_msgs = []
    while sub_monitor.pending > 0:
        msg = sub_monitor.try_recv()
        if msg:
            monitor_msgs.append(msg.data)

    print(f"  Logger received: {len(logger_msgs)} messages")
    for msg in logger_msgs:
        print(f"    {msg}")
    print(f"  Monitor received: {len(monitor_msgs)} messages")
    print(f"  Subscribers: {broadcast.subscriber_count}")


# -- MCP Server --

async def demo_mcp():
    print("\n=== MCP Server ===\n")

    server = McpServer()

    # Register a tool
    async def echo_handler(args):
        return {"echo": args.get("text", "")}

    server.register_tool("echo", "Echo back the input text",
                         {"type": "object", "properties": {"text": {"type": "string"}}},
                         echo_handler)

    # Register a resource
    async def status_provider():
        return json.dumps({"status": "healthy", "uptime": 3600})

    server.register_resource(
        uri="status://agent",
        name="Agent Status",
        description="Current agent health status",
        mime_type="application/json",
        provider=status_provider,
    )

    # Register a prompt
    server.register_prompt(
        name="analyze",
        description="Analyze a topic",
        arguments=[{"name": "topic", "required": True}],
        template="Please analyze the following topic in detail: {topic}",
    )

    # Initialize
    init_result = await server.handle_message(
        {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
    )
    caps = json.loads(init_result)["result"]["capabilities"]
    print(f"  Capabilities: {list(caps.keys())}")

    # List & call tool
    tool_result = await server.handle_message(
        {"jsonrpc": "2.0", "method": "tools/call",
         "params": {"name": "echo", "arguments": {"text": "hello"}}, "id": 2}
    )
    print(f"  Tool call: {json.loads(tool_result)['result']}")

    # Read resource
    res_result = await server.handle_message(
        {"jsonrpc": "2.0", "method": "resources/read",
         "params": {"uri": "status://agent"}, "id": 3}
    )
    print(f"  Resource: {json.loads(res_result)['result']['contents'][0]['text']}")

    # Get prompt
    prompt_result = await server.handle_message(
        {"jsonrpc": "2.0", "method": "prompts/get",
         "params": {"name": "analyze", "arguments": {"topic": "AI safety"}}, "id": 4}
    )
    prompt_text = json.loads(prompt_result)["result"]["messages"][0]["content"]["text"]
    print(f"  Prompt: {prompt_text}")


async def main():
    await demo_parallel()
    await demo_debate()
    await demo_ipc()
    await demo_mcp()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
