# Configuration

Healthy Agent uses a unified TOML/YAML configuration system with environment variable overrides and CLI parameter support.

## Configuration File

Create `healthy_agent.toml` or `healthy_agent.yaml` in the project root:

```toml
# Server configuration
[server]
host = "0.0.0.0"
port = 8000
cors_origins = ["*"]

# Kernel scheduling configuration
[kernel]
num_cores = 4                  # Number of virtual cores (concurrent processing capacity)
max_processes = 100            # Maximum number of processes
max_spawn_rate = 100.0         # Maximum spawn rate (per second)

# LLM driver configuration
[driver]
name = "openai"                # Driver name: openai/anthropic/ollama/custom
model = "gpt-4o"               # Model name
api_key = ""                   # API Key (recommended to set via environment variable)
base_url = ""                  # Custom API base URL (optional)
max_tokens = 4096              # Maximum output tokens
timeout = 60                   # Request timeout (seconds)

# Fallback driver configuration
[fallback_driver]
name = "openai"
model = "gpt-4o-mini"          # Cheaper/faster fallback model
api_key = ""
base_url = ""

# Memory system configuration
[memory]
backend = "local"              # Backend type: local/redis/mem0
redis_url = "redis://localhost:6379"  # Redis connection URL (when backend=redis)
ttl = 3600                     # Memory TTL (seconds)

# Persistence configuration
[persistence]
enabled = true                 # Enable persistence
db_path = "./healthy_agent.db" # Database file path

# Observability configuration
[observability]
log_level = "INFO"             # Log level: DEBUG/INFO/WARNING/ERROR
log_format = "text"            # Log format: text/json
metrics_enabled = false        # Enable metrics collection

# Authentication configuration
[auth]
enabled = false                # Enable authentication
api_keys = []                  # API key list
jwt_secret = ""                # JWT secret

# Skills system configuration
[skills]
directories = ["./skills"]     # Skills directory list
hot_reload = true              # Enable hot reload
poll_interval = 5              # Poll interval (seconds)

# Sandbox configuration
[sandbox]
enabled = false                # Enable sandbox
timeout = 30                   # Sandbox execution timeout (seconds)
max_memory_mb = 512            # Maximum memory limit (MB)

# Context compression configuration
[compression]
enabled = true                 # Enable context compression
max_tokens_threshold = 30000   # Token threshold to trigger compression
summary_model = ""             # Leave empty to use main driver model, or specify e.g. "gpt-4o-mini"

# Headroom rule-based compression configuration
[headroom]
enabled = true                 # Enable Headroom compression (first layer)
compress_tool_outputs = true   # Compress tool outputs (JSON, logs)
compress_code = true           # Compress code blocks
compress_json = true           # Compress JSON data
min_content_length = 200       # Only compress content longer than this (characters)
target_ratio = 0.3             # Target compression ratio (0.3 = keep 30%)

# Retry and circuit breaker configuration
[resilience]
max_retries = 3                # Maximum retry attempts
base_delay = 1.0               # Retry base delay (seconds)
max_delay = 30.0               # Retry maximum delay (seconds)
circuit_breaker_threshold = 5  # Consecutive failures before circuit breaker triggers
circuit_breaker_timeout = 60   # Circuit breaker recovery wait time (seconds)
```

## Configuration Sections

### [server]

Server listening configuration.

- `host`: Listening address (default: `"0.0.0.0"`)
- `port`: Listening port (default: `8000`)
- `cors_origins`: CORS allowed origins (default: `["*"]`)

### [kernel]

Kernel scheduling and resource limits.

- `num_cores`: Number of virtual execution cores (default: `4`)
- `max_processes`: Maximum concurrent processes (default: `100`)
- `max_spawn_rate`: Maximum process spawn rate per second (default: `100.0`)

### [driver]

Primary LLM driver configuration.

- `name`: Driver provider (`openai`, `anthropic`, `ollama`, `custom`)
- `model`: Model identifier
- `api_key`: API authentication key
- `base_url`: Custom API endpoint URL
- `max_tokens`: Maximum generation tokens (default: `4096`)
- `timeout`: Request timeout in seconds (default: `60`)

### [fallback_driver]

Fallback driver used when primary driver fails. Same fields as `[driver]`.

### [memory]

Memory backend configuration.

- `backend`: Storage backend (`local`, `redis`, `mem0`)
- `redis_url`: Redis connection string (when using redis backend)
- `ttl`: Memory entry time-to-live in seconds (default: `3600`)

### [persistence]

State persistence configuration.

- `enabled`: Enable/disable persistence (default: `true`)
- `db_path`: SQLite database file path (default: `"./healthy_agent.db"`)

### [observability]

Logging and metrics configuration.

- `log_level`: Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `log_format`: Output format (`text` or `json`)
- `metrics_enabled`: Enable Prometheus-style metrics (default: `false`)

### [auth]

API authentication configuration.

- `enabled`: Enable/disable authentication (default: `false`)
- `api_keys`: List of valid API keys
- `jwt_secret`: Secret key for JWT token signing

### [skills]

Skills plugin system configuration.

- `directories`: List of directories containing skill definitions
- `hot_reload`: Enable automatic skill reloading on file changes (default: `true`)
- `poll_interval`: File system polling interval in seconds (default: `5`)

### [sandbox]

Code execution sandbox configuration.

- `enabled`: Enable/disable sandbox isolation (default: `false`)
- `timeout`: Execution timeout in seconds (default: `30`)
- `max_memory_mb`: Memory limit in megabytes (default: `512`)

### [compression]

Context window compression configuration.

- `enabled`: Enable/disable compression (default: `true`)
- `max_tokens_threshold`: Token count threshold to trigger compression (default: `30000`)
- `summary_model`: Model to use for summarization (empty = use primary driver)

### [headroom]

Rule-based content compression (first layer before LLM summarization).

- `enabled`: Enable Headroom compression (default: `true`)
- `compress_tool_outputs`: Compress tool output data (default: `true`)
- `compress_code`: Compress code blocks (default: `true`)
- `compress_json`: Compress JSON structures (default: `true`)
- `min_content_length`: Minimum content length to compress in characters (default: `200`)
- `target_ratio`: Target size ratio after compression (default: `0.3`)

### [resilience]

Retry logic and circuit breaker configuration.

- `max_retries`: Maximum retry attempts per operation (default: `3`)
- `base_delay`: Initial retry delay in seconds (default: `1.0`)
- `max_delay`: Maximum retry delay cap in seconds (default: `30.0`)
- `circuit_breaker_threshold`: Consecutive failures to trigger circuit breaker (default: `5`)
- `circuit_breaker_timeout`: Circuit breaker cooldown period in seconds (default: `60`)

## Environment Variable Overrides

Use `HEALTHY_AGENT_` prefix to override any configuration value via environment variables:

```bash
export HEALTHY_AGENT_DRIVER_NAME=anthropic
export HEALTHY_AGENT_DRIVER_MODEL=claude-3-opus
export HEALTHY_AGENT_KERNEL_NUM_CORES=8
export HEALTHY_AGENT_OBSERVABILITY_LOG_LEVEL=DEBUG
export HEALTHY_AGENT_RESILIENCE_MAX_RETRIES=5
```

Format: `HEALTHY_AGENT_<SECTION>_<KEY>` (case-insensitive, underscores separate section and key).

Supported types: boolean (`true`/`false`), integer, float, string, comma-separated lists.

## CLI Parameter Override

Specify a custom configuration file path via CLI:

```bash
python -m healthy_agent --config /path/to/custom.toml
python -m healthy_agent -f /path/to/custom.yaml
```

## Configuration Priority

Configuration values are resolved in the following order (highest to lowest priority):

1. **CLI arguments** (`--config` / `-f`)
2. **Environment variables** (`HEALTHY_AGENT_*`)
3. **Configuration file** (`healthy_agent.toml` or `healthy_agent.yaml`)
4. **Default values** (hardcoded in `Settings` dataclass)

The first configuration file found is loaded from this search order:
1. Path provided via CLI `--config` parameter
2. Path specified by `HEALTHY_AGENT_CONFIG` environment variable
3. `./healthy_agent.toml` in current working directory
4. `./healthy_agent.yaml` in current working directory

## Next Steps

- Read [Architecture Overview](../concepts/architecture.md) to understand system design
- Explore [Kernel Concepts](../concepts/kernel.md) for scheduling details
- Check [Agent Patterns](../concepts/patterns.md) for common usage patterns
