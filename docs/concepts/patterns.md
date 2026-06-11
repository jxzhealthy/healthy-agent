# Agent Patterns

Healthy Agent supports multiple orchestration patterns for building complex agent workflows. These patterns are implemented in `src/healthy_agent/strategy` and `src/healthy_agent/orchestration`.

## ReAct Pattern

ReAct (Reasoning + Acting) combines logical reasoning with tool execution in an iterative loop. The agent alternates between thinking about the next step and executing actions to gather information.

**Workflow**: Thought ¡ú Action ¡ú Observation ¡ú Thought ¡ú ... ¡ú Final Answer

The agent generates a thought to plan its approach, selects a tool to execute, observes the result, and repeats until reaching a conclusion. This pattern excels at tasks requiring external data retrieval or multi-step problem solving.

**Implementation**: Use the primary driver with tools/skills registered. The agent prompt structures output to separate reasoning from action selection. Tool results feed back into context for subsequent reasoning cycles.

**Use Cases**: Research tasks, data analysis, debugging assistance, any scenario requiring iterative information gathering.

## Reflexion Pattern

Reflexion adds self-reflection to the ReAct loop, enabling agents to learn from mistakes and improve subsequent attempts. Implemented in `src/healthy_agent/strategy/reflexion.py`.

**Workflow**: Attempt ¡ú Evaluate ¡ú Reflect ¡ú Retry (with improved strategy)

After each attempt, the agent evaluates its own performance against success criteria. If unsuccessful, it generates reflection insights identifying what went wrong and how to improve. These reflections inform the next attempt's strategy.

**Key Components**:
- **Evaluator**: Assesses attempt quality against predefined criteria
- **Reflector**: Generates insights from failures (what failed, why, how to fix)
- **Retry Logic**: Incorporates reflections into new attempt with adjusted approach
- **Max Attempts**: Configurable retry limit prevents infinite loops

**Benefits**: Higher success rates on complex tasks, adaptive learning within session, explicit failure analysis for debugging.

**Use Cases**: Code generation with test validation, complex planning tasks, scenarios where first-attempt success is unlikely.

## Multi-Agent Orchestration

Multi-agent systems coordinate multiple specialized agents working toward a common goal. Implemented in `src/healthy_agent/orchestration/multi.py`.

**Architecture**: Supervisor agent delegates subtasks to worker agents, collects results, and synthesizes final output. Each worker specializes in a domain (research, coding, review, etc.).

**Workflow**:
1. Supervisor receives high-level task
2. Decomposes into subtasks based on required expertise
3. Spawns worker processes for each subtask via `kernel.spawn()`
4. Waits for all workers via `kernel.wait_pid()`
5. Aggregates results and produces final answer

**Coordination Strategies**:
- **Parallel**: Independent subtasks execute concurrently for speed
- **Sequential**: Dependent subtasks chain outputs as inputs
- **Hierarchical**: Supervisors can themselves be workers in larger hierarchies

**Process Isolation**: Each agent runs in separate process with unique PID, preventing state contamination. Parent-child relationships track delegation hierarchy.

**Use Cases**: Complex research projects, codebase refactoring, multi-domain problem solving, tasks benefiting from specialization.

## Workflow Pipeline

Workflow pipelines define deterministic sequences of steps with explicit data flow between stages. Implemented in `src/healthy_agent/orchestration/workflow.py`.

**Structure**: Linear or branching DAG (Directed Acyclic Graph) of nodes. Each node performs a specific operation (LLM call, tool execution, conditional branch, merge).

**Node Types**:
- **LLM Node**: Invokes driver with prompt, passes output to next node
- **Tool Node**: Executes skill/function, forwards result
- **Condition Node**: Branches based on predicate evaluation
- **Merge Node**: Combines multiple upstream outputs
- **Transform Node**: Processes data without LLM involvement

**Execution Model**: Nodes execute sequentially or in parallel branches. State object carries context through pipeline, accumulating results. Failed nodes can trigger rollback or alternative paths.

**Advantages Over Free-form Agents**: Predictable execution order, explicit error handling per stage, easier debugging via node-level inspection, reusable pipeline templates.

**Use Cases**: Content generation pipelines (research ¡ú outline ¡ú draft ¡ú edit), ETL workflows, approval chains, structured data processing.

## Planner Pattern

The Planner pattern separates high-level strategy from low-level execution. Implemented in `src/healthy_agent/strategy/planner.py`.

**Two-Phase Approach**:
1. **Planning Phase**: Planner agent analyzes task, generates structured plan with ordered steps, estimated complexity, and required tools
2. **Execution Phase**: Executor agent follows plan step-by-step, tracking progress, adapting when obstacles arise

**Plan Structure**: List of steps with descriptions, dependencies, expected outputs, and fallback strategies. Stored in process context for reference during execution.

**Adaptive Execution**: Executor can deviate from plan when encountering unexpected results. Logs deviations for post-hoc analysis. Can request replanning if original plan becomes invalid.

**Benefits**: Better task decomposition, explicit progress tracking, easier debugging via plan inspection, reusable plans for similar tasks.

**Integration**: Planner can invoke Reflexion for plan quality assessment. Multi-agent systems use planners to coordinate worker assignments. Workflows embed plans as node sequences.

**Use Cases**: Long-running tasks (>5 steps), tasks with clear substructure, scenarios requiring progress visibility, repeatable operations.

## Pattern Selection Guide

**Simple Q&A**: Direct ReAct with single agent
**Complex Research**: Multi-Agent with parallel workers
**Code Generation**: Reflexion with test validation
**Content Creation**: Workflow Pipeline for structured output
**Long Tasks**: Planner for decomposition and tracking
**Uncertain Outcomes**: Reflexion for adaptive retry
**High Throughput**: Multi-Agent with parallel execution

## Combining Patterns

Patterns compose naturally:
- Planner + Multi-Agent: Planner decomposes task, assigns subtasks to specialized workers
- Reflexion + Workflow: Failed workflow nodes trigger reflection and retry
- ReAct + Planner: Planner creates high-level plan, ReAct executes individual steps

Choose patterns based on task complexity, reliability requirements, and desired execution characteristics.

## Next Steps

- Read [Kernel Concepts](kernel.md) to understand process execution mechanics
- Explore [Architecture Overview](architecture.md) for system design context
- Review example implementations in `examples/` directory: `reflexion_demo.py`, `multi_agent.py`, `workflow_pipeline.py`
