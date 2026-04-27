"""Instrumentación simple de rendimiento para ETL y conectores."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PerfEvent:
    kind: str
    name: str
    started_at: float
    finished_at: float
    elapsed_seconds: float
    meta: dict[str, Any] = field(default_factory=dict)


class PerfTrace:
    def __init__(self, run_name: str, output_path: Path | None = None) -> None:
        self.run_name = run_name
        self.output_path = output_path
        self.created_at = time.time()
        self.events: list[PerfEvent] = []
        self.counters: dict[str, int | float] = {}
        self.meta: dict[str, Any] = {}

    def set_meta(self, **kwargs: Any) -> None:
        self.meta.update(kwargs)

    def incr(self, key: str, amount: int = 1) -> None:
        current = self.counters.get(key, 0)
        self.counters[key] = int(current) + amount

    def add_value(self, key: str, value: float) -> None:
        current = self.counters.get(key, 0.0)
        self.counters[key] = float(current) + float(value)

    def event(self, name: str, **meta: Any) -> None:
        now = time.perf_counter()
        self.events.append(
            PerfEvent(
                kind="event",
                name=name,
                started_at=now,
                finished_at=now,
                elapsed_seconds=0.0,
                meta=meta,
            )
        )

    @contextmanager
    def stage(self, name: str, **meta: Any):
        start = time.perf_counter()
        try:
            yield
        finally:
            end = time.perf_counter()
            self.events.append(
                PerfEvent(
                    kind="stage",
                    name=name,
                    started_at=start,
                    finished_at=end,
                    elapsed_seconds=end - start,
                    meta=meta,
                )
            )

    def summary(self) -> dict[str, Any]:
        total_elapsed = 0.0
        if self.events:
            starts = [e.started_at for e in self.events]
            ends = [e.finished_at for e in self.events]
            total_elapsed = max(ends) - min(starts)

        by_stage: dict[str, float] = {}
        for event in self.events:
            if event.kind != "stage":
                continue
            by_stage[event.name] = by_stage.get(event.name, 0.0) + event.elapsed_seconds

        return {
            "run_name": self.run_name,
            "created_at": self.created_at,
            "meta": self.meta,
            "counters": self.counters,
            "by_stage_seconds": by_stage,
            "total_measured_seconds": total_elapsed,
            "events_count": len(self.events),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_name": self.run_name,
            "created_at": self.created_at,
            "meta": self.meta,
            "counters": self.counters,
            "summary": self.summary(),
            "events": [
                {
                    "kind": e.kind,
                    "name": e.name,
                    "started_at": e.started_at,
                    "finished_at": e.finished_at,
                    "elapsed_seconds": e.elapsed_seconds,
                    "meta": e.meta,
                }
                for e in self.events
            ],
        }

    def dump(self) -> Path | None:
        if self.output_path is None:
            return None
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(self.as_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self.output_path