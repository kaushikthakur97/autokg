from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MetricsRegistry:
    counters: dict[str, int] = field(default_factory=dict)
    timings: dict[str, list[float]] = field(default_factory=dict)

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + value

    def observe(self, name: str, seconds: float) -> None:
        self.timings.setdefault(name, []).append(seconds)

    def summary(self) -> dict[str, Any]:
        return {
            "counters": self.counters,
            "timings": {k: {"count": len(v), "avg": sum(v) / len(v) if v else 0, "max": max(v) if v else 0} for k, v in self.timings.items()},
        }


class JsonlLogger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None

    def event(self, event: str, **fields: Any) -> None:
        row = {"ts": time.time(), "event": event, **fields}
        line = json.dumps(row, default=str)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line)
