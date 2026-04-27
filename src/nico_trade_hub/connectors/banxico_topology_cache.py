"""Caché persistente de topología Banxico (modo seguro 6B).

En modo seguro se reutilizan únicamente miembros/relaciones estructurales.
La frontera terminal persistida NO se usa por defecto para planear la extracción,
porque en la validación del warm run recortó cobertura.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd


@dataclass(slots=True)
class CachedTopologySnapshot:
    enabled: bool
    members: dict[str, dict[str, Any]]
    frontier_by_chapter: dict[str, list[str]]
    members_count: int
    frontier_count: int
    chapter_coverage: int
    frontier_enabled: bool = False
    members_signature: str = ""
    frontier_signature: str = ""

    def is_usable(self, *, min_frontier_nodes: int, min_chapter_coverage: int) -> bool:
        if not self.enabled or not self.frontier_enabled:
            return False
        if self.frontier_count < max(1, int(min_frontier_nodes)):
            return False
        if self.chapter_coverage < max(1, int(min_chapter_coverage)):
            return False
        return True


class BanxicoTopologyCache:
    def __init__(self, db_path: Path, *, enabled: bool = True) -> None:
        self.db_path = Path(db_path)
        self.enabled = bool(enabled)

    @staticmethod
    def _canonical_member_row(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
        return (
            str(row.get("unique_name") or ""),
            str(row.get("caption") or ""),
            str(row.get("parent_unique_name") or ""),
            str(row.get("level") or ""),
            str(row.get("raw_type") or ""),
            str(row.get("raw_parts_json") or ""),
            str(row.get("chapter_unique") or ""),
        )

    @classmethod
    def compute_members_signature(cls, members_rows: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for item in sorted((cls._canonical_member_row(row) for row in members_rows), key=lambda x: x[0]):
            digest.update("\x1f".join(item).encode("utf-8", errors="ignore"))
            digest.update(b"\n")
        return digest.hexdigest()

    @classmethod
    def compute_members_signature_from_snapshot(cls, members: dict[str, dict[str, Any]]) -> str:
        rows = [
            {
                "unique_name": unique_name,
                "caption": payload.get("caption") or "",
                "parent_unique_name": payload.get("parent_unique_name") or "",
                "level": payload.get("level") or "",
                "raw_type": payload.get("raw_type") or "",
                "raw_parts_json": json.dumps(list(payload.get("raw_parts") or []), ensure_ascii=False),
                "chapter_unique": payload.get("chapter_unique") or "",
            }
            for unique_name, payload in members.items()
        ]
        return cls.compute_members_signature(rows)

    @staticmethod
    def compute_frontier_signature(frontier_rows: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for row in sorted(frontier_rows, key=lambda x: (str(x.get("metric") or ""), str(x.get("chapter_unique") or ""), str(x.get("frontier_unique") or ""))):
            item = (
                str(row.get("metric") or ""),
                str(row.get("chapter_unique") or ""),
                str(row.get("frontier_unique") or ""),
                str(row.get("level") or ""),
            )
            digest.update("\x1f".join(item).encode("utf-8", errors="ignore"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def load_snapshot(
        self,
        *,
        metric: str,
        expected_chapters: Iterable[str],
        include_frontier: bool = False,
    ) -> CachedTopologySnapshot:
        expected_chapters = list(expected_chapters)
        if not self.enabled or not self.db_path.exists():
            return CachedTopologySnapshot(False, {}, {}, 0, 0, 0, frontier_enabled=bool(include_frontier))

        try:
            with self._connect() as conn:
                members_rows = conn.execute(
                    """
                    SELECT unique_name, caption, parent_unique_name, level, raw_type, raw_parts_json, chapter_unique
                    FROM banxico_topology_member_cache
                    """
                ).fetchall()
                frontier_rows = []
                if include_frontier:
                    frontier_rows = conn.execute(
                        """
                        SELECT chapter_unique, frontier_unique
                        FROM banxico_topology_frontier_cache
                        WHERE metric = ?
                        ORDER BY chapter_unique, frontier_unique
                        """,
                        [metric],
                    ).fetchall()
        except duckdb.Error:
            return CachedTopologySnapshot(False, {}, {}, 0, 0, 0, frontier_enabled=bool(include_frontier))

        members: dict[str, dict[str, Any]] = {}
        for unique_name, caption, parent_unique_name, level, raw_type, raw_parts_json, chapter_unique in members_rows:
            try:
                raw_parts = json.loads(raw_parts_json) if raw_parts_json else []
            except Exception:
                raw_parts = []
            members[str(unique_name)] = {
                "unique_name": str(unique_name),
                "caption": caption,
                "parent_unique_name": parent_unique_name,
                "level": level,
                "raw_type": raw_type,
                "raw_parts": raw_parts,
                "chapter_unique": chapter_unique,
            }

        frontier_by_chapter: dict[str, list[str]] = defaultdict(list)
        for chapter_unique, frontier_unique in frontier_rows:
            frontier_by_chapter[str(chapter_unique)].append(str(frontier_unique))

        chapter_coverage = sum(1 for ch in expected_chapters if frontier_by_chapter.get(ch)) if include_frontier else 0
        frontier_count = sum(len(values) for values in frontier_by_chapter.values()) if include_frontier else 0
        frontier_rows = [
            {"metric": metric, "chapter_unique": ch, "frontier_unique": fu, "level": None}
            for ch, values in frontier_by_chapter.items()
            for fu in values
        ] if include_frontier else []
        return CachedTopologySnapshot(
            True,
            members,
            dict(frontier_by_chapter),
            len(members),
            frontier_count,
            chapter_coverage,
            frontier_enabled=bool(include_frontier),
            members_signature=self.compute_members_signature_from_snapshot(members),
            frontier_signature=self.compute_frontier_signature(frontier_rows),
        )

    def should_persist(
        self,
        *,
        snapshot: CachedTopologySnapshot | None,
        members_rows: list[dict[str, Any]],
        frontier_rows: list[dict[str, Any]],
        persist_frontier: bool,
    ) -> tuple[bool, dict[str, Any]]:
        if not self.enabled:
            return False, {"reason": "disabled"}

        members_signature = self.compute_members_signature(members_rows)
        frontier_signature = self.compute_frontier_signature(frontier_rows) if persist_frontier else ""

        if snapshot is None or not snapshot.enabled:
            return True, {
                "reason": "no_snapshot",
                "members_signature": members_signature,
                "frontier_signature": frontier_signature,
                "members_changed": True,
                "frontier_changed": persist_frontier and bool(frontier_rows),
            }

        members_changed = (
            snapshot.members_count != len(members_rows)
            or snapshot.members_signature != members_signature
        )
        frontier_changed = False
        if persist_frontier:
            frontier_changed = (
                snapshot.frontier_count != len(frontier_rows)
                or snapshot.frontier_signature != frontier_signature
            )

        return (members_changed or frontier_changed), {
            "reason": "changed" if (members_changed or frontier_changed) else "noop",
            "members_signature": members_signature,
            "frontier_signature": frontier_signature,
            "members_changed": members_changed,
            "frontier_changed": frontier_changed,
        }

    def persist(
        self,
        *,
        metric: str,
        members_rows: list[dict[str, Any]],
        edges_rows: list[dict[str, Any]],
        frontier_rows: list[dict[str, Any]],
        chapters_count: int,
        persist_frontier: bool = False,
    ) -> None:
        if not self.enabled:
            return

        members_df = pd.DataFrame(members_rows)
        edges_df = pd.DataFrame(edges_rows)
        frontier_df = pd.DataFrame(frontier_rows) if persist_frontier else pd.DataFrame()

        try:
            with self._connect() as conn:
                if not members_df.empty:
                    conn.register("banxico_members_df", members_df)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO banxico_topology_member_cache (
                            unique_name,
                            caption,
                            parent_unique_name,
                            level,
                            raw_type,
                            raw_parts_json,
                            chapter_unique,
                            first_seen_at,
                            last_seen_at
                        )
                        SELECT
                            unique_name,
                            caption,
                            parent_unique_name,
                            level,
                            raw_type,
                            raw_parts_json,
                            chapter_unique,
                            COALESCE(
                                (
                                    SELECT first_seen_at
                                    FROM banxico_topology_member_cache AS old
                                    WHERE old.unique_name = banxico_members_df.unique_name
                                ),
                                CURRENT_TIMESTAMP
                            ),
                            CURRENT_TIMESTAMP
                        FROM banxico_members_df
                        """
                    )

                if not edges_df.empty:
                    conn.register("banxico_edges_df", edges_df)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO banxico_topology_edge_cache (
                            parent_unique_name,
                            child_unique_name,
                            chapter_unique,
                            first_seen_at,
                            last_seen_at
                        )
                        SELECT
                            parent_unique_name,
                            child_unique_name,
                            chapter_unique,
                            COALESCE(
                                (
                                    SELECT first_seen_at
                                    FROM banxico_topology_edge_cache AS old
                                    WHERE old.parent_unique_name = banxico_edges_df.parent_unique_name
                                      AND old.child_unique_name = banxico_edges_df.child_unique_name
                                ),
                                CURRENT_TIMESTAMP
                            ),
                            CURRENT_TIMESTAMP
                        FROM banxico_edges_df
                        """
                    )

                conn.execute("DELETE FROM banxico_topology_frontier_cache WHERE metric = ?", [metric])
                if persist_frontier and not frontier_df.empty:
                    conn.register("banxico_frontier_df", frontier_df)
                    conn.execute(
                        """
                        INSERT INTO banxico_topology_frontier_cache (
                            metric,
                            chapter_unique,
                            frontier_unique,
                            level,
                            first_seen_at,
                            last_verified_at
                        )
                        SELECT
                            metric,
                            chapter_unique,
                            frontier_unique,
                            level,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP
                        FROM banxico_frontier_df
                        """
                    )

                conn.execute(
                    """
                    INSERT OR REPLACE INTO banxico_topology_meta (
                        metric,
                        members_count,
                        edges_count,
                        frontier_count,
                        chapters_count,
                        last_refreshed_at
                    )
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    [
                        metric,
                        int(len(members_rows)),
                        int(len(edges_rows)),
                        int(len(frontier_rows) if persist_frontier else 0),
                        int(chapters_count),
                    ],
                )
        except duckdb.Error:
            return
