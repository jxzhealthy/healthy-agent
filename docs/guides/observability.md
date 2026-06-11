# Observability Guide

## Overview

Observability tools provide visibility into agent behavior through structured logging and metrics collection.

## setup_logging

Configures unified logging with support for structured JSON output:

```python
from healthy_agent import setup_logging

# Basic setup
setup_logging(level="INFO")

# Advanced setup with JSON format
setup_logging(
    level="DEBUG",
    log_format="json",
    output_file="agent.log"
)
```

### Log Formats

- **text**: Human-readable format (default)
- **json**: Structured JSON for machine parsing

### Configuration

```toml
[observability]
log_level = "INFO"
log_format = "text"
```

## MetricsCollector

Collects and tracks agent performance metrics:

```python
from healthy_agent import MetricsCollector

metrics = MetricsCollector()

# Increment counter
metrics.increment("kernel.spawns")

# Set gauge value
metrics.gauge("memory.usage", 1024)

# Record latency
with metrics.record_latency("llm.response_time"):
    response = llm.generate(prompt)

# Record histogram
metrics.histogram("task.duration", duration_seconds)
```

### Metric Types

- **Counter**: Monotonically increasing values
- **Gauge**: Point-in-time measurements
- **Histogram**: Distribution of values
- **Latency**: Timing measurements

## Built-in Metrics

Healthy Agent automatically tracks:

```python
# Kernel metrics
kernel.spawns        # Number of agent spawns
kernel.completed     # Successfully completed tasks
kernel.errors        # Failed tasks

# LLM metrics
llm.calls            # Total API calls
llm.tokens_input     # Input tokens used
llm.tokens_output    # Output tokens used
llm.latency          # Response time

# Memory metrics
memory.entries       # Active memory entries
memory.hits          # Cache hits
memory.misses        # Cache misses
```

## Example Usage

```python
from healthy_agent import Agent, setup_logging, MetricsCollector

# Configure logging
setup_logging(level="INFO", log_format="json")

# Create metrics collector
metrics = MetricsCollector()

# Create agent with observability
agent = Agent(metrics=metrics)

# Metrics automatically collected
response = agent.generate("Analyze this code...")

# Access metrics
print(f"Spawns: {metrics.get('kernel.spawns')}")
print(f"Errors: {metrics.get('kernel.errors')}")
```

## Custom Metrics

Track application-specific metrics:

```python
# Track custom business metrics
metrics.increment("custom.feature_usage")
metrics.gauge("custom.queue_size", queue_length)
metrics.record_latency("custom.processing_time")

# Export metrics
all_metrics = metrics.export()
```

## Integration with Monitoring

Export metrics to external systems:

```python
# Export to Prometheus format
prometheus_output = metrics.to_prometheus()

# Export to JSON
json_output = metrics.to_json()

# Custom exporter
def export_to_datadog(metrics):
    # Send to Datadog
    pass

metrics.register_exporter(export_to_datadog)
```

Observability enables debugging, performance optimization, and production monitoring of agent systems.
