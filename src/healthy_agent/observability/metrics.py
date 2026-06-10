"""In-process metrics collector for observability.

Tracks:
  - Task count, success/failure rates
  - Token usage per driver/session
  - Latency histograms (p50, p95, p99)
  - Active process count over time

Thread-safe, zero external dependencies.
"""
from __future__ import annotations

import time
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class TimerContext:
    """Context manager for timing operations."""
    collector: MetricsCollector
    name: str
    tags: dict[str, str]
    _start: float = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *args):
        elapsed = time.monotonic() - self._start
        self.collector.record_latency(self.name, elapsed, tags=self.tags)


class MetricsCollector:
    """Collects and aggregates runtime metrics.

    Usage:
        metrics.increment("tasks.completed", tags={"driver": "anthropic"})
        metrics.record_latency("executor.run", 1.23)
        metrics.gauge("kernel.active_processes", 5)

        with metrics.timer("llm.generate", tags={"model": "claude"}):
            result = await driver.generate(...)

        summary = metrics.snapshot()
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._tags: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._start_time = time.time()

    def increment(self, name: str, value: int = 1, *, tags: dict[str, str] | None = None) -> None:
        """Increment a counter."""
        with self._lock:
            self._counters[name] += value
            if tags:
                tag_key = f"{name}:{','.join(f'{k}={v}' for k, v in sorted(tags.items()))}"
                self._tags[name][tag_key] += value

    def gauge(self, name: str, value: float) -> None:
        """Set a gauge value (point-in-time measurement)."""
        with self._lock:
            self._gauges[name] = value

    def record_latency(self, name: str, seconds: float, *, tags: dict[str, str] | None = None) -> None:
        """Record a latency measurement."""
        with self._lock:
            self._latencies[name].append(seconds)
            # Keep only last 1000 measurements per metric
            if len(self._latencies[name]) > 1000:
                self._latencies[name] = self._latencies[name][-500:]

    def timer(self, name: str, *, tags: dict[str, str] | None = None) -> TimerContext:
        """Context manager that records elapsed time."""
        return TimerContext(collector=self, name=name, tags=tags or {})

    def snapshot(self) -> dict[str, Any]:
        """Get a snapshot of all metrics."""
        with self._lock:
            result: dict[str, Any] = {
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "latencies": {},
            }
            for name, values in self._latencies.items():
                if not values:
                    continue
                sorted_vals = sorted(values)
                count = len(sorted_vals)
                result["latencies"][name] = {
                    "count": count,
                    "min": round(sorted_vals[0], 4),
                    "max": round(sorted_vals[-1], 4),
                    "mean": round(sum(sorted_vals) / count, 4),
                    "p50": round(sorted_vals[count // 2], 4),
                    "p95": round(sorted_vals[int(count * 0.95)], 4) if count >= 20 else None,
                    "p99": round(sorted_vals[int(count * 0.99)], 4) if count >= 100 else None,
                }
            return result

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._latencies.clear()
            self._tags.clear()
            self._start_time = time.time()


# Global singleton
metrics = MetricsCollector()
