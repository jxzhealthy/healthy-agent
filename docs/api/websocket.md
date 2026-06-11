# WebSocket API

Real-time bidirectional communication via WebSocket for streaming responses and interactive sessions.

## Connection

```
ws://localhost:8000/ws/{session_id}
```

Replace `{session_id}` with your session identifier. If the session doesn't exist, it will be created automatically.

## Message Format

All messages are JSON-encoded strings.

### Client ¡ú Server

Send user messages:

```json
{
  "role": "user",
  "content": "Your message here"
}
```

### Server ¡ú Client

The server streams responses as chunks:

```json
{
  "type": "chunk",
  "content": "Partial response text"
}
```

Final message when complete:

```json
{
  "type": "complete",
  "content": "Full response"
}
```

Error messages:

```json
{
  "type": "error",
  "message": "Error description"
}
```

## Example Usage

### JavaScript

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/session-123');

ws.onopen = () => {
  console.log('Connected');
  ws.send(JSON.stringify({
    role: 'user',
    content: 'Hello!'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'chunk') {
    process.stdout.write(data.content);
  } else if (data.type === 'complete') {
    console.log('\nDone:', data.content);
  }
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};
```

### Python

```python
import asyncio
import websockets
import json

async def chat():
    uri = "ws://localhost:8000/ws/session-123"
    async with websockets.connect(uri) as ws:
        # Send message
        await ws.send(json.dumps({
            "role": "user",
            "content": "Hello!"
        }))
        
        # Receive streaming response
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "chunk":
                print(data["content"], end="", flush=True)
            elif data["type"] == "complete":
                print("\nComplete!")
                break

asyncio.run(chat())
```

## Connection Management

- Connections timeout after 300 seconds of inactivity
- Reconnect with exponential backoff on failure
- Each connection is tied to a single session
- Multiple clients can connect to the same session concurrently
