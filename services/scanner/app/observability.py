from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import perf_counter


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._durations: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_duration(self, name: str, value: float) -> None:
        with self._lock:
            self._durations[name].append(value)

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            duration_stats = {}
            for key, values in self._durations.items():
                count = len(values)
                duration_stats[key] = {
                    "count": count,
                    "avg_ms": round((sum(values) / count) * 1000, 2) if count else 0.0,
                    "max_ms": round(max(values) * 1000, 2) if count else 0.0,
                }
            return {
                "counters": dict(self._counters),
                "durations": duration_stats,
            }


metrics = MetricsRegistry()


class TimedBlock:
    def __init__(self, metric_name: str) -> None:
        self.metric_name = metric_name
        self.started_at = 0.0

    def __enter__(self) -> "TimedBlock":
        self.started_at = perf_counter()
        return self

    def __exit__(self, *_args) -> None:
        metrics.observe_duration(self.metric_name, perf_counter() - self.started_at)
