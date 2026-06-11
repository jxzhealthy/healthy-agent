# REST API Reference

Healthy Agent provides a comprehensive REST API for managing sessions, tasks, memory, and skills.

## Base URL

```
http://localhost:8000
```

## Authentication

All endpoints (except `/` and `/health`) require API key authentication via the `X-API-Key` header or `Authorization: Bearer <token>` header.

## Endpoints

### Service Status

**GET /**

Returns service status and basic information.

```bash
curl http://localhost:8000/
```

### Sessions

**POST /sessions**

Create a new session.

Request body:
```json
{
  "metadata": {}
}
```

Response:
```json
{
  "session_id": "abc123",
  "created_at": "2026-06-11T08:00:00"
}
```

**GET /sessions**

List all active sessions.

Response:
```json
{
  "sessions": [...],
  "active": 5
}
```

**GET /sessions/{session_id}**

Get details of a specific session.

**DELETE /sessions/{session_id}**

Delete a session and free resources.

### Messages

**POST /sessions/{session_id}/messages**

Add a message to session history.

Request body:
```json
{
  "role": "user",
  "content": "Hello"
}
```

**GET /sessions/{session_id}/messages**

Get message history. Query parameter `last_n` limits results.

### Tasks

**POST /sessions/{session_id}/tasks**

Submit a task for execution.

Request body:
```json
{
  "task_type": "llm_query",
  "payload": {
    "prompt": "What is AI?"
  }
}
```

Response:
```json
{
  "task_id": "t1234",
  "pid": 42,
  "status": "submitted"
}
```

**GET /sessions/{session_id}/tasks/{task_id}**

Query task status and result.

### Memory

**GET /sessions/{session_id}/memory/{key}**

Retrieve a stored memory value.

**POST /sessions/{session_id}/memory**

Store a memory value.

Request body:
```json
{
  "key": "user_name",
  "value": "Alice",
  "persist": false,
  "tags": ["profile"]
}
```

### Skills

**GET /skills**

List all available skills and tools.

**POST /sessions/{session_id}/skills/{skill_name}**

Invoke a skill with parameters.

Request body:
```json
{
  "params": {}
}
```

### Kernel Management

**GET /kernel/ps**

List all running processes.

**GET /kernel/stats**

Get kernel scheduler statistics.

**GET /metrics**

Return current metrics snapshot.
