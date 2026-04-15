"""CLI del proyecto."""

from __future__ import annotations

from pathlib import Path

import typer
from rich import print

from .database import Database
from .logging_utils import configure_logging
from .nico_catalog import NicoCatalogLoader
from .settings import load_settings
from .sync import Synchronizer

app = typer.Typer(add_completion=False, help="CLI para NICO Trade Hub")


def build_db() -> Database:
    settings = load_settings()
    configure_logging(settings.log_dir)
    return Database(settings.database_path, settings.root / "migrations")


@app.command("init-db")
def init_db() -> None:
    db = build_db()
    db.init_db()
    print("[green]Base inicializada correctamente.[/green]")


@app.command("status")
def status() -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    print(db.status())
    print(db.nico_catalog_status())


@app.command("load-nico-catalog")
def load_nico_catalog(path: str = typer.Option(..., help="Ruta al Excel maestro de NICO")) -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    loader = NicoCatalogLoader()
    rows = loader.load(Path(path))
    loaded = db.replace_nico_catalog([r.as_record() for r in rows], source_file=path)
    print(f"[green]Catálogo NICO cargado:[/green] {loaded} filas")


@app.command("ingest-inbox")
def ingest_inbox() -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    sync = Synchronizer(settings, db)
    print(sync.ingest_inbox())


@app.command("sync-banxico")
def sync_banxico(
    metric: str = typer.Option("both", help="value, volume o both"),
    flow: str = typer.Option("both", help="IMPORT, EXPORT o both"),
    start: str = typer.Option("2022-01", help="Mes inicial YYYY-MM"),
    end: str = typer.Option("2022-01", help="Mes final YYYY-MM"),
) -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    syncer = Synchronizer(settings, db)
    result = syncer.sync_banxico(metric=metric, flow=flow, start_month=start, end_month=end)
    print(result)


@app.command("export")
def export_data(
    flow: str | None = typer.Option(None, help="IMPORT o EXPORT"),
    country: str | None = typer.Option(None, help="Nombre canónico del país"),
    start: str | None = typer.Option(None, help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, help="YYYY-MM-DD"),
    level: int | None = typer.Option(None, help="2, 4, 6, 8 o 10"),
    prefix: str | None = typer.Option(None, help="Prefijo arancelario"),
    format: str = typer.Option("csv", help="csv, parquet o dta"),
    output: str | None = typer.Option(None, help="Ruta de salida opcional"),
) -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    db = Database(settings.database_path, settings.root / "migrations")
    db.init_db()
    df = db.query_export(flow=flow, country=country, start=start, end=end, level=level, prefix=prefix)
    payload, _mime, filename = db.export_dataframe(df, format)
    output_path = Path(output) if output else settings.export_dir / filename
    output_path.write_bytes(payload)
    print(f"[green]Exportado:[/green] {output_path}")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
