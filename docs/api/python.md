# Python SDK API

Programmatic access to Healthy Agent's core components through Python APIs.

## Kernel API

The kernel manages process scheduling and execution.

```python
from healthy_agent.kernel.runtime import Kernel

# Initialize kernel
kernel = Kernel(
    num_cores=4,
    max_processes=100,
    max_spawn_rate=10
)

# Spawn a process
pid = kernel.spawn(
    task_type="llm_query",
    payload={"prompt": "Hello"},
    handler=my_handler,
    preemptible=True
)

# Check process status
processes = kernel.ps()

# Wait for completion
await kernel.wait_pid(pid)

# Graceful shutdown
kernel.shutdown()

# Force cleanup finished processes
kernel.reap()
```

### Key Methods

- **`spawn(task_type, payload, handler, preemptible)`**: Create a new process
- **`wait_pid(pid)`**: Async wait for process completion
- **`ps()`**: List all processes
- **`reap()`**: Clean up finished processes
- **`shutdown()`**: Stop all cores gracefully

## Session API

Manage conversation sessions and context.

```python
from healthy_agent.session import SessionManager

manager = SessionManager()

# Create session
session = manager.create(metadata={"user": "alice"})

# Get session
session = manager.get("session-id")

# Add messages
session.add_message("user", "Hello")
session.add_message("assistant", "Hi there")

# Get history
history = session.get_history(last_n=10)

# Destroy session
manager.destroy("session-id")

# List sessions
all_sessions = manager.list_sessions()
```

## Skill API

Register and invoke skills and tools.

```python
from healthy_agent.skill import SkillRegistry, Tool, Skill

registry = SkillRegistry()

# Load skills from directory
registry.load_directory("./skills")

# Invoke a skill
result = await registry.invoke(
    "web_search",
    params={"query": "Python tips"},
    driver=driver,
    session=session
)

if result.success:
    print(result.data)
else:
    print(result.error)
```

### Components

- **`Tool`**: Simple deterministic functions
- **`Skill`**: LLM-enhanced capabilities requiring reasoning
- **`SkillRegistry`**: Manages skill lifecycle and invocation

## Memory API

Short-term and long-term memory management.

```python
# Short-term memory (session-scoped)
session.memory.put("key", "value", persist=False, tags=["temp"])
value = session.memory.recall("key")
all_memories = session.memory.all()

# Long-term memory (persistent)
from healthy_agent.memory import LongTermMemory

ltm = LongTermMemory(storage_path="./data/memory")
ltm.store("user_pref", {"theme": "dark"}, tags=["preferences"])
pref = ltm.retrieve("user_pref")
```

### ShortTermMemory Methods

- **`put(key, value, persist, tags)`**: Store a memory
- **`recall(key)`**: Retrieve by key
- **`all()`**: Get all memories
- **`search(query)`**: Semantic search

### LongTermMemory Methods

- **`store(key, value, tags)`**: Persist memory
- **`retrieve(key)`**: Load memory
- **`delete(key)`**: Remove memory
- **`list_tags()`**: List all tags

## Configuration API

Load and manage settings.

```python
from healthy_agent.config.settings import load_config, Settings

# Load from file
config = load_config(path="healthy_agent.toml")

# Access settings
num_cores = config.kernel.num_cores
model = config.driver.model
log_level = config.observability.log_level

# Programmatic overrides
config.kernel.num_cores = 8
config.auth.api_keys = ["key1", "key2"]
```

### Settings Structure

- **`kernel`**: Core scheduling parameters
- **`driver`**: LLM provider configuration
- **`auth`**: Authentication settings
- **`observability`**: Logging and metrics
- **`skills`**: Skill directories and options
- **`headroom`**: Context compression settings
