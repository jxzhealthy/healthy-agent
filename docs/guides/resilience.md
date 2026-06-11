# Resilience Guide

## Overview

Resilience patterns ensure reliable LLM interactions through retry mechanisms, circuit breakers, and fault tolerance.

## RetryPolicy

Implements exponential backoff retry strategy:

```python
from healthy_agent import RetryPolicy

policy = RetryPolicy(
    max_retries=3,
    base_delay=1.0,      # Start with 1 second
    max_delay=60.0,      # Cap at 60 seconds
    backoff_factor=2.0   # Double delay each retry
)

# Use with resilient driver
result = policy.execute(llm_call, args=(prompt,))
```

### Exponential Backoff

- **1st retry**: 1s delay
- **2nd retry**: 2s delay
- **3rd retry**: 4s delay
- Continues until max_delay or max_retries reached

## CircuitBreaker

Prevents cascading failures with three states:

```python
from healthy_agent import CircuitBreaker

breaker = CircuitBreaker(
    threshold=5,          # Failures before opening
    recovery_timeout=60   # Seconds before half-open
)

# States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
try:
    result = breaker.execute(llm_call)
except CircuitOpenError:
    print("Circuit is open, service unavailable")
```

### States

- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Failing, requests blocked immediately
- **HALF_OPEN**: Testing recovery, limited requests allowed

## ResilientDriver

Wraps LLM drivers with resilience patterns:

```python
from healthy_agent import ResilientDriver, OpenAIDriver

# Create base driver
base_driver = OpenAIDriver(api_key="...")

# Add resilience
resilient = ResilientDriver(
    driver=base_driver,
    retry_policy=RetryPolicy(max_retries=3),
    circuit_breaker=CircuitBreaker(threshold=5)
)

# Use as normal driver
response = resilient.generate(prompt)
```

### Features

- Automatic retries on transient failures
- Circuit breaker prevents overload
- Graceful degradation
- Configurable timeouts

## Configuration

Configure resilience in your config file:

```toml
[resilience]
max_retries = 3
base_delay = 1.0
circuit_breaker_threshold = 5
recovery_timeout = 60
```

### Configuration Options

- **max_retries**: Maximum retry attempts (default: 3)
- **base_delay**: Initial delay in seconds (default: 1.0)
- **circuit_breaker_threshold**: Failures before opening (default: 5)
- **recovery_timeout**: Seconds before testing recovery (default: 60)

## Example Usage

```python
from healthy_agent import Agent, ResilientDriver
from healthy_agent.resilience import RetryPolicy, CircuitBreaker

# Configure resilience
retry = RetryPolicy(max_retries=3, base_delay=1.0)
breaker = CircuitBreaker(threshold=5, recovery_timeout=60)

# Create resilient driver
driver = ResilientDriver(
    driver=OpenAIDriver(),
    retry_policy=retry,
    circuit_breaker=breaker
)

# Agent automatically uses resilient driver
agent = Agent(driver=driver)

# Handles failures gracefully
response = agent.generate("Analyze this code...")
```

## Error Handling

```python
from healthy_agent.resilience import CircuitOpenError, MaxRetriesExceeded

try:
    response = agent.generate(prompt)
except CircuitOpenError:
    print("Service temporarily unavailable")
except MaxRetriesExceeded:
    print("Failed after multiple attempts")
except Exception as e:
    print(f"Unexpected error: {e}")
```

Resilience patterns ensure your agents remain robust under failure conditions and recover gracefully from transient issues.
