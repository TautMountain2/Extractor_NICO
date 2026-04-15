"""Orquestación de sincronizaciones."""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import date

from .catalogs import CountryCatalog
from .connectors.api_banxico import BanxicoMatrixApiConnector
from .connectors.browser_banxico import BanxicoJob, BanxicoMatrixBrowserConnector
from .database import Database
from .ingest import InboxIngestor
from .settings import Settings

LOGGER = logging.getLogger(__name__)


def _parse_yyyy_mm(value: str) -> tuple[int, int]:
    y, m = value.split("-")
    year = int(y)
    month = int(m)
    if month < 1 or month > 12:
        raise ValueError(f"Mes inválido: {value}")
    return year, month


def _month_iter(start: str, end: str):
    sy, sm = _parse_yyyy_mm(start)
    ey, em = _parse_yyyy_mm(end)
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


class Synchronizer:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.catalog = CountryCatalog.from_csv(settings.country_aliases_path)

    def sync_banxico(self, *, metric: str, flow: str, start_month: str, end_month: str) -> dict[str, int]:
        preferred_mode = str(self.settings.raw["sources"]["banxico"].get("preferred_mode", "api")).lower()
        fallback_browser = bool(self.settings.raw["sources"]["banxico"].get("fallback_browser", True))
        connector = BanxicoMatrixApiConnector(self.settings) if preferred_mode == "api" else BanxicoMatrixBrowserConnector(self.settings)
        bronze_ingestor = InboxIngestor(self.db, self.settings.bronze_dir, self.catalog)

        metrics = [metric] if metric in {"value", "volume"} else ["value", "volume"]
        flows = [flow] if flow in {"IMPORT", "EXPORT"} else ["IMPORT", "EXPORT"]
        stats = {"jobs": 0, "downloads": 0, "records_loaded": 0}

        for metric_item in metrics:
            jobs: list[BanxicoJob] = []
            run_ids: dict[str, tuple[int, str]] = {}
            source_code = f"BANXICO_{'VALUE_USD' if metric_item == 'value' else 'VOLUME'}"

            for flow_item in flows:
                for year, month in _month_iter(start_month, end_month):
                    stats["jobs"] += 1
                    job = BanxicoJob(year=year, month=month, flow_code=flow_item, metric=metric_item)
                    jobs.append(job)
                    load_run_id = self.db.create_load_run(source_code=source_code, mode="browser")
                    run_ids[job.job_id] = (load_run_id, source_code)

            try:
                results = connector.run_jobs(jobs)
            except Exception as exc:
                LOGGER.error("Conector Banxico (%s) falló a nivel batch: %s", preferred_mode, exc)
                if preferred_mode == "api" and fallback_browser:
                    LOGGER.warning("Aplicando fallback Banxico hacia Playwright visual")
                    connector = BanxicoMatrixBrowserConnector(self.settings)
                    results = connector.run_jobs(jobs)
                else:
                    raise
            for result in results:
                load_run_id, _ = run_ids[result.job.job_id]
                if result.ok and result.output_path is not None:
                    self.db.finish_load_run(
                        load_run_id,
                        "SUCCESS",
                        0,
                        0,
                        artifact_path=str(result.output_path),
                        message=f"Descarga {result.job.job_id}",
                    )
                    stats["downloads"] += 1
                else:
                    self.db.log_error(
                        "banxico_sync",
                        None,
                        result.error_message or f"Falló {result.job.job_id}",
                        result.error_traceback or "",
                    )
                    self.db.finish_load_run(
                        load_run_id,
                        "FAILED",
                        0,
                        0,
                        message=f"{result.job.job_id}: {result.error_message}",
                    )
                    LOGGER.error(
                        "Falló el job %s: %s\n%s",
                        result.job.job_id,
                        result.error_message,
                        result.error_traceback or "",
                    )

        ingested = bronze_ingestor.ingest(source_code="BANXICO_BROWSER")
        stats["records_loaded"] = ingested["records_loaded"]
        return stats

    def ingest_inbox(self) -> dict[str, int]:
        ingestor = InboxIngestor(self.db, self.settings.inbox_dir, self.catalog)
        return ingestor.ingest(source_code="MANUAL_IMPORT")
