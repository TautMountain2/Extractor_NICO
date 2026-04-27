"""Ingesta de archivos colocados en el inbox o bronze."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Iterable

from .catalogs import CountryCatalog
from .database import Database
from .parsers.banxico_cube import BanxicoCubeExportParser
from .parsers.inegi_cube import InegiCubeExportParser
from .utils import file_sha256

LOGGER = logging.getLogger(__name__)

_ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}


class InboxIngestor:
    def __init__(self, db: Database, inbox_dir: Path, country_catalog: CountryCatalog) -> None:
        self.db = db
        self.inbox_dir = inbox_dir
        self.country_catalog = country_catalog
        self.parsers = [
            BanxicoCubeExportParser(),
            InegiCubeExportParser(),
        ]

    def ingest(self, source_code: str = "MANUAL_IMPORT") -> dict[str, int]:
        paths = [
            path
            for path in sorted(self.inbox_dir.iterdir())
            if self._is_eligible_path(path)
        ]
        return self.ingest_paths(paths, source_code=source_code)

    def ingest_paths(self, paths: Iterable[Path], source_code: str = "MANUAL_IMPORT") -> dict[str, int]:
        stats = {"files_seen": 0, "files_loaded": 0, "records_loaded": 0}
        seen_inputs: set[str] = set()

        for raw_path in paths:
            path = Path(raw_path)
            key = str(path)
            if key in seen_inputs:
                continue
            seen_inputs.add(key)

            if not self._is_eligible_path(path):
                continue

            stats["files_seen"] += 1
            file_hash = file_sha256(path)
            if self.db.file_already_processed(str(path), file_hash):
                LOGGER.info("Saltando archivo ya procesado: %s", path.name)
                continue

            parser = self._detect_parser(path)
            if parser is None:
                LOGGER.warning("No se reconoció el formato de %s", path.name)
                continue

            effective_source_code = (
                parser.resolve_source_code(path, source_code)
                if hasattr(parser, "resolve_source_code")
                else source_code
            )
            load_run_id = self.db.create_load_run(source_code=effective_source_code, mode="ingest")

            try:
                observations = parser.parse(
                    path=path,
                    catalog=self.country_catalog,
                    source_code=effective_source_code,
                    source_revision=None,
                    load_run_id=load_run_id,
                )
                loaded = self.db.upsert_observations(observations)
                self.db.register_processed_file(str(path), parser.name, file_hash, load_run_id)
                self.db.finish_load_run(load_run_id, "SUCCESS", len(observations), loaded, artifact_path=str(path))
                stats["files_loaded"] += 1
                stats["records_loaded"] += loaded
            except Exception as exc:
                self.db.log_error("ingest", str(path), str(exc), traceback.format_exc())
                self.db.finish_load_run(load_run_id, "FAILED", 0, 0, message=str(exc), artifact_path=str(path))
                LOGGER.exception("Falló la ingesta de %s", path)

        return stats

    def _is_eligible_path(self, path: Path) -> bool:
        return (
            path.exists()
            and path.is_file()
            and path.suffix.lower() in _ALLOWED_SUFFIXES
            and not path.name.startswith(".")
        )

    def _detect_parser(self, path: Path):
        for parser in self.parsers:
            try:
                if parser.detect(path):
                    return parser
            except Exception:
                LOGGER.exception("Error detectando parser para %s", path)
        return None
