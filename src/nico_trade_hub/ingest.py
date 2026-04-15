"""Ingesta de archivos colocados en el inbox o bronze."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from .catalogs import CountryCatalog
from .database import Database
from .parsers.banxico_cube import BanxicoCubeExportParser
from .parsers.inegi_cube import InegiCubeExportParser
from .utils import file_sha256

LOGGER = logging.getLogger(__name__)


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
        stats = {"files_seen": 0, "files_loaded": 0, "records_loaded": 0}
        allowed_suffixes = {".csv", ".xlsx", ".xls"}
        for path in sorted(self.inbox_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes or path.name.startswith("."):
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
            effective_source_code = parser.resolve_source_code(path, source_code) if hasattr(parser, "resolve_source_code") else source_code
            load_run_id = self.db.create_load_run(source_code=effective_source_code, mode="ingest")
            try:
                observations = parser.parse(path=path, catalog=self.country_catalog, source_code=effective_source_code, source_revision=None, load_run_id=load_run_id)
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

    def _detect_parser(self, path: Path):
        for parser in self.parsers:
            try:
                if parser.detect(path):
                    return parser
            except Exception:
                LOGGER.exception("Error detectando parser para %s", path)
        return None
