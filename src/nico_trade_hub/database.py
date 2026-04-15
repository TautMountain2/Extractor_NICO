"""Acceso a DuckDB y operaciones de persistencia."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from .models import TradeObservation
from .utils import dataframe_to_bytes_csv, record_hash


class Database:
    def __init__(self, db_path: Path, migrations_dir: Path) -> None:
        self.db_path = db_path
        self.migrations_dir = migrations_dir

    @contextmanager
    def connect(self):
        conn = duckdb.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            for migration in sorted(self.migrations_dir.glob("*.sql")):
                conn.execute(migration.read_text(encoding="utf-8"))

    def next_id(self, conn: duckdb.DuckDBPyConnection, table: str, id_column: str) -> int:
        result = conn.execute(f"SELECT COALESCE(MAX({id_column}), 0) + 1 FROM {table}").fetchone()
        return int(result[0])

    def create_load_run(self, source_code: str, mode: str) -> int:
        with self.connect() as conn:
            load_run_id = self.next_id(conn, "load_run", "load_run_id")
            conn.execute(
                """
                INSERT INTO load_run (load_run_id, source_code, mode, status, started_at)
                VALUES (?, ?, ?, 'RUNNING', CURRENT_TIMESTAMP)
                """,
                [load_run_id, source_code, mode],
            )
            return load_run_id

    def finish_load_run(self, load_run_id: int, status: str, records_read: int, records_loaded: int, message: str | None = None, artifact_path: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE load_run
                SET status = ?, finished_at = CURRENT_TIMESTAMP,
                    records_read = ?, records_loaded = ?,
                    message = ?, artifact_path = ?
                WHERE load_run_id = ?
                """,
                [status, records_read, records_loaded, message, artifact_path, load_run_id],
            )

    def log_error(self, context: str, file_path: str | None, error_message: str, traceback_text: str) -> None:
        with self.connect() as conn:
            error_id = self.next_id(conn, "etl_error_log", "error_id")
            conn.execute(
                """
                INSERT INTO etl_error_log (error_id, context, file_path, error_message, traceback)
                VALUES (?, ?, ?, ?, ?)
                """,
                [error_id, context, file_path, error_message, traceback_text],
            )

    def file_already_processed(self, file_path: str, file_hash: str) -> bool:
        with self.connect() as conn:
            result = conn.execute(
                "SELECT COUNT(*) FROM etl_file_registry WHERE file_path = ? AND file_hash = ?",
                [file_path, file_hash],
            ).fetchone()[0]
            return bool(result)

    def register_processed_file(self, file_path: str, parser_name: str, file_hash: str, load_run_id: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO etl_file_registry (file_path, parser_name, file_hash, processed_at, load_run_id)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                [file_path, parser_name, file_hash, load_run_id],
            )

    def replace_nico_catalog(self, rows: list[dict[str, str]], source_file: str) -> int:
        df = pd.DataFrame(rows).copy()
        df["source_file"] = source_file
        with self.connect() as conn:
            conn.execute("DELETE FROM dim_nico_catalog")
            conn.register("nico_catalog_df", df)
            conn.execute(
                """
                INSERT INTO dim_nico_catalog (nico10, fraccion8, nico, description, source_file)
                SELECT nico10, fraccion8, nico, description, source_file
                FROM nico_catalog_df
                """
            )
        return len(df)

    def nico_catalog_status(self) -> dict[str, object]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS nicos,
                       COUNT(DISTINCT fraccion8) AS fracciones,
                       MIN(loaded_at) AS first_loaded_at,
                       MAX(loaded_at) AS last_loaded_at
                FROM dim_nico_catalog
                """
            ).fetchdf().iloc[0].to_dict()
            return row

    def upsert_observations(self, observations: Iterable[TradeObservation]) -> int:
        records = []
        for obs in observations:
            record = obs.as_record()
            record["record_hash"] = record_hash(record)
            records.append(record)
        if not records:
            return 0
        df = pd.DataFrame(records)
        with self.connect() as conn:
            conn.register("staging_trade", df)
            conn.execute(
                """
                MERGE INTO fact_trade_monthly AS target
                USING staging_trade AS src
                ON target.date_month = src.date_month
                   AND target.flow_code = src.flow_code
                   AND target.country_name = src.country_name
                   AND target.tariff_code = src.tariff_code
                   AND target.source_code = src.source_code
                WHEN MATCHED AND target.record_hash <> src.record_hash THEN UPDATE SET
                    year = src.year,
                    month = src.month,
                    country_iso3 = src.country_iso3,
                    tariff_level = src.tariff_level,
                    hs2 = src.hs2,
                    hs4 = src.hs4,
                    hs6 = src.hs6,
                    fraccion8 = src.fraccion8,
                    nico10 = src.nico10,
                    tariff_description = src.tariff_description,
                    unit_name = src.unit_name,
                    quantity = src.quantity,
                    value_usd = src.value_usd,
                    source_file = src.source_file,
                    source_revision = src.source_revision,
                    load_run_id = src.load_run_id,
                    record_hash = src.record_hash,
                    updated_at = CURRENT_TIMESTAMP
                WHEN NOT MATCHED THEN INSERT (
                    date_month, year, month, flow_code, country_name, country_iso3,
                    tariff_code, tariff_level, hs2, hs4, hs6, fraccion8, nico10,
                    tariff_description, unit_name, quantity, value_usd,
                    source_code, source_file, source_revision, load_run_id, record_hash
                ) VALUES (
                    src.date_month, src.year, src.month, src.flow_code, src.country_name, src.country_iso3,
                    src.tariff_code, src.tariff_level, src.hs2, src.hs4, src.hs6, src.fraccion8, src.nico10,
                    src.tariff_description, src.unit_name, src.quantity, src.value_usd,
                    src.source_code, src.source_file, src.source_revision, src.load_run_id, src.record_hash
                )
                """
            )
        return len(df)

    def status(self) -> dict[str, object]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS rows_count,
                    COUNT(DISTINCT date_month) AS months_count,
                    COUNT(DISTINCT country_name) AS countries_count,
                    COUNT(DISTINCT COALESCE(nico10, tariff_code)) AS product_count,
                    MIN(date_month) AS min_month,
                    MAX(date_month) AS max_month
                FROM fact_trade_monthly
                """
            ).fetchdf().iloc[0].to_dict()
            return row

    def recent_load_runs(self, limit: int = 10) -> pd.DataFrame:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM load_run ORDER BY started_at DESC LIMIT ?", [limit]).fetchdf()

    def query_export(self, flow: str | None = None, country: str | None = None, start: str | None = None, end: str | None = None, level: int | None = None, prefix: str | None = None) -> pd.DataFrame:
        where: list[str] = []
        params: list[object] = []
        if flow:
            where.append("flow_code = ?")
            params.append(flow)
        if country:
            where.append("country_name = ?")
            params.append(country)
        if start:
            where.append("date_month >= ?")
            params.append(start)
        if end:
            where.append("date_month <= ?")
            params.append(end)
        if level:
            where.append("tariff_level = ?")
            params.append(level)
        if prefix:
            where.append("tariff_code LIKE ?")
            params.append(f"{prefix}%")
        sql = "SELECT * FROM v_trade_monthly_latest"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date_month, flow_code, country_name, tariff_code"
        with self.connect() as conn:
            return conn.execute(sql, params).fetchdf()

    def export_dataframe(self, df: pd.DataFrame, output_format: str) -> tuple[bytes, str, str]:
        output_format = output_format.lower()
        if output_format == "csv":
            return dataframe_to_bytes_csv(df), "text/csv", "trade_export.csv"
        if output_format == "parquet":
            buffer = BytesIO()
            df.to_parquet(buffer, index=False)
            return buffer.getvalue(), "application/octet-stream", "trade_export.parquet"
        if output_format == "dta":
            buffer = BytesIO()
            df.to_stata(buffer, write_index=False, version=118)
            return buffer.getvalue(), "application/octet-stream", "trade_export.dta"
        raise ValueError(f"Formato no soportado: {output_format}")
