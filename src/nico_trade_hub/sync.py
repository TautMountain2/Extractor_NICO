"""Orquestación de sincronizaciones."""

from __future__ import annotations

import logging
from pathlib import Path

from .catalogs import CountryCatalog
from .connectors.api_banxico import BanxicoMatrixApiConnector
from .connectors.browser_banxico import BanxicoJob, BanxicoMatrixBrowserConnector
from .database import Database
from .ingest import InboxIngestor
from .perf_trace import PerfTrace
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


def _unique_paths_in_order(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


class Synchronizer:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.catalog = CountryCatalog.from_csv(settings.country_aliases_path)

    def sync_banxico(
        self,
        *,
        metric: str,
        flow: str,
        start_month: str,
        end_month: str,
        trace: PerfTrace | None = None,
    ) -> dict[str, int]:
        preferred_mode = str(self.settings.raw["sources"]["banxico"].get("preferred_mode", "api")).lower()
        fallback_browser = bool(self.settings.raw["sources"]["banxico"].get("fallback_browser", True))

        bronze_ingestor = InboxIngestor(self.db, self.settings.bronze_dir, self.catalog)

        metrics = [metric] if metric in {"value", "volume"} else ["value", "volume"]
        flows = [flow] if flow in {"IMPORT", "EXPORT"} else ["IMPORT", "EXPORT"]
        stats = {"jobs": 0, "downloads": 0, "records_loaded": 0}
        downloaded_artifacts: list[Path] = []

        if trace:
            trace.set_meta(
                preferred_mode=preferred_mode,
                fallback_browser=fallback_browser,
                metrics=metrics,
                flows=flows,
                start_month=start_month,
                end_month=end_month,
            )

        for metric_item in metrics:
            jobs: list[BanxicoJob] = []
            run_ids: dict[str, tuple[int, str]] = {}
            source_code = f"BANXICO_{'VALUE_USD' if metric_item == 'value' else 'VOLUME'}"

            if trace:
                trace.event("metric_batch_start", metric=metric_item, source_code=source_code)

            with (trace.stage("sync.prepare_jobs", metric=metric_item) if trace else _nullcontext()):
                for flow_item in flows:
                    for year, month in _month_iter(start_month, end_month):
                        stats["jobs"] += 1
                        if trace:
                            trace.incr("jobs_created", 1)
                        job = BanxicoJob(year=year, month=month, flow_code=flow_item, metric=metric_item)
                        jobs.append(job)
                        load_run_id = self.db.create_load_run(source_code=source_code, mode="browser")
                        run_ids[job.job_id] = (load_run_id, source_code)

            connector = (
                BanxicoMatrixApiConnector(self.settings, trace=trace)
                if preferred_mode == "api"
                else BanxicoMatrixBrowserConnector(self.settings)
            )

            try:
                with (trace.stage("sync.connector_run", metric=metric_item, mode=preferred_mode) if trace else _nullcontext()):
                    results = connector.run_jobs(jobs)
            except Exception as exc:
                LOGGER.error("Conector Banxico (api) falló a nivel batch: %s", exc)

                if not fallback_browser:
                    raise RuntimeError(
                        "El conector API de Banxico falló y el fallback visual está deshabilitado por configuración."
                    ) from exc

                LOGGER.warning("Aplicando fallback Banxico hacia Playwright visual")
                browser_connector = BanxicoMatrixBrowserConnector(self.settings, trace=trace)
                results = browser_connector.run_jobs(jobs)

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
                    downloaded_artifacts.append(Path(result.output_path))
                    stats["downloads"] += 1
                    if trace:
                        trace.incr("jobs_ok", 1)
                        trace.incr("downloads_ok", 1)
                        trace.event(
                            "job_success",
                            job_id=result.job.job_id,
                            output_path=str(result.output_path),
                        )
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
                    if trace:
                        trace.incr("jobs_failed", 1)
                        trace.event("job_failed", job_id=result.job.job_id, error=result.error_message or "")
                    LOGGER.error(
                        "Falló el job %s: %s\n%s",
                        result.job.job_id,
                        result.error_message,
                        result.error_traceback or "",
                    )

        unique_artifacts = _unique_paths_in_order(downloaded_artifacts)
        if trace:
            trace.set_meta(downloaded_artifacts=[str(p) for p in unique_artifacts])
            trace.incr("downloaded_artifacts_selected", len(unique_artifacts))

        with (trace.stage("sync.ingest_new_artifacts") if trace else _nullcontext()):
            ingested = bronze_ingestor.ingest_paths(unique_artifacts, source_code="BANXICO_BROWSER")

        stats["records_loaded"] = ingested["records_loaded"]

        if trace:
            trace.set_meta(final_stats=stats)
            trace.incr("records_loaded", int(stats["records_loaded"]))
            trace.incr("files_seen_selected_ingest", int(ingested.get("files_seen", 0)))
            trace.incr("files_loaded_selected_ingest", int(ingested.get("files_loaded", 0)))
            trace.event(
                "sync.ingest_new_artifacts_finished",
                files_seen=ingested.get("files_seen", 0),
                files_loaded=ingested.get("files_loaded", 0),
                records_loaded=ingested.get("records_loaded", 0),
            )

        return stats

    def ingest_inbox(self) -> dict[str, int]:
        ingestor = InboxIngestor(self.db, self.settings.inbox_dir, self.catalog)
        return ingestor.ingest(source_code="MANUAL_IMPORT")


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False
