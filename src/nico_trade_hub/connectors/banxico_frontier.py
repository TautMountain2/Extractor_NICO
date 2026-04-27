"""Planner de frontera para el recorrido Banxico.

Fase 4/5:
- separa el control de frontera del código de extracción;
- aplica límites por capítulo de forma explícita;
- emite lotes equilibrados para concurrencia acotada.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class FrontierTask:
    chapter_unique: str
    current_unique: str
    position: int
    total_chapters: int
    leaf_hits: int
    fact_hits: int
    should_log: bool


class BanxicoFrontierPlanner:
    def __init__(
        self,
        *,
        chapter_uniques: list[str],
        chapter_seed_stats: dict[str, tuple[int, int]],
        log_every: int,
        limit_missing: int,
        limit_sparse: int,
        limit_rich: int,
        initial_targets: dict[str, list[str]] | None = None,
    ) -> None:
        self.chapter_order = list(chapter_uniques)
        self.chapter_seed_stats = dict(chapter_seed_stats)
        self.log_every = max(1, int(log_every))
        self.limit_missing = max(1, int(limit_missing))
        self.limit_sparse = max(1, int(limit_sparse))
        self.limit_rich = max(1, int(limit_rich))

        initial_targets = initial_targets or {}
        self.chapter_queues: OrderedDict[str, deque[str]] = OrderedDict(
            (chapter_unique, deque(initial_targets.get(chapter_unique) or [chapter_unique]))
            for chapter_unique in self.chapter_order
        )
        self.chapter_counts: dict[str, int] = {chapter_unique: 0 for chapter_unique in self.chapter_order}
        self.chapter_limits: dict[str, int] = {
            chapter_unique: self._limit_for_chapter(chapter_unique)
            for chapter_unique in self.chapter_order
        }
        self.expanded: set[str] = set()
        self.inflight: set[str] = set()

    def _limit_for_chapter(self, chapter_unique: str) -> int:
        leaf_hits, _fact_hits = self.chapter_seed_stats.get(chapter_unique, (0, 0))
        if leaf_hits == 0:
            return self.limit_missing
        if leaf_hits < 5:
            return self.limit_sparse
        return self.limit_rich

    def has_pending_work(self) -> bool:
        for chapter_unique in self.chapter_order:
            if self.chapter_counts[chapter_unique] >= self.chapter_limits[chapter_unique]:
                continue
            queue = self.chapter_queues[chapter_unique]
            for candidate in queue:
                if candidate not in self.expanded and candidate not in self.inflight:
                    return True
        return False

    def build_batch(self, *, remaining_budget: int, max_tasks: int) -> list[FrontierTask]:
        if remaining_budget <= 0 or max_tasks <= 0:
            return []

        target = min(int(remaining_budget), int(max_tasks))
        batch: list[FrontierTask] = []
        visited_chapters: set[str] = set()

        while len(batch) < target:
            made_progress = False
            for pos, chapter_unique in enumerate(self.chapter_order, start=1):
                if len(batch) >= target:
                    break
                if chapter_unique in visited_chapters:
                    continue
                if self.chapter_counts[chapter_unique] >= self.chapter_limits[chapter_unique]:
                    continue

                queue = self.chapter_queues[chapter_unique]
                while queue and (queue[0] in self.expanded or queue[0] in self.inflight):
                    queue.popleft()
                if not queue:
                    continue

                current_unique = queue.popleft()
                if current_unique in self.expanded or current_unique in self.inflight:
                    continue

                leaf_hits, fact_hits = self.chapter_seed_stats.get(chapter_unique, (0, 0))
                task = FrontierTask(
                    chapter_unique=chapter_unique,
                    current_unique=current_unique,
                    position=pos,
                    total_chapters=len(self.chapter_order),
                    leaf_hits=leaf_hits,
                    fact_hits=fact_hits,
                    should_log=(
                        self.chapter_counts[chapter_unique] == 0
                        and (pos == 1 or pos % self.log_every == 0 or pos == len(self.chapter_order))
                    ),
                )
                self.inflight.add(current_unique)
                batch.append(task)
                visited_chapters.add(chapter_unique)
                made_progress = True

            if not made_progress:
                break

        return batch

    def apply_result(
        self,
        task: FrontierTask,
        *,
        queried: bool,
        next_targets: Iterable[str],
    ) -> None:
        self.inflight.discard(task.current_unique)
        self.expanded.add(task.current_unique)
        if queried:
            self.chapter_counts[task.chapter_unique] += 1

        queue = self.chapter_queues[task.chapter_unique]
        cleaned = self._clean_targets(next_targets)
        if not cleaned:
            return

        if task.leaf_hits == 0:
            for item in reversed(cleaned):
                queue.appendleft(item)
        else:
            queue.extend(cleaned)

    def _clean_targets(self, values: Iterable[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not value:
                continue
            if value in seen or value in self.expanded or value in self.inflight:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
