# Memory Guide

## Overview

Memory systems enable agents to retain information across interactions. Healthy Agent provides both short-term and long-term memory capabilities.

## ShortTermMemory

In-memory storage with automatic expiration using TTL (Time-To-Live):

```python
from healthy_agent import ShortTermMemory

memory = ShortTermMemory(ttl=300)  # 5 minutes TTL

# Store data
memory.put("user_name", "Alice")
memory.put("session_id", "abc123", ttl=600)  # Override TTL

# Retrieve data
name = memory.get("user_name")

# Search by tags
results = memory.search(tag="important")

# Delete entry
memory.delete("session_id")

# Clear all
memory.clear()
```

### Features

- **Automatic Expiration**: Entries expire after TTL
- **Tag Support**: Organize entries with tags
- **Fast Access**: In-memory storage for quick retrieval

## LongTermMemory

Persistent storage to disk using JSON format:

```python
from healthy_agent import LongTermMemory

memory = LongTermMemory(storage_path="./memory_store.json")

# Store persistent data
memory.put("preferences", {"theme": "dark"})
memory.put("history", ["task1", "task2"], tags=["important"])

# Load from disk
prefs = memory.get("preferences")

# Search with tags
important_items = memory.search(tag="important")

# Remove entry
memory.delete("history")

# Clear all persistent data
memory.clear()
```

### Features

- **Persistence**: Survives process restarts
- **JSON Storage**: Human-readable format
- **Tag-based Search**: Filter entries by tags

## MemoryEntry

Each memory entry contains:

```python
class MemoryEntry:
    key: str          # Unique identifier
    value: Any        # Stored data
    tags: List[str]   # Optional tags for categorization
    ttl: int          # Time-to-live in seconds (ShortTerm only)
    created_at: float # Timestamp
```

## Operations

### put(key, value, tags=None, ttl=None)

Store a memory entry:

```python
memory.put("api_key", "secret123", tags=["credentials"])
memory.put("cache_data", data, ttl=60)
```

### get(key)

Retrieve a memory entry:

```python
value = memory.get("api_key")
if value is None:
    print("Key not found or expired")
```

### search(tag)

Find entries by tag:

```python
all_important = memory.search(tag="important")
credentials = memory.search(tag="credentials")
```

### delete(key)

Remove a specific entry:

```python
memory.delete("old_session")
```

### clear()

Remove all entries:

```python
memory.clear()
```

## Example Usage

```python
from healthy_agent import Agent, ShortTermMemory, LongTermMemory

# Combine both memory types
short_term = ShortTermMemory(ttl=300)
long_term = LongTermMemory("./agent_memory.json")

agent = Agent(
    short_term_memory=short_term,
    long_term_memory=long_term
)

# Use in agent workflow
agent.memory.put("current_task", task_id)
history = agent.memory.search(tag="completed_tasks")
```

Memory systems enable agents to maintain context and learn from past interactions.
